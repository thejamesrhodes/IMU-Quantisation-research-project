#!/usr/bin/env python3
"""
console_theme.py -- the Sheppard console's visual language, in one place.

Extracted from sheppard_console.py so that the analysis and figure panels can
be written as separate modules without importing the console back (which would
be circular). sheppard_console.py re-exports everything here, so every existing
name still resolves exactly as it did.

The palette is instrument-panel rather than code-editor: ink background, a
single warm signal colour for anything quantised, cool cyan for anything the
operator sent, and a muted red reserved for the quantisation error and for
failures. Nothing else gets a colour. A panel that lights up in six hues tells
you nothing; one that is grey except where it matters tells you where to look.
"""

from __future__ import annotations

import tkinter as tk

# ===========================================================================
# Palette
# ===========================================================================

C_INK = "#0e1116"
C_PANEL = "#141922"
C_EDGE = "#212936"
C_TERM = "#0a0d11"
C_TEXT = "#cdd6e0"
C_DIM = "#5d6b7a"
C_FAINT = "#2b3542"
C_SIGNAL = "#e8a33d"    # the quantised staircase
C_TRUE = "#7d8996"      # the true, unquantised input
C_ERROR = "#d4585a"     # e = Q(x) - x, and failures
C_SENT = "#57c7d4"
C_OK = "#5fbf8f"
C_HILITE = "#26374d"

F_MONO = "Consolas"
F_UI = "Segoe UI"


# ===========================================================================
# Primitives
# ===========================================================================

def sep(master, horizontal=True):
    return tk.Frame(master, bg=C_EDGE,
                    height=1 if horizontal else 0,
                    width=0 if horizontal else 1)


def section(parent, title, bg=C_PANEL, pady=(14, 5), padx=14):
    """A small capitalised heading with a rule running off to the right."""
    row = tk.Frame(parent, bg=bg)
    row.pack(fill="x", padx=padx, pady=pady)
    tk.Label(row, text=title.upper(), bg=bg, fg=C_DIM,
             font=(F_UI, 7, "bold")).pack(side="left")
    tk.Frame(row, bg=C_EDGE, height=1).pack(side="left", fill="x",
                                            expand=True, padx=(8, 0),
                                            pady=(6, 0))
    return row


class FlatButton(tk.Frame):
    def __init__(self, master, text, command, width=None, accent=False,
                 small=False, danger=False, **kw):
        if accent:
            bg, fg = C_SIGNAL, "#120c04"
        elif danger:
            bg, fg = "#2a1b1d", C_ERROR
        else:
            bg, fg = "#1c232e", C_TEXT
        super().__init__(master, bg=bg, highlightthickness=0, **kw)
        self._bg, self._accent, self._danger = bg, accent, danger
        self._cmd = command
        self._enabled = True
        self.label = tk.Label(self, text=text, bg=bg, fg=fg,
                              font=(F_UI, 8 if small else 9,
                                    "bold" if accent else "normal"),
                              padx=8, pady=4 if small else 6)
        if width:
            self.label.configure(width=width)
        self.label.pack(fill="both", expand=True)
        for w in (self, self.label):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    def set_text(self, text):
        self.label.configure(text=text)

    def _click(self, _e):
        if self._enabled and self._cmd:
            self._cmd()

    def _enter(self, _e):
        if self._enabled:
            if self._accent:
                hot = "#f2b757"
            elif self._danger:
                hot = "#3a2427"
            else:
                hot = "#28313f"
            self.configure(bg=hot)
            self.label.configure(bg=hot)

    def _leave(self, _e):
        if self._enabled:
            self.configure(bg=self._bg)
            self.label.configure(bg=self._bg)

    def set_enabled(self, on):
        self._enabled = on
        bg = self._bg if on else "#151a21"
        if on:
            fg = "#120c04" if self._accent else (C_ERROR if self._danger
                                                 else C_TEXT)
        else:
            fg = C_DIM
        self.configure(bg=bg)
        self.label.configure(bg=bg, fg=fg)


