#!/usr/bin/env python3
"""
sheppard_flash.py -- flash the Sheppard board over USB-C, no ST-LINK.

The running application receives its own replacement over the virtual COM
port, stages it in SRAM, verifies CRC-32 and the vector table, then erases
and reprograms flash from a routine executing in RAM and resets.

    $ python sheppard_flash.py --bin Debug/GMWM.bin
    port      : COM7  (0483:5740)
    image     : Debug/GMWM.bin  73412 bytes  crc32=9f3c11ae
    -> fw 73412 9f3c11ae
    <- FWREADY 73412
    sending 73412 bytes... done in 0.2 s
    <- FWRECV 73412
    <- FWCRC ok
    <- FWVEC ok
    <- FWPROG
    waiting for the board to come back...
    board is back on COM7

Requires pyserial only:  pip install pyserial
No STM32CubeProgrammer, no DFU driver, no Zadig.

As a CubeIDE External Tool (Run -> External Tools -> External Tools
Configurations -> new Program):

    Location:          <path to python.exe>
    Working directory: ${workspace_loc:/GMWM Software}
    Arguments:         ${workspace_loc:/GMWM Software}/tools/sheppard_flash.py
                       --bin ${workspace_loc:/GMWM Software}/Debug/GMWM.bin

Enable the .bin: Project -> Properties -> C/C++ Build -> Settings ->
MCU/MPU Post build outputs -> Convert to binary file.

RECOVERY
    The flasher is part of the image it replaces. If a flashed image does not
    run, there is nothing left to talk to and you must reflash over SWD:
        STM32_Programmer_CLI -c port=SWD mode=UR -e all -w firmware.elf -v -rst
    The window in which power loss bricks the board is the few seconds
    between FWPROG and the board reappearing.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import zlib

VID, PID = 0x0483, 0x5740

BAUD = 115200                 # ignored by CDC, but pyserial wants a number
READY_TIMEOUT_S = 5.0
RESULT_TIMEOUT_S = 30.0       # CRC over 160 KiB at 32 MHz is not instant
REAPPEAR_TIMEOUT_S = 40.0     # mass erase plus reprogram plus enumeration
CHUNK = 4096


def die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def require_serial():
    try:
        import serial                                    # noqa: F401
        from serial.tools import list_ports              # noqa: F401
    except ImportError:
        die("pyserial is required:  pip install pyserial")


def find_port(explicit: str | None) -> str | None:
    from serial.tools import list_ports
    if explicit:
        return explicit
    for p in list_ports.comports():
        if p.vid == VID and p.pid == PID:
            return p.device
    return None


def wait_for_port(explicit: str | None, timeout: float) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        port = find_port(explicit)
        if port:
            return port
        time.sleep(0.3)
    return None


def newest_source(root: str):
    """Newest source file under the directories you actually edit.
    Used to catch the commonest mistake of all: flashing a stale .bin because
    the project was edited but not rebuilt. Deliberately does not walk
    Drivers/ or Middlewares/ -- those are vendor trees, and if you edit one
    you will know to rebuild."""
    newest_t, newest_f = 0.0, None
    roots = [os.path.join(root, d) for d in ("Core", "USB_DEVICE", "FATFS")]
    for d in roots:
        for dirpath, _dirs, files in os.walk(d):
            for f in files:
                if f.endswith((".c", ".h", ".s")):
                    p = os.path.join(dirpath, f)
                    try:
                        t = os.path.getmtime(p)
                    except OSError:
                        continue
                    if t > newest_t:
                        newest_t, newest_f = t, p
    for f in os.listdir(root) if os.path.isdir(root) else []:
        if f.endswith(".ld"):
            p = os.path.join(root, f)
            try:
                t = os.path.getmtime(p)
            except OSError:
                continue
            if t > newest_t:
                newest_t, newest_f = t, p
    return newest_t, newest_f


def read_lines_until(ser, predicates, timeout: float, echo: bool = True):
    """Read lines until one starts with any string in `predicates`.
    Returns (matched_line, all_lines). matched_line is None on timeout."""
    deadline = time.time() + timeout
    seen = []
    buf = b""
    while time.time() < deadline:
        chunk = ser.read(256)
        if not chunk:
            continue
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            seen.append(line)
            if echo:
                print(f"    <- {line}")
            for p in predicates:
                if line.startswith(p):
                    return line, seen
    return None, seen


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bin", required=True, help="application .bin to flash")
    ap.add_argument("--port", default=None,
                    help="COM port / tty; auto-detected by VID:PID if omitted")
    ap.add_argument("--no-wait", action="store_true",
                    help="do not wait for the board to re-enumerate")
    ap.add_argument("--force", action="store_true",
                    help="flash even if the .bin is older than the sources")
    args = ap.parse_args()

    require_serial()
    import serial

    if not os.path.isfile(args.bin):
        die(f"image not found: {args.bin}")
    with open(args.bin, "rb") as fh:
        image = fh.read()
    if len(image) < 2048:
        die(f"image is only {len(image)} bytes -- is this really the .bin?")

    crc = zlib.crc32(image) & 0xFFFFFFFF
    bin_t = os.path.getmtime(args.bin)

    # --- stale-image guard ---------------------------------------------------
    # Flashing successfully and seeing no change is confusing out of all
    # proportion to the mistake, because everything reports success -- the
    # board really did rewrite its flash, with the old image.
    proj = os.path.dirname(os.path.dirname(os.path.abspath(args.bin)))
    src_t, src_f = newest_source(proj)
    if src_f and src_t > bin_t + 1.0:
        age = (src_t - bin_t) / 60.0
        print(f"error: {os.path.basename(args.bin)} is {age:.0f} min older than "
              f"your sources.\n"
              f"       newest: {os.path.relpath(src_f, proj)}\n"
              f"       Build the project first, or pass --force to flash it "
              f"anyway.", file=sys.stderr)
        if not args.force:
            return 1
        print("       --force given, continuing with the stale image\n")

    port = find_port(args.port)
    if port is None:
        die("no Sheppard virtual COM port found.\n"
            "       A charge-only USB-C cable is the most common cause and\n"
            "       looks exactly like a dead board. Try another cable first.")

    print(f"port      : {port}  ({VID:04x}:{PID:04x})")
    print(f"image     : {args.bin}  {len(image)} bytes  crc32={crc:08x}")
    print(f"built     : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(bin_t))}")

    try:
        ser = serial.Serial(port, BAUD, timeout=0.2, write_timeout=10.0)
    except Exception as exc:                              # noqa: BLE001
        die(f"could not open {port}: {exc}")

    with ser:
        ser.reset_input_buffer()

        cmd = f"fw {len(image)} {crc:08x}"
        print(f"    -> {cmd}")
        ser.write(b"\r\n" + cmd.encode() + b"\r\n")
        ser.flush()

        # The device echoes what you type, so the stream also contains the
        # command itself. read_lines_until ignores anything that is not a
        # protocol keyword.
        line, seen = read_lines_until(ser, ["FWREADY", "FWABORT", "usage:"],
                                      READY_TIMEOUT_S)
        if line is None:
            die("no FWREADY. Is this build older than the self-flasher?\n"
                f"       saw: {seen[-3:] if seen else 'nothing'}")
        if not line.startswith("FWREADY"):
            die(f"device refused: {line}")

        t0 = time.time()
        sent = 0
        for off in range(0, len(image), CHUNK):
            ser.write(image[off:off + CHUNK])
            sent += min(CHUNK, len(image) - off)
            pct = 100.0 * sent / len(image)
            print(f"\r    sending {sent}/{len(image)} bytes ({pct:5.1f}%)",
                  end="", flush=True)
        ser.flush()
        print(f"\r    sent {len(image)} bytes in {time.time() - t0:.1f} s"
              f"{' ' * 20}")

        line, seen = read_lines_until(
            ser, ["FWPROG", "FWABORT", "FWFAIL", "FWCRC bad", "FWVEC bad"],
            RESULT_TIMEOUT_S)

        if line is None:
            die("device went quiet before reporting a result.\n"
                f"       saw: {seen[-5:] if seen else 'nothing'}")
        if not line.startswith("FWPROG"):
            die(f"device rejected the image: {line}  (flash untouched)")

    if args.no_wait:
        print("FWPROG sent; not waiting.")
        return 0

    print("waiting for the board to come back...")
    time.sleep(1.0)
    back = wait_for_port(args.port, REAPPEAR_TIMEOUT_S)
    if back is None:
        die("the board did not re-enumerate.\n"
            "       If it never comes back the image was written but does not\n"
            "       run: reflash over SWD. See RECOVERY in this file's header.")

    print(f"board is back on {back}")

    # --- close the loop ------------------------------------------------------
    # Ask the board what it is actually running. Without this you are trusting
    # that "no errors" means "new firmware", which is precisely the assumption
    # that hides a stale .bin.
    for attempt in range(4):
        try:
            with serial.Serial(back, BAUD, timeout=0.2) as ser:
                time.sleep(0.3)
                ser.reset_input_buffer()
                ser.write(b"\r\nver\r\n")
                ser.flush()
                line, seen = read_lines_until(ser, ["  SYSCLK"], 3.0, echo=False)
                ident = [s for s in seen if "built" in s]
                if ident:
                    print(f"now running: {ident[0]}")
                    return 0
        except Exception:                                 # noqa: BLE001
            pass                                          # port not settled yet
        time.sleep(0.5)

    print("flashed, but could not read back the version "
          "(port busy? Tera Term open?)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
