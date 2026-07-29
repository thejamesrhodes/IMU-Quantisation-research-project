#!/usr/bin/env python3
"""
figures.py -- result figures for the Sheppard campaign, from summary.csv.

    python figures.py "..\\..\\Test Datasets\\summary.csv" -o "..\\..\\Figures"

These are RESULT figures, not diagnostics: analyse.py already produces the
per-record spectra, Allan curves and overviews. This draws the things that only
exist once records are compared with each other.

CONVENTIONS USED THROUGHOUT
  Delta   the 16-bit LSB, 2000/32768 dps = 61.035 mdps
  rho     sigma / Delta, the dither ratio -- the independent variable
  phi     mu mod Delta, in units of Delta. EDGE-referenced, because the
          quantiser truncates (TN-19 section 1). TN-12/13/14 reference mu to
          code CENTRES, so phi_TN14 = phi_measured - 0.5 (mod 1). See fig 2.
  eta     (Var[Q(x)] - Var[x]) / (Delta^2 / 12), the added-power ratio.
          +1 is the classical dither limit, negative is the dead-zone regime.
"""

from __future__ import annotations

import argparse
import csv
import glob
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyse import eta_exact                                  # noqa: E402

# TN-14 section 1.3, computed before any data was taken.
TN14 = {25: (0.165, -0.298), 50: (0.234, -0.266), 100: (0.331, 0.255),
        200: (0.468, 0.844), 500: (0.739, 0.999), 1000: (1.077, 1.000)}

C1, C2 = "#1f77b4", "#d62728"          # specimen 1, specimen 2
CPRED = "#444444"
MARK = {"X": "o", "Y": "s", "Z": "^"}

plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 160,
    "axes.grid": True, "grid.alpha": 0.25,
    "font.size": 9, "axes.titlesize": 10, "legend.fontsize": 8,
})


def load(path):
    rows = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if not r.get("axis"):
            continue
        try:
            r["odr_nom"] = int(float(r["odr_nom"]))
            r["slot"] = int(float(r["slot"]))
            for k in ("mu_D", "phi", "rho", "rho_clean", "eta", "sigma_mdps",
                      "line_D", "temp_span_mK", "f_meas", "tail_ratio"):
                r[k] = float(r[k])
            r["codes"] = int(float(r["codes"]))
            r["offset_user"] = int(float(r["offset_user"]))
        except (ValueError, KeyError):
            continue
        rows.append(r)
    return rows


def odr_axis(rows):
    """Only the ODR-sweep records; excludes the AAF pair and offset ladder."""
    return [r for r in rows if r["label"].startswith(("s1_odr", "s2_odr"))]


# ==========================================================================

def fig_eta_rho(rows, out):
    """The primary curve. eta against rho, with TN-14's prediction.

    Gate-failed records are drawn hollow. They are not excluded, because
    excluding them silently would hide how much of the axis is currently
    inadmissible -- but they must not be read as measurements of eta at a
    phase: TN-14 section 2 shows a drifting phi smears eta rather than biasing
    it in a known direction.
    """
    fig, ax = plt.subplots(figsize=(7.2, 5.0))

    # Exact theory, not the six tabulated points. The band between the
    # mid-code and code-edge curves is the whole range eta can take at a given
    # rho, and every measurement must fall inside it -- a far stronger
    # statement than agreement with a single phase.
    rr = np.linspace(0.10, 1.45, 200)
    e_mid = np.array([eta_exact(r, 0.5) for r in rr])
    e_edge = np.array([eta_exact(r, 0.0) for r in rr])
    ax.fill_between(rr, e_mid, e_edge, color=CPRED, alpha=0.10, zorder=0,
                    label="exact theory, all φ")
    ax.plot(rr, e_mid, "-", color=CPRED, lw=1.6, zorder=1,
            label=r"exact theory, mid-code ($\varphi_{TN} = 0$)")
    ax.plot(rr, e_edge, "-", color="#c92a2a", lw=1.0, alpha=0.7, zorder=1,
            label=r"exact theory, code edge")

    r_pred = np.array([TN14[k][0] for k in sorted(TN14)])
    e_pred = np.array([TN14[k][1] for k in sorted(TN14)])
    ax.plot(r_pred, e_pred, "d", color=CPRED, ms=6, zorder=2,
            label="TN-14 §1.3 tabulated")

    for r in odr_axis(rows):
        c = C1 if r["slot"] == 1 else C2
        ok = r["gate"] != "FAIL"
        ax.plot(r["rho_clean"], r["eta"], MARK[r["axis"]], color=c, ms=6.5,
                mfc=c if ok else "none", mew=1.3, alpha=0.9, zorder=3)

    ax.axhline(1.0, color="k", lw=0.7, ls=":", zorder=0)
    ax.axhline(0.0, color="k", lw=0.7, zorder=0)
    ax.text(1.28, 1.02, "classical dither limit  η = +1", fontsize=7.5,
            va="bottom", ha="right", color="k")
    ax.text(0.16, -0.55, "dead-zone regime\nη < 0", fontsize=8, color="#555")

    ax.set_xlabel(r"dither ratio  $\rho = \sigma/\Delta$   (line-corrected)")
    ax.set_ylabel(r"added-power ratio  $\eta$")
    ax.set_title("Quantiser added power against dither ratio\n"
                 "ICM-42688-P, two specimens, three axes, ODR 25–8000 Hz")
    ax.set_xlim(0.08, 1.45)
    ax.set_ylim(-0.8, 2.6)

    handles = [Line2D([], [], color=CPRED, lw=1.6,
                      label=r"exact theory, mid-code"),
               Line2D([], [], color="#c92a2a", lw=1.0, alpha=0.7,
                      label=r"exact theory, code edge"),
               Line2D([], [], color=CPRED, marker="d", ls="none",
                      label="TN-14 §1.3 tabulated"),
               Line2D([], [], color=C1, marker="o", ls="none",
                      label="specimen 1"),
               Line2D([], [], color=C2, marker="o", ls="none",
                      label="specimen 2"),
               Line2D([], [], color="k", marker="o", ls="none", mfc="none",
                      label="R2 thermal gate FAILED")]
    ax.legend(handles=handles, loc="lower right", framealpha=0.95, ncol=1)

    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"  -> {out}")


