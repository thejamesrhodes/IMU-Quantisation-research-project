#!/usr/bin/env python3
"""
console_analysis.py -- the Analysis and Figures panels of the Sheppard console.

Two embeddable frames:

    AnalysisPanel   local records, the analysis runners, and summary.csv
                    rendered as a table you can actually read
    FiguresPanel    a gallery that renders the PNGs in-app instead of
                    shelling out to the file manager

Why these are here and not in sheppard_console.py: the console is about the
link -- bytes to and from a board over a wire -- and everything in it is
written around a serial reader thread. Analysis is about files that are
already on disk and does not touch the board at all. Keeping them apart means
a numpy or matplotlib failure cannot take the terminal down with it, and it
means this file can be opened and read without scrolling past a USB protocol.

The analysis tools are run as SUBPROCESSES, not imported. Three reasons, in
order of importance:

  1. What you see in the GUI is reproducible by typing the same command. The
     panel prints the exact argv it ran before it runs it, so a result here
     and a result on the command line are the same result.
  2. numpy and matplotlib are heavy and fail in ways -- missing DLLs, backend
     selection, a bad wheel -- that would abort the whole application at
     import time. A subprocess that will not start is a message in a log pane.
  3. A long run can be killed. `analyse.py summary` over a night of records
     with two ODR-8000 files in it is several minutes of work; the existing
     path used subprocess.run() with captured output, so the window showed
     nothing at all until it finished. Here the output is streamed line by
     line and there is a Stop button.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog

from console_theme import (
    C_DIM, C_EDGE, C_ERROR, C_FAINT, C_HILITE, C_INK, C_PANEL,
    C_SIGNAL, C_TERM, C_TEXT, F_MONO, F_UI,
    FlatButton, ScrollFrame, StepBar, append, hsize, logbox, section, sep,
)

# Windows: keep the console window of every child process hidden.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def tool_script(name: str):
    """Sibling tool, by name. They all live in the same folder by design."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    return p if os.path.exists(p) else None


# ===========================================================================
# Figure captions
#
# From TN-20 section 6. Carried here so the gallery explains what it is
# showing rather than presenting six files called fig1..fig6. A figure whose
# meaning lives only in a technical note is a figure that gets misread at
# 02:00.
# ===========================================================================