class StepBar(tk.Canvas):
    """Progress drawn as quantiser treads rather than a smooth bar.

    A continuous fill would be the wrong metaphor for an instrument whose
    subject is that continuous things become steps.
    """

    def __init__(self, master, height=7, **kw):
        super().__init__(master, height=height, bg=C_PANEL,
                         highlightthickness=0, **kw)
        self.h = height
        self.pct = 0.0
        self.bind("<Configure>", lambda _e: self.redraw())

    def set(self, pct):
        self.pct = max(0.0, min(100.0, pct))
        self.redraw()

    def redraw(self):
        self.delete("all")
        w = self.winfo_width() or 1
        self.create_rectangle(0, 0, w, self.h, fill=C_TERM, outline="")
        n = 24
        filled = int(round(n * self.pct / 100.0))
        gap = 2
        cw = max(1.0, (w - gap * (n - 1)) / n)
        for i in range(filled):
            x = i * (cw + gap)
            self.create_rectangle(x, 0, x + cw, self.h,
                                  fill=C_SIGNAL, outline="")


class Sparkline(tk.Canvas):
    """Recent link throughput. Flat means quiet, not broken."""

    def __init__(self, master, width=168, height=34, points=56, **kw):
        super().__init__(master, width=width, height=height, bg=C_TERM,
                         highlightthickness=0, **kw)
        self.w, self.h, self.n = width, height, points
        self.vals = [0.0] * points

    def push(self, value):
        self.vals.append(max(0.0, float(value)))
        del self.vals[:-self.n]
        self.redraw()

    def redraw(self):
        self.delete("all")
        top = max(self.vals) or 1.0
        step = self.w / float(self.n - 1)
        pts = []
        for i, v in enumerate(self.vals):
            x = i * step
            y = self.h - 2 - (self.h - 5) * (v / top)
            pts += [x, y]
        self.create_line(0, self.h - 2, self.w, self.h - 2,
                         fill=C_FAINT, width=1)
        if len(pts) >= 4:
            self.create_line(*pts, fill=C_SIGNAL, width=1, smooth=False)
            self.create_oval(pts[-2] - 2, pts[-1] - 2, pts[-2] + 2,
                             pts[-1] + 2, fill=C_SIGNAL, outline="")


# ===========================================================================
# Tab strip
#
# Hand-drawn rather than ttk.Notebook. ttk cannot be themed to this palette on
# Windows without fighting the native theme engine, and a notebook tab with a
# system-grey border in the middle of an ink panel looks like a bug. This is a
# row of labels with a signal-coloured underline on the active one -- the same
# device the header uses for the firmware line.
# ===========================================================================

class TabStrip(tk.Frame):
    """Horizontal tab selector. Calls on_change(key) when the selection moves."""

    def __init__(self, master, tabs, on_change, bg=C_PANEL, **kw):
        """tabs: sequence of (key, label) or (key, label, hint)."""
        super().__init__(master, bg=bg, **kw)
        self._bg = bg
        self._on_change = on_change
        self._items = {}
        self._active = None
        self._badges = {}

        row = tk.Frame(self, bg=bg)
        row.pack(fill="x", padx=10)
        self._row = row

        for spec in tabs:
            key, label = spec[0], spec[1]
            hint = spec[2] if len(spec) > 2 else ""
            self._add(row, key, label, hint)

        # The rule under the whole strip; the active tab paints over it.
        tk.Frame(self, bg=C_EDGE, height=1).pack(fill="x")

    def _add(self, row, key, label, hint):
        cell = tk.Frame(row, bg=self._bg)
        cell.pack(side="left")

        lab = tk.Label(cell, text=label.upper(), bg=self._bg, fg=C_DIM,
                       font=(F_UI, 8, "bold"), padx=13, pady=7)
        lab.pack()

        badge = tk.Label(cell, text="", bg=self._bg, fg=C_SIGNAL,
                         font=(F_MONO, 7))
        # packed on demand by set_badge

        rule = tk.Frame(cell, bg=self._bg, height=2)
        rule.pack(fill="x")

        self._items[key] = (cell, lab, rule)
        self._badges[key] = badge

        for w in (cell, lab):
            w.bind("<Button-1>", lambda _e, k=key: self.select(k))
            w.bind("<Enter>", lambda _e, k=key: self._hover(k, True))
            w.bind("<Leave>", lambda _e, k=key: self._hover(k, False))
        if hint:
            lab.configure()          # hint reserved for a future tooltip

    def _hover(self, key, on):
        if key == self._active:
            return
        _cell, lab, _rule = self._items[key]
        lab.configure(fg=C_TEXT if on else C_DIM)

    def select(self, key, notify=True):
        # notify=False is how a refused tab change puts the strip back without
        # re-entering on_change, so the caller does not have to guard against
        # its own callback.
        if key not in self._items or key == self._active:
            return
        for k, (_cell, lab, rule) in self._items.items():
            active = (k == key)
            lab.configure(fg=C_SIGNAL if active else C_DIM)
            rule.configure(bg=C_SIGNAL if active else self._bg)
        self._active = key
        if notify and self._on_change:
            self._on_change(key)

    @property
    def active(self):
        return self._active

    def set_badge(self, key, text, colour=C_SIGNAL):
        """A small count or state marker beside a tab label."""
        b = self._badges.get(key)
        if b is None:
            return
        if text:
            b.configure(text=text, fg=colour)
            if not b.winfo_ismapped():
                b.pack()
        else:
            b.pack_forget()


