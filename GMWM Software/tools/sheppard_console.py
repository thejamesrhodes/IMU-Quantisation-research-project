#!/usr/bin/env python3
"""
sheppard_console.py -- companion app for the Sheppard IMU board.

One window that replaces Tera Term and the command-line scripts. Five tabs
across the top, a left rail that does not change with them:

  Console    terminal with history, timestamps, hex view, find, file logging
  Records    the SD card: list, download with CRC verification, delete
  Sequence   compose a campaign plan, upload it line by line, arm it
  Analysis   run analyse.py / figures.py / offset_fit.py against the local
             records, with live output and a Stop button, and read
             summary.csv as a sortable table rather than in Notepad
  Figures    render the PNGs in the application, with the TN-20 §6 captions

The rail keeps Flash, the macro buttons and the link trace visible on every
tab, because an instrument whose connection indicator disappears when you
change view is an instrument you stop trusting.

Ctrl+1..5 move between tabs.

With this open, STM32CubeIDE only has to build. Edit, Ctrl+B, press Flash.

Analysis and Figures are optional. They are the only part of the app that
wants matplotlib or Pillow anywhere near it; if either import fails the two
tabs are simply absent and the reason appears under the Go menu. A console
that will not open because a plotting library is missing would be a poor
trade on a night when the only job is to check the board is still logging.

    pip install pyserial
    python sheppard_console.py

Only one program can hold a COM port on Windows. Close Tera Term before
starting this, and do not run the command-line scripts while it is open.

Settings are remembered in ~/.sheppard_console.json. Delete it to start clean.

---------------------------------------------------------------------------
On the artwork
---------------------------------------------------------------------------
The emblem in the header is a mid-tread uniform quantiser: the grey diagonal
is the true input, the amber staircase is what a rate register can actually
represent, and the red stub joining them is the instantaneous quantisation
error e = Q(x) - x. That error, and specifically the claim that it presents
at a -1/2 Allan slope and is absorbed into fitted ARW, is the whole subject
of this project -- so the board's own instrument panel may as well show it.

The dot sweeps only while the board is connected. Turn it off in View if it
is distracting.

The board is named after W. F. Sheppard, whose 1898 paper gave the -c^2/12
correction for the variance of grouped data -- the same Delta^2/12 that sits
in the header.
"""

from __future__ import annotations

import glob
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import zlib
from tkinter import filedialog, font as tkfont, messagebox

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial is required:  pip install pyserial", file=sys.stderr)
    sys.exit(1)

# The palette and the shared widgets live in console_theme so that the
# analysis panels can use them without importing the console back. Every name
# the rest of this file used before still resolves; nothing moved except where
# it is defined.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from console_theme import (                                   # noqa: E402
    C_DIM, C_EDGE, C_ERROR, C_FAINT, C_HILITE, C_INK, C_OK, C_PANEL,
    C_SENT, C_SIGNAL, C_TERM, C_TEXT, C_TRUE, F_MONO, F_UI,
    FlatButton, Sparkline, StepBar, TabStrip, sep,
)

# The analysis and figure panels are optional: they are the only part of the
# app that wants matplotlib anywhere near it, and a console that will not open
# because a plotting library is missing would be a poor trade. If the import
# fails the tabs are simply absent and the reason is printed once.
try:
    from console_analysis import AnalysisPanel, FiguresPanel  # noqa: E402
    ANALYSIS_ERROR = ""
except Exception as _e:                                       # noqa: BLE001
    AnalysisPanel = FiguresPanel = None
    ANALYSIS_ERROR = f"{type(_e).__name__}: {_e}"


# ===========================================================================
# Board identity and protocol constants
# ===========================================================================

VID, PID = 0x0483, 0x5740          # USB identity, not a COM number
BAUD = 115200                      # ignored by USB CDC; pyserial wants a value

FW_NAME_PREFIX = "sheppard"        # must match SHEPPARD_FW_NAME

FLASH_CHUNK = 4096
READY_TIMEOUT = 5.0
RESULT_TIMEOUT = 30.0
RECONNECT_TIMEOUT = 40.0

SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".sheppard_console.json")

DEFAULT_MACROS = [
    ("ver", "ver"),
    ("help", "help"),
    ("scan", "scan"),
    ("usb", "usb"),
    ("sd", "sd"),
    ("rate 10s", "rate"),
    ("rate 10m", "rate 600"),
    ("rate stop", "rate stop"),
]


# ===========================================================================
# Settings
# ===========================================================================

def load_settings():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                     # noqa: BLE001
        return {}


def save_settings(d):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=2)
    except Exception:                                     # noqa: BLE001
        pass


# ===========================================================================
# Locating the project and its build output
#
# Deliberately does not trust __file__ alone: depending on how the script is
# launched -- shortcut, IDLE, older Python, an odd working directory --
# __file__ can be relative, and dirname(dirname(...)) then resolves somewhere
# unrelated. Gather candidates, walk upward from each, accept the first that
# actually contains the project.
# ===========================================================================

PROJECT_MARKER = os.path.join("Core", "Inc", "sheppard_config.h")


def find_project_root():
    candidates = []
    try:
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    if sys.argv and sys.argv[0]:
        candidates.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    candidates.append(os.getcwd())

    seen = set()
    for start in candidates:
        d = start
        for _ in range(6):
            if not d or d in seen:
                break
            seen.add(d)
            if os.path.isfile(os.path.join(d, PROJECT_MARKER)):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return None


def workspace_root():
    """The folder holding the whole project, not just the firmware.

    find_project_root() locates the directory containing Core/Inc/... which is
    the FIRMWARE root (`GMWM Software`). Records, figures and notes live one
    level above it, alongside the firmware rather than inside it.
    """
    fw = find_project_root()
    if fw:
        parent = os.path.dirname(fw)
        if parent and os.path.isdir(parent):
            return parent
        return fw
    return os.getcwd()


def default_dir(name):
    """A project sub-directory, created on demand.

    Anchored on the project root rather than the current working directory:
    the app is launched from a shortcut as often as from a shell, and the two
    give different answers. Records and figures then always land in the same
    place however the console was started, which matters when the analysis
    path has to be reproducible.
    """
    d = os.path.join(workspace_root(), name)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def tool_script(name):
    """Absolute path to a sibling tool such as analyse.py.

    __file__ is NOT reliable here. Launched from a shortcut it can be a bare
    filename, and os.path.abspath() then joins it to the current working
    directory -- which is how the analyser came to be looked for on the
    Desktop. The firmware root is found by marker file, so derive from that
    first and only fall back to __file__ afterwards.
    """
    cands = []
    fw = find_project_root()
    if fw:
        cands.append(os.path.join(fw, "tools", name))
    try:
        cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  name))
    except NameError:
        pass
    if sys.argv and sys.argv[0]:
        cands.append(os.path.join(
            os.path.dirname(os.path.abspath(sys.argv[0])), name))
    cands.append(os.path.join(os.getcwd(), name))

    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def guess_bin(root):
    """Newest .bin under a build directory. Survives a project rename, which
    a hard-coded filename would not."""
    if not root:
        return ""
    hits = []
    for cfg in ("Debug", "Release"):
        hits.extend(glob.glob(os.path.join(root, cfg, "*.bin")))
    return max(hits, key=os.path.getmtime) if hits else ""


def newest_source(root):
    newest_t, newest_f = 0.0, None
    if not root:
        return newest_t, newest_f
    for sub in ("Core", "USB_DEVICE", "FATFS"):
        for dirpath, _dirs, files in os.walk(os.path.join(root, sub)):
            for f in files:
                if f.endswith((".c", ".h", ".s")):
                    p = os.path.join(dirpath, f)
                    try:
                        t = os.path.getmtime(p)
                    except OSError:
                        continue
                    if t > newest_t:
                        newest_t, newest_f = t, p
    return newest_t, newest_f


# ===========================================================================
# Serial plumbing
#
# One background thread owns the port: opens it when the board appears, reads
# from it, closes it when the board goes away. Nothing else touches _ser.
# Received data reaches the GUI through a queue, because Tk widgets may only
# be touched from the main thread.
# ===========================================================================