CAPTIONS = {
    "fig1_eta_vs_rho": (
        "The primary curve",
        "Measurements against the exact theory of TN-20 §2.3. The shaded band "
        "spans every phase at that ρ, so every point must lie inside it — a "
        "far stronger constraint than agreement with one tabulated curve. The "
        "mid-code branch passes through TN-14's tabulated diamonds. Hollow "
        "markers failed the R2 thermal gate and are plotted, not dropped."),
    "fig2_eta_vs_phi": (
        "The result",
        "η against distance from a code centre, ODR 25–50, both specimens, "
        "three axes, with one exact curve per ρ present. No fitting and no "
        "free parameters. Spans −0.24 to +2.42. The gate-passing records sit "
        "on the curves; the hollow ones scatter, which is what TN-14 §2 says "
        "a smeared φ should do."),
    "fig3_rho_validation": (
        "ρ against ODR",
        "Raw and line-corrected, and measured against TN-14 predicted on a "
        "1:1 axis. Above ODR 200 the line subtraction removes 20–50% of the "
        "variance, so those points are less trustworthy than they look; η is "
        "saturated there, so no conclusion depends on them."),
    "fig4_line_vs_odr": (
        "The 119 Hz contaminant",
        "Line amplitude falling to zero below ODR 100 — the UI decimation "
        "filter removes it, so R4 passes exactly where the paper's claims "
        "live and no J₀ correction is needed at ODR 25–50."),
    "fig5_offset_step": (
        "The OFFSET_USER ambiguity",
        "0.512 and 0.500 Δ/step against the data, showing why five steps "
        "cannot separate them. Superseded once plan_offset.txt has run: see "
        "offset_fit.py, which adds a 2000-step lever arm and a thermal "
        "regressor."),
    "fig6_thermal_gate": (
        "R2 compliance",
        "Gate result across the night. Superseded in part by fig13: the gate "
        "was evaluated on a sample range, which is an extreme-value statistic, "
        "and every record passes once the drift is estimated instead."),

    # ---- added after the 29 July phase sweep (TN-23) ----------------------
    "fig7_phase_sweep": (
        "The controlled phase sweep",
        "η against φ from the OFFSET_USER ladder — one specimen, one ODR, one "
        "configuration, and the only thing that changes between the sixteen "
        "records is a number written to a trim register. TN-20 fig2 showed "
        "the same shape from phases that happened by accident; this is the "
        "manipulation. Residual RMS 0.018, which is 0.6% of the η range, with "
        "no free parameters."),
    "fig8_reference_truncation": (
        "Sheppard's correction, applied to the reference channel",
        "The 19-bit reference is itself a truncating quantiser with step "
        "0.125 Δ, so every phase read from it is low by 1/16 Δ and its "
        "variance carries Δ′²/12 of its own quantisation noise. Left: the "
        "residual is a smooth sign-changing function of φ, not scatter. "
        "Right: the same data corrected, RMS 0.393 → 0.018, nothing fitted."),
    "fig9_vernier": (
        "The vernier",
        "A trim register too coarse to resolve one LSB used as a fine phase "
        "control. It works because the step MISSES half an LSB by 0.05%: even "
        "steps precess and sweep the whole period. Note the two step-size "
        "estimates disagree at 4.9σ (TN-23 §5) — open, and it touches no "
        "physics because φ is measured per record, never commanded."),
    "fig10_allan_family": (
        "The architectural claim",
        "Rate-register quantisation lands on the −½ family and is absorbed "
        "into fitted ARW. IEEE-952's Q term sits at −1 and belongs to "
        "angle-increment outputs; the figure is the ABSENCE of that slope. "
        "Both reference lines are anchored on the data, so the only thing "
        "being compared is the slope."),
    "fig11_arw_consequence": (
        "What it costs a practitioner",
        "The same sensor at the same configuration gives a ×4.7 range in "
        "fitted angle random walk depending on a sub-LSB bias phase that no "
        "calibration toolchain measures. The classical model predicts one "
        "number; the truth is anywhere on the curve."),
    "fig12_offset_linearity": (
        "OFFSET_USER linearity",
        "Shift against step count for both specimens, with residual. Replaces "
        "fig5. The intercept c is a fixed per-record offset that biases any "
        "single-pair estimate by c/k — which is why the four-step measurement "
        "of 28 July could not have worked at any sample size."),
    "fig13_r2_estimator": (
        "The R2 gate was watching the wrong number",
        "max − min over 60k samples is ~8.5σ of the thermometer's own noise. "
        "Every gated record passes once the drift is estimated instead. The "
        "old statistic also tightened as ODR fell, because the temperature "
        "channel is filtered with ODR — worst exactly where the claims live."),
    "fig14_residual_anatomy": (
        "Residual anatomy",
        "What the remaining 0.018 correlates with, and what it does not. A "
        "residual that correlates with nothing available is the honest end of "
        "an analysis; one that tracks φ or ρ or drift is an unmodelled term."),
    "fig15_code_histograms": (
        "The marginal channel",
        "Observed code occupancy against the exact prediction at four phases, "
        "maximum discrepancy 0.005 with nothing fitted. This is a "
        "distributional statistic sharing no algebra with η, which is what "
        "rule R6 means by refusing to select on a single summary statistic."),

    # ---- the transfer rule itself (Concept Note v2.3 §3.2) ----------------
    "fig16_transfer_three_worlds": (
        "The rule, and the fix that does not fix it",
        "Three worlds. AS PRACTISED — no quantisation term anywhere, which is "
        "every surveyed toolchain. PQN-AWARE — the obvious correction, which "
        "nobody applies and which is STILL wrong, and below 69 Hz returns a "
        "negative noise density. EXACT — right by construction from two "
        "measured parameters. Panel B separates the register failure from the "
        "bandwidth failure, which are both present in real data."),
    "fig17_transfer_surface": (
        "The plane the rule assumes is flat",
        "Transfer error over calibration ODR and bias phase. The practitioner "
        "chooses one axis and does not know the other exists. The black line "
        "is where the two errors happen to cancel — the reason a single "
        "well-chosen configuration can look like a validation."),
    "fig18_density_invariance": (
        "The invariant that is not one",
        "The rate noise density Kalibr and the rest carry across ODR, drawn "
        "flat as they assume, then as the sensor delivers it. Green markers "
        "are measured and carry a bandwidth departure as well as a register "
        "one; F16 panel B decomposes them."),
}

SUFFIX_NOTE = {
    "screen": ("R4 line screen", "Spectrum of the 19-bit stream with the "
                                 "coherent-line test. A line in band makes "
                                 "the closed-form tables wrong, not merely "
                                 "imprecise."),
    "overview": ("Record overview", "Time series, code histogram and "
                                    "temperature for one record."),
    "allan": ("Allan deviation", "σ(τ) for the record. Rate-register "
                                 "quantisation presents at the −½ slope and "
                                 "is absorbed into fitted ARW."),
}


def describe(stem: str):
    if stem in CAPTIONS:
        return CAPTIONS[stem]
    for suf, note in SUFFIX_NOTE.items():
        if stem.endswith("_" + suf):
            title, body = note
            return f"{title} — {stem[:-len(suf) - 1]}", body
    return stem, ""


# ===========================================================================
# Subprocess runner
# ===========================================================================

