#!/usr/bin/env python3
"""
figures_results.py -- the result and diagnostic figures, F7-F15.

Imported by figures.py; kept in its own file because the original six were
written against the ODR axis alone and these need either the controlled phase
ladder, the raw records, or both. Nothing here duplicates a figure that
already existed.

    F7   eta(phi), the CONTROLLED sweep         paper, headline
    F8   the reference-truncation correction    paper, methods
    F9   the vernier                            paper or supplementary
    F10  Allan slopes: -1/2 present, -1 absent  paper, the architectural claim
    F11  consequence for fitted ARW             paper, the "so what"
    F12  OFFSET_USER linearity, both specimens  supplementary
    F13  the R2 estimator                       supplementary
    F14  residual anatomy                       supplementary
    F15  code histograms against prediction     supplementary

CONVENTIONS  (as figures.py, plus)
    phi_ref  phi corrected for the reference stream's own truncation, +1/16
    rho_ref  rho with Sheppard's correction for the reference stream's own
             quantisation noise, sqrt(sigma^2 - (1/8)^2/12)
Both are computed in analyse.Stats and carried in summary.csv. The raw phi and
rho are retained alongside so every figure here can be redrawn either way, and
F8 exists precisely to show the difference.
"""

from __future__ import annotations

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
from analyse import (REF_STEP, Stats, allan_dev, drift_excursion,  # noqa: E402
                     eta_exact)
import sdat                                                       # noqa: E402

C1, C2 = "#1f77b4", "#d62728"
CPRED = "#444444"
CGOOD, CBAD = "#2a9d5c", "#c0392b"
MARK = {"X": "o", "Y": "s", "Z": "^"}
DELTA_MDPS = 61.03515625


def _phase_rows(rows):
    """Slot-1 sweep only.

    Deliberately NOT both specimens. Anything fitting the vernier needs one
    part at a time, because eps is per-part (TN-21 s9) and pooling two would
    fit a step size neither of them has.
    """
    return [r for r in rows if str(r.get("label", "")).startswith("ph_k")]


def _sweep_rows(rows):
    """Both specimens' phase sweeps, slot-1 first so colours stay stable.

    For figures about the THEORY rather than about the register: there the
    second specimen is a replication and belongs in the same axes.
    """
    a = [r for r in rows if str(r.get("label", "")).startswith("ph_k")]
    b = [r for r in rows if str(r.get("label", "")).startswith("s2ph_k")]
    return a + b


def _is_slot2(r):
    return str(r.get("label", "")).startswith("s2ph_k")


def _save(fig, out):
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"  -> {out}")


def _num(r, key, default=float("nan")):
    try:
        return float(r[key])
    except (KeyError, TypeError, ValueError):
        return default


# ==========================================================================
# F7 -- the controlled phase sweep
# ==========================================================================