# ===========================================================================
# Scrollable frame
#
# tkinter has no such thing built in; every scrolling panel needs a Canvas with
# an interior Frame and a <Configure> binding to keep the scrollregion honest.
# Written once here so the figure gallery and the summary table share it.
# ===========================================================================

class ScrollFrame(tk.Frame):
    def __init__(self, master, bg=C_INK, **kw):
        super().__init__(master, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vs = tk.Scrollbar(self, orient="vertical",
                               command=self.canvas.yview, bg=C_PANEL,
                               troughcolor=C_TERM, activebackground=C_EDGE,
                               borderwidth=0, highlightthickness=0, width=12)
        self.canvas.configure(yscrollcommand=self.vs.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vs.pack(side="right", fill="y")

        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body,
                                              anchor="nw")

        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        # Wheel binding is on <Enter>/<Leave> rather than bind_all, so two
        # scrollable panels in the same window do not fight over the wheel.
        self.canvas.bind("<Enter>", lambda _e: self._wheel(True))
        self.canvas.bind("<Leave>", lambda _e: self._wheel(False))

    def _on_body(self, _e):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

    def _wheel(self, on):
        if on:
            self.canvas.bind_all("<MouseWheel>", self._scroll)
            self.canvas.bind_all("<Button-4>", self._scroll)
            self.canvas.bind_all("<Button-5>", self._scroll)
        else:
            for s in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.canvas.unbind_all(s)

    def _scroll(self, e):
        if getattr(e, "num", None) == 4:
            delta = -1
        elif getattr(e, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if e.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")

    def to_top(self):
        self.canvas.yview_moveto(0.0)


# ===========================================================================
# Small helpers shared by the panels
# ===========================================================================

def entry(master, textvariable=None, mono=True, size=9, **kw):
    return tk.Entry(master, textvariable=textvariable, bg=C_TERM, fg=C_TEXT,
                    insertbackground=C_SIGNAL,
                    font=(F_MONO if mono else F_UI, size), relief="flat",
                    highlightthickness=1, highlightbackground=C_EDGE,
                    highlightcolor=C_SIGNAL, **kw)


def logbox(master, height=8, size=8):
    """The standard read-only monospace output pane, with its scrollbar."""
    wrap = tk.Frame(master, bg=C_EDGE)
    txt = tk.Text(wrap, bg=C_TERM, fg=C_TEXT, font=(F_MONO, size),
                  relief="flat", height=height, wrap="none", padx=8, pady=6,
                  state="disabled", borderwidth=0, insertbackground=C_TEXT,
                  selectbackground=C_HILITE)
    vs = tk.Scrollbar(wrap, orient="vertical", command=txt.yview, bg=C_PANEL,
                      troughcolor=C_TERM, activebackground=C_EDGE,
                      borderwidth=0, highlightthickness=0, width=12)
    txt.configure(yscrollcommand=vs.set)
    txt.pack(side="left", fill="both", expand=True, padx=1, pady=1)
    vs.pack(side="right", fill="y")
    txt.tag_configure("dim", foreground=C_DIM)
    txt.tag_configure("good", foreground=C_OK)
    txt.tag_configure("bad", foreground=C_ERROR)
    txt.tag_configure("sig", foreground=C_SIGNAL)
    return wrap, txt


def append(txt: tk.Text, line: str, tag: str = "", limit: int = 4000):
    txt.configure(state="normal")
    txt.insert("end", line if line.endswith("\n") else line + "\n",
               tag or ())
    n = int(txt.index("end-1c").split(".")[0])
    if n > limit:
        txt.delete("1.0", f"{n - limit}.0")
    txt.see("end")
    txt.configure(state="disabled")


def hsize(n: float) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"