class Board:
    def __init__(self, ui_queue: queue.Queue):
        self.ui = ui_queue
        self._ser = None
        self._stop = threading.Event()
        self.connected = threading.Event()
        self.port_name = None
        self.rx_bytes = 0
        self.tx_bytes = 0

        self._proto = queue.Queue()
        self._proto_on = threading.Event()

        # Line assembly is done on BYTES, not on a decoded string.
        #
        # `get` announces itself with a text line and then sends raw payload
        # with no framing, and both can land in a single serial read(). Decoding
        # the chunk to str before splitting would run the payload through a
        # utf-8 decoder, and the bytes could not be recovered afterwards. So the
        # buffer stays as bytes and each completed line is decoded on its own.
        self._rawbuf = b""

        # Transfer capture. States: "idle" (normal console), "await" (armed,
        # watching for the begin line), "capture" (consuming payload).
        self._xfer_state = "idle"
        self._xfer_buf = bytearray()
        self._xfer_want = 0
        self._xfer_name = None
        self._xfer_err = None
        self._xfer_lock = threading.Lock()
        self.xfer_started = threading.Event()
        self.xfer_done = threading.Event()

        self._thread = threading.Thread(target=self._io_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2.0)

    @staticmethod
    def _find_port():
        for p in list_ports.comports():
            if p.vid == VID and p.pid == PID:
                return p.device
        return None

    def _open(self, port):
        try:
            self._ser = serial.Serial(port, BAUD, timeout=0.05,
                                      write_timeout=10.0)
        except Exception:                                 # noqa: BLE001
            self._ser = None
            self.ui.put(("status", ("busy",
                                    f"{port} is held by another program")))
            return False
        self.port_name = port
        self.connected.set()
        self.ui.put(("status", ("connected", port)))
        self.ui.put(("connected", port))
        return True

    def _close(self):
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:                             # noqa: BLE001
                pass
        self._ser = None
        was = self.connected.is_set()
        self.connected.clear()
        self.port_name = None
        if was:
            self.ui.put(("status", ("waiting", "board disconnected")))
            self.ui.put(("disconnected", None))

    def _io_loop(self):
        backoff = 0.5
        while not self._stop.is_set():
            if self._ser is None:
                port = self._find_port()
                if port is None:
                    self.ui.put(("status", ("waiting", "waiting for the board")))
                    time.sleep(0.4)
                    continue
                if not self._open(port):
                    time.sleep(backoff)
                    backoff = min(backoff + 0.5, 3.0)
                    continue
                backoff = 0.5
            try:
                data = self._ser.read(2048)
            except Exception:                             # noqa: BLE001
                self._close()
                continue
            if data:
                self.rx_bytes += len(data)
                self._feed(data)

    def _feed(self, data: bytes):
        while data:
            if self._xfer_state == "capture":
                data = self._xfer_take(data)
                continue

            self._rawbuf += data
            data = b""
            emit = bytearray()

            while b"\n" in self._rawbuf:
                raw, self._rawbuf = self._rawbuf.split(b"\n", 1)
                emit += raw + b"\n"
                line = raw.decode("utf-8", errors="replace").strip()
                if line and self._proto_on.is_set():
                    self._proto.put(line)

                if self._xfer_state == "await" and line.startswith("xfer: begin "):
                    self._begin_capture(line)
                    if self._xfer_state == "capture":
                        # Everything still in the buffer after the begin line is
                        # payload, not text. Hand it straight to the capture and
                        # go round again.
                        data = bytes(self._rawbuf)
                        self._rawbuf = b""
                        break

            if self._xfer_state == "idle":
                # Normal console: show partial lines too, so prompts and
                # progress that arrive without a newline are not held back.
                self.ui.put(("rx", bytes(emit) + self._rawbuf))
                self._rawbuf = b""
            elif emit:
                # Armed: only complete lines go to the display, because the
                # bytes after the begin line are payload.
                self.ui.put(("rx", bytes(emit)))

    def _begin_capture(self, line: str):
        parts = line.split()
        try:
            self._xfer_want = int(parts[2])
            self._xfer_name = parts[3] if len(parts) > 3 else "?"
        except (ValueError, IndexError):
            self._xfer_err = f"malformed begin line: {line}"
            self._xfer_state = "idle"
            self.xfer_done.set()
            return
        with self._xfer_lock:
            self._xfer_buf = bytearray()
        self._xfer_state = "capture"
        self.xfer_started.set()

    def _xfer_take(self, data: bytes) -> bytes:
        """Consume payload; return whatever is left over once it is complete."""
        with self._xfer_lock:
            need = self._xfer_want - len(self._xfer_buf)
            self._xfer_buf += data[:need]
            complete = len(self._xfer_buf) >= self._xfer_want
        rest = data[need:] if len(data) > need else b""
        if complete:
            # Back to line mode so the trailing `xfer: end <crc>` is parsed
            # normally -- it can arrive in the same chunk as the last payload.
            self._xfer_state = "idle"
            self.xfer_done.set()
        return rest

    # --- transfer control, called from a worker thread ---------------------

    def xfer_arm(self):
        self._xfer_state = "await"
        self._xfer_want = 0
        self._xfer_name = None
        self._xfer_err = None
        with self._xfer_lock:
            self._xfer_buf = bytearray()
        self.xfer_started.clear()
        self.xfer_done.clear()

    def xfer_cancel(self):
        self._xfer_state = "idle"
        self.xfer_started.clear()
        self.xfer_done.clear()

    def xfer_progress(self):
        with self._xfer_lock:
            return len(self._xfer_buf), self._xfer_want

    def xfer_payload(self) -> bytes:
        with self._xfer_lock:
            return bytes(self._xfer_buf)

    @property
    def xfer_error(self):
        return self._xfer_err

    def send_line(self, text: str) -> bool:
        return self.write_raw(text.encode() + b"\r\n")

    def write_raw(self, data: bytes) -> bool:
        ser = self._ser
        if ser is None:
            return False
        try:
            ser.write(data)
            ser.flush()
            self.tx_bytes += len(data)
            return True
        except Exception:                                 # noqa: BLE001
            self._close()
            return False

    def proto_begin(self):
        while not self._proto.empty():
            try:
                self._proto.get_nowait()
            except queue.Empty:
                break
        self._proto_on.set()

    def proto_end(self):
        self._proto_on.clear()

    def expect(self, prefixes, timeout):
        deadline = time.time() + timeout
        seen = []
        while time.time() < deadline:
            try:
                line = self._proto.get(timeout=0.1)
            except queue.Empty:
                continue
            seen.append(line)
            for p in prefixes:
                if line.startswith(p):
                    return line, seen
        return None, seen

    def wait_disconnect(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.connected.is_set():
                return True
            time.sleep(0.05)
        return False

    def wait_connect(self, timeout):
        return self.connected.wait(timeout)


# ===========================================================================
# Artwork
# ===========================================================================

class QuantiserGlyph(tk.Canvas):
    """A mid-tread uniform quantiser, drawn live.

    Grey diagonal   - the true continuous input x
    Amber staircase - Q(x), what a 16-bit rate register can represent
    Red stub        - the instantaneous error e = Q(x) - x

    The staircase carries the connection state in its colour, so the emblem
    and the status light are the same object. The sweeping dot runs only
    while the board is connected -- a still panel means a still link.
    """

    STEPS = 7

    def __init__(self, master, width=132, height=44, **kw):
        super().__init__(master, width=width, height=height, bg=C_PANEL,
                         highlightthickness=0, **kw)
        self.w, self.h = width, height
        self.colour = C_DIM
        self.phase = 0.0
        self.animate = True
        self._dot = None
        self._err = None
        self._tick = None
        self._draw_static()

    def _draw_static(self):
        self.delete("static")
        pad = 5
        w, h = self.w - 2 * pad, self.h - 2 * pad

        # true input: x -> x
        self.create_line(pad, self.h - pad, pad + w, pad,
                         fill=C_TRUE, width=1, tags="static")

        # quantiser: mid-tread, STEPS levels
        n = self.STEPS
        for i in range(n):
            x0 = pad + i * w / n
            x1 = pad + (i + 1) * w / n
            y = self.h - pad - (i + 0.5) * h / n
            self.create_line(x0, y, x1, y, fill=self.colour, width=2,
                             tags="static", capstyle="round")
            if i < n - 1:
                y2 = self.h - pad - (i + 1.5) * h / n
                self.create_line(x1, y, x1, y2, fill=self.colour, width=1,
                                 tags="static")

    def set_state(self, colour):
        if colour != self.colour:
            self.colour = colour
            self._draw_static()

    def step(self, dt):
        """Advance the sampling point. Called from the GUI timer."""
        for item in (self._dot, self._err, self._tick):
            if item:
                self.delete(item)
        self._dot = self._err = self._tick = None

        if not self.animate:
            return

        self.phase = (self.phase + dt / 7.0) % 1.0
        pad = 5
        w, h = self.w - 2 * pad, self.h - 2 * pad
        t = self.phase

        x = pad + t * w
        y_true = self.h - pad - t * h
        level = min(self.STEPS - 1, int(t * self.STEPS))
        y_q = self.h - pad - (level + 0.5) * h / self.STEPS

        # the error itself: the point of the whole exercise
        self._err = self.create_line(x, y_true, x, y_q, fill=C_ERROR, width=1)
        self._tick = self.create_oval(x - 1.5, y_true - 1.5,
                                      x + 1.5, y_true + 1.5,
                                      fill=C_TRUE, outline="")
        self._dot = self.create_oval(x - 2.5, y_q - 2.5, x + 2.5, y_q + 2.5,
                                     fill=self.colour, outline="")


# StepBar, Sparkline, FlatButton and sep() now live in console_theme.py and
# are imported at the top of this file. QuantiserGlyph stays here: it is not
# a reusable widget, it is this application's emblem.


# ===========================================================================
# Terminal line colouring
# ===========================================================================

def tag_for_line(line: str):
    s = line.strip()
    if s.startswith(("FWCRC ok", "FWVEC ok")):
        return "good"
    if s.startswith(("FWABORT", "FWFAIL", "FWCRC bad", "FWVEC bad")):
        return "bad"
    if s.startswith(("FWREADY", "FWRECV", "FWPROG")):
        return "signal"
    if "[DEAD/UNKNOWN]" in s or "FAIL" in s:
        return "bad"
    if s.endswith("PASS") or ": PASS" in s:
        return "good"
    if s.startswith(("---", "===", "====")):
        return "dim"
    return None


# ===========================================================================
# Application
# ===========================================================================

class DatasetPanel(tk.Frame):
    """File manager for the records on the SD card.

    Was a separate Toplevel; now a tab. The reason for the original split has
    not gone away -- a transfer must not have console traffic interleaved with
    it, and the Board reader thread switches to byte capture for the duration
    so that nothing of the payload reaches the terminal widget. That is a
    property of the Board object, not of the window, and it survives the move.
    What the move buys is that the card listing, the plan and the figures are
    now one application rather than four windows to arrange.

    Threading: the transfer runs on a worker; the panel polls its own state
    with after() rather than routing through the App's UI queue, so nothing in
    the existing console path changes.
    """

    POLL_MS = 80

    def __init__(self, master, app):
        super().__init__(master, bg=C_INK)
        self.app = app
        self.board = app.board

        self._lock = threading.Lock()
        self._log_q = []
        self._prog = (0, 0)
        self._status = ""
        self._busy = False
        self._finished = False
        self._files = []
        self._worker = None

        self._build()
        self.after(self.POLL_MS, self._poll)

    @property
    def dest(self):
        """One folder, owned by the App, so the Records tab downloads into the
        same place the Analysis tab reads from. Two settings keys drifting
        apart was the failure mode this replaces."""
        return self.app.dataset_dir

    # --- layout -----------------------------------------------------------

    def _build(self):
        head = tk.Frame(self, bg=C_PANEL)
        head.pack(fill="x")

        tk.Label(head, text="SD CARD", bg=C_PANEL, fg=C_DIM,
                 font=(F_UI, 8, "bold")).pack(side="left", padx=(14, 8),
                                              pady=9)
        self.sum_var = tk.StringVar(value="")
        tk.Label(head, textvariable=self.sum_var, bg=C_PANEL, fg=C_SIGNAL,
                 font=(F_MONO, 9)).pack(side="left", pady=9)

        bar = tk.Frame(self, bg=C_INK)
        bar.pack(fill="x", padx=10, pady=(9, 4))
        self.b_refresh = FlatButton(bar, "Refresh", self.refresh, small=True)
        self.b_refresh.pack(side="left", padx=(0, 4))
        self.b_get = FlatButton(bar, "Download selected",
                                self.download_selected, accent=True, small=True)
        self.b_get.pack(side="left", padx=4)
        self.b_all = FlatButton(bar, "Download all new", self.download_new,
                                small=True)
        self.b_all.pack(side="left", padx=4)
        self.b_del = FlatButton(bar, "Delete from card", self.delete_selected,
                                small=True)
        self.b_del.pack(side="left", padx=4)

        sep(bar, horizontal=False).pack(side="left", fill="y", padx=8)
        self.b_ana = FlatButton(bar, "Analyse + figures", self.analyse_selected,
                                small=True)
        self.b_ana.pack(side="left", padx=4)
        FlatButton(bar, "Open figures", self._open_figs,
                   small=True).pack(side="left", padx=4)

        lb = tk.Frame(self, bg=C_EDGE)
        lb.pack(fill="both", expand=True, padx=10, pady=4)
        self.list = tk.Listbox(lb, bg=C_TERM, fg=C_TEXT, bd=0,
                               highlightthickness=0, selectmode="extended",
                               font=(F_MONO, 9), activestyle="none",
                               selectbackground=C_HILITE,
                               selectforeground=C_TEXT)
        self.list.pack(fill="both", expand=True, padx=1, pady=1)

        foot = tk.Frame(self, bg=C_INK)
        foot.pack(fill="x", padx=10, pady=(2, 4))
        self.dest_var = tk.StringVar()
        tk.Label(foot, textvariable=self.dest_var, bg=C_INK, fg=C_DIM,
                 font=(F_MONO, 8), anchor="w").pack(side="left", fill="x",
                                                    expand=True)
        FlatButton(foot, "Change folder...", self._pick_dest,
                   small=True).pack(side="right")
        self._update_dest()

        self.bar = StepBar(self, height=8)
        self.bar.pack(fill="x", padx=10, pady=(2, 2))

        self.stat_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.stat_var, bg=C_INK, fg=C_DIM,
                 font=(F_MONO, 8), anchor="w").pack(fill="x", padx=12,
                                                    pady=(0, 8))

    def _update_dest(self):
        self.dest_var.set(f"→ {self.dest}")

    def _pick_dest(self):
        d = filedialog.askdirectory(initialdir=self.dest,
                                    title="Where to save records")
        if d:
            self.app.set_dataset_dir(d)
            self._update_dest()
            self.refresh()

    # --- worker plumbing --------------------------------------------------

    def _log(self, text):
        with self._lock:
            self._log_q.append(text)

    def _set(self, status=None, prog=None):
        with self._lock:
            if status is not None:
                self._status = status
            if prog is not None:
                self._prog = prog

    def _poll(self):
        with self._lock:
            msgs, self._log_q = self._log_q, []
            status, (got, want) = self._status, self._prog
            finished, self._finished = self._finished, False
        for m in msgs:
            self.app._note(m, "app")
        self.stat_var.set(status)
        self.bar.set(100.0 * got / want if want else 0.0)
        if finished:
            self._done()
        self.after(self.POLL_MS, self._poll)

    def _start(self, fn, *a, needs_board=True):
        if self._busy:
            return
        if needs_board and not self.board.connected.is_set():
            self.stat_var.set("board not connected")
            return
        self._busy = True
        self.app._set_busy(True)
        for b in (self.b_refresh, self.b_get, self.b_all, self.b_del,
                  self.b_ana):
            b.set_enabled(False)
        self._worker = threading.Thread(target=self._wrap, args=(fn,) + a,
                                        daemon=True)
        self._worker.start()

    def _wrap(self, fn, *a):
        try:
            fn(*a)
        except Exception as e:                             # noqa: BLE001
            self._log(f"datasets: {type(e).__name__}: {e}")
            self._set(status=f"failed: {e}")
        finally:
            self.board.proto_end()
            self.board.xfer_cancel()
            # Hand completion back to the main thread via the poll loop rather
            # than calling after() from here. Tk is not thread-safe, and every
            # widget touched by _done() belongs to the main thread.
            with self._lock:
                self._finished = True

    def _done(self):
        self._busy = False
        self.app._set_busy(False)
        for b in (self.b_refresh, self.b_get, self.b_all, self.b_del,
                  self.b_ana):
            b.set_enabled(True)
        self._render()

    # --- listing ----------------------------------------------------------

    def refresh(self):
        self._start(self._ls_worker)

    def _ls_worker(self):
        self._set(status="listing...", prog=(0, 0))
        self.board.proto_begin()
        self.board.send_line("ls")
        line, seen = self.board.expect(["ls: "], 15.0)
        if line is None:
            self._set(status="no reply to ls")
            return

        files = []
        for s in seen:
            parts = s.split()
            if len(parts) >= 3 and parts[-1] == "kB" and not s.startswith("ls:"):
                try:
                    files.append((parts[0], int(parts[-2]) * 1024))
                except ValueError:
                    pass
        with self._lock:
            self._files = files
        self._set(status=f"{len(files)} file(s) on card")

    def _render(self):
        with self._lock:
            files = list(self._files)
        self.list.delete(0, "end")
        total = 0
        for name, size in files:
            total += size
            here = os.path.join(self.dest, name)
            mark = "✓" if os.path.exists(here) else " "
            self.list.insert("end", f" {mark}  {name:<44} {_hsize(size):>10}")
            if mark == "✓":
                self.list.itemconfig("end", foreground=C_DIM)
        self.sum_var.set(f"{len(files)} records, {_hsize(total)}   "
                         f"(✓ = already downloaded)")

    def _selected(self):
        with self._lock:
            files = list(self._files)
        return [files[i] for i in self.list.curselection() if i < len(files)]

    # --- download ---------------------------------------------------------

    def download_selected(self):
        sel = self._selected()
        if not sel:
            self.stat_var.set("nothing selected")
            return
        self._start(self._dl_worker, sel, True)

    def download_new(self):
        with self._lock:
            files = list(self._files)
        todo = [f for f in files
                if not os.path.exists(os.path.join(self.dest, f[0]))]
        if not todo:
            self.stat_var.set("nothing new to download")
            return
        self._start(self._dl_worker, todo, False)

    def _dl_worker(self, files, overwrite):
        os.makedirs(self.dest, exist_ok=True)
        for i, (name, _size) in enumerate(files, 1):
            out = os.path.join(self.dest, name)
            if os.path.exists(out) and not overwrite:
                continue
            self._set(status=f"[{i}/{len(files)}] {name}: starting")
            ok, msg = self._pull_one(name, out)
            self._log(f"datasets: {name}: {msg}")
            self._set(status=f"[{i}/{len(files)}] {name}: {msg}")
            if not ok:
                return
        self._set(status="done", prog=(1, 1))

    def _pull_one(self, name, out):
        board = self.board
        board.proto_begin()
        board.xfer_arm()
        if not board.send_line(f"get {name}"):
            return False, "write failed"

        # Either capture starts, or the board refuses with a `get:` line.
        deadline = time.time() + 30.0
        while time.time() < deadline:
            if board.xfer_started.is_set() or board.xfer_done.is_set():
                break
            line, _ = board.expect(["get:"], 0.25)
            if line and not line.startswith("get: begin"):
                return False, line
        else:
            return False, "timed out waiting for the transfer to start"

        if board.xfer_error:
            return False, board.xfer_error

        t0 = time.time()
        last_got, last_move = 0, time.time()
        while not board.xfer_done.wait(0.1):
            got, want = board.xfer_progress()
            self._set(prog=(got, want),
                      status=f"{name}  {_hsize(got)} / {_hsize(want)}  "
                             f"{got / max(time.time() - t0, 1e-3) / 1024:.0f} kB/s")
            if got != last_got:
                last_got, last_move = got, time.time()
            elif time.time() - last_move > 20.0:
                return False, f"link went quiet after {got} of {want} bytes"

        payload = board.xfer_payload()
        got, want = board.xfer_progress()
        self._set(prog=(got, want))

        # The trailer carries the CRC the board accumulated over exactly the
        # bytes it handed to the endpoint, so this checks card, FATFS, USB and
        # host in one comparison. It is independent of the per-block CRCs
        # inside the record, which only prove the blocks were correct when
        # they were written.
        line, _ = board.expect(["xfer: end"], 15.0)
        if line is None:
            return False, "no 'xfer: end' trailer"
        try:
            want_crc = int(line.split()[2], 16)
        except (ValueError, IndexError):
            return False, f"malformed trailer: {line}"

        got_crc = zlib.crc32(payload) & 0xFFFFFFFF
        if got_crc != want_crc:
            return False, (f"CRC mismatch: board 0x{want_crc:08X}, "
                           f"received 0x{got_crc:08X}")

        tmp = out + ".part"
        with open(tmp, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, out)

        el = time.time() - t0
        msg = (f"{_hsize(len(payload))} in {el:.1f}s "
               f"({len(payload) / el / 1024:.0f} kB/s), CRC ok")

        extra = _verify_sdat(out)
        if extra:
            msg += " | " + extra
        return True, msg

    # --- analysis ---------------------------------------------------------
    #
    # analyse.py is run as a subprocess rather than imported. It pulls in numpy
    # and matplotlib, which are heavy and which fail in ways that would take the
    # whole console down with them; and running it as a process means the GUI
    # and the command line stay exactly equivalent, so a result you see here is
    # reproducible by typing the same command.

    @property
    def figdir(self):
        return self.app.figdir

    def _open_figs(self):
        """Straight to the Figures tab, which renders them in place. The old
        behaviour -- hand the folder to Explorer -- is still one click away
        from there, and is the fallback if the panel failed to import."""
        if AnalysisPanel is not None:
            self.app.show_tab("figures")
            return
        d = self.figdir
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)                                # noqa: S606  (Windows)
        except AttributeError:
            import subprocess
            subprocess.Popen(["xdg-open", d])

    def analyse_selected(self):
        sel = self._selected()
        if not sel:
            self.stat_var.set("select one or more records first")
            return
        here = [(n, s) for n, s in sel
                if os.path.exists(os.path.join(self.dest, n))]
        if not here:
            self.stat_var.set("download them first — nothing to analyse")
            return
        self._start(self._ana_worker, here, needs_board=False)

    def _ana_worker(self, files):
        import subprocess

        script = tool_script("analyse.py")
        if script is None:
            self._log("analyse: cannot find analyse.py -- it should sit next "
                      "to sheppard_console.py in GMWM Software\\tools")
            self._set(status="analyse.py not found")
            return
        figdir = self.figdir
        os.makedirs(figdir, exist_ok=True)

        for i, (name, _size) in enumerate(files, 1):
            path = os.path.join(self.dest, name)
            self._set(status=f"[{i}/{len(files)}] analysing {name}...",
                      prog=(i - 1, len(files)))
            self._log(f"--- analyse {name} ---")
            try:
                p = subprocess.run(
                    [sys.executable, script, "all", path, "--figdir", figdir],
                    capture_output=True, text=True, timeout=900)
            except subprocess.TimeoutExpired:
                self._log("analyse: timed out after 15 min")
                continue
            except Exception as e:                         # noqa: BLE001
                self._log(f"analyse: could not run: {e}")
                return

            for line in (p.stdout or "").splitlines():
                self._log(line)
            for line in (p.stderr or "").splitlines():
                self._log(f"! {line}")
            if p.returncode != 0 and not p.stdout:
                self._log(f"analyse: exited {p.returncode} — is numpy "
                          f"installed?  pip install numpy matplotlib")

        self._set(status=f"analysed {len(files)}; figures in {figdir}",
                  prog=(len(files), len(files)))
        # Tk is not thread-safe, so the refresh is scheduled onto the main
        # loop rather than called from this worker.
        self.after(0, self.app.figures_changed)

    # --- delete -----------------------------------------------------------

    def delete_selected(self):
        sel = self._selected()
        if not sel:
            self.stat_var.set("nothing selected")
            return
        names = "\n".join(f"  {n}" for n, _ in sel[:12])
        if len(sel) > 12:
            names += f"\n  ... and {len(sel) - 12} more"
        if not messagebox.askyesno(
                "Delete from card",
                f"Permanently delete {len(sel)} record(s) from the SD card?\n\n"
                f"{names}\n\nThis cannot be undone. Records not yet downloaded "
                f"will be lost.", parent=self):
            return
        self._start(self._rm_worker, sel)

    def _rm_worker(self, files):
        self.board.proto_begin()
        for name, _ in files:
            self.board.send_line(f"rm {name}")
            line, _ = self.board.expect(["rm: "], 10.0)
            self._log(f"datasets: {line or f'{name}: no reply'}")
        self.board.proto_end()
        self._ls_worker()

    def can_leave(self) -> bool:
        """Asked before the tab strip moves away, and before the app closes.

        A transfer that is interrupted leaves a .part file and a board still
        streaming into a dead capture buffer, so it is worth one question."""
        if not self._busy:
            return True
        return messagebox.askyesno(
            "Transfer running",
            "A transfer is in progress. Leave this tab anyway?\n\n"
            "The download will be abandoned and the partial file discarded.",
            parent=self)