def fig_phase_sweep(rows, out):
    """eta against phi from the OFFSET_USER ladder. The causal manipulation.

    TN-20 fig2 showed eta spanning -0.24 to +2.42, but those phases were an
    ACCIDENT: the two specimens happened to sit at different bias phases.
    Objection #14 part 2 (Objections v2.1 Z.2) rests on phi being manipulated
    rather than merely observed, and this is the figure that answers it. One
    specimen, one ODR, one configuration; the only thing that changes between
    the sixteen records is a number written to a trim register.

    The curve is exact theory evaluated at each record's own measured rho.
    Nothing is fitted.
    """
    sel = _phase_rows(rows)
    if not sel:
        print("  (no ph_k records; skipping the phase sweep)")
        return

    fig, (ax, bx) = plt.subplots(
        2, 1, figsize=(7.6, 6.6), sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.06})

    rho_m = float(np.mean([_num(r, "rho_ref") for r in sel]))
    pp = np.linspace(0, 1, 401)
    ax.plot(pp, [eta_exact(rho_m, p) for p in pp], "-", color=CPRED, lw=1.8,
            zorder=2, label=fr"exact theory at $\rho$ = {rho_m:.3f}")

    # The band is the spread the theory itself has across the rho actually
    # present, so a point outside it is a real disagreement rather than a
    # consequence of drawing one curve for a range of rho.
    rr = [_num(r, "rho_ref") for r in sel]
    lo = np.array([eta_exact(min(rr), p) for p in pp])
    hi = np.array([eta_exact(max(rr), p) for p in pp])
    ax.fill_between(pp, np.minimum(lo, hi), np.maximum(lo, hi),
                    color=CPRED, alpha=0.13, lw=0, zorder=1,
                    label=fr"$\rho \in$ [{min(rr):.3f}, {max(rr):.3f}]")

    for r in sel:
        ax.plot(_num(r, "phi_ref"), _num(r, "eta"), MARK[r["axis"]],
                color=C1, ms=7, mfc=C1, mew=0, alpha=0.9, zorder=4)
        bx.plot(_num(r, "phi_ref"), _num(r, "eta_resid"), MARK[r["axis"]],
                color=C1, ms=6, mew=0, alpha=0.9)

    res = np.array([_num(r, "eta_resid") for r in sel])
    rms = float(np.sqrt(np.mean(res ** 2)))

    ax.axhline(1.0, color="#888", ls=":", lw=1)
    ax.annotate(r"classical dither limit, $\eta = 1$", (0.5, 1.0),
                ha="center", xytext=(0, 6), textcoords="offset points",
                fontsize=7.5, color="#666")
    ax.axhline(0.0, color="#888", ls="-", lw=0.6)
    ax.set_ylabel(r"$\eta$   (added power / $(\Delta^2/12)$)")
    ax.set_title(
        "Controlled phase sweep: OFFSET_USER ladder, specimen 1, ODR 50 Hz\n"
        f"{len(sel)} measurements, three axes — curve is exact theory with "
        "no free parameters")
    ax.legend(handles=[
        Line2D([], [], color=CPRED, lw=1.8, label=ax.get_legend_handles_labels()[1][0]),
        Line2D([], [], color=CPRED, lw=8, alpha=0.3,
               label=ax.get_legend_handles_labels()[1][1]),
        Line2D([], [], color=C1, marker="o", ls="none", label="X"),
        Line2D([], [], color=C1, marker="s", ls="none", label="Y"),
        Line2D([], [], color=C1, marker="^", ls="none", label="Z")],
        loc="lower right", fontsize=7.5, framealpha=0.95)

    bx.axhline(0, color=CPRED, lw=1)
    m = float(res.mean())
    bx.axhspan(m - res.std(), m + res.std(), color=CPRED, alpha=0.12, lw=0)
    bx.axhline(m, color=CPRED, lw=0.8, ls="--")
    bx.set_ylim(-0.09, 0.09)
    bx.set_xlim(0, 1)
    bx.set_xlabel(r"$\varphi$, sub-code phase of the bias  (units of $\Delta$, "
                  r"edge-referenced)")
    bx.set_ylabel("residual")
    span = max(_num(r, "eta") for r in sel) - min(_num(r, "eta") for r in sel)
    bx.annotate(f"RMS {rms:.4f} = {100 * rms / span:.1f}% of the "
                rf"$\eta$ range;  mean {m:+.4f}",
                (0.985, 0.062), ha="right", fontsize=7.5, color="#555")
    _save(fig, out)


# ==========================================================================
# F8 -- the reference stream is a quantiser too
# ==========================================================================