class Runner:
    """One child process at a time, with its output streamed to a callback."""

    def __init__(self, on_line, on_done):
        self.on_line = on_line
        self.on_done = on_done
        self.q: queue.Queue = queue.Queue()
        self.proc = None
        self._thread = None
        self.label = ""

    @property
    def busy(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, argv, label="", cwd=None) -> bool:
        if self.busy:
            return False
        self.label = label
        self.q.put(("line", "$ " + " ".join(
            f'"{a}"' if " " in str(a) else str(a) for a in argv), "dim"))
        try:
            self.proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                cwd=cwd, creationflags=_NO_WINDOW)
        except Exception as e:                              # noqa: BLE001
            self.q.put(("line", f"could not run: {type(e).__name__}: {e}",
                        "bad"))
            self.q.put(("done", -1, ""))
            self.proc = None
            return False
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        return True

    def _pump(self):
        p = self.proc
        try:
            for line in p.stdout:                            # type: ignore
                self.q.put(("line", line.rstrip("\n"), ""))
        except Exception:                                    # noqa: BLE001
            pass
        rc = p.wait()                                        # type: ignore
        self.q.put(("done", rc, self.label))

    def stop(self):
        if self.busy:
            try:
                self.proc.terminate()                        # type: ignore
            except Exception:                                # noqa: BLE001
                pass

    def drain(self):
        """Called from the Tk main loop. Nothing else touches widgets."""
        while True:
            try:
                kind, a, b = self.q.get_nowait()
            except queue.Empty:
                return
            if kind == "line":
                self.on_line(a, b)
            else:
                self.proc = None
                self.on_done(a, b)


# ===========================================================================
# Analysis panel
# ===========================================================================