class SequencePanel(tk.Frame):
    """Compose a campaign plan, upload it, arm it.

    The SD card cannot be removed, so the plan reaches it the same way
    everything else does -- one line at a time over the console, via `seq add`.
    The board echoes each line back and this checks the echo, so a line mangled
    by a dropped byte is caught at upload time rather than at 02:00 when the
    settle field has silently vanished and every low-ODR record fails its
    thermal gate.

    Editing happens here, in a text box, not on the board: `seq` deliberately
    has no line editing. A plan is short enough to resend in full, and a
    half-edited plan that ran overnight would be worse than no plan at all.
    """

    POLL_MS = 100

    def __init__(self, master, app):
        super().__init__(master, bg=C_INK)
        self.app = app
        self.board = app.board

        self._lock = threading.Lock()
        self._log_q = []
        self._status = ""
        self._finished = False
        self._busy = False

        self._build()
        self.after(self.POLL_MS, self._poll)
        self._load_default()

    def can_leave(self) -> bool:
        return True

    def _build(self):
        head = tk.Frame(self, bg=C_PANEL)
        head.pack(fill="x")
        tk.Label(head, text="PLAN", bg=C_PANEL, fg=C_DIM,
                 font=(F_UI, 8, "bold")).pack(side="left", padx=(14, 8), pady=9)
        tk.Label(head, text="one directive per line   #  comments",
                 bg=C_PANEL, fg=C_FAINT,
                 font=(F_MONO, 8)).pack(side="left", pady=9)

        bar = tk.Frame(self, bg=C_INK)
        bar.pack(fill="x", padx=10, pady=(9, 4))
        self.buttons = []
        for text, cmd, accent in (
                ("Open...", self._open, False),
                ("Save as...", self._save, False),
                ("Upload to board", self.upload, True),
                ("Read from board", self.read_back, False),
                ("Arm", self.arm, True),
                ("Disarm", self.disarm, False),
                ("Status", self.status, False),
                ("Run now", self.run_now, False)):
            b = FlatButton(bar, text, cmd, small=True, accent=accent)
            b.pack(side="left", padx=2)
            self.buttons.append(b)

        wrap = tk.Frame(self, bg=C_EDGE)
        wrap.pack(fill="both", expand=True, padx=10, pady=4)
        self.text = tk.Text(wrap, bg=C_TERM, fg=C_TEXT, bd=0,
                            insertbackground=C_TEXT, highlightthickness=0,
                            font=(F_MONO, 9), wrap="none", undo=True)
        self.text.pack(fill="both", expand=True, padx=1, pady=1)

        self.est_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.est_var, bg=C_INK, fg=C_SIGNAL,
                 font=(F_MONO, 9), anchor="w").pack(fill="x", padx=12)
        self.stat_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.stat_var, bg=C_INK, fg=C_DIM,
                 font=(F_MONO, 8), anchor="w").pack(fill="x", padx=12,
                                                    pady=(0, 8))
        self.text.bind("<KeyRelease>", lambda _e: self._estimate())

    # --- plan text --------------------------------------------------------

    def _plan_path(self):
        return os.path.join(self.app.dataset_dir, "plan.txt")

    def _load_default(self):
        p = self._plan_path()
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as fh:
                self.text.insert("1.0", fh.read())
        self._estimate()

    def _open(self):
        p = filedialog.askopenfilename(
            initialdir=default_dir("Test Datasets"),
            filetypes=[("Plan", "*.txt"), ("All", "*.*")], parent=self)
        if p:
            with open(p, "r", encoding="utf-8") as fh:
                self.text.delete("1.0", "end")
                self.text.insert("1.0", fh.read())
            self._estimate()

    def _save(self):
        p = filedialog.asksaveasfilename(
            initialdir=default_dir("Test Datasets"), initialfile="plan.txt",
            defaultextension=".txt", parent=self)
        if p:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(self.text.get("1.0", "end-1c"))
            self.stat_var.set(f"saved {p}")

    def _lines(self):
        out = []
        for raw in self.text.get("1.0", "end-1c").splitlines():
            s = raw.strip()
            if s and not s.startswith("#"):
                out.append(s)
        return out

    def _estimate(self):
        """Wall clock, so a plan that cannot finish overnight is obvious now."""
        total, steps = 0, 0
        for s in self._lines():
            t = s.split()
            if t[0] in ("step", "phase") and len(t) >= 3:
                steps += 1
                total += int(t[2]) if t[2].isdigit() else 0
                if len(t) >= 8 and t[7].isdigit():
                    total += int(t[7])
            elif t[0] == "warmup" and len(t) >= 2 and t[1].isdigit():
                total += int(t[1])
        h, m = divmod(total // 60, 60)
        self.est_var.set(f"{steps} steps,  about {h} h {m:02d} min of wall "
                         f"clock,  finishes ~{_finish_time(total)}")

    # --- board ------------------------------------------------------------

    def _log(self, s):
        with self._lock:
            self._log_q.append(s)

    def _poll(self):
        with self._lock:
            msgs, self._log_q = self._log_q, []
            status = self._status
            fin, self._finished = self._finished, False
        for m in msgs:
            self.app._note(m, "app")
        if status:
            self.stat_var.set(status)
        if fin:
            self._busy = False
            self.app._set_busy(False)
            for b in self.buttons:
                b.set_enabled(True)
        self.after(self.POLL_MS, self._poll)

    def _start(self, fn, *a):
        if self._busy:
            return
        if not self.board.connected.is_set():
            self.stat_var.set("board not connected")
            return
        self._busy = True
        self.app._set_busy(True)
        for b in self.buttons:
            b.set_enabled(False)
        threading.Thread(target=self._wrap, args=(fn,) + a,
                         daemon=True).start()

    def _wrap(self, fn, *a):
        try:
            fn(*a)
        except Exception as e:                             # noqa: BLE001
            self._log(f"seq: {type(e).__name__}: {e}")
        finally:
            self.board.proto_end()
            with self._lock:
                self._finished = True

    def _cmd(self, line, expect, timeout=6.0):
        self.board.send_line(line)
        got, seen = self.board.expect(expect, timeout)
        for s in seen:
            self._log(s)
        return got

    def upload(self):
        lines = self._lines()
        if not lines:
            self.stat_var.set("nothing to upload")
            return
        self._start(self._upload_worker, lines)

    def _upload_worker(self, lines):
        self.board.proto_begin()
        with self._lock:
            self._status = "clearing plan..."
        if self._cmd("seq new", ["seq: plan cleared", "seq: cannot"], 8.0) is None:
            self._log("seq: no reply to `seq new`")
            return

        for i, ln in enumerate(lines, 1):
            with self._lock:
                self._status = f"uploading {i}/{len(lines)}"
            got = self._cmd(f"seq add {ln}", ["seq+ ", "seq: "], 6.0)
            if got is None or not got.startswith("seq+ "):
                self._log(f"seq: line {i} rejected: {ln}")
                with self._lock:
                    self._status = f"FAILED at line {i}"
                return
            # The board echoes what it actually stored. Whitespace is
            # normalised on the way through, so compare token by token.
            if got[5:].split() != ln.split():
                self._log(f"seq: line {i} came back changed:")
                self._log(f"     sent {ln}")
                self._log(f"     got  {got[5:]}")
                with self._lock:
                    self._status = f"MISMATCH at line {i} -- not armed"
                return

        with self._lock:
            self._status = f"uploaded {len(lines)} lines — now Arm"

    def read_back(self):
        self._start(self._readback_worker)

    def _readback_worker(self):
        self.board.proto_begin()
        self.board.send_line("seq plan")
        _got, seen = self.board.expect(["seq: about", "seq: no plan"], 10.0)
        for s in seen:
            self._log(s)
        with self._lock:
            self._status = "plan read back into the console log"

    def arm(self):
        if not self._lines():
            self.stat_var.set("upload a plan first")
            return
        if not messagebox.askyesno(
                "Arm the sequence",
                "The board will run this plan automatically at the next "
                "BATTERY boot.\n\nIt will not run while USB is connected, and "
                "it disarms itself when the sequence finishes.\n\nArm it?",
                parent=self):
            return
        self._start(self._simple, "seq arm", ["seq: ARMED", "seq: refusing"])

    def disarm(self):
        self._start(self._simple, "seq disarm", ["seq: disarmed"])

    def status(self):
        self._start(self._simple, "seq status", ["seq: plan "])

    def run_now(self):
        if not messagebox.askyesno(
                "Run now",
                "Run the plan immediately over USB?\n\nThis blocks the board "
                "for the full duration of the plan and USB traffic will be "
                "part of every record.\n\nFor campaign data use Arm and a "
                "battery boot instead.", parent=self):
            return
        self._start(self._simple, "seq run", ["seq: done"], 86400.0)

    def _simple(self, line, expect, timeout=15.0):
        self.board.proto_begin()
        got = self._cmd(line, expect, timeout)
        with self._lock:
            self._status = got or f"no reply to `{line}`"


def _finish_time(seconds: int) -> str:
    import datetime
    return (datetime.datetime.now()
            + datetime.timedelta(seconds=seconds)).strftime("%H:%M")


def _hsize(n: float) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.0f} B"