def fig_reference_truncation(rows, out):
    """Why the 19-bit reference needs Sheppard's correction applied to itself.

    The reference stream is the 20-bit hi-res field over 16, and that field is
    a truncating quantiser with step 0.125 Delta (its own LSB is always zero,
    TN-19 s1). A truncator's mean sits half a step low, so every phase read
    from the reference is low by 1/16 Delta, and its variance carries
    step^2/12 of its own quantisation noise.

    THREE PANELS, because the correction has three parts and the campaign
    applied two of them for a day (TN-24 s3). Drawing only the before and after
    hides the most instructive step: after correcting phi and rho the residual
    stops being phi-shaped but keeps a CONSTANT offset, and that constant is
    (Delta'/Delta)^2 = 1/64 exactly -- eta's own missing term.

    Left:   nothing corrected. Not scatter: a smooth sign-changing function of
            phi, the signature of a phase offset.
    Middle: phi and rho corrected. The shape is gone, a constant is left.
    Right:  eta corrected too. Zero mean, and the spread is what the apparatus
            can repeat to.

    No free parameters anywhere: 1/16 and 1/64 are both forced by Delta' =
    Delta/8.
    """
    sel = _sweep_rows(rows)
    if not sel:
        print("  (no ph_k records; skipping the truncation figure)")
        return

    REF_STEP = 2.0 / 16.0
    ETA_FIX = REF_STEP ** 2                     # 1/64, see TN-24 s3.2

    # NOT sharey across all three. Panel 1's residual is 0.38 RMS and panels 2
    # and 3 are 0.019 and 0.012, so a common axis makes the last two visually
    # identical and the middle panel cannot show the constant it exists to
    # show. Panels 2 and 3 share a zoomed axis with each other, which is the
    # comparison that matters, and panel 1 is annotated with the change of
    # scale so nobody reads the widths as comparable.
    fig, axes = plt.subplots(1, 3, figsize=(13.8, 4.5))
    axes[2].sharey(axes[1])

    none_, two, three = [], [], []
    for r in sel:
        rho, phi = _num(r, "rho"), _num(r, "phi")
        # eta as stored is now the FULLY corrected value, so undo the eta part
        # to recover the two intermediate states rather than hard-coding them.
        e_full = _num(r, "eta")
        e_uncorr = e_full - ETA_FIX
        s2 = 1.0 if _is_slot2(r) else 0.0
        none_.append((phi, e_uncorr - eta_exact(rho, phi), s2))
        two.append((_num(r, "phi_ref"), e_uncorr - _num(r, "eta_exact"), s2))
        three.append((_num(r, "phi_ref"), _num(r, "eta_resid"), s2))
    none_, two, three = np.array(none_), np.array(two), np.array(three)

    panels = (
        (axes[0], none_, "1  Nothing corrected\n"
                         r"$\varphi,\rho$ straight from the reference stream"),
        (axes[1], two, "2  Phase and width corrected\n"
                       r"$\varphi + \frac{1}{16}$,  $\sigma^2 - \Delta'^2/12$"),
        (axes[2], three, "3  And $\\eta$ corrected\n"
                         r"$+\,(\Delta'/\Delta)^2 = \frac{1}{64}$"),
    )
    for panel, dat, title in panels:
        panel.axhline(0, color=CPRED, lw=1)
        # Two specimens, distinguished. The replication is the second-strongest
        # claim in the paper and it should be visible in the figure rather than
        # only in the caption.
        for s2, mk, col, lab in ((0.0, "o", C1, "specimen 1"),
                                 (1.0, "^", CBAD, "specimen 2")):
            m = dat[:, 2] == s2
            if m.any():
                panel.plot(dat[m, 0], dat[m, 1], mk, color=col, ms=5.5, mew=0,
                           alpha=0.8, label=lab)
        rms = float(np.sqrt(np.mean(dat[:, 1] ** 2)))
        mean = float(np.mean(dat[:, 1]))
        panel.axhspan(-rms, rms, color=CPRED, alpha=0.12, lw=0)
        panel.set_title(title, fontsize=9.5)
        panel.set_xlabel(r"$\varphi$  (units of $\Delta$)")
        panel.set_xlim(0, 1)
        panel.annotate(f"RMS {rms:.4f}\nmean {mean:+.4f}",
                       (0.5, 0.94), xycoords="axes fraction",
                       ha="center", va="top", fontsize=10, color="#333")
    axes[2].legend(loc="lower right", fontsize=8, framealpha=0.95)

    # The smooth trend on panel 1, so the eye sees a systematic and not a cloud.
    o = np.argsort(none_[:, 0])
    axes[0].plot(none_[o, 0],
                 np.convolve(none_[o, 1], np.ones(5) / 5, mode="same"),
                 "-", color=CBAD, lw=1.4, alpha=0.8, zorder=1)

    # Panel 2's constant, drawn as the line it is. This is the whole point of
    # having a middle panel: a flat non-zero offset is a different diagnosis
    # from a phi-shaped one, and it names its own cause.
    axes[1].axhline(-ETA_FIX, color="#111", lw=1.6, ls="--", zorder=4,
                    label=r"$-(\Delta'/\Delta)^2 = -\frac{1}{64}$, predicted")
    axes[1].legend(loc="lower right", fontsize=8.5, framealpha=0.95)

    axes[0].set_ylabel(r"$\eta_{\mathrm{measured}} - \eta_{\mathrm{exact}}$")
    axes[0].set_ylim(-0.95, 0.95)
    axes[1].set_ylim(-0.062, 0.062)
    axes[1].set_ylabel(r"$\eta_{\mathrm{measured}} - \eta_{\mathrm{exact}}$"
                       "\n(note the change of scale)", fontsize=9)
    # Mark on panel 1 how far the next two are zoomed, so the eye is not
    # invited to compare spreads across the break.
    axes[0].axhspan(-0.062, 0.062, color="#111", alpha=0.10, lw=0, zorder=0)
    axes[0].annotate("panels 2--3 span\nthis band only",
                     (0.03, 0.062), fontsize=7.5, color="#444",
                     ha="left", va="bottom")
    fig.suptitle("Sheppard's correction, applied to the instrument's own "
                 "reference channel --- in all three places it belongs",
                 fontsize=10.5)
    _save(fig, out)


# ==========================================================================
# F9 -- the vernier
# ==========================================================================