class AnalysisPanel(tk.Frame):
    """Local records, the runners, and summary.csv as a readable table."""

    POLL_MS = 80

    # (csv column, header, width, alignment)
    #
    # phi_ref and rho_ref, not phi and rho: the reference stream is itself a
    # truncating quantiser, so the raw pair is low by 1/16 Delta in phase and
    # high by Delta'^2/12 in variance (TN-23 §3). The raw columns are still in
    # the csv for audit; they are not what anyone should be reading.
    #
    # eta_resid is the column to read first. It is the measurement against the
    # exact theory at that record's own (rho, phi), with nothing fitted, so it
    # answers "does this record agree" in one number.
    COLS = [
        ("label", "label", 14, "<"),
        ("slot", "sl", 3, ">"),
        ("odr_nom", "ODR", 6, ">"),
        ("offset_user", "off", 5, ">"),
        ("axis", "ax", 3, ">"),
        ("mu_D", "mu(D)", 10, ">"),
        ("phi_ref", "phi", 7, ">"),
        ("rho_ref", "rho", 7, ">"),
        ("eta", "eta", 8, ">"),
        ("eta_exact", "exact", 8, ">"),
        ("eta_resid", "resid", 8, ">"),
        ("codes", "cds", 5, ">"),
        ("mu_drift_D", "mu drift", 9, ">"),
        ("temp_drift_mK", "dT(mK)", 8, ">"),
        ("gate", "gate", 6, ">"),
        ("verify", "vfy", 5, ">"),
    ]

    # |eta_resid| above this is worth looking at. The 29 July sweep sits at
    # RMS 0.018 across 48 records, so 0.10 is roughly 5x the achieved scatter.
    RESID_FLAG = 0.10

    def __init__(self, master, app):
        super().__init__(master, bg=C_INK)
        self.app = app
        self.rows = []
        self.sort_key = None
        self.sort_rev = False
        self._records = []

        self.runner = Runner(self._on_line, self._on_done)
        self._build()
        self.after(self.POLL_MS, self._poll)

    # -- construction ------------------------------------------------------

    def _build(self):
        head = tk.Frame(self, bg=C_PANEL)
        head.pack(fill="x")
        tk.Label(head, text="DATASETS", bg=C_PANEL, fg=C_DIM,
                 font=(F_UI, 8, "bold")).pack(side="left", padx=(14, 8), pady=9)
        self.dir_var = tk.StringVar()
        tk.Label(head, textvariable=self.dir_var, bg=C_PANEL, fg=C_SIGNAL,
                 font=(F_MONO, 8)).pack(side="left", pady=9)
        FlatButton(head, "Change folder...", self._pick_dir,
                   small=True).pack(side="right", padx=(0, 12), pady=7)
        FlatButton(head, "Rescan", self.rescan,
                   small=True).pack(side="right", padx=6, pady=7)

        # ---- upper: records and actions ---------------------------------
        upper = tk.Frame(self, bg=C_INK, height=192)
        upper.pack(fill="x", padx=10, pady=(9, 0))
        upper.pack_propagate(False)

        lb = tk.Frame(upper, bg=C_EDGE)
        lb.pack(side="left", fill="both", expand=True)
        self.list = tk.Listbox(lb, bg=C_TERM, fg=C_TEXT, bd=0,
                               highlightthickness=0, selectmode="extended",
                               font=(F_MONO, 8), activestyle="none",
                               selectbackground=C_HILITE,
                               selectforeground=C_TEXT)
        lvs = tk.Scrollbar(lb, orient="vertical", command=self.list.yview,
                           bg=C_PANEL, troughcolor=C_TERM,
                           activebackground=C_EDGE, borderwidth=0,
                           highlightthickness=0, width=12)
        self.list.configure(yscrollcommand=lvs.set)
        self.list.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        lvs.pack(side="right", fill="y")

        acts = tk.Frame(upper, bg=C_INK, width=210)
        acts.pack(side="left", fill="y", padx=(10, 0))
        acts.pack_propagate(False)

        section(acts, "run", bg=C_INK, pady=(0, 5), padx=2)
        self.b_summary = FlatButton(acts, "Summary — whole folder",
                                    self.run_summary, accent=True, small=True)
        self.b_summary.pack(fill="x", pady=2)
        self.b_figs = FlatButton(acts, "Result figures (1–6)",
                                 self.run_figures, small=True)
        self.b_figs.pack(fill="x", pady=2)
        self.b_one = FlatButton(acts, "Analyse selected", self.run_selected,
                                small=True)
        self.b_one.pack(fill="x", pady=2)
        self.b_off = FlatButton(acts, "OFFSET_USER fit", self.run_offset_fit,
                                small=True)
        self.b_off.pack(fill="x", pady=2)

        opts = tk.Frame(acts, bg=C_INK)
        opts.pack(fill="x", pady=(7, 0))
        self.v_fast = tk.BooleanVar(value=True)
        self.v_resume = tk.BooleanVar(value=True)
        for var, text, tip in (
                (self.v_fast, "--fast",
                 "skip Allan; it is O(N·n_tau) and dominates on 8 kHz files"),
                (self.v_resume, "--resume",
                 "keep rows already in summary.csv")):
            cb = tk.Checkbutton(opts, text=text, variable=var, bg=C_INK,
                                fg=C_DIM, selectcolor=C_TERM,
                                activebackground=C_INK, activeforeground=C_TEXT,
                                font=(F_MONO, 8), bd=0, highlightthickness=0,
                                anchor="w")
            cb.pack(fill="x")
            cb.bind("<Enter>", lambda _e, t=tip: self.status_var.set(t))

        self.b_stop = FlatButton(acts, "Stop", self.stop, small=True,
                                 danger=True)
        self.b_stop.pack(fill="x", pady=(9, 0))
        self.b_stop.set_enabled(False)

        self.bar = StepBar(acts, height=6)
        self.bar.pack(fill="x", pady=(7, 0))

        # ---- middle: the summary table ----------------------------------
        section(self, "summary.csv", bg=C_INK, pady=(11, 4), padx=12)

        thead = tk.Frame(self, bg=C_PANEL)
        thead.pack(fill="x", padx=10)
        self._hdr_labels = {}
        for i, (key, title, width, align) in enumerate(self.COLS):
            # The data rows carry a one-character left margin, so the first
            # heading carries one too. Without it the header sits a character
            # to the left of its own column, which on a numeric table reads as
            # a bug in the numbers.
            text = (" " if i == 0 else "") + f"{title:{align}{width}}"
            lab = tk.Label(thead, text=text, bg=C_PANEL,
                           fg=C_DIM, font=(F_MONO, 8, "bold"), padx=0)
            lab.pack(side="left")
            lab.bind("<Button-1>", lambda _e, k=key: self._sort_by(k))
            lab.bind("<Enter>", lambda _e, w=lab: w.configure(fg=C_TEXT))
            lab.bind("<Leave>",
                     lambda _e, w=lab, k=key: w.configure(
                         fg=C_SIGNAL if k == self.sort_key else C_DIM))
            self._hdr_labels[key] = lab

        tb = tk.Frame(self, bg=C_EDGE)
        tb.pack(fill="both", expand=True, padx=10, pady=(1, 0))
        self.table = tk.Text(tb, bg=C_TERM, fg=C_TEXT, font=(F_MONO, 8),
                             relief="flat", wrap="none", padx=0, pady=4,
                             state="disabled", borderwidth=0,
                             selectbackground=C_HILITE)
        tvs = tk.Scrollbar(tb, orient="vertical", command=self.table.yview,
                           bg=C_PANEL, troughcolor=C_TERM,
                           activebackground=C_EDGE, borderwidth=0,
                           highlightthickness=0, width=12)
        self.table.configure(yscrollcommand=tvs.set)
        self.table.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        tvs.pack(side="right", fill="y")

        self.table.tag_configure("fail", foreground=C_ERROR)
        self.table.tag_configure("dead", foreground=C_SIGNAL)
        self.table.tag_configure("odd", foreground="#c07ad8")
        self.table.tag_configure("plain", foreground=C_TEXT)
        self.table.tag_configure("dim", foreground=C_DIM)

        # ---- lower: the log ----------------------------------------------
        section(self, "output", bg=C_INK, pady=(10, 4), padx=12)
        wrap, self.log = logbox(self, height=7, size=8)
        wrap.pack(fill="x", padx=10)

        self.status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.status_var, bg=C_INK, fg=C_DIM,
                 font=(F_MONO, 8), anchor="w").pack(fill="x", padx=12,
                                                    pady=(4, 8))

    # -- folders -----------------------------------------------------------

    @property
    def dest(self):
        return self.app.dataset_dir

    @property
    def figdir(self):
        return self.app.figdir

    def _pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.dest,
                                    title="Where the records live")
        if d:
            self.app.set_dataset_dir(d)
            self.rescan()

    # -- record list -------------------------------------------------------

    def rescan(self):
        self.dir_var.set(self.dest)
        try:
            names = sorted(n for n in os.listdir(self.dest)
                           if n.lower().endswith(".sdat"))
        except OSError as e:
            self.status_var.set(f"cannot read the folder: {e}")
            names = []

        self._records = []
        for n in names:
            path = os.path.join(self.dest, n)
            meta = _peek(path)
            meta["name"] = n
            meta["size"] = os.path.getsize(path)
            self._records.append(meta)

        self.list.delete(0, "end")
        for m in self._records:
            flag = " " if m.get("closed", True) else "!"
            self.list.insert(
                "end",
                f" {flag} {m['name']:<38} {m.get('label', ''):<12} "
                f"{m.get('odr', ''):>5}Hz  s{m.get('slot', '?')} "
                f"off{m.get('offset', 0):<5} {m.get('aaf', ''):<14} "
                f"{hsize(m['size']):>9}")
            if not m.get("closed", True):
                self.list.itemconfig("end", foreground=C_ERROR)
        total = sum(m["size"] for m in self._records)
        self.status_var.set(f"{len(self._records)} record(s), {hsize(total)}"
                            f"   ('!' = never closed — the run was cut short)")
        self.load_summary()

    def _selected_paths(self):
        return [os.path.join(self.dest, self._records[i]["name"])
                for i in self.list.curselection() if i < len(self._records)]

    # -- runners -----------------------------------------------------------

    def _py(self):
        return sys.executable

    def _guard(self, script):
        s = tool_script(script)
        if s is None:
            append(self.log, f"cannot find {script} — it should sit next to "
                             f"sheppard_console.py", "bad")
            return None
        if self.runner.busy:
            append(self.log, "a run is already in progress", "dim")
            return None
        return s

    def run_summary(self):
        s = self._guard("analyse.py")
        if not s:
            return
        out = os.path.join(self.dest, "summary.csv")
        argv = [self._py(), s, "summary", self.dest, "-o", out]
        if self.v_fast.get():
            argv.append("--fast")
        if self.v_resume.get():
            argv.append("--resume")
        self._launch(argv, "summary")

    def run_figures(self):
        s = self._guard("figures.py")
        if not s:
            return
        csv_path = os.path.join(self.dest, "summary.csv")
        if not os.path.exists(csv_path):
            append(self.log, "no summary.csv yet — run Summary first", "bad")
            return
        os.makedirs(self.figdir, exist_ok=True)
        # --records: figures 10, 12 and 15 need the time series, not just the
        # summary. figures.py falls back to the csv's own folder, but say it
        # explicitly so a csv kept elsewhere still works.
        self._launch([self._py(), s, csv_path, "-o", self.figdir,
                      "--records", self.dest], "figures")

    def run_selected(self):
        s = self._guard("analyse.py")
        if not s:
            return
        paths = self._selected_paths()
        if not paths:
            append(self.log, "select one or more records first", "dim")
            return
        os.makedirs(self.figdir, exist_ok=True)
        self._queue = [([self._py(), s, "all", p, "--figdir", self.figdir],
                        "analyse") for p in paths]
        self._queue_total = len(self._queue)
        self._next_in_queue()

    # Each of these is a separate ladder and they must not be pooled: they were
    # taken on different nights, at different ODR, and on different specimens.
    # offset_fit is run once per group present, in sequence, using the same
    # queue the per-record analysis uses.
    OFFSET_GROUPS = [
        ("*_off_*.sdat", "slot 1 ladder, ODR 1000"),
        ("*p2cal*.sdat", "slot 2 calibration"),
        ("*ph_k*.sdat", "phase sweep, ODR 50"),
    ]

    def run_offset_fit(self):
        s = self._guard("offset_fit.py")
        if not s:
            return
        groups = [(g, d) for g, d in self.OFFSET_GROUPS
                  if glob.glob(os.path.join(self.dest, g))]
        if not groups:
            append(self.log, "no offset-ladder records in this folder "
                             "(expected *_off_*, *p2cal* or *ph_k*)", "dim")
            return
        append(self.log, f"offset fit over {len(groups)} group(s): "
                         + ", ".join(d for _g, d in groups), "sig")
        self._queue = [([self._py(), s, self.dest, "--glob", g],
                        f"offset fit — {d}") for g, d in groups]
        self._queue_total = len(self._queue)
        self._next_in_queue()

    def _next_in_queue(self):
        q = getattr(self, "_queue", None)
        if not q:
            return
        argv, label = q.pop(0)
        done = self._queue_total - len(q) - 1
        self.bar.set(100.0 * done / max(self._queue_total, 1))
        self._launch(argv, label, chained=True)

    def _launch(self, argv, label, chained=False):
        self._chained = chained
        if not chained:
            self._queue = []
        append(self.log, "", "")
        if self.runner.start(argv, label):
            self._set_busy(True)
            self.status_var.set(f"{label}: running")

    def stop(self):
        self._queue = []
        self.runner.stop()
        self.status_var.set("stopping...")

    def _set_busy(self, on):
        for b in (self.b_summary, self.b_figs, self.b_one, self.b_off):
            b.set_enabled(not on)
        self.b_stop.set_enabled(on)

    # -- runner callbacks (main thread) ------------------------------------

    def _on_line(self, line, tag):
        low = line.lower()
        if not tag:
            if line.startswith("!") or "error" in low or "traceback" in low:
                tag = "bad"
            elif "fail" in low:
                tag = "bad"
            elif line.startswith("VERDICT") or "-> " in line:
                tag = "sig"
            elif line.startswith("  [") or line.startswith("$ "):
                tag = "dim"
        append(self.log, line, tag)

    def _on_done(self, rc, label):
        if getattr(self, "_queue", None):
            self._next_in_queue()
            return
        self.bar.set(100.0)
        self._set_busy(False)
        if rc == 0:
            append(self.log, f"{label}: done", "good")
            self.status_var.set(f"{label}: done")
        else:
            append(self.log, f"{label}: exited {rc}", "bad")
            self.status_var.set(f"{label}: exited {rc} — numpy and matplotlib "
                                f"installed?  pip install numpy matplotlib")
        if label == "summary" or label.startswith("offset fit"):
            self.load_summary()
        if label in ("figures", "analyse"):
            self.app.figures_changed()

    def _poll(self):
        self.runner.drain()
        self.after(self.POLL_MS, self._poll)

    # -- summary.csv -------------------------------------------------------

    def load_summary(self):
        path = os.path.join(self.dest, "summary.csv")
        self.rows = []
        if os.path.exists(path):
            try:
                with open(path, newline="", encoding="utf-8") as fh:
                    self.rows = [r for r in csv.DictReader(fh) if r.get("axis")]
            except Exception as e:                          # noqa: BLE001
                append(self.log, f"summary.csv: {e}", "bad")
        self._render_table()

    def _sort_by(self, key):
        if self.sort_key == key:
            self.sort_rev = not self.sort_rev
        else:
            self.sort_key, self.sort_rev = key, False
        for k, lab in self._hdr_labels.items():
            lab.configure(fg=C_SIGNAL if k == self.sort_key else C_DIM)
        self._render_table()

    def _render_table(self):
        rows = list(self.rows)
        if self.sort_key:
            def keyf(r):
                v = r.get(self.sort_key, "")
                try:
                    return (0, float(v))
                except (TypeError, ValueError):
                    return (1, str(v))
            rows.sort(key=keyf, reverse=self.sort_rev)

        self.table.configure(state="normal")
        self.table.delete("1.0", "end")
        if not rows:
            self.table.insert("end",
                              "  no summary.csv in this folder — press "
                              "'Summary — whole folder'\n", "dim")
            self.table.configure(state="disabled")
            return

        n_fail = n_odd = 0
        for r in rows:
            cells = []
            for key, _t, width, align in self.COLS:
                v = r.get(key, "")
                try:
                    f = float(v)
                    v = f"{f:.4f}" if key in (
                        "mu_D", "phi_ref", "rho_ref", "eta", "eta_exact",
                        "eta_resid", "mu_drift_D") \
                        else (f"{f:.0f}" if key == "temp_drift_mK"
                              else f"{f:g}")
                except (TypeError, ValueError):
                    v = str(v)
                cells.append(f"{v[:width]:{align}{width}}")
            line = "".join(cells)

            gate = (r.get("gate") or "").strip().lower()
            vfy = (r.get("verify") or "").strip().lower()
            def _f(k):
                try:
                    return float(r.get(k, "nan"))
                except (TypeError, ValueError):
                    return float("nan")
            eta, resid = _f("eta"), _f("eta_resid")

            if gate.startswith("fail") or (vfy and vfy != "ok"):
                tag = "fail"
                n_fail += 1
            elif resid == resid and abs(resid) > self.RESID_FLAG:
                # Disagrees with the exact theory at its own measured (rho,
                # phi) by more than five times the achieved scatter. Since
                # 29 July that is the first thing worth knowing about a
                # record, ahead of anything thermal.
                tag = "odd"
                n_odd += 1
            elif eta == eta and eta < 0.0:
                # The dead-zone branch: the register is a compressor here and
                # this is the regime the paper exists to describe.
                tag = "dead"
            else:
                tag = "plain"
            self.table.insert("end", " " + line + "\n", tag)

        self.table.configure(state="disabled")
        note = f"{len(rows)} axis-record(s)"
        if n_fail:
            note += f"   {n_fail} inadmissible (red)"
        if n_odd:
            note += f"   {n_odd} off theory by >{self.RESID_FLAG:g} (magenta)"
        note += "   amber: eta < 0, the dead-zone regime"
        self.status_var.set(note)