def fig_eta_phi(rows, out):
    """The phase dependence, and the half-LSB convention.

    Every low-rho measurement, plotted against distance from a code centre.
    The two analytic limits as rho -> 0 bracket it:

        mid-code   Q is constant           eta -> -12 rho^2
        on an edge input straddles 50/50   eta -> 3 - 12 rho^2

    The measurements order monotonically under phi_TN14 = phi - 0.5 and under
    no other mapping, which is what fixes the convention.
    """
    sel = [r for r in odr_axis(rows) if r["rho_clean"] < 0.30]
    if not sel:
        print("  (no low-rho records; skipping eta-phi)")
        return

    fig, ax = plt.subplots(figsize=(7.4, 5.2))

    # One exact curve per rho present, because eta(phi) depends on rho and
    # the ODR 25 and ODR 50 records sit at visibly different ones. Drawing a
    # single curve for a median rho would manufacture scatter that is not
    # there.
    rhos = sorted({round(r["rho_clean"], 3) for r in sel})
    dd = np.linspace(0.0, 0.5, 201)
    for i, rho in enumerate(rhos):
        col = plt.cm.viridis(0.15 + 0.6 * i / max(len(rhos) - 1, 1))
        curve = [eta_exact(rho, 0.5 + d) for d in dd]
        ax.plot(dd, curve, "-", color=col, lw=1.6,
                label=fr"exact theory, $\rho$ = {rho:.3f}")

    for r in sel:
        c = C1 if r["slot"] == 1 else C2
        phi_tn = (r["phi"] - 0.5) % 1.0
        d = min(phi_tn, 1 - phi_tn)                  # distance from code centre
        ok = r["gate"] != "FAIL"
        ax.plot(d, r["eta"], MARK[r["axis"]], color=c, ms=8,
                mfc=c if ok else "none", mew=1.4, zorder=4)
        ax.annotate(f"{r['label'].replace('_odr','·')}{r['axis']}",
                    (d, r["eta"]), textcoords="offset points",
                    xytext=(7, 4), fontsize=6.5, color="#666")

    ax.set_xlabel(r"$|\varphi_{\mathrm{TN\text{-}14}}|$   "
                  r"= distance of $\mu$ from a code centre  (units of $\Delta$)")
    ax.set_ylabel(r"$\eta$")
    ax.set_title("Phase dependence at low dither, and the half-LSB convention\n"
                 "ODR 25–50 Hz, both specimens, three axes — "
                 "curves are exact theory, not fits")
    ax.set_xlim(0, 0.52)

    handles = [Line2D([], [], color=C1, marker="o", ls="none",
                      label="specimen 1  (○ X, □ Y, △ Z)"),
               Line2D([], [], color=C2, marker="o", ls="none",
                      label="specimen 2"),
               Line2D([], [], color="k", marker="o", ls="none", mfc="none",
                      label="R2 gate FAILED")]
    ax.legend(handles=handles + ax.get_legend_handles_labels()[0],
              loc="upper left", framealpha=0.95, fontsize=7.5)

    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"  -> {out}")