def fig_vernier(rows, out, s=0.499513):
    """A trim register too coarse to resolve one LSB, used as a fine phase control.

    One OFFSET_USER step is 0.4995 Delta -- so close to half an LSB that a
    naive ladder reaches two phases and nothing else. It is the small MISS
    that makes it work: with s = 1/2 - eps the even steps precess by 2 eps
    each and sweep the whole period in 1/(2 eps) steps.

    This is a method contribution in its own right, and the figure is the
    clearest way to say it.
    """
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(10.8, 4.4),
                                 gridspec_kw={"width_ratios": [1.4, 1]})

    # The unit's own untrimmed bias phase, and its own step size. Two things
    # have to come from the data being plotted rather than from elsewhere:
    #
    #   phi0  the ladder starts wherever the part happens to sit, so a curve
    #         anchored at zero would describe a different sensor;
    #   s     mu does not wrap, so the sweep measures its own step size to
    #         1.3e-5 -- better than the dedicated ladder did, and the two
    #         DISAGREE (see the annotation). Using the other run's number here
    #         would draw a line the data is not obliged to follow.
    sel = _phase_rows(rows)
    seen, mus = {}, {}
    for r in sel:
        kk = int(_num(r, "offset_user", 0))
        seen.setdefault(kk, _num(r, "phi_ref"))
        mus.setdefault(kk, []).append(_num(r, "mu_D"))
    phi0 = seen.get(0, 0.0)
    s_lad = s
    if len(mus) >= 3:
        kk = np.array(sorted(mus), dtype=float)
        mm = np.array([np.mean(mus[int(q)]) for q in kk])
        A = np.column_stack([kk, np.ones_like(kk)])
        beta, *_ = np.linalg.lstsq(A, mm, rcond=None)
        resid = mm - A @ beta
        se = float(resid.std(ddof=2) / math.sqrt(np.sum((kk - kk.mean()) ** 2)))
        s = float(beta[0])

    k = np.arange(2048)
    ax.plot(k, (phi0 + 0.5 * k) % 1.0, ".", color="#c8c8c8", ms=1.4,
            label=r"if $s$ were exactly $\frac{1}{2}$: two phases, for ever")
    ax.plot(k, (phi0 + s * k) % 1.0, ".", color=C1, ms=1.4,
            label=fr"$s$ fitted here = {s:.6f}: all 2048")

    if seen:
        ax.plot(list(seen), list(seen.values()), "o", color=CBAD, ms=7,
                mfc="none", mew=1.6, zorder=5,
                label=f"the {len(seen)} records run")

    ax.set_xlabel("OFFSET_USER step count $k$")
    ax.set_ylabel(r"$\varphi$  (units of $\Delta$)")
    ax.set_title("A trim register too coarse to resolve one LSB,\n"
                 "used as a fine phase control")
    ax.legend(handles=[
        Line2D([], [], color="#c8c8c8", marker=".", ls="none", ms=9,
               label=r"if $s$ were exactly $\frac{1}{2}$: two phases, for ever"),
        Line2D([], [], color=C1, marker=".", ls="none", ms=9,
               label=fr"$s$ fitted here = {s:.6f}: all 2048"),
        Line2D([], [], color=CBAD, marker="o", ls="none", mfc="none", mew=1.6,
               ms=7, label=f"the {len(seen)} records run")],
        loc="lower left", fontsize=7.5, framealpha=0.95)
    ax.set_xlim(-20, 2067)
    ax.set_ylim(-0.02, 1.02)

    # The honest caveat, and it is the reason phi is measured per record rather
    # than commanded: eps is known to 15%, so the predicted phase degrades as
    # k grows even though the ladder itself is exact.
    if seen:
        kk = np.array(sorted(seen), dtype=float)
        pm = np.array([seen[int(q)] for q in kk])
        pp = (phi0 + s * kk) % 1.0
        err = np.abs(((pm - pp + 0.5) % 1.0) - 0.5)
        ax.annotate(
            f"$s$ from this sweep: {s:.6f} $\\pm$ {se:.6f}\n"
            f"$s$ from the dedicated ladder: {s_lad:.6f}   "
            f"({abs(s - s_lad) * 1920:.2f} $\\Delta$ apart at $k$=1920)\n"
            f"residual of the points about the fitted line: "
            f"{err.mean():.3f} $\\Delta$ mean\n"
            r"$\varphi$ is MEASURED per record, so neither number is "
            "load-bearing",
            (0.5, 1.14), xycoords="axes fraction", ha="center", va="top",
            fontsize=7, color="#444",
            bbox=dict(fc="white", ec="#ccc", alpha=0.92, pad=3))

    # Coverage: the largest gap left in phase as k is allowed to grow.
    ks = [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048]
    gap = []
    for n in ks:
        p = np.sort((s * np.arange(n)) % 1.0)
        gap.append(float(np.max(np.diff(np.concatenate([p, [p[0] + 1]])))))
    bx.loglog(ks, gap, "o-", color=C1, lw=1.6, ms=5, label="vernier")
    bx.axhline(0.008, color=CBAD, ls="--", lw=1.4,
               label="64/125 scheme assumed by the corpus")
    bx.axhline(0.5, color="#bbb", ls=":", lw=1.4,
               label=r"degenerate ladder, $s = \frac{1}{2}$ exactly")
    bx.set_xlabel("number of step counts used")
    bx.set_ylabel(r"largest gap left in $\varphi$  ($\Delta$)")
    bx.set_title("Phase coverage")
    bx.legend(loc="lower left", fontsize=7.5, framealpha=0.95)
    _save(fig, out)


# ==========================================================================
# F10 -- the architectural claim, in the Allan domain
# ==========================================================================