def _verify_sdat(path: str) -> str:
    """Structural check of a downloaded record, if sdat.py is importable."""
    if not path.lower().endswith(".sdat"):
        return ""
    try:
        s = tool_script("sdat.py")
        if s is None:
            return "sdat.py not found"
        d = os.path.dirname(s)
        if d not in sys.path:
            sys.path.insert(0, d)
        import sdat
        res = sdat.verify(path)
    except Exception as e:                                 # noqa: BLE001
        return f"sdat check unavailable ({type(e).__name__})"
    if res.ok:
        return (f"sdat PASS {res.n_blocks} blocks, {res.n_packets} samples, "
                f"{res.f_board_hz:.3f} Hz")
    first = res.problems[0] if res.problems else "?"
    return f"sdat FAIL ({len(res.problems)}): {first}"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_settings()
        self.ui = queue.Queue()
        self.board = Board(self.ui)
        self.panels = {}                # key -> the frame, once built
        self.tab = None                 # the strip, once built

        self.project = self.cfg.get("project") or find_project_root()
        if self.project and not os.path.isdir(self.project):
            self.project = find_project_root()

        self.history = []
        self.hist_pos = None
        self.logfile = None
        self.busy = False
        self.pending = ""                 # partial line awaiting a newline
        self.last_rx = 0.0
        self.hex_col = 0
        self._rx_mark = 0
        self._last_tick = time.time()
        self._sec_mark = time.time()

        self._build()
        self._apply_settings()
        self.root.after(50, self._pump)
        self.root.after(60, self._animate)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._banner()
        if not self.project:
            self._note("could not locate the project folder — use "
                       "File > Set project folder", "bad")

    # -- construction ------------------------------------------------------

    def _build(self):
        r = self.root
        r.title("Sheppard Console")
        r.configure(bg=C_INK)
        r.geometry(self.cfg.get("geometry", "1140x740"))
        r.minsize(900, 540)

        self._build_menu()

        # ---- header -------------------------------------------------------
        head = tk.Frame(r, bg=C_PANEL, height=62)
        head.pack(fill="x")
        head.pack_propagate(False)

        self.glyph = QuantiserGlyph(head)
        self.glyph.pack(side="left", padx=(14, 12), pady=8)

        title = tk.Frame(head, bg=C_PANEL)
        title.pack(side="left", pady=10)
        tk.Label(title, text="S H E P P A R D", bg=C_PANEL, fg=C_TEXT,
                 font=(F_UI, 13, "bold")).pack(anchor="w")
        tk.Label(title, text="rate-register quantisation testbed",
                 bg=C_PANEL, fg=C_DIM, font=(F_UI, 8)).pack(anchor="w")

        right = tk.Frame(head, bg=C_PANEL)
        right.pack(side="right", padx=(0, 16), pady=10)
        # The correction the board is named after. Sheppard (1898): grouping
        # into bins of width Delta inflates the variance by Delta^2/12.
        # Kept to characters Consolas certainly has -- a tofu box in the
        # header would be a poor advertisement for a metrology instrument.
        tk.Label(right, text="sheppard   σ² − Δ²/12", bg=C_PANEL, fg=C_FAINT,
                 font=(F_MONO, 10)).pack(anchor="e")
        self.fw_var = tk.StringVar(value="firmware unknown")
        tk.Label(right, textvariable=self.fw_var, bg=C_PANEL, fg=C_SIGNAL,
                 font=(F_MONO, 8)).pack(anchor="e")

        mid = tk.Frame(head, bg=C_PANEL)
        mid.pack(side="right", padx=(0, 26), pady=10)
        self.status_var = tk.StringVar(value="starting")
        tk.Label(mid, textvariable=self.status_var, bg=C_PANEL, fg=C_TEXT,
                 font=(F_UI, 9)).pack(anchor="e")
        self.counts_var = tk.StringVar(value="")
        tk.Label(mid, textvariable=self.counts_var, bg=C_PANEL, fg=C_DIM,
                 font=(F_MONO, 8)).pack(anchor="e")

        sep(r).pack(fill="x")

        # ---- body ----------------------------------------------------------
        #
        # The left rail stays global rather than becoming per-tab. Flash, the
        # macro buttons and the link trace are useful whatever you are looking
        # at, and an instrument whose connection indicator disappears when you
        # change view is an instrument you stop trusting. Only the main pane
        # is tabbed.
        body = tk.Frame(r, bg=C_INK)
        body.pack(fill="both", expand=True)

        side = tk.Frame(body, bg=C_PANEL, width=198)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self._build_sidebar(side)

        sep(body, horizontal=False).pack(side="left", fill="y")

        main = tk.Frame(body, bg=C_INK)
        main.pack(side="left", fill="both", expand=True)

        tabs = [("console", "Console"),
                ("records", "Records"),
                ("sequence", "Sequence")]
        if AnalysisPanel is not None:
            tabs += [("analysis", "Analysis"), ("figures", "Figures")]

        self.tab = TabStrip(main, tabs, self._on_tab)
        self.tab.pack(fill="x")

        self.stack = tk.Frame(main, bg=C_INK)
        self.stack.pack(fill="both", expand=True)

        # The terminal is built eagerly because the banner is written into it
        # before the first tab change. Everything else is built on first use,
        # which keeps start-up to the time it takes to open a COM port.
        self.panels["console"] = tk.Frame(self.stack, bg=C_INK)
        self._build_terminal(self.panels["console"])

        self.tab.select(self.cfg.get("tab", "console"))

    # -- tabs ---------------------------------------------------------------

    def _make_panel(self, key):
        if key == "records":
            return DatasetPanel(self.stack, self)
        if key == "sequence":
            return SequencePanel(self.stack, self)
        if key == "analysis":
            return AnalysisPanel(self.stack, self)
        if key == "figures":
            return FiguresPanel(self.stack, self)
        return None

    def _on_tab(self, key):
        current = getattr(self, "_tab_key", None)
        if current and current in self.panels:
            panel = self.panels[current]
            leave = getattr(panel, "can_leave", None)
            if leave is not None and not leave():
                # Put the strip back where it was without re-entering here.
                self.root.after_idle(
                    lambda: self.tab.select(current, notify=False))
                return
            panel.pack_forget()

        panel = self.panels.get(key)
        if panel is None:
            panel = self._make_panel(key)
            if panel is None:
                return
            self.panels[key] = panel
        panel.pack(fill="both", expand=True)
        self._tab_key = key

        # Cheap refreshes on entry, so a tab never shows a stale folder. Each
        # of these reads a directory listing and, for records, 4 KiB per file.
        if key == "records" and self.board.connected.is_set():
            panel.refresh()
        elif key == "analysis":
            panel.rescan()
        elif key == "figures":
            panel.rescan()
        if key == "console":
            try:
                self.entry.focus_set()
            except (AttributeError, tk.TclError):
                pass

    def show_tab(self, key):
        if self.tab:
            self.tab.select(key)

    def figures_changed(self):
        """Called by the analysis panel when a run has written new PNGs."""
        p = self.panels.get("figures")
        if p is not None:
            p.rescan()
        if self.tab:
            self.tab.set_badge("figures", "new")

    # -- shared folders -----------------------------------------------------
    #
    # One dataset folder and one figure folder for the whole application. The
    # Records tab downloads into the first, the Analysis tab summarises it,
    # and the Figures tab renders what comes out. Before this they were three
    # separate settings keys that could quietly disagree.

    @property
    def dataset_dir(self):
        return self.cfg.get("dataset_dir") or default_dir("Test Datasets")

    @property
    def figdir(self):
        return self.cfg.get("fig_dir") or default_dir("Figures")

    def set_dataset_dir(self, path):
        self.cfg["dataset_dir"] = path
        save_settings(self.cfg)
        for key in ("records", "analysis"):
            p = self.panels.get(key)
            if p is None:
                continue
            if key == "analysis":
                p.rescan()
            else:
                p._update_dest()                             # noqa: SLF001

    def set_fig_dir(self, path):
        self.cfg["fig_dir"] = path
        save_settings(self.cfg)
        self.figures_changed()

    def _build_menu(self):
        m = tk.Menu(self.root, tearoff=0)

        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Set project folder...", command=self._set_project)
        f.add_command(label="Select firmware image...", command=self._browse_bin)
        f.add_separator()
        f.add_command(label="Start log file...", command=self._start_log)
        f.add_command(label="Stop log", command=self._stop_log)
        f.add_command(label="Save terminal buffer...", command=self._save_buffer)
        f.add_separator()
        f.add_command(label="Send file (raw)...", command=self._send_file)
        f.add_separator()
        f.add_command(label="Exit", command=self._on_close)
        m.add_cascade(label="File", menu=f)

        b = tk.Menu(m, tearoff=0)
        b.add_command(label="Flash over USB", command=self._on_flash)
        b.add_command(label="Run safety self-test", command=self._on_selftest)
        b.add_separator()
        b.add_command(label="Reset board", command=lambda: self._send("reset"))
        b.add_command(label="Read version", command=lambda: self._send("ver"))
        m.add_cascade(label="Board", menu=b)

        g = tk.Menu(m, tearoff=0)
        for i, (key, label) in enumerate((("console", "Console"),
                                          ("records", "Records"),
                                          ("sequence", "Sequence"),
                                          ("analysis", "Analysis"),
                                          ("figures", "Figures")), start=1):
            if key in ("analysis", "figures") and AnalysisPanel is None:
                continue
            g.add_command(label=f"{label}\tCtrl+{i}",
                          command=lambda k=key: self.show_tab(k))
            self.root.bind(f"<Control-Key-{i}>",
                           lambda _e, k=key: self.show_tab(k))
        if AnalysisPanel is None and ANALYSIS_ERROR:
            g.add_separator()
            g.add_command(label=f"Analysis unavailable — {ANALYSIS_ERROR}",
                          state="disabled")
        m.add_cascade(label="Go", menu=g)

        v = tk.Menu(m, tearoff=0)
        self.v_autoscroll = tk.BooleanVar(value=True)
        self.v_timestamps = tk.BooleanVar(value=False)
        self.v_hex = tk.BooleanVar(value=False)
        self.v_echo = tk.BooleanVar(value=True)
        self.v_colour = tk.BooleanVar(value=True)
        self.v_animate = tk.BooleanVar(value=True)
        v.add_checkbutton(label="Auto-scroll", variable=self.v_autoscroll)
        v.add_checkbutton(label="Timestamps", variable=self.v_timestamps)
        v.add_checkbutton(label="Colour protocol lines", variable=self.v_colour)
        v.add_checkbutton(label="Hex view", variable=self.v_hex,
                          command=self._hex_toggled)
        v.add_checkbutton(label="Echo sent commands", variable=self.v_echo)
        v.add_separator()
        v.add_checkbutton(label="Animate the quantiser",
                          variable=self.v_animate)
        v.add_separator()
        v.add_command(label="Larger text", command=lambda: self._font_step(+1))
        v.add_command(label="Smaller text", command=lambda: self._font_step(-1))
        v.add_command(label="Clear terminal", command=self._clear)
        m.add_cascade(label="View", menu=v)

        h = tk.Menu(m, tearoff=0)
        h.add_command(label="Console commands", command=lambda: self._send("help"))
        h.add_command(label="About the emblem", command=self._about_emblem)
        h.add_command(label="About", command=self._about)
        m.add_cascade(label="Help", menu=h)

        self.root.configure(menu=m)

    def _section(self, parent, title):
        row = tk.Frame(parent, bg=C_PANEL)
        row.pack(fill="x", padx=14, pady=(14, 5))
        tk.Label(row, text=title.upper(), bg=C_PANEL, fg=C_DIM,
                 font=(F_UI, 7, "bold")).pack(side="left")
        tk.Frame(row, bg=C_EDGE, height=1).pack(side="left", fill="x",
                                                expand=True, padx=(8, 0),
                                                pady=(6, 0))

    def _build_sidebar(self, side):
        self._section(side, "firmware")

        self.flash_btn = FlatButton(side, "Flash over USB", self._on_flash,
                                    accent=True)
        self.flash_btn.pack(fill="x", padx=12, pady=2)
        self.selftest_btn = FlatButton(side, "Run safety self-test",
                                       self._on_selftest)
        self.selftest_btn.pack(fill="x", padx=12, pady=2)

        self.progress = StepBar(side)
        self.progress.pack(fill="x", padx=12, pady=(7, 0))

        self.bin_label = tk.Label(side, text="", bg=C_PANEL, fg=C_DIM,
                                  font=(F_MONO, 7), anchor="w",
                                  wraplength=172, justify="left")
        self.bin_label.pack(fill="x", padx=13, pady=(7, 0))
        FlatButton(side, "Change image...", self._browse_bin,
                   small=True).pack(fill="x", padx=12, pady=(5, 0))

        self._section(side, "commands")
        self.macro_frame = tk.Frame(side, bg=C_PANEL)
        self.macro_frame.pack(fill="x")
        self._rebuild_macros()
        FlatButton(side, "Edit buttons...", self._edit_macros,
                   small=True).pack(fill="x", padx=12, pady=(6, 0))

        self._section(side, "go to")
        FlatButton(side, "Records on card",
                   lambda: self.show_tab("records")).pack(fill="x", padx=12,
                                                          pady=2)
        FlatButton(side, "Sequence plan",
                   lambda: self.show_tab("sequence")).pack(fill="x", padx=12,
                                                           pady=2)
        if AnalysisPanel is not None:
            FlatButton(side, "Analysis",
                       lambda: self.show_tab("analysis")).pack(fill="x",
                                                               padx=12, pady=2)
            FlatButton(side, "Figures",
                       lambda: self.show_tab("figures")).pack(fill="x",
                                                              padx=12, pady=2)

        self._section(side, "board")
        FlatButton(side, "Reset", lambda: self._send("reset"),
                   small=True).pack(fill="x", padx=12, pady=2)

        # activity trace pinned to the bottom
        foot = tk.Frame(side, bg=C_PANEL)
        foot.pack(side="bottom", fill="x", pady=(0, 12))

        cap = tk.Frame(foot, bg=C_PANEL)
        cap.pack(fill="x", padx=14, pady=(0, 4))
        tk.Label(cap, text="LINK", bg=C_PANEL, fg=C_DIM,
                 font=(F_UI, 7, "bold")).pack(side="left")
        self.rate_var = tk.StringVar(value="0 B/s")
        tk.Label(cap, textvariable=self.rate_var, bg=C_PANEL, fg=C_SIGNAL,
                 font=(F_MONO, 9)).pack(side="right")

        self.spark = Sparkline(foot)
        self.spark.pack(padx=13)

        self.peak_var = tk.StringVar(value="")
        tk.Label(foot, textvariable=self.peak_var, bg=C_PANEL, fg=C_FAINT,
                 font=(F_MONO, 7), anchor="e").pack(fill="x", padx=14,
                                                    pady=(2, 0))

    def _rebuild_macros(self):
        for w in self.macro_frame.winfo_children():
            w.destroy()
        grid = tk.Frame(self.macro_frame, bg=C_PANEL)
        grid.pack(fill="x", padx=12)
        for i, item in enumerate(self.cfg.get("macros") or DEFAULT_MACROS):
            try:
                label, cmd = item
            except (ValueError, TypeError):
                continue
            FlatButton(grid, label, lambda c=cmd: self._send(c),
                       small=True).grid(row=i // 2, column=i % 2,
                                        sticky="ew", padx=1, pady=1)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

    def _build_terminal(self, main):
        wrap = tk.Frame(main, bg=C_INK)
        wrap.pack(fill="both", expand=True, padx=(10, 0), pady=(9, 0))

        self.font_size = int(self.cfg.get("font_size", 10))
        self.term_font = tkfont.Font(family=F_MONO, size=self.font_size)

        self.text = tk.Text(wrap, bg=C_TERM, fg=C_TEXT, insertbackground=C_TEXT,
                            font=self.term_font, wrap="none", relief="flat",
                            padx=11, pady=9, state="disabled",
                            selectbackground=C_HILITE, borderwidth=0,
                            spacing1=1)
        vs = tk.Scrollbar(wrap, orient="vertical", command=self.text.yview,
                          bg=C_PANEL, troughcolor=C_TERM,
                          activebackground=C_EDGE, borderwidth=0,
                          highlightthickness=0, width=12)
        self.text.configure(yscrollcommand=vs.set)
        self.text.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")

        self.text.tag_configure("sent", foreground=C_SENT)
        self.text.tag_configure("app", foreground=C_SIGNAL)
        self.text.tag_configure("signal", foreground=C_SIGNAL)
        self.text.tag_configure("good", foreground=C_OK)
        self.text.tag_configure("bad", foreground=C_ERROR)
        self.text.tag_configure("dim", foreground=C_DIM)
        self.text.tag_configure("find", background=C_HILITE)

        findbar = tk.Frame(main, bg=C_INK)
        findbar.pack(fill="x", padx=10, pady=(7, 0))
        tk.Label(findbar, text="find", bg=C_INK, fg=C_DIM,
                 font=(F_UI, 8)).pack(side="left", padx=(2, 7))
        self.find_var = tk.StringVar()
        e = tk.Entry(findbar, textvariable=self.find_var, bg=C_TERM, fg=C_TEXT,
                     insertbackground=C_TEXT, font=(F_MONO, 9), relief="flat",
                     highlightthickness=1, highlightbackground=C_EDGE,
                     highlightcolor=C_EDGE)
        e.pack(side="left", fill="x", expand=True, ipady=2)
        e.bind("<KeyRelease>", lambda _e: self._do_find())
        FlatButton(findbar, "clear", self._clear,
                   small=True).pack(side="left", padx=(6, 0))

        inrow = tk.Frame(main, bg=C_INK)
        inrow.pack(fill="x", padx=10, pady=(7, 11))
        tk.Label(inrow, text="›", bg=C_INK, fg=C_SIGNAL,
                 font=(F_MONO, 13, "bold")).pack(side="left", padx=(3, 7))
        self.entry = tk.Entry(inrow, bg=C_TERM, fg=C_TEXT,
                              insertbackground=C_SIGNAL, font=(F_MONO, 10),
                              relief="flat", highlightthickness=1,
                              highlightbackground=C_EDGE,
                              highlightcolor=C_SIGNAL)
        self.entry.pack(side="left", fill="x", expand=True, ipady=6,
                        padx=(0, 8))
        self.entry.bind("<Return>", self._on_enter)
        self.entry.bind("<Up>", self._hist_up)
        self.entry.bind("<Down>", self._hist_down)
        self.entry.focus_set()
        FlatButton(inrow, "Send", self._on_enter, accent=True).pack(side="left")

    def _banner(self):
        self._raw("  Sheppard console\n", "dim")
        self._raw("  W. F. Sheppard, 1898 — the variance of grouped data is "
                  "high by Δ²/12\n", "dim")
        self._raw("  " + "─" * 62 + "\n\n", "dim")

    # -- settings ----------------------------------------------------------

    def _apply_settings(self):
        self.v_timestamps.set(self.cfg.get("timestamps", False))
        self.v_hex.set(self.cfg.get("hex", False))
        self.v_echo.set(self.cfg.get("echo", True))
        self.v_autoscroll.set(self.cfg.get("autoscroll", True))
        self.v_colour.set(self.cfg.get("colour", True))
        self.v_animate.set(self.cfg.get("animate", True))
        self.bin_path = self.cfg.get("bin") or guess_bin(self.project) or ""
        self._update_bin_label()

    def _collect_settings(self):
        return {
            "geometry": self.root.winfo_geometry(),
            "project": self.project or "",
            "bin": self.bin_path,
            "font_size": self.font_size,
            "timestamps": self.v_timestamps.get(),
            "hex": self.v_hex.get(),
            "echo": self.v_echo.get(),
            "autoscroll": self.v_autoscroll.get(),
            "colour": self.v_colour.get(),
            "animate": self.v_animate.get(),
            "macros": self.cfg.get("macros") or DEFAULT_MACROS,
            "tab": getattr(self, "_tab_key", "console"),
            "dataset_dir": self.dataset_dir,
            "fig_dir": self.figdir,
        }

    def _update_bin_label(self):
        if self.bin_path and os.path.isfile(self.bin_path):
            t = time.strftime("%d %b %H:%M",
                              time.localtime(os.path.getmtime(self.bin_path)))
            self.bin_label.configure(
                text=f"{os.path.basename(self.bin_path)}\n"
                     f"{os.path.getsize(self.bin_path)} B · {t}", fg=C_DIM)
        elif self.bin_path:
            self.bin_label.configure(
                text=f"{os.path.basename(self.bin_path)}\n(not built yet)",
                fg=C_SIGNAL)
        else:
            self.bin_label.configure(text="no image selected", fg=C_SIGNAL)

    def _set_project(self):
        d = filedialog.askdirectory(
            title="Select the project folder (the one containing Core\\)",
            initialdir=self.project or os.getcwd())
        if not d:
            return
        if not os.path.isfile(os.path.join(d, PROJECT_MARKER)):
            if not messagebox.askyesno(
                    "Project folder",
                    f"{d}\n\ndoes not contain {PROJECT_MARKER}.\n\n"
                    f"Use it anyway?"):
                return
        self.project = d
        found = guess_bin(d)
        if found:
            self.bin_path = found
        self._update_bin_label()
        self._note(f"project folder set to {d}")

    def _browse_bin(self):
        start = os.path.dirname(self.bin_path) if self.bin_path else \
            (os.path.join(self.project, "Debug") if self.project else os.getcwd())
        path = filedialog.askopenfilename(
            title="Select firmware image (.bin)",
            filetypes=[("Firmware binary", "*.bin"), ("All files", "*.*")],
            initialdir=start if os.path.isdir(start) else os.getcwd())
        if path:
            self.bin_path = path
            self._update_bin_label()

    def _edit_macros(self):
        win = tk.Toplevel(self.root)
        win.title("Edit command buttons")
        win.configure(bg=C_INK)
        win.geometry("430x370")
        win.transient(self.root)
        tk.Label(win, bg=C_INK, fg=C_DIM, font=(F_UI, 8), justify="left",
                 text="One button per line:   label = command\n"
                      "e.g.   rate 10m = rate 600").pack(anchor="w", padx=12,
                                                          pady=(12, 6))
        box = tk.Text(win, bg=C_TERM, fg=C_TEXT, insertbackground=C_TEXT,
                      font=(F_MONO, 10), relief="flat", padx=8, pady=6)
        box.pack(fill="both", expand=True, padx=12)
        for label, cmd in (self.cfg.get("macros") or DEFAULT_MACROS):
            box.insert("end", f"{label} = {cmd}\n")

        def apply():
            out = []
            for line in box.get("1.0", "end").splitlines():
                if "=" not in line:
                    continue
                label, cmd = line.split("=", 1)
                if label.strip() and cmd.strip():
                    out.append([label.strip(), cmd.strip()])
            self.cfg["macros"] = out or DEFAULT_MACROS
            self._rebuild_macros()
            win.destroy()

        row = tk.Frame(win, bg=C_INK)
        row.pack(fill="x", padx=12, pady=10)
        FlatButton(row, "Save", apply, accent=True).pack(side="right")
        FlatButton(row, "Cancel", win.destroy).pack(side="right", padx=(0, 6))

    def _about_emblem(self):
        messagebox.showinfo(
            "The emblem",
            "A mid-tread uniform quantiser.\n\n"
            "Grey diagonal   the true input x\n"
            "Amber staircase Q(x) — what a 16-bit rate register can hold\n"
            "Red stub        e = Q(x) − x, the quantisation error\n\n"
            "The claim this board exists to test is that e presents at a −1/2 "
            "Allan slope on rate-register parts and is silently absorbed into "
            "fitted ARW, rather than appearing as the −1 angle-quantisation "
            "term that belongs to angle-increment architectures.\n\n"
            "The staircase carries the connection state in its colour, and "
            "the dot sweeps only while the link is live.")

    def _about(self):
        messagebox.showinfo(
            "Sheppard Console",
            "Companion app for the Sheppard IMU board.\n\n"
            "STM32F723ZE · 2× ICM-42688-P · ISM330DHCX · BMI323\n"
            "Finds the board by USB ID 0483:5740, reconnects by itself, and "
            "flashes firmware over the same cable as the console.\n\n"
            "Named for W. F. Sheppard, whose 1898 paper "
            "(DOI 10.1112/plms/s1-29.1.353) gave the −c²/12 correction for "
            "the variance of grouped data.\n\n"
            "TN-17A is the procedure. TN-17 is why it works this way.")

    # -- terminal output ----------------------------------------------------

    def _stamp(self):
        ms = int((time.time() % 1) * 1000)
        return time.strftime("%H:%M:%S") + f".{ms:03d}  "

    def _raw(self, text, tag=None):
        """Write text exactly as given."""
        if not text:
            return
        self.text.configure(state="normal")
        self.text.insert("end", text, tag)
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > 6000:
            self.text.delete("1.0", f"{lines - 4000}.0")
        self.text.configure(state="disabled")
        if self.v_autoscroll.get():
            self.text.see("end")

    def _emit_line(self, line, forced_tag=None):
        # The header shows whatever the board last reported, no matter what
        # prompted it -- the automatic query on connect, a typed `ver`, the
        # boot banner, or the read-back after a flash. Previously only the
        # flash worker set it, so it read "firmware unknown" until you
        # flashed something.
        stripped = line.strip()
        if stripped.startswith(FW_NAME_PREFIX):
            self.fw_var.set(stripped)

        tag = forced_tag
        if tag is None and self.v_colour.get():
            tag = tag_for_line(line)
        if self.v_timestamps.get():
            self._raw(self._stamp(), "dim")
        self._raw(line + "\n", tag)

    def _feed_display(self, text):
        """Buffer into whole lines so each can be coloured by its content."""
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            self._emit_line(line)

    def _flush_pending(self):
        if self.pending:
            self._emit_line(self.pending)
            self.pending = ""

    def _write_hex(self, data: bytes):
        self.text.configure(state="normal")
        for byte in data:
            if self.hex_col == 0 and self.v_timestamps.get():
                self.text.insert("end", self._stamp(), "dim")
            self.text.insert("end", f"{byte:02X} ")
            self.hex_col += 1
            if self.hex_col >= 16:
                self.text.insert("end", "\n")
                self.hex_col = 0
        self.text.configure(state="disabled")
        if self.v_autoscroll.get():
            self.text.see("end")

    def _hex_toggled(self):
        self._flush_pending()
        self.hex_col = 0
        self._note("hex view on" if self.v_hex.get() else "hex view off")

    def _note(self, text, kind="app"):
        self._flush_pending()
        tag = {"good": "good", "bad": "bad"}.get(kind, "app")
        self._raw(f"  · {text}\n", tag)

    def _clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self.pending = ""
        self.hex_col = 0

    def _font_step(self, delta):
        self.font_size = max(7, min(20, self.font_size + delta))
        self.term_font.configure(size=self.font_size)

    def _do_find(self):
        self.text.tag_remove("find", "1.0", "end")
        needle = self.find_var.get()
        if len(needle) < 2:
            return
        idx = "1.0"
        while True:
            idx = self.text.search(needle, idx, nocase=True, stopindex="end")
            if not idx:
                break
            end = f"{idx}+{len(needle)}c"
            self.text.tag_add("find", idx, end)
            idx = end

    def _save_buffer(self):
        path = filedialog.asksaveasfilename(
            title="Save terminal buffer", defaultextension=".txt",
            initialfile=time.strftime("sheppard_buffer_%Y%m%d_%H%M%S.txt"))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.text.get("1.0", "end"))
            self._note(f"buffer saved to {path}", "good")
        except OSError as exc:
            messagebox.showerror("Save", str(exc))

    # -- logging -------------------------------------------------------------

    def _start_log(self):
        path = filedialog.asksaveasfilename(
            title="Log received data to", defaultextension=".txt",
            initialfile=time.strftime("sheppard_%Y%m%d_%H%M%S.txt"))
        if not path:
            return
        try:
            self.logfile = open(path, "a", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Log", str(exc))
            return
        self._note(f"logging to {path}", "good")

    def _stop_log(self):
        if self.logfile:
            self.logfile.close()
            self.logfile = None
            self._note("logging stopped")

    def _send_file(self):
        path = filedialog.askopenfilename(title="Send file contents raw")
        if not path:
            return
        with open(path, "rb") as fh:
            data = fh.read()
        if len(data) > 64 * 1024 and not messagebox.askyesno(
                "Send file", f"{len(data)} bytes. Send it all?"):
            return
        self.board.write_raw(data)
        self._note(f"sent {len(data)} bytes from {os.path.basename(path)}")

    # -- sending -------------------------------------------------------------

    def _send(self, cmd):
        if self.busy:
            self._note("busy — wait for the current operation", "bad")
            return
        if not self.board.connected.is_set():
            self._note("not connected", "bad")
            return

        # `get` sends raw binary with no framing. Typed here it would pour a
        # whole record into the text widget, which is what made the window
        # appear to hang. Route it to the browser, which puts the reader thread
        # into byte-capture mode for the duration instead.
        if cmd.split()[:1] == ["get"]:
            self._note("`get` streams raw binary — switching to the Records "
                       "tab instead", "app")
            self.show_tab("records")
            return
        if self.v_echo.get():
            self._flush_pending()
            self._raw(f"› {cmd}\n", "sent")
        self.board.send_line(cmd)

    def _on_enter(self, _event=None):
        cmd = self.entry.get().strip()
        self.entry.delete(0, "end")
        if not cmd:
            return
        self.history.append(cmd)
        self.hist_pos = None
        self._send(cmd)

    def _hist_up(self, _e):
        if not self.history:
            return "break"
        self.hist_pos = (len(self.history) - 1 if self.hist_pos is None
                         else max(0, self.hist_pos - 1))
        self.entry.delete(0, "end")
        self.entry.insert(0, self.history[self.hist_pos])
        return "break"

    def _hist_down(self, _e):
        if self.hist_pos is None:
            return "break"
        self.hist_pos += 1
        self.entry.delete(0, "end")
        if self.hist_pos >= len(self.history):
            self.hist_pos = None
        else:
            self.entry.insert(0, self.history[self.hist_pos])
        return "break"

    # -- busy / progress -------------------------------------------------------

    def _set_busy(self, on):
        self.busy = on
        self.flash_btn.set_enabled(not on)
        self.selftest_btn.set_enabled(not on)
        if not on:
            self.progress.set(0)

    # -- flashing --------------------------------------------------------------

    def _on_flash(self):
        if self.busy:
            return
        path = self.bin_path
        if not path or not os.path.isfile(path):
            found = guess_bin(self.project)
            if found:
                self.bin_path = path = found
                self._update_bin_label()
            else:
                messagebox.showerror(
                    "Flash",
                    "No firmware image selected.\n\n"
                    + (f"Looked in:\n{os.path.join(self.project, 'Debug')}\n\n"
                       if self.project else
                       "The project folder could not be located.\n\n")
                    + "Build in CubeIDE with 'Convert to binary file' enabled "
                      "(TN-17A section 1.2), then pick the .bin with "
                      "File > Select firmware image.")
                return

        with open(path, "rb") as fh:
            image = fh.read()
        if len(image) < 2048:
            messagebox.showerror("Flash", f"That file is only {len(image)} "
                                          f"bytes.\nDid you pick the .elf?")
            return

        bin_t = os.path.getmtime(path)
        src_t, src_f = newest_source(self.project)
        if src_f and src_t > bin_t + 1.0:
            mins = (src_t - bin_t) / 60.0
            if not messagebox.askyesno(
                    "Stale image",
                    f"{os.path.basename(path)} is about {mins:.0f} minutes "
                    f"older than your sources.\n\n"
                    f"Newest: {os.path.relpath(src_f, self.project)}\n\n"
                    f"Flashing it will succeed and change nothing.\n"
                    f"Build in CubeIDE first.\n\nFlash anyway?"):
                return

        if not self.board.connected.is_set():
            messagebox.showerror("Flash", "The board is not connected.")
            return

        self._set_busy(True)
        threading.Thread(target=self._flash_worker, args=(image, path),
                         daemon=True).start()

    def _flash_worker(self, image, path):
        b, put = self.board, self.ui.put
        crc = zlib.crc32(image) & 0xFFFFFFFF
        try:
            put(("note", (f"flashing {os.path.basename(path)} — {len(image)} "
                          f"bytes, crc32={crc:08x}", "app")))
            b.proto_begin()
            if not b.send_line(f"\r\nfw {len(image)} {crc:08x}"):
                put(("note", ("write failed — board gone?", "bad")))
                return

            line, _ = b.expect(("FWREADY", "FWABORT", "usage:"), READY_TIMEOUT)
            if line is None:
                put(("note", ("no FWREADY. Is this firmware older than the "
                              "self-flasher? Flash once over SWD.", "bad")))
                return
            if not line.startswith("FWREADY"):
                put(("note", (f"refused: {line}", "bad")))
                return

            t0, sent = time.time(), 0
            for off in range(0, len(image), FLASH_CHUNK):
                if not b.write_raw(image[off:off + FLASH_CHUNK]):
                    put(("note", ("link dropped mid-transfer", "bad")))
                    return
                sent += min(FLASH_CHUNK, len(image) - off)
                put(("prog", 100.0 * sent / len(image)))
            put(("note", (f"sent {len(image)} bytes in "
                          f"{time.time() - t0:.1f} s", "app")))

            line, _ = b.expect(("FWPROG", "FWABORT", "FWFAIL",
                                "FWCRC bad", "FWVEC bad"), RESULT_TIMEOUT)
            if line is None:
                put(("note", ("board went quiet before reporting", "bad")))
                return
            if not line.startswith("FWPROG"):
                put(("note", (f"rejected: {line} — flash untouched", "bad")))
                return

            put(("note", ("committed; erasing and rewriting — do not unplug",
                          "app")))
            b.wait_disconnect(8.0)
            if not b.wait_connect(RECONNECT_TIMEOUT):
                put(("note", ("the board did not come back. The image was "
                              "written but does not run — recover over SWD "
                              "(TN-17A section 8).", "bad")))
                return

            time.sleep(0.5)
            b.proto_begin()
            b.send_line("ver")
            ident, _ = b.expect((FW_NAME_PREFIX,), 4.0)
            if ident:
                put(("fw", ident))
                put(("note", (f"now running: {ident}", "good")))
            else:
                put(("note", ("flashed, but could not read the version back",
                              "app")))
        finally:
            b.proto_end()
            put(("busy", False))

    # -- self-test --------------------------------------------------------------

    def _on_selftest(self):
        if self.busy:
            return
        if not self.board.connected.is_set():
            messagebox.showerror("Self-test", "The board is not connected.")
            return
        if not messagebox.askyesno(
                "Safety self-test",
                "Feeds the board deliberately bad firmware data five ways and "
                "checks each one is refused.\n\n"
                "Nothing here can erase the board: every case is designed to "
                "be rejected before the erase step.\n\n"
                "Takes about 15 seconds. Run it?"):
            return
        self._set_busy(True)
        threading.Thread(target=self._selftest_worker, daemon=True).start()

    def _selftest_worker(self):
        b, put = self.board, self.ui.put
        results = []

        def check(name, ok, detail):
            results.append((name, ok, detail))
            put(("note", (f"{'PASS' if ok else 'FAIL'}  {name} — {detail}",
                          "good" if ok else "bad")))

        try:
            b.proto_begin()
            put(("note", ("safety self-test starting", "app")))

            b.send_line("ver")
            ident, _ = b.expect((FW_NAME_PREFIX,), 4.0)
            check("board responds", ident is not None, ident or "no reply")
            if ident is None:
                return

            for size, name in ((100, "tiny image refused"),
                               (999999, "oversize image refused")):
                b.proto_begin()
                b.send_line(f"fw {size} 0")
                line, _ = b.expect(("FWABORT", "FWREADY"), 3.0)
                check(name,
                      line is not None and line.startswith("FWABORT size"),
                      line or "timeout")

            payload = bytes([0xA5]) * 4096

            b.proto_begin()
            b.send_line("fw 4096 deadbeef")
            line, _ = b.expect(("FWREADY", "FWABORT"), 3.0)
            if line and line.startswith("FWREADY"):
                b.write_raw(payload)
                line, _ = b.expect(("FWCRC", "FWPROG", "FWABORT"), 10.0)
                check("bad CRC refused",
                      line is not None and line.startswith("FWCRC bad"),
                      line or "timeout")
            else:
                check("bad CRC refused", False, f"no FWREADY: {line}")

            crc = zlib.crc32(payload) & 0xFFFFFFFF
            b.proto_begin()
            b.send_line(f"fw 4096 {crc:08x}")
            line, _ = b.expect(("FWREADY", "FWABORT"), 3.0)
            if line and line.startswith("FWREADY"):
                b.write_raw(payload)
                line, seen = b.expect(("FWVEC", "FWPROG", "FWABORT"), 10.0)
                crc_ok = any(s.startswith("FWCRC ok") for s in seen)
                check("junk payload refused by vector check",
                      line is not None and line.startswith("FWVEC bad")
                      and crc_ok, line or "timeout")
            else:
                check("junk payload refused by vector check", False,
                      f"no FWREADY: {line}")

            b.proto_begin()
            b.send_line("fw 4096 00000000")
            line, _ = b.expect(("FWREADY", "FWABORT"), 3.0)
            if line and line.startswith("FWREADY"):
                b.write_raw(bytes(100))
                line, _ = b.expect(("FWABORT",), 12.0)
                check("abandoned transfer times out",
                      line is not None and line.startswith("FWABORT timeout"),
                      line or "timeout")
            else:
                check("abandoned transfer times out", False,
                      f"no FWREADY: {line}")

            b.proto_begin()
            b.send_line("ver")
            after, _ = b.expect((FW_NAME_PREFIX,), 4.0)
            check("flash untouched, board alive", after == ident,
                  after or "no reply")

        finally:
            b.proto_end()
            put(("busy", False))
            bad = [r for r in results if not r[1]]
            put(("selftest_done", (len(results), len(bad))))

    # -- animation -------------------------------------------------------------

    def _animate(self):
        now = time.time()
        dt = now - self._last_tick
        self._last_tick = now
        self.glyph.animate = (self.v_animate.get()
                              and self.board.connected.is_set())
        self.glyph.step(dt)
        self.root.after(60, self._animate)

    # -- main-thread pump -------------------------------------------------------

    def _pump(self):
        try:
            while True:
                kind, payload = self.ui.get_nowait()

                if kind == "rx":
                    self.last_rx = time.time()
                    if self.v_hex.get():
                        self._write_hex(payload)
                    else:
                        text = payload.decode("utf-8", errors="replace")
                        self._feed_display(
                            text.replace("\r\n", "\n").replace("\r", "\n"))
                    if self.logfile:
                        try:
                            self.logfile.write(
                                payload.decode("utf-8", errors="replace"))
                            self.logfile.flush()
                        except (OSError, ValueError):
                            pass

                elif kind == "status":
                    state, detail = payload
                    colour = {"connected": C_SIGNAL, "waiting": C_DIM,
                              "busy": C_ERROR}.get(state, C_DIM)
                    self.glyph.set_state(colour)
                    self.status_var.set(
                        f"connected  ·  {detail}" if state == "connected"
                        else detail)

                elif kind == "connected":
                    self.root.after(700, lambda: self._quiet("ver"))
                    # The Records tab lists the card, so it is stale the
                    # moment the board resets. Refresh it if it is the one
                    # on screen; leave it alone otherwise, because a listing
                    # costs a console round trip.
                    if getattr(self, "_tab_key", None) == "records":
                        p = self.panels.get("records")
                        if p is not None:
                            self.root.after(900, p.refresh)

                elif kind == "disconnected":
                    self.fw_var.set("firmware unknown")

                elif kind == "note":
                    self._note(payload[0], payload[1])

                elif kind == "prog":
                    self.progress.set(payload)

                elif kind == "fw":
                    self.fw_var.set(payload)

                elif kind == "busy":
                    self._set_busy(payload)

                elif kind == "selftest_done":
                    total, bad = payload
                    if bad:
                        messagebox.showerror(
                            "Self-test", f"{bad} of {total} checks FAILED.\n\n"
                                         f"Do not flash over USB until these "
                                         f"pass.")
                    else:
                        messagebox.showinfo(
                            "Self-test", f"All {total} checks passed.\n\n"
                                         f"The safety gates work; flashing "
                                         f"over USB is safe to use.")
        except queue.Empty:
            pass

        # A line that never terminates would otherwise stay invisible.
        if self.pending and (time.time() - self.last_rx) > 0.20:
            self._flush_pending()

        now = time.time()
        if now - self._sec_mark >= 0.5:
            elapsed = now - self._sec_mark
            delta = self.board.rx_bytes - self._rx_mark
            self._rx_mark = self.board.rx_bytes
            self._sec_mark = now

            bps = int(delta / elapsed) if elapsed > 0 else 0
            self._peak_bps = max(getattr(self, "_peak_bps", 0), bps)
            self.spark.push(bps)
            self.rate_var.set(f"{bps:,} B/s")
            self.peak_var.set(f"peak {self._peak_bps:,}")
            self.counts_var.set(f"rx {self.board.rx_bytes:,}   "
                                f"tx {self.board.tx_bytes:,}")

        self.root.after(50, self._pump)

    def _quiet(self, cmd):
        if self.board.connected.is_set() and not self.busy:
            self.board.send_line(cmd)

    # -- shutdown -------------------------------------------------------------

    def _on_close(self):
        if self.busy:
            if not messagebox.askyesno(
                    "Quit",
                    "An operation is in progress.\nQuitting now could leave "
                    "the board unbootable.\n\nQuit anyway?"):
                return
        for panel in self.panels.values():
            leave = getattr(panel, "can_leave", None)
            if leave is not None and not leave():
                return
            stop = getattr(panel, "stop", None)
            if stop is not None:
                try:
                    stop()
                except Exception:                            # noqa: BLE001
                    pass
        if self.logfile:
            self.logfile.close()
        self.cfg.update(self._collect_settings())
        save_settings(self.cfg)
        self.board.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
