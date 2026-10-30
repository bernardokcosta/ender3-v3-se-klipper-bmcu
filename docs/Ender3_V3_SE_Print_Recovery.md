# Filament operation identifiers and print recovery

The optional integration installer supports BMCU-Klipper 1.0.6 and its 1.0.1
controller firmware. This update changes host Python code only. It does not
require flashing the printer MCU or the BMCU.

## Cached operation results after a host restart

The transport daemon originally restarted its wire command counter at 1. The
controller retains four completed operation results across a host session
handshake. Reusing a retained identifier can replay an old result instead of
starting the requested operation, including an old success or abort.

The installed `EnderTransportGuard` first requests fresh controller status and
requires an idle operation state in the same session. It then queries the
controller history for a candidate operation identifier. A retained identifier
is skipped without sending a motion command. Only the protocol's explicit
"result unavailable" response authorizes starting the new operation. Up to four
retained results can be skipped; malformed replies, an occupied controller,
session changes, cancellation and expired verification stop the request.

This applies to native feed, retract, encoder-test, autoload and automatic
calibration operations. Normal printing buffer-follow control is unchanged.
The guard does not retry a physical load or withdrawal blindly.

## Failed tool changes during printing

When `BMCU_TROCAR_ENDER` fails while executing a virtual-SD print command, the
integration stops the feeder and pauses the file without propagating the
filament error into `virtual_sdcard.on_error_gcode`. The file remains selected,
the next G-code line does not execute, and the logical tool mapping is retained.
The original print position, coordinate/extrusion state and nozzle target are
saved separately from the purge position.

After checking the filament path, use the normal **Resume** button or `RESUME`.
The pending tool change is completed at the purge position before normal
resumption. An already loaded target is purged/wiped again. The original print
temperature and saved printing state are restored before returning to the part.
If the recovery attempt fails, the file stays paused with the same pending tool.

Recovery is blocked when the file or its logical position changed, a route is
uncertain, sensor and route state disagree, another operation is active, the
controller is unavailable, coordinates were changed, motors were disabled or
the machine was homed again. A firmware shutdown or lost mechanical position
cannot be repaired by this pause mechanism. Existing idle-timeout behavior is
preserved; do not leave a pending recovery unattended until motors are disabled.
An entry sensor alone cannot confirm physical nozzle extrusion.

## Confirming a manually cleared path during a paused recovery

For an uncertain route, physically remove any obstruction from the shared
PTFE/extruder path and park that channel's filament behind the entry sensor,
clear of the shared junction. The sensor must read clear. The following command
does not move filament; it records the operator's explicit physical check:

```gcode
BMCU_CONFIRMAR_CAMINHO_LIVRE CANAL=3 CONFIRMAR=1
```

Replace `3` with the physical channel recorded in the paused failure. This
command is restricted to that channel, the same paused print and an idle feeder.
It rejects an active entry sensor, another occupied route or a detached tail.
Firmware route readback is required before host recovery state is cleared. The
print map is preserved. Then use `RESUME` to finish the pending change.

Do not confirm an empty path merely to bypass an error. The entry switch cannot
detect filament left elsewhere in the shared path. Normal native route
confirmation remains unchanged outside this guarded print-recovery command.

`CANCEL_PRINT` and `SDCARD_RESET_FILE` discard pending recovery. Manual load
errors continue to report normally. Other G-code errors retain the configured
virtual-SD error policy. Restarting Klipper discards the in-memory print recovery;
this is not recovery across a controller restart or power loss.

## Installation and verification

Finish or cancel any print, physically park channels and verify the entry sensor
is clear before running:

```sh
cd "$HOME/klipper" &&
git pull --ff-only origin master &&
sudo python3 scripts/ender3-v3-se/install_multicolor.py \
  --purge-mm 35 --pullback-speed 300
```

The installer backs up the affected host files and rolls back if startup fails.
Existing tip-forming, PID, Z offset and mesh settings remain preserved. Verify a
single-channel load/unload and a short multicolor print before a long print.
Automated tests exercise the actual Klipper virtual-SD dispatcher, pause/resume
and G-code state restoration, plus native transport methods with simulated
controller history. These tests do not replace physical verification.

Native protocol and transport references:

- [BMCU transport daemon v1.0.6](https://github.com/jarczakpawel/BMCU-Klipper/blob/v1.0.6/scripts/bmcu_transportd.py)
- [BMCU protocol and retained operation results](https://github.com/jarczakpawel/BMCU-Klipper/blob/v1.0.6/firmware/src/bmcu_protocol.cpp)
