#!/usr/bin/env python3
"""
figures_transfer.py -- the sqrt(ODR) transfer rule, and its three failure modes.

    F16  the three worlds, theory and measurement
    F17  the transfer surface over (ODR_cal, phi)
    F18  the fitted density the rule says is invariant

WHAT THIS SET IS FOR

Concept Note v2.3 s3.2 states the central question:

    "Which of four discrete architectures does the output register implement
     ... and does the resulting (exactly computable, parameter-free)
     departure account for the observed failure of the sqrt(ODR) transfer
     rule?"

and s2 states the practice under test: a parameter set fitted at one
configuration is transferred to another by a sqrt(ODR) scaling of the white
density, which Kalibr's own documentation gives as a CONDITION requiring ideal
decimation rather than as a validated result.

GMWM-to-Kalman-Q v1.2 s3 surveys the pipelines. The finding these figures have
to carry is in its Z.4, and it is stronger than "the toolchains use the wrong
model":

    "The surveyed pipelines DO NOT MODEL register quantisation at all -- it is
     absent from the model set, not approximated within it."

So there are three worlds to draw, not two:

    1. AS PRACTISED       no quantisation term anywhere. Kalibr,
                          allan_variance_ros, imu_utils, MATLAB Sensor Fusion,
                          NaveGo. The fitted density is carried unchanged.
    2. PQN-AWARE          the world in which somebody HAD modelled it, with the
                          classical Delta^2/12. Nobody occupies this world;
                          it is drawn because it is the obvious fix and it is
                          still wrong.
    3. EXACT              eta(rho, phi) from two measured parameters.

The middle one is the point most easily missed. A PQN-aware pipeline still
mis-transfers, by a factor that does not vanish, because the fitted density
carries a configuration-dependent term the rule assumes away
(GMWM-to-Kalman-Q v1.2 Z.2, finding 3).

TWO FAILURES MUST NOT BE CONFLATED.  The measured input density is itself not
ODR-invariant on this part, because the anti-alias filter stops tracking ODR
below a few hundred hertz -- measured spread x2.5 across the axis. That is a
BANDWIDTH failure of the rule and it is real, but it is not this paper's
subject. F16 therefore separates them: panel A holds the input density
invariant by construction so the only thing breaking the rule is the register,
and panel B shows the measured total with the bandwidth part drawn separately.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyse import eta_exact                                   # noqa: E402

DELTA_MDPS = 61.03515625
SIGMA_A = 2.8                       # DS-000347 Rev 1.6 Table 1, mdps/rtHz

# DS-000347 Rev 1.6 s5.5, UI filter noise bandwidth at GYRO_UI_FILT_BW = 0.
NBW = {12.5: 13.0, 25: 13.0, 50: 26.0, 100: 52.0, 200: 104.0,
       500: 260.0, 1000: 519.0, 8000: 4160.0}

C_PRACT, C_PQN, C_EXACT = "#c0392b", "#e8a33d", "#1f77b4"
CPRED = "#444444"

plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 160,
    "axes.grid": True, "grid.alpha": 0.25,
    "font.size": 9, "axes.titlesize": 10, "legend.fontsize": 8,
})


def _nbw(odr):
    if odr in NBW:
        return NBW[odr]
    return 0.52 * odr           # the BW = 0 relation the table follows


def state(odr, phi, sigma_a=SIGMA_A):
    """(rho, S_unq, eta) at one configuration, input density held invariant.

    S_unq = 2 Var / ODR is the one-sided density of the unquantised discrete
    sequence. With Var = sigma_a^2 * NBW and NBW proportional to ODR it is
    configuration-invariant, which is exactly the assumption the rule makes.
    """
    var = sigma_a ** 2 * _nbw(odr)
    rho = np.sqrt(var) / DELTA_MDPS
    return rho, 2.0 * var / odr, eta_exact(rho, phi)


def ratios(cal, op, phi, sigma_a=SIGMA_A):
    """Density carried / density needed, for each of the three worlds."""
    _r, Su_c, e_c = state(cal, phi, sigma_a)
    _r2, Su_o, e_o = state(op, phi, sigma_a)
    q_c = DELTA_MDPS ** 2 / (6.0 * cal)
    q_o = DELTA_MDPS ** 2 / (6.0 * op)
    S_cal = Su_c + e_c * q_c                    # what you actually fit
    S_true = Su_o + e_o * q_o                   # what you actually need
    practised = S_cal / S_true                  # carried unchanged
    pqn = (S_cal - q_c + q_o) / S_true          # classical correction applied
    return practised, pqn, 1.0                  # exact is 1 by construction


# ==========================================================================
# F16
# ==========================================================================

def fig_transfer_three_worlds(rows, out, op=500.0):
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11.4, 4.9))

    # eta(rho, .) is extremal at the code edge (phi = 0, maximum) and mid-code
    # (phi = 0.5, minimum) -- the same bracketing fig1 uses for its band. So the
    # envelope over the unmeasured phase needs two curves, not a scan of a
    # hundred: eta_exact costs a K x K outer product per call and a scan makes
    # this figure take a minute for no extra information.
    cals = np.geomspace(12.5, 1000, 70)
    edge = np.array([ratios(c, op, 0.0)[0] for c in cals])
    mid = np.array([ratios(c, op, 0.5)[0] for c in cals])
    pqn = np.array([ratios(c, op, 0.5)[1] for c in cals])
    band_lo = np.minimum(edge, mid)
    band_hi = np.maximum(edge, mid)

    ax.fill_between(cals, band_lo, band_hi, color=C_PRACT, alpha=0.16, lw=0,
                    label="as practised — range over the unmeasured φ")
    ax.plot(cals, mid, "-", color=C_PRACT, lw=1.8,
            label="as practised, mid-code φ")
    ax.plot(cals, pqn, "-", color=C_PQN, lw=2.0,
            label=r"PQN-aware — if anyone modelled $\Delta^2/12$")
    ax.axhline(1.0, color=C_EXACT, lw=2.2,
               label=r"exact, from measured $(\rho,\varphi)$")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("calibration ODR  (Hz)")
    ax.set_ylabel(f"density carried / density needed at {op:.0f} Hz")
    ax.set_title("A  Bandwidth held ideal, so the register is the only\n"
                 "thing breaking the rule", loc="left", fontsize=9.5)
    ax.legend(loc="upper right", fontsize=7.4, framealpha=0.95)
    ax.set_ylim(0.03, 40)
    for y, t in ((2.0, "×2"), (0.5, "÷2")):
        ax.axhline(y, color="#bbb", ls=":", lw=0.8)
        ax.annotate(t, (13, y), fontsize=7, color="#888", va="bottom")

    # Where the classical correction returns a NEGATIVE density. Subtracting a
    # full Delta^2/12 from a fitted density that never contained one drives the
    # estimate below zero -- not merely wrong, unphysical, and the regime
    # GMWM-to-Kalman-Q v1.2 Z.3 is about. A log axis silently drops these, so
    # say so instead.
    bad = cals[pqn <= 0]
    if bad.size:
        ax.axvspan(cals[0], bad.max(), color=C_PQN, alpha=0.13, lw=0)
        ax.annotate(f"below {bad.max():.0f} Hz the classical correction\n"
                    "returns a NEGATIVE noise density",
                    (bad.max(), 0.055), fontsize=7.3, color="#8a6410",
                    ha="left", va="bottom",
                    xytext=(4, 0), textcoords="offset points")
    lo_end, hi_end = band_lo[0], band_hi[0]
    ax.annotate(f"at {cals[0]:.0f} Hz two identical units,\n"
                f"identically configured, differ by ×{hi_end / max(lo_end, 1e-9):.0f}",
                (0.035, 0.30), xycoords="axes fraction", ha="left", va="top",
                fontsize=7.6, color="#333",
                bbox=dict(fc="white", ec="#ccc", alpha=0.92, pad=3))

    # ---- panel B: what the measurement actually gives ------------------
    D = DELTA_MDPS
    sel = {}
    for r in rows:
        lab = str(r.get("label", ""))
        if not lab.startswith(("s1_odr", "s2_odr")):
            continue
        try:
            odr = float(r["odr_nom"])
            rho = float(r["rho_ref"])
            eta = float(r["eta"])
        except (KeyError, TypeError, ValueError):
            continue
        sel.setdefault((lab.split("_")[0], r["axis"]), []).append(
            (odr, 2 * (rho * D) ** 2 / odr, eta))

    drawn = False
    for (spec, axis), pts in sorted(sel.items()):
        pts.sort()
        o = np.array([p[0] for p in pts])
        Su = np.array([p[1] for p in pts])
        et = np.array([p[2] for p in pts])
        if op not in o:
            continue
        j = int(np.argmin(np.abs(o - op)))
        S = Su + et * D ** 2 / (6 * o)
        col = C_EXACT if spec == "s1" else C_PRACT
        bx.plot(o, S / S[j], "o-", color=col, lw=1.1, ms=5, alpha=0.75)
        bx.plot(o, Su / Su[j], "--", color=col, lw=1.0, alpha=0.45)
        drawn = True

    bx.axhline(1.0, color=CPRED, lw=1.6)
    bx.set_xlim(20, 1300)
    bx.set_xscale("log")
    bx.set_yscale("log")
    bx.set_xlabel("calibration ODR  (Hz)")
    bx.set_ylabel(f"measured density / measured at {op:.0f} Hz")
    bx.set_title("B  Measured, both failures present\n"
                 "solid: total   dashed: input alone (the bandwidth part)",
                 loc="left", fontsize=9.5)
    if drawn:
        bx.legend(handles=[
            Line2D([], [], color=C_EXACT, marker="o", lw=1.1,
                   label="specimen 1, observed"),
            Line2D([], [], color=C_PRACT, marker="o", lw=1.1,
                   label="specimen 2, observed"),
            Line2D([], [], color="#777", ls="--", lw=1.0,
                   label="input density alone — the AAF stops tracking ODR"),
            Line2D([], [], color=CPRED, lw=1.6,
                   label="what the rule assumes")],
            loc="upper left", fontsize=7.4, framealpha=0.95)
        bx.annotate("the gap between solid and dashed is the register;\n"
                    "the dashed line's own departure from flat is bandwidth",
                    (0.97, 0.04), xycoords="axes fraction", ha="right",
                    fontsize=7.5, color="#444",
                    bbox=dict(fc="white", ec="#ccc", alpha=0.9, pad=3))

    fig.suptitle(r"Failure of the $\sqrt{\mathrm{ODR}}$ transfer rule — and "
                 "why modelling it classically does not fix it", fontsize=11)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"  -> {out}")


# ==========================================================================
# F17 -- the surface
# ==========================================================================

def fig_transfer_surface(rows, out, op=500.0):
    """The whole (ODR_cal, phi) plane, because the practitioner controls one
    axis of it and does not know the other exists."""
    from mpl_toolkits.mplot3d import Axes3D            # noqa: F401

    cals = np.geomspace(12.5, 1000, 44)
    phis = np.linspace(0, 1, 56)
    X, Y = np.meshgrid(np.log10(cals), phis)
    Z = np.empty_like(X)
    for i, p in enumerate(phis):
        for j, c in enumerate(cals):
            Z[i, j] = np.log10(ratios(c, op, p)[0])
    # PQN is phi-independent, so it is one curve, not a surface.
    Zp = np.array([np.log10(ratios(c, op, 0.5)[1]) for c in cals])

    fig = plt.figure(figsize=(12.2, 5.2))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1], wspace=0.10)
    ax = fig.add_subplot(gs[0], projection="3d")
    lim = float(np.abs(Z).max())
    ax.plot_surface(X, Y, Z, cmap="coolwarm", vmin=-lim, vmax=lim,
                        rstride=1, cstride=1, lw=0, antialiased=True,
                        alpha=0.96)
    ax.plot_surface(X, Y, np.zeros_like(Z), color="#1f77b4", alpha=0.20,
                    lw=0)
    ax.plot(np.log10(cals), np.ones_like(cals) * 0.5, Zp, color=C_PQN,
            lw=3, zorder=10)
    ax.set_xlabel("calibration ODR (Hz)")
    ax.set_ylabel(r"bias phase $\varphi$")
    ax.set_zlabel(r"$\log_{10}$ (carried / needed)")
    ax.set_xticks(np.log10([12.5, 25, 50, 100, 200, 500, 1000]))
    ax.set_xticklabels(["12.5", "25", "50", "100", "200", "500", "1k"],
                       fontsize=7)
    ax.view_init(elev=24, azim=-131)
    ax.set_title("The error surface a practitioner is standing on\n"
                 "blue plane = correct; amber line = PQN-aware",
                 fontsize=9.5)

    # ---- flat contour view, which is the one you can actually read -----
    bx = fig.add_subplot(gs[1])
    cf = bx.contourf(np.log10(cals), phis, Z, levels=21, cmap="coolwarm",
                     vmin=-lim, vmax=lim)
    cs = bx.contour(np.log10(cals), phis, Z, levels=[0.0], colors="k",
                    linewidths=2.2)
    bx.clabel(cs, fmt={0.0: "no error"}, fontsize=8)
    # The vertical branch at cal = op is trivial -- transferring a calibration
    # to the configuration it was taken at cannot be wrong. Say so, or it reads
    # as a second physical result.
    bx.annotate("this branch is trivial:\ncalibrating at the\noperating point",
                (np.log10(op), 0.13), fontsize=7, color="#555", ha="right",
                xytext=(-6, 0), textcoords="offset points",
                bbox=dict(fc="white", ec="none", alpha=0.8, pad=2))
    for lv, lab in ((np.log10(2), "×2"), (np.log10(0.5), "÷2")):
        c2 = bx.contour(np.log10(cals), phis, Z, levels=[lv], colors="k",
                        linewidths=0.9, linestyles="--")
        bx.clabel(c2, fmt={lv: lab}, fontsize=7)
    bx.set_xticks(np.log10([12.5, 25, 50, 100, 200, 500, 1000]))
    bx.set_xticklabels(["12.5", "25", "50", "100", "200", "500", "1k"])
    bx.set_xlabel("calibration ODR  (Hz)")
    bx.set_ylabel(r"bias phase $\varphi$  — nobody measures this axis")
    bx.set_title("Same surface from above\n"
                 "the black line is where two errors happen to cancel",
                 fontsize=9.5)
    fig.colorbar(cf, ax=bx, shrink=0.85,
                 label=r"$\log_{10}$ (carried / needed)")

    # Where the measured records sit on this plane.
    got = set()
    for r in rows:
        lab = str(r.get("label", ""))
        if not lab.startswith(("s1_odr", "s2_odr")):
            continue
        try:
            o, p = float(r["odr_nom"]), float(r["phi_ref"])
        except (KeyError, TypeError, ValueError):
            continue
        if 12.5 <= o <= 1000:
            bx.plot(np.log10(o), p, "o", color="k", ms=4.5, mfc="none",
                    mew=1.2, zorder=6)
            got.add(lab)
    if got:
        bx.plot([], [], "o", color="k", mfc="none", mew=1.2,
                label=f"{len(got)} measured records")
        bx.legend(loc="lower left", fontsize=7.5, framealpha=0.95)

    fig.suptitle("Transfer error over the plane the rule assumes is flat  "
                 f"(operating point {op:.0f} Hz)", fontsize=11)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"  -> {out}")


# ==========================================================================
# F18 -- the invariant that is not one
# ==========================================================================

def fig_density_invariance(rows, out):
    """The rule in the form the toolchains state it.

    Kalibr and the rest fit a rate noise density and carry it across ODR. The
    claim is that this quantity is flat against ODR. Draw it flat, then draw
    what the sensor does.
    """
    D = DELTA_MDPS
    fig, ax = plt.subplots(figsize=(7.8, 5.2))

    cals = np.geomspace(20, 1200, 70)
    ref = state(500, 0.5)[1]
    ax.plot(cals, np.ones_like(cals) * np.sqrt(ref), "-", color=CPRED, lw=2.0,
            label=r"what every surveyed toolchain assumes: flat")
    for phi, ls, lab in ((0.5, "-", "mid-code"), (0.0, "--", "code edge")):
        v = []
        for c in cals:
            _r, Su, e = state(c, phi)
            v.append(np.sqrt(Su + e * D ** 2 / (6 * c)))
        ax.plot(cals, v, ls, color=C_EXACT, lw=1.7,
                label=fr"exact theory, {lab} $\varphi$")
    v = [np.sqrt(state(c, 0.5)[1] + D ** 2 / (6 * c)) for c in cals]
    ax.plot(cals, v, "-", color=C_PQN, lw=1.7, label="PQN, if anyone used it")

    seen = set()
    for r in rows:
        lab = str(r.get("label", ""))
        if not lab.startswith(("s1_odr", "s2_odr")):
            continue
        try:
            o = float(r["odr_nom"])
            rho = float(r["rho_ref"])
            eta = float(r["eta"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 20 <= o <= 1200:
            continue
        S = 2 * (rho * D) ** 2 / o + eta * D ** 2 / (6 * o)
        m = "o" if lab.startswith("s1") else "s"
        ax.plot(o, np.sqrt(max(S, 1e-9)), m, color="#2a9d5c", ms=6, mew=0,
                alpha=0.75)
        seen.add(lab)

    ax.set_xscale("log")
    ax.set_xlabel("ODR  (Hz)")
    ax.set_ylabel(r"fitted rate noise density  (mdps/$\sqrt{\mathrm{Hz}}$)")
    ax.set_title("The quantity the transfer rule calls configuration-invariant\n"
                 "ICM-42688-P at ±2000 dps; green markers are measured")
    ax.legend(loc="upper right", fontsize=7.8, framealpha=0.95)
    ax.annotate("the measured points carry a bandwidth departure as well as a\n"
                "register one — see F16 panel B for the decomposition",
                (0.03, 0.04), xycoords="axes fraction", fontsize=7.5,
                color="#555")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"  -> {out}")


ALL = [
    ("fig16_transfer_three_worlds.png", "rows", fig_transfer_three_worlds),
    ("fig17_transfer_surface.png", "rows", fig_transfer_surface),
    ("fig18_density_invariance.png", "rows", fig_density_invariance),
]
