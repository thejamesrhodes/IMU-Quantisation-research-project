#!/usr/bin/env python3
"""
offset_fit.py -- settle the OFFSET_USER step size.

TN-20 section 2.5 leaves one number unresolved, and the entire digital phase
axis hangs off it: is one OFFSET_USER register step 0.512 Delta (the datasheet
figure, 1/32 dps against Delta = 2000/32768 dps) or 0.500 Delta (half a 16-bit
LSB)?  The 28 July trio measured 0.503 +/- 0.006 over a four-step interval,
which sits 1.5 sigma from one hypothesis and 0.5 sigma from the other and
therefore settles nothing.

Two things were wrong with that measurement and both are fixed here.

1.  THE LEVER ARM WAS TOO SHORT.  Four steps separate the hypotheses by
    4 x 0.012 = 0.048 Delta.  One thousand steps separate them by 12 Delta,
    and two thousand by 24 Delta.  The register is 12-bit signed over
    +/-64 dps (DS-000347 Rev 1.6 section 5.4), so k = 2000 is in range with
    2.3% to spare.

2.  THERMAL DRIFT WAS UNMODELLED.  The gyro ZRO tempco is +/-5 mdps/K
    (DS-000347 Rev 1.6, Table 1: "ZRO Variation vs. Temperature ... +/-0.005
    deg/s/degC"), so

        dmu/dT = 5 mdps/K / 61.035 mdps = 0.0819 Delta/K

    and the 28 July records each spanned 0.79-0.88 K -- i.e. up to 0.07 Delta
    of nuisance against a 0.048 Delta signal.  The drift was larger than the
    effect.  Here mu is regressed jointly on the step count and the record's
    mean die temperature, so the drift is measured and removed rather than
    hoped away, and the fitted temperature coefficient is itself a useful
    by-product: it is an in-situ calibration of the same tempco the thermal
    phase ramp of TN-14 section 3 depends on.

MODEL, per axis:

    mu_i = a + s * k_i + b * (T_i - Tbar) + eps_i

  mu_i  record i's mean of the 19-bit stream, in units of Delta   [Delta]
  k_i   OFFSET_USER step count written for record i               [steps]
  T_i   record i's mean die temperature                           [K]
  Tbar  mean of T_i over the run (centring only; no effect on s)  [K]
  a     intercept: the unit's untrimmed bias phase plus origin    [Delta]
  s     THE ESTIMAND: step size                                   [Delta/step]
  b     bias tempco referred to the register lattice              [Delta/K]
  eps_i residual, SD = sigma_i sqrt(C / n_i)                      [Delta]

C = 1.3 is the sample-correlation inflation of TN-14 section 1.1.  Weighted
least squares, weights 1/SE_i^2.

Identifiability: k and T are collinear if the ladder is run monotonically while
the die warms, which is exactly what happened on 28 July.  The plan file
`plan_offset.txt` breaks the collinearity by returning to k = 0 four times
through the run.  This script reports the variance inflation factor so a
collinear dataset announces itself instead of producing a confident wrong
answer.

Pre-registered decision rule (fix before looking at the data):

    R-O1  Accept s = 0.512 if |s_hat - 0.512| < 3 SE(s_hat) AND
          |s_hat - 0.500| > 3 SE(s_hat).  Accept 0.500 under the converse.
          Any other outcome is reported as unresolved, not adjudicated.
    R-O2  The fit must be linear: residual RMS < 0.05 Delta, and no single
          |residual| > 0.15 Delta.  A break at the largest k indicates
          register clamping and that point is dropped, not the hypothesis.
    R-O3  The three axes carry the same register write, so s must agree
          across them within 3 SE.  Disagreement falsifies the common-write
          assumption and invalidates the pooled figure.

Usage:

    python offset_fit.py "..\\..\\Test Datasets"                 # all off_* records
    python offset_fit.py "..\\..\\Test Datasets" --slot 1 --csv fit.csv
    python offset_fit.py rec1.sdat rec2.sdat ...
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sdat  # noqa: E402

FINE_PER_LSB = 16.0          # Delta = 16 codes of the 20-bit field (TN-20 4.4)
DELTA_MDPS = 61.03515625     # 2000 dps / 32768
CORR_C = 1.3                 # sample-correlation inflation, TN-14 1.1
AXES = ("X", "Y", "Z")

H_DATASHEET = 0.512          # (1/32 dps) / (2000/32768 dps), exactly 64/125
H_HALF_LSB = 0.500           # half a 16-bit LSB


# --------------------------------------------------------------------------
# Per-record reduction
# --------------------------------------------------------------------------

class Point:
    """One record, reduced to what the fit needs."""

    __slots__ = ("path", "label", "slot", "k", "n", "temp_c", "temp_span_mk",
                 "mu20", "mu16", "sigma", "se", "odr", "aaf", "t0", "run")

    def __repr__(self) -> str:
        return f"<Point {self.label} k={self.k} mu20={self.mu20}>"


def reduce_record(path: str, skip_s: float = 1.0) -> Point | None:
    """Load one .sdat and reduce it to (k, T, mu, SE) per axis.

    The first `skip_s` seconds are discarded.  The OFFSET_USER write happens
    at record start (storage.c), so the opening samples carry the AAF/UI step
    response.  It settles in milliseconds at ODR 1000, but discarding a second
    costs nothing and removes the question.
    """
    rec = sdat.load(path)
    hdr = rec.header
    cfg = hdr.get("config") or {}
    tim = hdr.get("timing") or {}

    fs = float(tim.get("f_measured_mhz", 0) or 0) / 1000.0
    if fs <= 0:
        fs = float(cfg.get("odr_nominal_hz", 1000) or 1000)

    i0 = int(round(skip_s * fs))
    if rec.n - i0 < 1000:
        print(f"  ! {os.path.basename(path)}: too few samples after skip",
              file=sys.stderr)
        return None

    x = rec.gyro20[i0:].astype(np.float64) / FINE_PER_LSB   # Delta
    q = rec.gyro16[i0:].astype(np.float64)                  # Delta
    t = rec.temp_c()[i0:]

    p = Point()
    p.path = path
    p.label = str(hdr.get("label", "?"))
    p.slot = int((hdr.get("sensor") or {}).get("slot", 0))
    p.k = int(cfg.get("offset_user_steps", 0) or 0)
    p.odr = int(cfg.get("odr_nominal_hz", 0) or 0)
    p.aaf = str(cfg.get("aaf", "?"))
    p.n = int(x.shape[0])
    p.temp_c = float(t.mean())
    p.temp_span_mk = float((t.max() - t.min()) * 1000.0)

    # Run order, and it must be numeric. The run id is the TIM2 tick at record
    # start, so on slot 2 the night crossed 10^6 and a string sort put
    # r1047542 ahead of r973767 -- which silently reordered the ladder and left
    # the k = 0 brackets no longer flanking anything. Sort on the timestamp the
    # header already carries, and fall back to the id parsed as an integer.
    p.t0 = float(tim.get("ts_first_us", 0) or 0)
    try:
        p.run = int(str(hdr.get("run_id", "0")).lstrip("rR") or 0)
    except ValueError:
        p.run = 0

    p.mu20 = x.mean(axis=0)          # [3]
    p.mu16 = q.mean(axis=0)          # [3]
    # Detrended SD, so a within-record ramp is not counted as noise; this is
    # the same convention analyse.py uses for rho.
    idx = np.arange(p.n, dtype=np.float64)
    idx -= idx.mean()
    denom = float(idx @ idx)
    resid = x - np.outer(idx, (idx @ x) / denom) - x.mean(axis=0)
    p.sigma = resid.std(axis=0, ddof=2)
    p.se = p.sigma * math.sqrt(CORR_C / p.n)
    return p


# --------------------------------------------------------------------------
# The fit
# --------------------------------------------------------------------------

def wls(y: np.ndarray, X: np.ndarray, se: np.ndarray):
    """Weighted least squares.  Returns (beta, cov, resid, dof)."""
    w = 1.0 / se ** 2
    W = np.sqrt(w)[:, None]
    Xw, yw = X * W, y * W[:, 0]
    beta, *_ = np.linalg.lstsq(Xw, yw, rcond=None)
    resid = y - X @ beta
    dof = len(y) - X.shape[1]
    xtx_inv = np.linalg.inv(Xw.T @ Xw)
    # Scale by the reduced chi-square so an under-stated SE (unmodelled drift,
    # a coherent line, a bad record) inflates the reported uncertainty rather
    # than being silently absorbed.
    chi2_red = float(np.sum(w * resid ** 2) / dof) if dof > 0 else 1.0
    cov = xtx_inv * max(chi2_red, 1.0)
    return beta, cov, resid, dof, chi2_red


def bracket_fit(points: list[Point], ax: int):
    """The primary estimator, from the k = 0 returns rather than from T.

    The temperature regression of fit_axis() assumes mu moves because the die
    moves.  The 29 July run falsified that: the fitted tempco came out at
    27 mdps/K on Y against a +/-5 mdps/K datasheet spec, and the long-tau Allan
    deviation of the same records is FLAT (slope ~0), which is bias
    instability, not a thermal ramp.  Regressing on a variable that is not the
    cause buys nothing and can bias the coefficient of interest.

    The k = 0 brackets measure the nuisance directly, whatever its cause.
    Interpolating between the two that flank each ladder point removes it
    without a model of it.

    The residual then shows a clear 1/k signature, so the shift is fitted as

        shift(k) = s*k + c

    with c a fixed per-record offset (settling, and the interpolation error of
    the bracket itself).  Reading s off shift/k at a single k -- which is what
    the 28 July trio did at k = 4 -- absorbs c into s and biases it by c/k.
    That is why the small-k estimates come out low and converge upward.
    """
    ks = np.array([p.k for p in points], dtype=float)
    mu = np.array([p.mu20[ax] for p in points])
    zi = np.flatnonzero(ks == 0)
    if zi.size < 2:
        return None

    kk, shift = [], []
    for i, k in enumerate(ks):
        if k == 0:
            continue
        lo = zi[zi < i]
        hi = zi[zi > i]
        if not lo.size or not hi.size:
            continue                      # unbracketed: no baseline to remove
        lo, hi = lo.max(), hi.min()
        w = (i - lo) / (hi - lo)
        kk.append(k)
        shift.append(mu[i] - (mu[lo] * (1 - w) + mu[hi] * w))
    if len(kk) < 2:
        return None

    kk, shift = np.array(kk), np.array(shift)
    if len(kk) == 2:
        # The two-point calibration of plan_phase.txt's p2cal block. Fitting
        # s and c to two points leaves no residual, but the DIFFERENCE of the
        # two shifts cancels c exactly, which is the whole reason the block
        # carries two ladder points rather than one. The uncertainty then comes
        # from the baseline scatter, not from a residual that cannot exist.
        s_hat = float((shift[1] - shift[0]) / (kk[1] - kk[0]))
        c_hat = float(shift[1] - s_hat * kk[1])
        base_sd = float(np.std(mu[zi], ddof=1))
        se = base_sd * math.sqrt(2.0) / float(kk[1] - kk[0])
        return {"s": s_hat, "c": c_hat, "se_s": se, "k": kk, "shift": shift,
                "resid": np.zeros(2), "rms": float("nan"),
                "baseline_excursion": float(mu[zi].max() - mu[zi].min()),
                "two_point": True}

    A = np.column_stack([kk, np.ones_like(kk)])
    beta, *_ = np.linalg.lstsq(A, shift, rcond=None)
    resid = shift - A @ beta
    dof = len(kk) - 2
    sig2 = float(resid @ resid) / dof if dof > 0 else float("nan")
    cov = sig2 * np.linalg.inv(A.T @ A)
    # The baseline excursion across the run is the honest floor on how well
    # any of this can be known; it is reported so the SE can be sanity-checked
    # against it rather than believed on its own.
    return {"s": beta[0], "c": beta[1], "se_s": math.sqrt(abs(cov[0, 0])),
            "k": kk, "shift": shift, "resid": resid,
            "rms": math.sqrt(sig2) if sig2 == sig2 else float("nan"),
            "baseline_excursion": float(mu[zi].max() - mu[zi].min()),
            "two_point": False}


def phase_ladder(s: float, k_max: int = 2047, n: int = 8):
    """Step counts reaching a uniform n-point phase ladder, given the measured s.

    If s were exactly 0.5 the register would reach two phases and the digital
    axis would be dead.  It is not exactly 0.5, and that is the whole story:
    with s = 1/2 - eps the even steps precess by 2*eps per step and sweep the
    entire period in 1/(2*eps) steps.  The register becomes a vernier.
    """
    k = np.arange(k_max + 1)
    ph = (s * k) % 1.0
    out = []
    for m in range(n):
        target = m / n
        j = int(np.argmin(np.abs(((ph - target + 0.5) % 1.0) - 0.5)))
        out.append((target, j, float(ph[j])))
    gaps = np.diff(np.sort(ph))
    return out, float(gaps.max()), int(k_max + 1)


def vif_k(k: np.ndarray, T: np.ndarray) -> float:
    """Variance inflation factor on the step coefficient from k-T collinearity.

    VIF = 1/(1 - r^2).  VIF > 10 means the run was effectively monotonic in
    both and the step size cannot be separated from the drift.
    """
    if np.ptp(k) == 0 or np.ptp(T) == 0:
        return float("inf")
    r = float(np.corrcoef(k, T)[0, 1])
    return float("inf") if abs(r) >= 1.0 else 1.0 / (1.0 - r * r)


def fit_axis(points: list[Point], ax: int):
    y = np.array([p.mu20[ax] for p in points])
    k = np.array([float(p.k) for p in points])
    T = np.array([p.temp_c for p in points])
    se = np.array([p.se[ax] for p in points])

    Tc = T - T.mean()
    X = np.column_stack([np.ones_like(k), k, Tc])
    beta, cov, resid, dof, chi2 = wls(y, X, se)
    return {
        "a": beta[0], "s": beta[1], "b": beta[2],
        "se_s": math.sqrt(cov[1, 1]), "se_b": math.sqrt(cov[2, 2]),
        "resid": resid, "dof": dof, "chi2_red": chi2,
        "vif": vif_k(k, T), "k": k, "T": T, "y": y,
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+",
                    help="record files, or a directory to scan")
    ap.add_argument("--slot", type=int, default=None,
                    help="restrict to one sensor slot")
    ap.add_argument("--glob", default="*_off_*.sdat",
                    help="filename pattern when a directory is given. The "
                         "default matches this run's labels (off_0a, "
                         "off_1000, ...) and excludes the 28 July trio "
                         "(off0/off1/off5), which cannot be pooled with it. "
                         "Use '*off*.sdat' to see the old records.")
    ap.add_argument("--skip-s", type=float, default=1.0,
                    help="seconds discarded at record start (default 1.0)")
    ap.add_argument("--csv", default=None, help="write the reduced points")
    args = ap.parse_args(argv)

    files: list[str] = []
    for p in args.paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, args.glob)))
        else:
            files.append(p)
    if not files:
        print("no records matched", file=sys.stderr)
        return 2

    pts: list[Point] = []
    for f in files:
        try:
            pt = reduce_record(f, skip_s=args.skip_s)
        except Exception as exc:                      # noqa: BLE001
            print(f"  ! {os.path.basename(f)}: {exc}", file=sys.stderr)
            continue
        if pt is None:
            continue
        if args.slot is not None and pt.slot != args.slot:
            continue
        pts.append(pt)

    if len(pts) < 3:
        print(f"need at least 3 records, have {len(pts)}", file=sys.stderr)
        return 2

    pts.sort(key=lambda p: (p.slot, p.t0, p.run))

    print()
    print(f"{len(pts)} record(s)   ODR {sorted({p.odr for p in pts})}   "
          f"AAF {sorted({p.aaf for p in pts})}   "
          f"slot {sorted({p.slot for p in pts})}")
    print()
    print(f"{'label':<12}{'k':>6}{'n':>9}{'T(C)':>8}{'span(mK)':>10}"
          f"{'muX':>12}{'muY':>12}{'muZ':>12}{'SE_X':>9}")
    for p in pts:
        print(f"{p.label:<12}{p.k:>6}{p.n:>9}{p.temp_c:>8.3f}"
              f"{p.temp_span_mk:>10.1f}"
              f"{p.mu20[0]:>12.4f}{p.mu20[1]:>12.4f}{p.mu20[2]:>12.4f}"
              f"{p.se[0]:>9.5f}")

    # ---- primary: bracket interpolation + s*k + c ----------------------
    print()
    print("PRIMARY  shift(k) = s*k + c, baseline removed by interpolating the "
          "k = 0 returns")
    print()
    print(f"{'axis':<6}{'s (D/step)':>14}{'SE(s)':>11}{'c (D)':>10}"
          f"{'resid RMS':>11}{'baseline excursion':>20}")
    bf, bs, bw = [], [], []
    for i, ax in enumerate(AXES):
        r = bracket_fit(pts, i)
        bf.append(r)
        if r is None:
            print(f"{ax:<6}  needs at least two k = 0 brackets flanking the "
                  f"ladder points")
            continue
        print(f"{ax:<6}{r['s']:>14.6f}{r['se_s']:>11.6f}{r['c']:>+10.4f}"
              f"{r['rms']:>11.4f}{r['baseline_excursion']:>20.4f}")
        bs.append(r["s"])
        bw.append(1.0 / max(r["se_s"], 1e-12) ** 2)

    if bs:
        s_b = float(np.sum(np.array(bw) * np.array(bs)) / np.sum(bw))
        se_b = float(np.std(np.array(bs), ddof=1) / math.sqrt(len(bs))
                     if len(bs) > 1 else 1.0 / math.sqrt(np.sum(bw)))
        print()
        print(f"  s = {s_b:.6f} +/- {se_b:.6f} Delta/step "
              f"= {s_b * DELTA_MDPS:.5f} mdps/step")
        print("  the per-k estimates, if c is ignored (this is what a "
              "single pair measures):")
        r0 = bf[0]
        if r0 is not None:
            for k_, sh in zip(r0["k"], r0["shift"]):
                print(f"     k = {int(k_):>5}  ->  s_hat = {sh / k_:.6f}"
                      f"   bias from c = {r0['c'] / k_:+.6f}")

        print()
        lad, gap, npt = phase_ladder(s_b)
        if abs(s_b - 0.5) * 2047 > 0.5:
            print("  THE LADDER IS A VERNIER, NOT A DEGENERATE PAIR.")
            print(f"  s = 1/2 - {0.5 - s_b:.6f}, so even steps precess by "
                  f"{2 * abs(0.5 - s_b):.6f} Delta each and cover the full "
                  f"period in {int(1 / (2 * abs(0.5 - s_b)))} steps.")
            print(f"  k = 0..2047 reaches {npt} phases, largest gap "
                  f"{gap:.5f} Delta")
            print("  (the 64/125 scheme the corpus assumed: 125 phases at "
                  "0.008 Delta)")
            print()
            print("  step counts for a uniform 8-point phase ladder:")
            for target, k_, actual in lad:
                print(f"     phi = {target:.3f}  ->  k = {k_:>5}"
                      f"   (reaches {actual:.4f})")
        else:
            print("  s is within half an LSB of exactly 0.5 over the whole "
                  "register: the ladder IS degenerate and the thermal ramp "
                  "is the only phase axis.")

    # ---- cross-check: the temperature regression -----------------------
    print()
    print("CROSS-CHECK  mu = a + s*k + b*(T - Tbar)   [Delta, Delta/step, "
          "Delta/K]")
    print("  keep an eye on the fitted tempco: if it leaves the +/-5 mdps/K "
          "datasheet")
    print("  envelope, T is not what is moving mu and this row is the one to "
          "distrust.")
    print()
    print(f"{'axis':<6}{'s (D/step)':>14}{'SE(s)':>11}{'b (D/K)':>11}"
          f"{'tempco mdps/K':>15}{'resid RMS':>11}{'chi2red':>9}{'VIF':>8}")

    fits, ss, ws = [], [], []
    for i, ax in enumerate(AXES):
        r = fit_axis(pts, i)
        fits.append(r)
        rms = float(np.sqrt(np.mean(r["resid"] ** 2)))
        print(f"{ax:<6}{r['s']:>14.6f}{r['se_s']:>11.6f}{r['b']:>11.5f}"
              f"{r['b'] * DELTA_MDPS:>15.3f}{rms:>11.5f}"
              f"{r['chi2_red']:>9.2f}{r['vif']:>8.2f}")
        if math.isfinite(r["se_s"]) and r["se_s"] > 0:
            ss.append(r["s"])
            ws.append(1.0 / r["se_s"] ** 2)

    if not ss:
        print("\nno usable axis fit", file=sys.stderr)
        return 1

    ss_a, ws_a = np.array(ss), np.array(ws)
    s_hat = float(np.sum(ws_a * ss_a) / np.sum(ws_a))
    se_pool = float(1.0 / math.sqrt(np.sum(ws_a)))
    # R-O3: axes share one register write, so between-axis scatter is a check,
    # not a component of the uncertainty -- but if it exceeds the within-axis
    # error the pooled SE is understated and must be widened.
    if len(ss) > 1:
        scatter = float(np.std(ss_a, ddof=1) / math.sqrt(len(ss_a)))
        se_report = max(se_pool, scatter)
    else:
        scatter, se_report = 0.0, se_pool

    print()
    print(f"pooled s = {s_hat:.6f} +/- {se_report:.6f} Delta/step"
          f"   (within-axis {se_pool:.6f}, between-axis {scatter:.6f})")
    print(f"         = {s_hat * DELTA_MDPS:.5f} mdps/step "
          f"(datasheet 1/32 dps = {1000.0 / 32:.3f} mdps/step)")

    z512 = abs(s_hat - H_DATASHEET) / se_report if se_report > 0 else float("inf")
    z500 = abs(s_hat - H_HALF_LSB) / se_report if se_report > 0 else float("inf")
    print()
    print(f"  vs 0.512 (datasheet, 1/32 dps) : {s_hat - H_DATASHEET:+.6f}  "
          f"= {z512:.1f} sigma")
    print(f"  vs 0.500 (half a 16-bit LSB)   : {s_hat - H_HALF_LSB:+.6f}  "
          f"= {z500:.1f} sigma")

    # ---- pre-registered verdict ---------------------------------------
    print()
    vif_max = max(f["vif"] for f in fits)
    dof_min = min(f["dof"] for f in fits)
    tempco_max = max(abs(f["b"]) * DELTA_MDPS for f in fits)
    if dof_min <= 0:
        print(f"UNRESOLVED: the fit is saturated -- {len(pts)} records against "
              f"3 free parameters leaves {dof_min} degrees of freedom, so the "
              f"residuals are identically zero and the reported SE is not a "
              f"measurement of anything. Use plan_offset.txt (9 records).")
    elif vif_max > 10.0:
        print(f"UNRESOLVED (R-O1): k and T are collinear, VIF = {vif_max:.1f}. "
              f"The step size cannot be separated from thermal drift in this "
              f"dataset. Re-run with the k = 0 brackets of plan_offset.txt.")
    elif z512 < 3.0 and z500 > 3.0:
        print("VERDICT: s = 0.512 Delta/step -- the datasheet figure holds. "
              "The 64/125 ladder is valid and reaches 125 distinct phases "
              "(TN-20 section 4.6). The digital phase axis survives.")
    elif z500 < 3.0 and z512 > 3.0:
        print("VERDICT: s = 0.500 Delta/step -- the ladder is DEGENERATE. "
              "Even step counts land on phi = 0, odd on phi = 0.5, and only "
              "two phases are reachable. TN-13 section 4.3's pre-register "
              "fine-lattice premise is falsified in its stated form: an "
              "integer number of 20-bit field codes (8 codes = Delta/2) is "
              "the mechanism. The thermal ramp becomes the ONLY phase axis "
              "and must be scheduled ahead of the FSR axis.")
    else:
        print(f"UNRESOLVED (R-O1): s = {s_hat:.6f} is not within 3 sigma of "
              f"exactly one hypothesis. Report the number, do not adjudicate.")

    if dof_min > 0 and tempco_max > 15.0:
        print()
        print(f"  ! the fitted tempco reaches {tempco_max:.1f} mdps/K against a "
              f"datasheet ZRO spec of +/-5 mdps/K (DS-000347 Rev 1.6 Table 1). "
              f"The drift term is absorbing something that is not temperature "
              f"-- most likely residual collinearity with k, or a record taken "
              f"before the die settled. Treat s with suspicion.")

    # ---- linearity, R-O2 ----------------------------------------------
    print()
    print("Residuals by step count (R-O2: RMS < 0.05, max < 0.15 Delta):")
    print(f"{'k':>7}" + "".join(f"{a:>11}" for a in AXES))
    worst = 0.0
    for j, p in enumerate(pts):
        row = [fits[i]["resid"][j] for i in range(3)]
        worst = max(worst, max(abs(v) for v in row))
        print(f"{p.k:>7}" + "".join(f"{v:>11.5f}" for v in row))
    rms_all = float(np.sqrt(np.mean(np.concatenate(
        [f["resid"] for f in fits]) ** 2)))
    flag = "PASS" if (rms_all < 0.05 and worst < 0.15) else "FAIL"
    print(f"  RMS {rms_all:.5f}   max |resid| {worst:.5f}   -> {flag}")
    if flag == "FAIL":
        print("  A break confined to the largest k is register clamping: drop "
              "that point and refit. Curvature across all k is not.")

    # ---- 16-bit cross-check -------------------------------------------
    # If OFFSET_USER is applied upstream of the UI register (TN-13 4.3's
    # premise) the 16-bit mean must shift by the same amount as the 19-bit
    # mean.  At rho > 1 the truncator contributes a constant -0.5 and nothing
    # phase-dependent, since g_1 = exp(-2 pi^2 rho^2) is ~1e-12 there, so the
    # two shifts must agree to well inside the SE.
    print()
    print("16-bit register cross-check (offset upstream of the register?):")
    base = pts[0]
    print(f"{'k':>7}{'d_mu20':>12}{'d_mu16':>12}{'diff':>12}")
    for p in pts[1:]:
        d20 = float(np.mean(p.mu20 - base.mu20))
        d16 = float(np.mean(p.mu16 - base.mu16))
        print(f"{p.k:>7}{d20:>12.4f}{d16:>12.4f}{d20 - d16:>12.5f}")
    print("  agreement => the offset is applied before the 16-bit truncation, "
          "which is TN-13 section 4.3's premise.")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["file", "label", "slot", "odr", "aaf", "k", "n",
                        "temp_c", "temp_span_mK",
                        "mu20_X", "mu20_Y", "mu20_Z",
                        "mu16_X", "mu16_Y", "mu16_Z",
                        "sigma_X", "sigma_Y", "sigma_Z",
                        "se_X", "se_Y", "se_Z"])
            for p in pts:
                w.writerow([os.path.basename(p.path), p.label, p.slot, p.odr,
                            p.aaf, p.k, p.n, f"{p.temp_c:.4f}",
                            f"{p.temp_span_mk:.1f}",
                            *[f"{v:.6f}" for v in p.mu20],
                            *[f"{v:.6f}" for v in p.mu16],
                            *[f"{v:.6f}" for v in p.sigma],
                            *[f"{v:.6f}" for v in p.se]])
        print(f"\nreduced points -> {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
