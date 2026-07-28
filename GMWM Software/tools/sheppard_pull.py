#!/usr/bin/env python3
"""
sheppard_pull.py -- download records from the Sheppard board over USB CDC.

The microSD card is soldered to the board and there is no separate reader, so
this is the only path from instrument to analysis.  It drives the firmware's
`ls` and `get` commands and verifies every byte on arrival.

    python sheppard_pull.py list
    python sheppard_pull.py get r45944_smoke_100Hz.sdat -d "..\\..\\Test Datasets"
    python sheppard_pull.py all -d "..\\..\\Test Datasets"

VERIFICATION
    The firmware sends the file's CRC-32 in the BEGIN line, before any payload,
    and repeats it in the END line.  Checking the first against the bytes
    actually received is an end-to-end test of card, FATFS, USB and host
    together.  It is independent of the per-block CRCs inside the .sdat, which
    only prove the blocks were correct when written -- both must pass before a
    record is considered landed, so `get` runs sdat.verify afterwards when
    sdat.py is importable.

PORT SELECTION
    The board enumerates as a USB CDC device.  With no --port given, the first
    port whose VID:PID or description looks like an ST CDC device is used, and
    if exactly one serial port exists that one is used regardless.  Close the
    GUI console first: a COM port cannot be open twice.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import zlib

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial is required:  pip install pyserial", file=sys.stderr)
    raise SystemExit(2)

ST_VID = 0x0483
BEGIN = b"xfer: begin "
END = b"xfer: end "

# The firmware blocks for SHEPPARD_CONSOLE_CDC_TIMEOUT_MS on a stalled endpoint
# and the SD card can stall for tens of ms, so the host must be more patient
# than any single stall but not so patient that a dead link hangs the session.
READ_TIMEOUT_S = 10.0


def pick_port(explicit: str | None) -> str:
    if explicit:
        return explicit
    ports = list(list_ports.comports())
    if not ports:
        raise RuntimeError("no serial ports found; is the board plugged in?")
    for p in ports:
        if p.vid == ST_VID:
            return p.device
    for p in ports:
        blob = f"{p.description} {p.manufacturer or ''}".lower()
        if "stm" in blob or "cdc" in blob or "virtual com" in blob:
            return p.device
    if len(ports) == 1:
        return ports[0].device
    raise RuntimeError(
        "could not identify the board.  Ports seen:\n  "
        + "\n  ".join(f"{p.device}  {p.description}" for p in ports)
        + "\nPass --port explicitly.")


class Board:
    def __init__(self, port: str, verbose: bool = False):
        self.verbose = verbose
        self.ser = serial.Serial(port, baudrate=115200, timeout=READ_TIMEOUT_S)
        self.port = port
        time.sleep(0.2)
        self.ser.reset_input_buffer()

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def send(self, line: str) -> None:
        if self.verbose:
            print(f"> {line}")
        self.ser.write((line + "\r\n").encode())
        self.ser.flush()

    def read_line(self) -> bytes:
        """One CRLF-terminated line.  Returns b'' on timeout."""
        return self.ser.readline()

    def read_exact(self, n: int, progress=None) -> bytes:
        """Read exactly n bytes.  pyserial's read() can return short, so loop.

        A short read that never completes is a stalled transfer, not a slow
        one: the timeout applies per read() call, so if a call returns nothing
        the link has genuinely gone quiet."""
        out = bytearray()
        last_report = 0
        while len(out) < n:
            chunk = self.ser.read(min(65536, n - len(out)))
            if not chunk:
                raise RuntimeError(
                    f"link went quiet after {len(out)} of {n} bytes")
            out += chunk
            if progress and len(out) - last_report > 262144:
                last_report = len(out)
                progress(len(out), n)
        if progress:
            progress(len(out), n)
        return bytes(out)

    def drain(self, settle_s: float = 0.4) -> list[bytes]:
        """Collect whatever the board has to say until it goes quiet."""
        lines, t_end = [], time.time() + settle_s
        old = self.ser.timeout
        self.ser.timeout = 0.15
        try:
            while time.time() < t_end:
                ln = self.ser.readline()
                if ln:
                    lines.append(ln)
                    t_end = time.time() + settle_s
        finally:
            self.ser.timeout = old
        return lines


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n} B"


def cmd_list(board: Board, args) -> int:
    board.send("ls")
    for ln in board.drain(0.8):
        sys.stdout.write(ln.decode("utf-8", "replace"))
    return 0


def parse_ls(board: Board) -> list[tuple[str, int]]:
    """Filenames and sizes in kB, from the `ls` output."""
    board.send("ls")
    out = []
    for ln in board.drain(0.8):
        s = ln.decode("utf-8", "replace").rstrip()
        if s.startswith("ls:") or not s.strip():
            continue
        parts = s.split()
        if len(parts) >= 3 and parts[-1] == "kB":
            try:
                out.append((parts[0], int(parts[-2]) * 1024))
            except ValueError:
                pass
    return out


def pull_one(board: Board, name: str, dest_dir: str,
             overwrite: bool = False) -> tuple[bool, str]:
    """Download one file.  Returns (ok, message)."""
    out_path = os.path.join(dest_dir, os.path.basename(name))
    if os.path.exists(out_path) and not overwrite:
        return True, f"skipped, already present ({out_path})"

    board.ser.reset_input_buffer()
    board.send(f"get {name}")

    # Wait for the BEGIN line.  Anything before it is console chatter -- the
    # echoed command, a lazy mount message -- and is ignored rather than
    # treated as an error, because the board is entitled to talk.
    deadline = time.time() + 30.0
    begin = None
    while time.time() < deadline:
        ln = board.read_line()
        if not ln:
            continue
        if ln.startswith(BEGIN):
            begin = ln
            break
        s = ln.decode("utf-8", "replace").rstrip()
        if s.startswith("get:") and ("usage" in s or ":" in s and "bytes" not in s):
            # An error line such as "get: SHEPPARD/x: no such file"
            if "no such" in s or "error" in s or "held by" in s or "record is open" in s:
                return False, s
    if begin is None:
        return False, "no 'xfer: begin' line (timed out)"

    try:
        _, _, rest = begin.decode("ascii", "replace").partition("xfer: begin ")
        size = int(rest.split()[0])
    except (ValueError, IndexError):
        return False, f"malformed begin line: {begin!r}"

    t0 = time.time()

    def progress(done, total):
        el = max(time.time() - t0, 1e-3)
        pct = 100.0 * done / total if total else 100.0
        sys.stdout.write(f"\r    {pct:5.1f}%  {_fmt_bytes(done)} / "
                         f"{_fmt_bytes(total)}  {done / el / 1024:.0f} kB/s   ")
        sys.stdout.flush()

    try:
        payload = board.read_exact(size, progress)
    except RuntimeError as e:
        sys.stdout.write("\n")
        return False, str(e)
    sys.stdout.write("\n")

    # The trailer carries the CRC the board accumulated over exactly the bytes
    # it handed to the endpoint, so comparing it against the bytes we received
    # tests card, FATFS, USB and host together.
    tail = board.read_line()
    if not tail.startswith(END):
        return False, f"missing 'xfer: end' (got {tail!r})"
    try:
        want_crc = int(tail.decode("ascii", "replace").split()[2], 16)
    except (ValueError, IndexError):
        return False, f"malformed end line: {tail!r}"

    got_crc = zlib.crc32(payload) & 0xFFFFFFFF
    if got_crc != want_crc:
        return False, (f"CRC mismatch: board 0x{want_crc:08X}, "
                       f"received 0x{got_crc:08X} over {len(payload)} bytes")

    os.makedirs(dest_dir, exist_ok=True)
    tmp = out_path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(payload)
    os.replace(tmp, out_path)

    board.drain(0.3)                       # the board's own timing summary
    el = time.time() - t0
    return True, (f"{_fmt_bytes(size)} in {el:.1f}s "
                  f"({size / el / 1024:.0f} kB/s), CRC 0x{got_crc:08X} ok")


def _verify_sdat(path: str) -> str:
    """Run the .sdat structural check if sdat.py is importable."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import sdat
    except Exception as e:
        return f"    (sdat.py not available: {e})"
    try:
        res = sdat.verify(path)
    except Exception as e:
        return f"    sdat verify FAILED: {e}"
    if res.ok:
        return (f"    sdat verify PASS: {res.n_blocks} blocks, "
                f"{res.n_packets} samples, {res.f_board_hz:.3f} Hz")
    lines = [f"    sdat verify FAIL: {len(res.problems)} problem(s)"]
    lines += [f"      ! {p}" for p in res.problems[:5]]
    return "\n".join(lines)


