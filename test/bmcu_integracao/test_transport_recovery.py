import ast
import logging
import struct
import types
import unittest
from unittest.mock import patch

from test_integracao import BASE, ROOT, installer


protocol = types.ModuleType('integration_test.bmcu_core.protocol')
names = (
    'MSG_TEST_ENCODER',
    'MSG_CHANNEL_AUTOLOAD',
    'MSG_FEED_TO_CONTACT',
    'MSG_FEED_DISTANCE',
    'MSG_CHANNEL_RETRACT',
    'MSG_CAL_AUTO_START',
    'MSG_STOP_ALL',
    'MSG_ABORT_OP',
    'MSG_RESET_ERROR',
    'MSG_GET_OP_RESULT',
    'MSG_OP_RESULT',
    'MSG_ERROR',
    'MSG_HELLO',
    'MSG_SESSION_CONFIRM',
    'MSG_GET_SNAPSHOT',
    'MSG_ACK',
    'MSG_GET_STATUS',
    'MSG_STATUS',
)
for index, name in enumerate(names, 1):
    setattr(protocol, name, index)
transport = types.SimpleNamespace(OP_SEND=1, OP_ERROR=2)
protocol.OP_STATE_RUNNING = 1
protocol.parse_status = lambda payload: payload
guard_source = (ROOT / 'integrations/bmcu/ender_transport.py').read_text()
guard_tree = ast.parse(guard_source)
guard_tree.body = [
    node for node in guard_tree.body if not isinstance(node, ast.ImportFrom)
]
namespace = {'protocol': protocol, 'transport': transport}
exec(compile(guard_tree, 'ender_transport.py', 'exec'), namespace)
native_tree = ast.parse((BASE / 'transport_original.txt').read_text())
for node in ast.walk(native_tree):
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == 'protocol'
        and node.attr.startswith('MSG_')
        and not hasattr(protocol, node.attr)
    ):
        setattr(protocol, node.attr, len(vars(protocol)) + 1)
native_class = next(
    node for node in native_tree.body if isinstance(node, ast.ClassDef)
)
methods = {
    '_handle_client_message',
    '_handle_serial_packet',
    '_next_external_cmd',
    '_remove_external',
    '_rewrite_op_result_id',
}
native_class.body = [
    node
    for node in native_class.body
    if isinstance(node, ast.FunctionDef) and node.name in methods
]
native = {
    'protocol': protocol,
    'transport': transport,
    'struct': struct,
    'time': types.SimpleNamespace(monotonic=lambda: 0.0),
    'logging': logging,
    '_OPERATION_START_TYPES': frozenset(
        getattr(protocol, n) for n in names[:6]
    ),
    '_MAX_EXTERNAL_PENDING': 2048,
    '_EXTERNAL_TIMEOUT': 310.0,
    '_COMPLETED_OPERATION_TTL': 310.0,
    '_INTERNAL_BASE': 0xF0000000,
}
exec(
    compile(
        ast.Module(body=[native_class], type_ignores=[]),
        'transport_original.txt',
        'exec',
    ),
    native,
)


class TransportBench(
    namespace['EnderTransportGuard'], native['TransportDaemon']
):
    def __init__(self):
        self.client = object()
        self.client_epoch = 1
        self.serial = object()
        self.session_ready = True
        self.session_id = 42
        self.external_cmd = 7
        self.external_pending = {}
        self.operation_wire_by_client = {}
        self.internal_pending = {}
        self.internal_cmd = 0xF0000000
        self.latest_status_dict = {}
        self.serial_packets = []
        self.client_packets = []
        self.time = 0.0

    def _queue_internal(self, message_type, payload, purpose):
        command = self.internal_cmd
        self.internal_cmd += 1
        self.internal_pending[command] = purpose
        self._queue_serial(message_type, command, payload)
        return command

    def _queue_serial(self, *args, **kwargs):
        self.serial_packets.append(args)

    def _queue_client(self, *args, **kwargs):
        self.client_packets.append(args)

    def _queue_packet_client(self, *args, **kwargs):
        self.client_packets.append(args)

    def start(self, message_type=None):
        self._handle_client_message(
            (
                transport.OP_SEND,
                message_type or protocol.MSG_FEED_DISTANCE,
                10,
                0,
                b'new operation',
            )
        )
        probe = self._ender_operation_probe
        self._handle_serial_packet(
            protocol.MSG_STATUS,
            1,
            probe['query'],
            dict(
                self.latest_status_dict,
                session_id=self.session_id,
                active_op_state=self.latest_status_dict.get(
                    'active_op_state', 0
                ),
            ),
        )

    def result(self, cached=False, error=22):
        probe = self._ender_operation_probe
        payload = (
            struct.pack('<I', probe['wire']) + b'old aborted result'
            if cached
            else struct.pack('<BHI', 255, error, 0)
        )
        self._handle_serial_packet(
            protocol.MSG_OP_RESULT if cached else protocol.MSG_ERROR,
            1,
            probe['query'],
            payload,
        )


class TransportRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.bench = TransportBench()
        self.clock = patch.object(
            namespace['time'], 'monotonic', lambda: self.bench.time
        )
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_cached_aborted_operation_is_skipped_without_motor_command(self):
        b = self.bench
        b.start()
        b.result(cached=True)
        self.assertEqual(
            [protocol.MSG_GET_STATUS] + [protocol.MSG_GET_OP_RESULT] * 2,
            [p[0] for p in b.serial_packets],
        )
        b.result()
        self.assertEqual(
            (protocol.MSG_FEED_DISTANCE, 8, b'new operation'),
            b.serial_packets[-1],
        )
        self.assertEqual(8, b.operation_wire_by_client[(1, 10)])
        self.assertFalse(b.client_packets)

    def test_every_native_distance_operation_checks_firmware_history(self):
        for name in names[:6]:
            b = TransportBench()
            b.start(getattr(protocol, name))
            self.assertEqual(protocol.MSG_GET_STATUS, b.serial_packets[0][0])
            b.result()
            self.assertEqual(getattr(protocol, name), b.serial_packets[-1][0])

    def test_live_and_pending_identifiers_are_not_reused(self):
        b = self.bench
        b.latest_status_dict = {'active_op_id': 7}
        b.external_pending[8] = {'kind': 'request'}
        b.start()
        self.assertEqual(9, b._ender_operation_probe['wire'])

    def test_all_four_cached_results_can_be_skipped(self):
        b = self.bench
        b.start()
        for _ in range(4):
            b.result(cached=True)
        b.result()
        self.assertEqual(11, b.serial_packets[-1][1])

    def test_stop_during_history_check_prevents_late_motion(self):
        b = self.bench
        b.start()
        probe = dict(b._ender_operation_probe)
        b._handle_client_message(
            (transport.OP_SEND, protocol.MSG_STOP_ALL, 11, 0, b'')
        )
        b._handle_serial_packet(
            protocol.MSG_ERROR,
            1,
            probe['query'],
            struct.pack('<BHI', 255, 22, 0),
        )
        self.assertNotIn(
            protocol.MSG_FEED_DISTANCE, [p[0] for p in b.serial_packets]
        )

    def test_disconnect_session_change_and_expiration_do_not_start_motion(
        self,
    ):
        for condition in ('client', 'session', 'epoch', 'deadline'):
            b = self.bench = TransportBench()
            b.start()
            if condition == 'client':
                b.client = None
            elif condition == 'session':
                b.session_id += 1
            elif condition == 'epoch':
                b.client_epoch += 1
            else:
                b.time = 1.1
            b.result()
            self.assertEqual(
                [protocol.MSG_GET_STATUS, protocol.MSG_GET_OP_RESULT],
                [p[0] for p in b.serial_packets],
            )

    def test_unknown_error_fails_closed_without_motion(self):
        b = self.bench
        b.start()
        b.result(error=96)
        self.assertTrue(b.client_packets)
        self.assertEqual(2, len(b.serial_packets))

    def test_existing_firmware_operation_blocks_new_motion(self):
        b = self.bench
        b.latest_status_dict = {'active_op_id': 7, 'active_op_state': 1}
        b.start()
        self.assertIsNone(b._ender_operation_probe)
        self.assertEqual(
            [protocol.MSG_GET_STATUS], [p[0] for p in b.serial_packets]
        )

    def test_installer_patch_is_repeatable_and_preserves_native_daemon(self):
        source = (BASE / 'transport_original.txt').read_text()
        result = installer.patch_transport(source)
        self.assertEqual(result, installer.patch_transport(result))
        start = source.index('class TransportDaemon')
        end = source.index('\ndef parse_args')
        self.assertIn(source[start:end], result)
        self.assertIn('daemon = EnderTransportDaemon(args)', result)