def fig_allan_family(recdir, out, labels=("s1_odr25", "s2_odr25",
                                          "s1_odr50", "s1_odr100")):
    """The paper's strongest claim, drawn.

    IEEE-952's quantisation term Q sits at slope -1 and belongs to
    angle-INCREMENT outputs (FOG/RLG). A rate register has no such term: its
    quantisation lands on the -1/2 family and is absorbed into fitted ARW.
    So the figure to draw is the ABSENCE of a -1 slope, with a -1 reference
    line placed where IEEE-952 would put it, and the measured curve visibly
    parallel to -1/2 instead.
    """
    if not recdir:
        print("  (no --records dir; skipping the Allan family)")
        return
    files = []
    for lab in labels:
        g = glob.glob(os.path.join(recdir, f"*{lab}_*.sdat"))
        if g:
            files.append((lab, sorted(g)[0]))
    if not files:
        print("  (no matching records; skipping the Allan family)")
        return

    fig, ax = plt.subplots(figsize=(7.4, 5.4))
    anchor = None
    for i, (lab, path) in enumerate(files):
        rec = sdat.load(path)
        fs = (rec.header.get("timing") or {}).get("f_measured_mhz", 0) / 1000.0
        taus, devs = allan_dev(rec.gyro20[:, 0].astype(float) / 16.0
                               * (1.0 / 16.384), fs)
        col = plt.cm.viridis(0.12 + 0.62 * i / max(len(files) - 1, 1))
        ax.loglog(taus, devs * 1e3, "-", color=col, lw=1.7, label=lab)
        if anchor is None and taus.size:
            j = int(np.argmin(np.abs(taus - 0.2)))
            anchor = (float(taus[j]), float(devs[j] * 1e3))

    # Anchor both reference slopes ON the data at a common tau. A reference
    # line floating above the curves invites the reader to compare positions;
    # anchored, the only thing left to compare is the slope, which is the
    # entire claim.
    if anchor:
        t_a, y_a = anchor
        t0 = np.array([t_a * 0.6, t_a * 120.0])
        ax.loglog(t0, y_a * (t0 / t_a) ** -0.5, "--", color="#333", lw=1.5,
                  zorder=6)
        ax.annotate(r"$-\frac{1}{2}$  ARW — and where rate-register"
                    "\nquantisation lands, absorbed into it",
                    (t0[1], y_a * (t0[1] / t_a) ** -0.5), fontsize=8.5,
                    color="#222", xytext=(-4, 12), textcoords="offset points",
                    ha="right", va="bottom",
                    bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.5))
        ax.loglog(t0, y_a * (t0 / t_a) ** -1.0, ":", color=CBAD, lw=1.8,
                  zorder=6)
        ax.annotate(r"$-1$  IEEE-952 $Q$, if this part emitted"
                    "\nangle increments. It does not, and"
                    "\nno such term appears.",
                    (t_a * 6, y_a * 6.0 ** -1.0), fontsize=8.5, color=CBAD,
                    xytext=(14, 4), textcoords="offset points", ha="left",
                    bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.5))
        ax.set_ylim(y_a * 0.02, y_a * 6)

    ax.set_xlabel(r"$\tau$  (s)")
    ax.set_ylabel(r"$\sigma(\tau)$  (mdps)")
    ax.set_title("Allan deviation of the rate register\n"
                 "the quantisation term is on the "
                 r"$-\frac{1}{2}$ family, not at $-1$")
    ax.legend(loc="lower left", fontsize=8, framealpha=0.95)
    ax.grid(True, which="both", alpha=0.22)
    _save(fig, out)


# ==========================================================================
# F11 -- what it does to a practitioner's fitted ARW
# ==========================================================================