def _peek(path: str) -> dict:
    """Read a record's 4 KiB JSON header. No numpy, no decode, no cost."""
    out = {"label": "", "odr": "", "slot": "?", "offset": 0, "aaf": "",
           "closed": True}
    try:
        with open(path, "rb") as fh:
            raw = fh.read(4096)
        h = json.loads(raw.decode("utf-8", "replace").strip())
    except Exception:                                       # noqa: BLE001
        return out
    cfg = h.get("config") or {}
    out["label"] = str(h.get("label", ""))
    out["odr"] = cfg.get("odr_nominal_hz", "")
    out["slot"] = (h.get("sensor") or {}).get("slot", "?")
    out["offset"] = cfg.get("offset_user_steps", 0)
    out["aaf"] = str(cfg.get("aaf", ""))
    out["closed"] = bool((h.get("integrity") or {}).get("closed", True))
    return out


# ===========================================================================
# Figures panel
# ===========================================================================

class FiguresPanel(tk.Frame):
    """A gallery that renders the PNGs, with the TN-20 §6 captions attached.

    Image scaling: Pillow if it is installed, because a Lanczos downscale of a
    matplotlib figure stays legible. Without it, Tk's own PhotoImage can only
    subsample by whole numbers, which is coarse but readable and needs no
    dependency at all. The panel says which path it took rather than quietly
    looking worse than it should.
    """

    def __init__(self, master, app):
        super().__init__(master, bg=C_INK)
        self.app = app
        self.files = []
        self._rows = {}                  # path -> (row, title, filename)
        self.current = None
        self.zoom = 0                    # 0 = fit; otherwise a power of two
        self._img = None                 # keep a reference or Tk frees it
        self._pil = None
        try:
            from PIL import Image, ImageTk       # noqa: F401
            self._pil = (Image, ImageTk)
        except ImportError:
            self._pil = None
        self._build()

    def _build(self):
        head = tk.Frame(self, bg=C_PANEL)
        head.pack(fill="x")
        tk.Label(head, text="FIGURES", bg=C_PANEL, fg=C_DIM,
                 font=(F_UI, 8, "bold")).pack(side="left", padx=(14, 8), pady=9)
        self.dir_var = tk.StringVar()
        tk.Label(head, textvariable=self.dir_var, bg=C_PANEL, fg=C_SIGNAL,
                 font=(F_MONO, 8)).pack(side="left", pady=9)
        FlatButton(head, "Open folder", self._open_folder,
                   small=True).pack(side="right", padx=(0, 12), pady=7)
        FlatButton(head, "Rescan", self.rescan,
                   small=True).pack(side="right", padx=6, pady=7)

        body = tk.Frame(self, bg=C_INK)
        body.pack(fill="both", expand=True)

        # ---- left rail: the plate list -----------------------------------
        rail = tk.Frame(body, bg=C_PANEL, width=248)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        self.rail = ScrollFrame(rail, bg=C_PANEL)
        self.rail.pack(fill="both", expand=True)

        sep(body, horizontal=False).pack(side="left", fill="y")

        # ---- right: the plate --------------------------------------------
        right = tk.Frame(body, bg=C_INK)
        right.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(right, bg=C_TERM, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        self.canvas.bind("<Configure>", lambda _e: self._redraw())

        ctrl = tk.Frame(right, bg=C_INK)
        ctrl.pack(fill="x", padx=10, pady=(7, 0))
        FlatButton(ctrl, "Fit", lambda: self._set_zoom(0), small=True
                   ).pack(side="left", padx=(0, 4))
        FlatButton(ctrl, "1:1", lambda: self._set_zoom(1), small=True
                   ).pack(side="left", padx=4)
        FlatButton(ctrl, "−", lambda: self._step_zoom(-1), small=True
                   ).pack(side="left", padx=4)
        FlatButton(ctrl, "+", lambda: self._step_zoom(+1), small=True
                   ).pack(side="left", padx=4)
        self.meta_var = tk.StringVar(value="")
        tk.Label(ctrl, textvariable=self.meta_var, bg=C_INK, fg=C_FAINT,
                 font=(F_MONO, 8)).pack(side="right")

        cap = tk.Frame(right, bg=C_INK)
        cap.pack(fill="x", padx=10, pady=(8, 10))
        self.cap_title = tk.Label(cap, text="", bg=C_INK, fg=C_SIGNAL,
                                  font=(F_UI, 10, "bold"), anchor="w")
        self.cap_title.pack(fill="x")
        self.cap_body = tk.Label(cap, text="", bg=C_INK, fg=C_DIM,
                                 font=(F_UI, 8), anchor="w", justify="left",
                                 wraplength=640)
        self.cap_body.pack(fill="x", pady=(3, 0))
        cap.bind("<Configure>",
                 lambda e: self.cap_body.configure(wraplength=max(300,
                                                                  e.width - 8)))

    # -- listing -----------------------------------------------------------

    def rescan(self):
        d = self.app.figdir
        self.dir_var.set(d)
        try:
            names = sorted(n for n in os.listdir(d)
                           if n.lower().endswith((".png", ".gif")))
        except OSError:
            names = []
        self.files = [os.path.join(d, n) for n in names]

        for w in self.rail.body.winfo_children():
            w.destroy()
        self._rows.clear()

        results = [p for p in self.files
                   if os.path.splitext(os.path.basename(p))[0] in CAPTIONS]
        others = [p for p in self.files if p not in results]

        if not self.files:
            tk.Label(self.rail.body,
                     text="  no figures yet.\n  Analysis tab → "
                          "Result figures",
                     bg=C_PANEL, fg=C_DIM, font=(F_UI, 8), justify="left",
                     anchor="w").pack(fill="x", padx=12, pady=14)
            self._clear_plate()
            return

        if results:
            section(self.rail.body, "result figures", bg=C_PANEL,
                    pady=(12, 4), padx=12)
            for p in results:
                self._rail_item(p)
        if others:
            section(self.rail.body, f"per-record  ({len(others)})", bg=C_PANEL,
                    pady=(14, 4), padx=12)
            for p in others:
                self._rail_item(p)

        self.rail.to_top()
        if self.current in self.files:
            self.show(self.current)
        else:
            self.show(results[0] if results else self.files[0])

    def _rail_item(self, path):
        stem = os.path.splitext(os.path.basename(path))[0]
        title, _body = describe(stem)
        row = tk.Frame(self.rail.body, bg=C_PANEL)
        row.pack(fill="x")
        lab = tk.Label(row, text="  " + title, bg=C_PANEL, fg=C_TEXT,
                       font=(F_UI, 8), anchor="w", padx=8, pady=4,
                       wraplength=222, justify="left")
        lab.pack(fill="x")
        sub = tk.Label(row, text="  " + stem, bg=C_PANEL, fg=C_FAINT,
                       font=(F_MONO, 7), anchor="w", padx=8)
        sub.pack(fill="x", pady=(0, 4))
        # Held in a dict rather than stamped onto the widget. The section
        # headings are children of the same body frame, so walking
        # winfo_children() and testing for an attribute would mean every
        # heading had to be recognised by something it does not have.
        self._rows[path] = (row, lab, sub)
        for w in (row, lab, sub):
            w.bind("<Button-1>", lambda _e, p=path: self.show(p))
            w.bind("<Enter>", lambda _e, p=path: self._rail_hover(p, True))
            w.bind("<Leave>", lambda _e, p=path: self._rail_hover(p, False))

    def _rail_hover(self, path, on):
        if path == self.current:
            return
        widgets = self._rows.get(path)
        if not widgets:
            return
        bg = "#1a212b" if on else C_PANEL
        for w in widgets:
            w.configure(bg=bg)

    def _mark_active(self):
        for path, (row, lab, sub) in self._rows.items():
            active = (path == self.current)
            bg = C_HILITE if active else C_PANEL
            row.configure(bg=bg)
            lab.configure(bg=bg, fg=C_SIGNAL if active else C_TEXT)
            sub.configure(bg=bg)

    # -- rendering ---------------------------------------------------------

    def show(self, path):
        self.current = path
        stem = os.path.splitext(os.path.basename(path))[0]
        title, body = describe(stem)
        self.cap_title.configure(text=title)
        self.cap_body.configure(text=body)
        self._mark_active()
        self.zoom = 0
        self._redraw()

    def _clear_plate(self):
        self.current = None
        self._img = None
        self.canvas.delete("all")
        self.cap_title.configure(text="")
        self.cap_body.configure(text="")
        self.meta_var.set("")

    def _set_zoom(self, z):
        self.zoom = z
        self._redraw()

    def _step_zoom(self, d):
        if self.zoom == 0:
            self.zoom = 1          # leaving fit: start from actual size
        self.zoom = max(1, min(8, self.zoom + d))
        self._redraw()

    def _redraw(self):
        self.canvas.delete("all")
        if not self.current or not os.path.exists(self.current):
            return
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        if cw < 40 or ch < 40:
            return

        try:
            img, native, shown = self._load(self.current, cw - 16, ch - 16)
        except Exception as e:                              # noqa: BLE001
            self.canvas.create_text(cw // 2, ch // 2, fill=C_ERROR,
                                    font=(F_MONO, 9),
                                    text=f"cannot render this image\n{e}")
            return

        self._img = img
        self.canvas.create_image(cw // 2, ch // 2, image=img)
        how = "Pillow" if self._pil else "Tk subsample"
        self.meta_var.set(f"{native[0]}×{native[1]} px   →  "
                          f"{shown[0]}×{shown[1]}   [{how}]")

    def _load(self, path, box_w, box_h):
        """Return (tk image, (native w,h), (shown w,h))."""
        if self._pil:
            Image, ImageTk = self._pil
            im = Image.open(path)
            nw, nh = im.size
            if self.zoom == 0:
                scale = min(box_w / nw, box_h / nh, 1.0)
            else:
                scale = float(self.zoom)
            tw, th = max(1, int(nw * scale)), max(1, int(nh * scale))
            if (tw, th) != (nw, nh):
                resample = getattr(Image, "Resampling", Image).LANCZOS
                im = im.resize((tw, th), resample)
            return ImageTk.PhotoImage(im), (nw, nh), (tw, th)

        # No Pillow. PhotoImage handles PNG on Tk 8.6, but scales only by
        # whole numbers, so fit becomes "the smallest subsample that fits".
        img = tk.PhotoImage(file=path)
        nw, nh = img.width(), img.height()
        if self.zoom == 0:
            k = 1
            while (nw // k) > box_w or (nh // k) > box_h:
                k += 1
                if k > 12:
                    break
            if k > 1:
                img = img.subsample(k, k)
        elif self.zoom > 1:
            img = img.zoom(int(self.zoom), int(self.zoom))
        return img, (nw, nh), (img.width(), img.height())

    def _open_folder(self):
        d = self.app.figdir
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)                                  # noqa: S606
        except AttributeError:
            subprocess.Popen(["xdg-open", d])                # noqa: S603,S607
