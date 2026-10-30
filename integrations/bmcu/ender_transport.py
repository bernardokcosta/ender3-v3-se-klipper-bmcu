import logging
import struct
import time

from . import protocol, transport


class EnderTransportGuard:
    def _next_external_cmd(self):
        reserved = getattr(self, '_ender_reserved_command', None)
        if reserved is not None:
            self._ender_reserved_command = None
            return reserved
        probe = getattr(self, '_ender_operation_probe', None)
        active = (self.latest_status_dict or {}).get('active_op_id', 0)
        while True:
            candidate = super()._next_external_cmd()
            if (
                candidate not in self.external_pending
                and candidate != active
                and (probe is None or candidate != probe['wire'])
            ):
                return candidate

    def _ender_cancel_probe(self, reason):
        probe = getattr(self, '_ender_operation_probe', None)
        self._ender_operation_probe = None
        if probe is not None:
            self.internal_pending.pop(probe['query'], None)
            if self.client is not None and probe['epoch'] == self.client_epoch:
                self._queue_client(
                    transport.OP_ERROR,
                    probe['message'][2],
                    0,
                    0,
                    reason.encode('utf-8'),
                    reliable=True,
                    control=True,
                )

    def _ender_probe_candidate(self, probe):
        probe['phase'] = 'history'
        probe['wire'] = self._next_external_cmd()
        probe['query'] = self._queue_internal(
            protocol.MSG_GET_OP_RESULT,
            struct.pack('<I', probe['wire']),
            'ender_operation_probe',
        )
        self._ender_operation_probe = probe

    def _handle_client_message(self, message):
        op, message_type, command, _unused, _payload = message
        starts = (
            protocol.MSG_TEST_ENCODER,
            protocol.MSG_CHANNEL_AUTOLOAD,
            protocol.MSG_FEED_TO_CONTACT,
            protocol.MSG_FEED_DISTANCE,
            protocol.MSG_CHANNEL_RETRACT,
            protocol.MSG_CAL_AUTO_START,
        )
        if op == transport.OP_SEND:
            if message_type in (
                protocol.MSG_STOP_ALL,
                protocol.MSG_ABORT_OP,
                protocol.MSG_RESET_ERROR,
            ):
                self._ender_cancel_probe('Operation cancelled before motion')
            if (
                message_type in starts
                and not getattr(self, '_ender_verified_operation', False)
                and self.serial is not None
                and self.session_ready
            ):
                pending = getattr(self, '_ender_operation_probe', None)
                if pending is not None:
                    self._queue_client(
                        transport.OP_ERROR,
                        command,
                        0,
                        0,
                        b'Another operation is awaiting history verification',
                        reliable=True,
                        control=True,
                    )
                    return
                probe = {
                    'message': message,
                    'epoch': self.client_epoch,
                    'session': self.session_id,
                    'deadline': time.monotonic() + 1.0,
                    'collisions': 0,
                    'wire': None,
                    'phase': 'status',
                }
                probe['query'] = self._queue_internal(
                    protocol.MSG_GET_STATUS, b'', 'ender_operation_status'
                )
                self._ender_operation_probe = probe
                return
        return super()._handle_client_message(message)

    def _handle_serial_packet(self, message_type, sequence, command, payload):
        probe = getattr(self, '_ender_operation_probe', None)
        if probe is None or command != probe['query']:
            return super()._handle_serial_packet(
                message_type, sequence, command, payload
            )
        if (
            self.client is None
            or self.client_epoch != probe['epoch']
            or self.session_id != probe['session']
            or not self.session_ready
            or time.monotonic() >= probe['deadline']
        ):
            self._ender_cancel_probe('Operation history verification expired')
            return
        self.internal_pending.pop(command, None)
        if probe['phase'] == 'status':
            if message_type != protocol.MSG_STATUS:
                self._ender_cancel_probe('Could not verify BMCU idle state')
                return
            status = protocol.parse_status(payload)
            if (
                int(status['session_id']) != probe['session']
                or status['active_op_state'] == protocol.OP_STATE_RUNNING
            ):
                self._ender_cancel_probe('The BMCU session is busy or changed')
                return
            self.latest_status_dict = status
            self._ender_probe_candidate(probe)
            return
        if message_type == protocol.MSG_OP_RESULT:
            if (
                len(payload) < 4
                or struct.unpack('<I', payload[:4])[0] != probe['wire']
            ):
                self._ender_cancel_probe('Invalid operation history response')
                return
            logging.warning(
                'discarding cached BMCU operation id=%d before new motion',
                probe['wire'],
            )
            probe['collisions'] += 1
            if probe['collisions'] >= 5:
                self._ender_cancel_probe(
                    'Operation identifiers remain occupied'
                )
            else:
                self._ender_probe_candidate(probe)
            return
        if message_type == protocol.MSG_ERROR and len(payload) == 7:
            channel, error, _details = struct.unpack('<BHI', payload)
            if channel == 255 and error == 22:
                self._ender_operation_probe = None
                self._ender_reserved_command = probe['wire']
                self._ender_verified_operation = True
                try:
                    super()._handle_client_message(probe['message'])
                finally:
                    self._ender_reserved_command = None
                    self._ender_verified_operation = False
                return
        self._ender_cancel_probe('Could not verify operation history')

    def _drop_client(self):
        self._ender_cancel_probe('Klipper disconnected before motion')
        return super()._drop_client()