def fig_arw_consequence(rows, out):
    """The "so what", in the units a practitioner calibrates in.

    The register contributes eta * Delta^2 / (6 ODR) to the observed white
    noise density (GMWM-to-Kalman-Q v1.2 Z.1, after the double-count erratum).
    Fitted ARW therefore carries a multiplicative error

        ARW_fit / ARW_true = sqrt(1 + eta * Delta^2 / (6 ODR S_x))

    which depends on eta and so on a phase nobody measures. The point of the
    figure is that the error is not small, not one-signed, and not knowable
    from anything in a datasheet.
    """
    sel = _phase_rows(rows)
    if not sel:
        print("  (no ph_k records; skipping the ARW consequence)")
        return

    fig, ax = plt.subplots(figsize=(7.6, 5.0))
    odr = float(np.median([_num(r, "odr_nom", 50) for r in sel]))
    # DS-000347 Rev 1.6 section 5.5, UI filter noise bandwidth at BW = 0.
    NBW = {25: 13.0, 50: 26.0, 100: 52.0, 200: 104.0, 500: 260.0, 1000: 519.0}
    nbw = NBW.get(int(odr), 0.52 * odr)
    for r in sel:
        sig = _num(r, "rho_ref") * DELTA_MDPS  # Sheppard-corrected, mdps
        if not (sig == sig) or sig <= 0:
            continue
        Sx = (sig ** 2) / nbw                  # mdps^2/Hz
        add = _num(r, "eta") * DELTA_MDPS ** 2 / (6.0 * odr)
        ax.plot(_num(r, "phi_ref"), math.sqrt(max(1 + add / Sx, 0.0)),
                MARK[r["axis"]], color=C1, ms=7, mew=0, alpha=0.9)

    pp = np.linspace(0, 1, 401)
    rho_m = float(np.mean([_num(r, "rho_ref") for r in sel]))
    Sx = (rho_m * DELTA_MDPS) ** 2 / nbw
    curve = [math.sqrt(max(1 + eta_exact(rho_m, p) * DELTA_MDPS ** 2
                           / (6 * odr) / Sx, 0.0)) for p in pp]
    lo_r = min(math.sqrt(max(1 + _num(r, "eta") * DELTA_MDPS ** 2
                             / (6 * odr) / Sx, 0.0)) for r in sel)
    hi_r = max(math.sqrt(max(1 + _num(r, "eta") * DELTA_MDPS ** 2
                             / (6 * odr) / Sx, 0.0)) for r in sel)
    ax.annotate(f"measured span: ×{hi_r / lo_r:.1f} in fitted ARW, from one\n"
                "register setting and one phase nobody measures",
                (0.97, 0.055), xycoords="axes fraction", ha="right",
                fontsize=8.5, color="#333",
                bbox=dict(fc="white", ec="#ccc", alpha=0.9, pad=3))
    ax.plot(pp, curve, "-", color=CPRED, lw=1.8, zorder=2,
            label="exact theory")
    cls = math.sqrt(1 + DELTA_MDPS ** 2 / (6 * odr) / Sx)
    ax.axhline(cls, color=CBAD, ls="--", lw=1.5,
               label=fr"what the classical model predicts, $\eta$=1: "
                     fr"{cls:.3f}")
    ax.axhline(1.0, color="#888", ls=":", lw=1,
               label="no register contribution at all")

    ax.set_xlabel(r"$\varphi$  — unmeasured by every calibration toolchain")
    ax.set_ylabel(r"ARW$_{\mathrm{fit}}$ / ARW$_{\mathrm{true}}$")
    ax.set_title(f"Consequence for a fitted angle random walk, ODR {odr:.0f} Hz\n"
                 "the same sensor, the same configuration, a different "
                 "sub-LSB bias phase")
    ax.set_xlim(0, 1)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.95)
    _save(fig, out)


# ==========================================================================
# F12 -- OFFSET_USER linearity
# ==========================================================================

def fig_offset_linearity(recdir, out):
    """Shift against step count for both specimens, and the residual.

    Replaces the old fig5, which showed the inconclusive 28 July trio. The
    slope is the step size; the intercept is a fixed per-record offset that
    biases any single-pair estimate by c/k, which is why the four-step
    measurement could not have worked at any sample size.
    """
    if not recdir:
        print("  (no --records dir; skipping offset linearity)")
        return
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(7.4, 5.8), sharex=True,
                                 gridspec_kw={"height_ratios": [2.4, 1],
                                              "hspace": 0.08})
    any_pts = False
    for pat, col, name in (("*_off_*", C1, "specimen 1"),
                           ("*p2cal*", C2, "specimen 2")):
        pts = []
        for f in sorted(glob.glob(os.path.join(recdir, pat + ".sdat"))):
            rec = sdat.load(f)
            h = rec.header
            t = h.get("timing") or {}
            fs = t.get("f_measured_mhz", 0) / 1000.0 or 1000.0
            i0 = int(round(fs))
            x = rec.gyro20[i0:, 0].astype(float) / 16.0
            pts.append((int((h.get("config") or {})["offset_user_steps"]),
                        float(x.mean()), float(t.get("ts_first_us", 0))))
        if len(pts) < 3:
            continue
        pts.sort(key=lambda p: p[2])
        k = np.array([p[0] for p in pts], float)
        mu = np.array([p[1] for p in pts])
        zi = np.flatnonzero(k == 0)
        base = np.interp(np.arange(len(k)), zi, mu[zi])
        sh = mu - base
        m = k > 0
        A = np.column_stack([k[m], np.ones(m.sum())])
        beta, *_ = np.linalg.lstsq(A, sh[m], rcond=None)
        ax.plot(k[m], sh[m], "o", color=col, ms=7, mew=0,
                label=f"{name}: $s$ = {beta[0]:.6f}, $c$ = {beta[1]:+.3f}")
        kk = np.linspace(0, 2050, 50)
        ax.plot(kk, beta[0] * kk + beta[1], "-", color=col, lw=1.2, alpha=0.6)
        bx.plot(k[m], sh[m] - (A @ beta), "o", color=col, ms=7, mew=0)
        any_pts = True

    if not any_pts:
        plt.close(fig)
        print("  (too few offset records; skipping)")
        return

    ax.plot([0, 2050], [0, 2050 * 0.512], ":", color=CBAD, lw=1.5,
            label=r"datasheet, $1/32$ dps = 0.512 $\Delta$/step")
    ax.set_ylabel(r"shift in $\mu$  ($\Delta$)")
    ax.set_title("OFFSET_USER is linear to 2000 steps, and its step is not "
                 "the datasheet value\nbaseline removed by interpolating the "
                 r"$k=0$ returns")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.95)
    bx.axhline(0, color=CPRED, lw=1)
    bx.set_xlabel("OFFSET_USER step count $k$")
    bx.set_ylabel("residual")
    bx.set_xlim(-40, 2090)
    _save(fig, out)


