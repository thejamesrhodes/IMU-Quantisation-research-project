#!/usr/bin/env python3
"""
sheppard_selftest.py -- prove the firmware-update safety checks work
                        BEFORE trusting them with a real image.

Run this once, on a board you have just flashed over SWD, before you ever use
sheppard_flash.py. It deliberately feeds the board bad data five different
ways and confirms that each one is refused with the flash left untouched.

    $ python sheppard_selftest.py

Nothing here can erase the board. Every test is designed to be rejected
before the erase step, and the last test confirms the board is still running
the same firmware it started with.

    pip install pyserial
"""

from __future__ import annotations

import argparse
import sys
import time
import zlib

VID, PID = 0x0483, 0x5740
BAUD = 115200


def require_serial():
    try:
        import serial                                    # noqa: F401
        from serial.tools import list_ports              # noqa: F401
    except ImportError:
        print("error: pyserial is required:  pip install pyserial",
              file=sys.stderr)
        sys.exit(1)


def find_port(explicit):
    from serial.tools import list_ports
    if explicit:
        return explicit
    for p in list_ports.comports():
        if p.vid == VID and p.pid == PID:
            return p.device
    return None


def collect(ser, wanted, timeout, quiet=False):
    """Read lines until one starts with any prefix in `wanted`.
    Returns (matched, all_lines)."""
    deadline = time.time() + timeout
    seen, buf = [], b""
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
            if not quiet:
                print(f"        {line}")
            for w in wanted:
                if line.startswith(w):
                    return line, seen
    return None, seen


def send(ser, text):
    ser.reset_input_buffer()
    ser.write(b"\r\n" + text.encode() + b"\r\n")
    ser.flush()


class Results:
    def __init__(self):
        self.rows = []

    def add(self, name, ok, detail=""):
        self.rows.append((name, ok, detail))
        mark = "PASS" if ok else "FAIL"
        print(f"    -> {mark}  {detail}\n")

    def report(self):
        print("=" * 62)
        width = max(len(r[0]) for r in self.rows)
        for name, ok, detail in self.rows:
            print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
        print("=" * 62)
        bad = [r for r in self.rows if not r[1]]
        if bad:
            print(f"{len(bad)} of {len(self.rows)} checks FAILED. "
                  f"Do not use sheppard_flash.py until these pass.")
            return 1
        print(f"All {len(self.rows)} checks passed. "
              f"The safety gates work; sheppard_flash.py is safe to use.")
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default=None, help="COM port; auto-detected if omitted")
    args = ap.parse_args()

    require_serial()
    import serial

    port = find_port(args.port)
    if port is None:
        print("error: no Sheppard virtual COM port found.\n"
              "       Close Tera Term first -- Windows only lets one program\n"
              "       open a COM port at a time.", file=sys.stderr)
        return 1

    print(f"port: {port}\n")
    r = Results()

    with serial.Serial(port, BAUD, timeout=0.2, write_timeout=10.0) as ser:

        # --- baseline: what is running now? -------------------------------
        print("[0] baseline: read the current build identity")
        send(ser, "ver")
        line, seen = collect(ser, ["  boot attempts"], 3.0)
        baseline = [s for s in seen if "built" in s]
        r.add("board responds to `ver`", bool(baseline),
              baseline[0] if baseline else "no response")
        if not baseline:
            return r.report()

        # --- 1: size too small --------------------------------------------
        print("[1] reject an image that is too small (100 bytes)")
        send(ser, "fw 100 0")
        line, _ = collect(ser, ["FWABORT", "FWREADY"], 3.0)
        r.add("tiny image refused",
              line is not None and line.startswith("FWABORT size-out-of-range"),
              line or "timeout")

        # --- 2: size too large --------------------------------------------
        print("[2] reject an image larger than the staging buffer")
        send(ser, "fw 999999 0")
        line, _ = collect(ser, ["FWABORT", "FWREADY"], 3.0)
        r.add("oversize image refused",
              line is not None and line.startswith("FWABORT size-out-of-range"),
              line or "timeout")

        # --- 3: wrong CRC --------------------------------------------------
        # THE important one. This gate is all that stands between a corrupted
        # transfer and a mass erase.
        print("[3] reject a transfer whose CRC does not match  <-- the critical gate")
        payload = bytes([0xA5]) * 4096
        send(ser, "fw 4096 deadbeef")
        line, _ = collect(ser, ["FWREADY", "FWABORT"], 3.0)
        if line and line.startswith("FWREADY"):
            ser.write(payload)
            ser.flush()
            line, _ = collect(ser, ["FWCRC", "FWABORT", "FWPROG"], 10.0)
            r.add("bad CRC refused",
                  line is not None and line.startswith("FWCRC bad"),
                  line or "timeout")
        else:
            r.add("bad CRC refused", False, f"never got FWREADY: {line}")

        # --- 4: correct CRC, but the payload is not firmware ---------------
        print("[4] accept the CRC but reject a payload that is not a firmware image")
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        send(ser, f"fw 4096 {crc:08x}")
        line, _ = collect(ser, ["FWREADY", "FWABORT"], 3.0)
        if line and line.startswith("FWREADY"):
            ser.write(payload)
            ser.flush()
            line, seen = collect(ser, ["FWVEC", "FWPROG", "FWABORT"], 10.0)
            saw_crc_ok = any(s.startswith("FWCRC ok") for s in seen)
            ok = (line is not None and line.startswith("FWVEC bad") and saw_crc_ok)
            r.add("junk payload refused by vector check", ok, line or "timeout")
        else:
            r.add("junk payload refused by vector check", False,
                  f"never got FWREADY: {line}")

        # --- 5: transfer abandoned half way --------------------------------
        print("[5] recover from a transfer that stops part-way (takes ~7 s)")
        send(ser, "fw 4096 00000000")
        line, _ = collect(ser, ["FWREADY", "FWABORT"], 3.0)
        if line and line.startswith("FWREADY"):
            ser.write(bytes(100))               # 100 bytes, then silence
            ser.flush()
            line, _ = collect(ser, ["FWABORT"], 12.0)
            r.add("abandoned transfer times out",
                  line is not None and line.startswith("FWABORT timeout"),
                  line or "timeout")
        else:
            r.add("abandoned transfer times out", False,
                  f"never got FWREADY: {line}")

        # --- 6: still the same firmware, still alive -----------------------
        print("[6] confirm the board is untouched and still responsive")
        send(ser, "ver")
        line, seen = collect(ser, ["  boot attempts"], 3.0)
        after = [s for s in seen if "built" in s]
        same = bool(after) and after[0] == baseline[0]
        r.add("flash untouched, board alive", same,
              after[0] if after else "no response")

    return r.report()


if __name__ == "__main__":
    sys.exit(main())