def cmd_get(board: Board, args) -> int:
    rc = 0
    for name in args.name:
        print(f"{name}")
        ok, msg = pull_one(board, name, args.dest, args.overwrite)
        print(f"    {msg}")
        if ok and not args.no_verify:
            out_path = os.path.join(args.dest, os.path.basename(name))
            if os.path.exists(out_path):
                print(_verify_sdat(out_path))
        if not ok:
            rc = 1
    return rc


def cmd_all(board: Board, args) -> int:
    files = parse_ls(board)
    if not files:
        print("no files listed by the board")
        return 1
    print(f"{len(files)} file(s), {_fmt_bytes(sum(s for _, s in files))} total\n")
    rc = 0
    for name, _ in files:
        print(f"{name}")
        ok, msg = pull_one(board, name, args.dest, args.overwrite)
        print(f"    {msg}")
        if ok and not args.no_verify and name.endswith(".sdat"):
            out_path = os.path.join(args.dest, os.path.basename(name))
            if os.path.exists(out_path):
                print(_verify_sdat(out_path))
        if not ok:
            rc = 1
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Download Sheppard records over the USB CDC link.")
    ap.add_argument("--port", help="COM port (auto-detected if omitted)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="list records on the card")
    p.set_defaults(func=cmd_list)

    def add_dl(p):
        p.add_argument("-d", "--dest", default=".", help="destination directory")
        p.add_argument("--overwrite", action="store_true")
        p.add_argument("--no-verify", action="store_true",
                       help="skip the .sdat structural check after download")

    p = sub.add_parser("get", help="download named files")
    p.add_argument("name", nargs="+")
    add_dl(p)
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("all", help="download everything the board lists")
    add_dl(p)
    p.set_defaults(func=cmd_all)

    args = ap.parse_args(argv)

    try:
        port = pick_port(args.port)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"port {port}")
    board = Board(port, verbose=args.verbose)
    try:
        return args.func(board, args)
    except serial.SerialException as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        board.close()


if __name__ == "__main__":
    sys.exit(main())