# ==========================================================================
# F13 -- the R2 estimator
# ==========================================================================

def fig_r2_estimator(rows, out):
    """Why the gate was failing records that were fine.

    max - min over N samples is an extreme-value statistic: it grows as about
    8.5 sigma at N = 6e4, so it measured the die thermometer's own noise. And
    because the temperature channel is filtered with ODR, sigma_T runs from
    13 mK at ODR 25 to 120 mK at ODR 8000 -- so the gate tightened as ODR fell,
    for a reason that had nothing to do with temperature.
    """
    sel = [r for r in rows
           if _num(r, "gate_mK", 0) > 0 and r.get("axis") == "X"]
    if not sel:
        print("  (no gated records; skipping the R2 estimator figure)")
        return
    sel.sort(key=lambda r: (r["label"]))

    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    xs = np.arange(len(sel))
    span = [_num(r, "temp_span_mK") for r in sel]
    drift = [_num(r, "temp_drift_mK") for r in sel]
    gate = [_num(r, "gate_mK") for r in sel]

    ax.bar(xs - 0.2, span, 0.38, color="#c9c9c9", label="max − min, as gated "
                                                        "until 29 Jul")
    ax.bar(xs + 0.2, drift, 0.38, color=C1, label="actual drift across the "
                                                  "record")
    for i, g in enumerate(gate):
        ax.plot([i - 0.45, i + 0.45], [g, g], "-", color=CBAD, lw=2,
                zorder=5)
    ax.plot([], [], "-", color=CBAD, lw=2, label="R2 gate (TN-14 §2.2)")

    for i, r in enumerate(sel):
        old = "FAIL" if span[i] > gate[i] else "pass"
        new = "pass" if drift[i] <= gate[i] else "FAIL"
        ax.annotate(f"{old}→{new}", (i, max(span[i], gate[i])),
                    xytext=(0, 4), textcoords="offset points", ha="center",
                    fontsize=6.5,
                    color=CGOOD if (old, new) == ("FAIL", "pass") else "#666")

    ax.set_xticks(xs)
    ax.set_xticklabels([r["label"] for r in sel], rotation=35, ha="right",
                       fontsize=7.5)
    ax.set_ylabel("mK")
    ax.set_title("The R2 gate was evaluated on an extreme-value statistic\n"
                 "every gated record passes once the drift is estimated "
                 "instead of the range")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.95)
    _save(fig, out)


# ==========================================================================
# F14 -- residual anatomy
# ==========================================================================

def fig_residual_anatomy(rows, out):
    """Where the remaining 0.018 goes, and what it is not correlated with.

    A residual that correlates with nothing available is the honest end of an
    analysis; one that correlates with phi, or with rho, or with drift, is an
    unmodelled term. This is the figure that says which.
    """
    sel = _phase_rows(rows)
    if not sel:
        print("  (no ph_k records; skipping residual anatomy)")
        return
    res = np.array([_num(r, "eta_resid") for r in sel])

    fig, axes = plt.subplots(1, 4, figsize=(12.4, 3.4))
    for panel, key, lab in (
            (axes[0], "phi_ref", r"$\varphi$"),
            (axes[1], "rho_ref", r"$\rho$"),
            (axes[2], "mu_drift_D", r"in-record $\mu$ drift  ($\Delta$)")):
        v = np.array([_num(r, key) for r in sel])
        panel.plot(v, res, "o", color=C1, ms=5, mew=0, alpha=0.8)
        panel.axhline(0, color=CPRED, lw=1)
        good = np.isfinite(v) & np.isfinite(res)
        c = np.corrcoef(v[good], res[good])[0, 1] if good.sum() > 2 else np.nan
        panel.set_title(f"vs {lab}\n$r$ = {c:+.2f}", fontsize=9)
        panel.set_xlabel(lab)
    axes[0].set_ylabel(r"$\eta$ residual")

    axes[3].hist(res, bins=12, color=C1, alpha=0.85)
    axes[3].axvline(0, color=CPRED, lw=1)
    axes[3].set_title(f"distribution\nRMS {np.sqrt(np.mean(res ** 2)):.4f}",
                      fontsize=9)
    axes[3].set_xlabel(r"$\eta$ residual")
    fig.suptitle("Residual anatomy after the reference-truncation correction "
                 "— 48 measurements, no free parameters", fontsize=10)
    _save(fig, out)


# ==========================================================================
# F15 -- code histograms
# ==========================================================================