def fig_rho_odr(rows, out):
    """rho against ODR, measured and predicted -- the axis validation."""
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(10.4, 4.4))

    for slot, c in ((1, C1), (2, C2)):
        pts = sorted([(r["odr_nom"], r["rho_clean"], r["rho"])
                      for r in odr_axis(rows)
                      if r["slot"] == slot and r["axis"] == "X"])
        if not pts:
            continue
        o = [p[0] for p in pts]
        ax.plot(o, [p[2] for p in pts], "o--", color=c, ms=5, alpha=0.45,
                label=f"specimen {slot}, raw")
        ax.plot(o, [p[1] for p in pts], "o-", color=c, ms=6,
                label=f"specimen {slot}, line-corrected")

    o_pred = sorted(TN14)
    ax.plot(o_pred, [TN14[k][0] for k in o_pred], "d-", color=CPRED, lw=1.4,
            label="TN-14 §1.3")
    ax.set_xscale("log")
    ax.set_xlabel("ODR (Hz)")
    ax.set_ylabel(r"$\rho$")
    ax.set_title(r"$\rho$ against ODR")
    ax.legend(loc="upper left")

    # Measured against predicted, the like-for-like comparison.
    for slot, c in ((1, C1), (2, C2)):
        xs, ys = [], []
        for r in odr_axis(rows):
            if r["slot"] == slot and r["axis"] == "X" and r["odr_nom"] in TN14:
                xs.append(TN14[r["odr_nom"]][0])
                ys.append(r["rho_clean"])
        bx.plot(xs, ys, "o", color=c, ms=7, label=f"specimen {slot}")
    lim = [0, 1.2]
    bx.plot(lim, lim, "k-", lw=1, label="1:1")
    bx.set_xlim(lim)
    bx.set_ylim(lim)
    bx.set_xlabel(r"$\rho$ predicted (TN-14 §1.3)")
    bx.set_ylabel(r"$\rho$ measured, line-corrected")
    bx.set_title("Measured against predicted")
    bx.legend(loc="upper left")

    fig.suptitle("Dither ratio: the campaign's independent variable", y=1.0)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"  -> {out}")


def fig_line_vs_odr(rows, out):
    """The 119 Hz contaminant against ODR -- why R4 passes where it matters."""
    fig, ax = plt.subplots(figsize=(7.2, 4.6))

    for slot, c in ((1, C1), (2, C2)):
        pts = sorted({(r["odr_nom"], r["line_D"]) for r in odr_axis(rows)
                      if r["slot"] == slot})
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], "o-",
                    color=c, ms=6, label=f"specimen {slot}")

    ax.axhspan(0, 0.05, color="#2b8a3e", alpha=0.12)
    ax.text(27, 0.055, "negligible against the quantiser step", fontsize=7.5,
            color="#2b8a3e")
    ax.set_xscale("log")
    ax.set_xlabel("ODR (Hz)")
    ax.set_ylabel(r"119 Hz line amplitude  (units of $\Delta$)")
    ax.set_title("The 119 Hz contaminant is removed at low ODR\n"
                 "by the UI decimation filter, not by the AAF")
    ax.legend()

    ax.annotate("contrast points:\nline absent, R4 passes",
                xy=(35, 0.02), xytext=(60, 0.45), fontsize=8,
                arrowprops=dict(arrowstyle="->", color="#2b8a3e", lw=1.2),
                color="#2b8a3e")

    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"  -> {out}")


def fig_offset(rows, out):
    """The OFFSET_USER step size -- and why the current data cannot settle it.

    mu, not phi: phi wraps at 1, so a shift of 10.24 LSB is indistinguishable
    from 0.24. The two candidate step sizes differ by 0.012 Delta per step, and
    thermal drift in mu between records is +/-0.03 Delta, so a one-step or
    five-step lever cannot separate them.
    """
    sel = [r for r in rows if r["label"].startswith("off")]
    if not sel:
        print("  (no offset records; skipping)")
        return

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    base = {}
    for r in sel:
        if r["offset_user"] == 0:
            base[r["axis"]] = r["mu_D"]

    for ax_name in ("X", "Y", "Z"):
        pts = sorted([(r["offset_user"], r["mu_D"] - base.get(ax_name, 0.0))
                      for r in sel if r["axis"] == ax_name])
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts],
                    MARK[ax_name] + "-", ms=7, label=f"gyro {ax_name}")

    k = np.array([0, 5])
    ax.plot(k, 0.512 * k, "--", color="#c92a2a", lw=1.3,
            label=r"0.512 $\Delta$/step  (1/32 dps, datasheet)")
    ax.plot(k, 0.500 * k, ":", color="#2b8a3e", lw=1.8,
            label=r"0.500 $\Delta$/step  (ladder DEGENERATE)")

    ax.set_xlabel("OFFSET_USER steps")
    ax.set_ylabel(r"shift in $\mu$  (units of $\Delta$)")
    ax.set_title("OFFSET_USER step size is unresolved\n"
                 "the two hypotheses differ by 0.06 Δ at 5 steps, "
                 "against ±0.03 Δ of drift")
    ax.legend(loc="upper left")

    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"  -> {out}")