def fig_code_histograms(recdir, out, labels=("ph_k0512", "ph_k0000",
                                             "ph_k1024", "ph_k0896")):
    """The marginal channel, which is orthogonal to everything eta uses.

    eta is a variance statistic. The code histogram is a distributional one,
    computed from the same records but sensitive to different things -- which
    is what rule R6 means by refusing to select a hypothesis on a single
    summary statistic. Predicted occupancy for a truncating quantiser with
    Gaussian input at the measured (rho, phi) is

        P(j) = Phi(j + 1 - phi_c) - Phi(j - phi_c)

    with no fitted quantities.
    """
    if not recdir:
        print("  (no --records dir; skipping code histograms)")
        return
    files = []
    for lab in labels:
        g = glob.glob(os.path.join(recdir, f"*{lab}_*.sdat"))
        if g:
            files.append((lab, sorted(g)[0]))
    if not files:
        print("  (no matching records; skipping code histograms)")
        return

    from math import erf
    def Phi(z):
        return 0.5 * (1.0 + erf(z / math.sqrt(2.0)))

    # Reduce every candidate first, then pick four that span the phase, so the
    # panels show the two regimes the discrimination argument turns on:
    # near phi = 0.5 one code takes almost everything, near phi = 0 two codes
    # split it. Choosing by filename would show whatever the ladder happened
    # to land on.
    cand = []
    for path in sorted(glob.glob(os.path.join(recdir, "*ph_k*.sdat"))):
        rec = sdat.load(path)
        fs = (rec.header.get("timing") or {}).get("f_measured_mhz", 0) / 1000.0
        i0 = int(round(fs))
        x = rec.gyro20[i0:, 0].astype(float) / 16.0
        q = rec.gyro16[i0:, 0].astype(float)
        st = Stats(x, q, fs)
        cand.append((st.phi_ref, os.path.basename(path).split("_", 1)[1],
                     q, st))
    if not cand:
        print("  (no phase records; skipping code histograms)")
        return
    picks = []
    for target in (0.50, 0.70, 0.85, 0.98):
        c = min(cand, key=lambda t, g=target: abs(((t[0] - g + .5) % 1) - .5))
        picks.append(c)

    fig, axes = plt.subplots(1, len(picks), figsize=(3.05 * len(picks), 3.8),
                             sharey=True)
    axes = np.atleast_1d(axes)
    for panel, (phi, lab, q, st) in zip(axes, picks):
        rho = st.rho_ref
        # mu corrected for the reference stream's own truncation, exactly as
        # phi_ref is. The code edges sit at integers; nothing here is fitted.
        mu_c = st.mu + REF_STEP / 2.0
        codes, counts = np.unique(q, return_counts=True)
        lo, hi = int(codes.min()) - 1, int(codes.max()) + 1
        cc = np.arange(lo, hi + 1)
        frac = np.zeros(cc.size)
        frac[np.searchsorted(cc, codes)] = counts / counts.sum()
        panel.bar(cc - mu_c, frac, 0.9, color=C1, alpha=0.85, label="measured")
        pred = [Phi((c + 1 - mu_c) / rho) - Phi((c - mu_c) / rho) for c in cc]
        panel.plot(cc - mu_c, pred, "o", color=CPRED, ms=7, mfc="none",
                   mew=1.8, label="exact, no fit", zorder=5)
        worst = float(np.max(np.abs(np.array(pred) - frac)))
        panel.set_title(fr"$\varphi$ = {phi:.3f},  $\rho$ = {rho:.3f}" "\n"
                        f"max discrepancy {worst:.3f}", fontsize=8.5)
        panel.set_xlabel(r"code $-\ \mu$  ($\Delta$)")
        panel.set_xlim(-1.9, 1.4)
    axes[0].set_ylabel("fraction of samples")
    axes[0].legend(fontsize=7.5, loc="upper left")
    fig.suptitle("Output code occupancy across the phase sweep — the marginal "
                 "channel, which shares no statistic with $\\eta$", fontsize=10)
    _save(fig, out)


ALL = [
    ("fig7_phase_sweep.png", "rows", fig_phase_sweep),
    ("fig8_reference_truncation.png", "rows", fig_reference_truncation),
    ("fig9_vernier.png", "rows", fig_vernier),
    ("fig10_allan_family.png", "recdir", fig_allan_family),
    ("fig11_arw_consequence.png", "rows", fig_arw_consequence),
    ("fig12_offset_linearity.png", "recdir", fig_offset_linearity),
    ("fig13_r2_estimator.png", "rows", fig_r2_estimator),
    ("fig14_residual_anatomy.png", "rows", fig_residual_anatomy),
    ("fig15_code_histograms.png", "recdir", fig_code_histograms),
]


def draw_all(rows, outdir, recdir=None):
    for name, kind, fn in ALL:
        try:
            fn(rows if kind == "rows" else recdir,
               os.path.join(outdir, name))
        except Exception as e:                              # noqa: BLE001
            print(f"  !! {name}: {type(e).__name__}: {e}")