def fig_admissibility(rows, out):
    """What is actually usable. A record can be perfect and inadmissible."""
    recs = {}
    for r in odr_axis(rows):
        recs.setdefault((r["slot"], r["odr_nom"]), r)
    if not recs:
        return

    fig, ax = plt.subplots(figsize=(7.6, 3.6))
    odrs = sorted({k[1] for k in recs})
    for slot, y in ((1, 1), (2, 0)):
        for i, o in enumerate(odrs):
            r = recs.get((slot, o))
            if r is None:
                continue
            if r["gate"] == "FAIL":
                col, txt = "#c92a2a", "R2 FAIL"
            elif r["gate"] == "pass":
                col, txt = "#2b8a3e", "pass"
            else:
                col, txt = "#adb5bd", "no gate"
            ax.add_patch(plt.Rectangle((i - 0.42, y - 0.32), 0.84, 0.64,
                                       color=col, alpha=0.85))
            ax.text(i, y, txt, ha="center", va="center", fontsize=7.5,
                    color="white", weight="bold")
            ax.text(i, y - 0.42, f"{r['temp_span_mK']:.0f} mK", ha="center",
                    va="top", fontsize=6.5, color="#555")

    ax.set_xticks(range(len(odrs)))
    ax.set_xticklabels([f"{o} Hz" for o in odrs])
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["specimen 2", "specimen 1"])
    ax.set_xlim(-0.6, len(odrs) - 0.4)
    ax.set_ylim(-0.75, 1.5)
    ax.grid(False)
    ax.set_title("R2 thermal-gate compliance, first campaign night\n"
                 "descending-ODR ordering left the die drifting through every "
                 "gated record")

    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"  -> {out}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("-o", "--out", default=".")
    ap.add_argument("--records", default=None,
                    help="folder of .sdat records. Figures 10, 12 and 15 need "
                         "the time series and are skipped without it; "
                         "everything else comes from summary.csv alone.")
    ap.add_argument("--only", default=None,
                    help="comma-separated figure numbers, e.g. 7,8,11")
    a = ap.parse_args(argv)

    os.makedirs(a.out, exist_ok=True)
    rows = load(a.csv)
    print(f"{len(rows)} rows from {a.csv}")

    # If --records was not given but the csv sits in a folder of records, use
    # that folder: it is what the operator meant, every time.
    recdir = a.records
    if recdir is None:
        here = os.path.dirname(os.path.abspath(a.csv))
        if glob.glob(os.path.join(here, "*.sdat")):
            recdir = here
            print(f"  records: {recdir}")

    want = None
    if a.only:
        want = {int(t) for t in a.only.replace(" ", "").split(",") if t}

    j = lambda n: os.path.join(a.out, n)                      # noqa: E731
    # fig5 (fig_offset) is no longer generated: it showed the inconclusive
    # 28 July trio and is superseded by fig12, which has the full ladder for
    # both specimens. The function is kept for reference.
    core = [(1, fig_eta_rho, "fig1_eta_vs_rho.png"),
            (2, fig_eta_phi, "fig2_eta_vs_phi.png"),
            (3, fig_rho_odr, "fig3_rho_validation.png"),
            (4, fig_line_vs_odr, "fig4_line_vs_odr.png"),
            (6, fig_admissibility, "fig6_thermal_gate.png")]
    for num, fn, name in core:
        if want and num not in want:
            continue
        try:
            fn(rows, j(name))
        except Exception as e:                                # noqa: BLE001
            print(f"  !! {name}: {type(e).__name__}: {e}")

    extra = []
    for mod in ("figures_results", "figures_transfer"):
        try:
            extra += __import__(mod).ALL
        except Exception as e:                                # noqa: BLE001
            print(f"  ({mod} unavailable: {type(e).__name__}: {e})")
    for name, kind, fn in extra:
        num = int("".join(c for c in name.split("_")[0] if c.isdigit()))
        if want and num not in want:
            continue
        try:
            fn(rows if kind == "rows" else recdir, j(name))
        except Exception as e:                                # noqa: BLE001
            print(f"  !! {name}: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
