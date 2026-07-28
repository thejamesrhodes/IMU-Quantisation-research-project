#!/usr/bin/env python3
"""
analyse.py -- R4 spectral screening and the 19-bit estimators, for Sheppard
.sdat records.

WHAT THIS IS FOR

  Rule R4 (TN-14 section 6) is a pre-registered gate:

      "The 19-bit spectrum is screened for coherent lines before any
       exact-theory table is applied.  If lines are present in band,
       predictions switch to the empirical-CF chain."

  So this is not a plotting convenience.  Whether the bench carries coherent
  lines decides which prediction machinery the paper is allowed to use, and it
  has to be answered before the campaign runs, not after.

  Rule R3 is enforced structurally here: sigma, and hence rho, are computed
  ONLY from the fine (20-bit) stream.  The 16-bit code histogram is a test
  statistic and is never used to estimate sigma.  Breaking that would make the
  test circular -- an H0-based estimator used to test H0 -- which TN-14 section
  7 calls the design's principal defence.

UNITS

  Everything is expressed in units of the 16-bit LSB, Delta, because every
  quantity of interest is a ratio to it.  The fine word is bits [19:4] of the
  same lattice plus a 4-bit extension (TN-19 section 1), so

      Delta = 16 fine codes = 1/16.384 dps = 61.035 mdps

  and the input in LSB units is simply gyro20/16, with the quantiser output
  gyro16 already in LSB units as an integer.  That makes

      rho = sigma / Delta          -> sigma measured in LSB units, directly
      phi = (mu mod Delta)/Delta   -> the fractional part of mu in LSB units
      eta = (Var[Q(x)] - Var[x]) / (Delta^2/12)

  eta is the added-power ratio: +1 is the classical dither limit where
  quantisation contributes exactly Delta^2/12, and negative values are the
  dead-zone regime where the quantiser SUPPRESSES variance.  TN-14 section 1.3
  predicts -0.298 at rho = 0.165 rising to +1.000 by rho = 1.077, and that
  curve is the paper's primary evidence.

USAGE

    python analyse.py screen FILE [--fig OUT.png]
    python analyse.py stats  FILE
    python analyse.py allan  FILE [--fig OUT.png]
    python analyse.py all    FILE [--figdir DIR]

  numpy is required.  matplotlib is optional and only needed for figures.
  scipy is NOT required -- Welch and the median filter are implemented here so
  the gate can be run on a machine with a minimal install.
"""

from __future__ import annotations

import argparse
import math
import os
import sys

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:                                    # pragma: no cover
    plt = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sdat                                            # noqa: E402


# Fine codes per 16-bit LSB.  The UI register is bits [19:4] of the fine word,
# so this is exactly 2**4 -- established by measurement in TN-19 section 1, not
# assumed from the datasheet.
FINE_PER_LSB = 16.0

# One 16-bit LSB in dps at FSR +/-2000.  32768/2000 = 16.384 codes/dps.
DELTA_DPS = 1.0 / 16.384

AXES = ("X", "Y", "Z")


# ==========================================================================
# Signal processing (no scipy)
# ==========================================================================

def welch(x: np.ndarray, fs: float, nperseg: int | None = None,
          overlap: float = 0.5):
    """One-sided Welch PSD with a Hann window.

    Returns (freqs, psd, enbw, n_segments).  psd is in units^2/Hz; enbw is the
    equivalent noise bandwidth of one bin,

        ENBW = fs * sum(w^2) / (sum w)^2,

    which is what converts a line's excess power back into a sinusoid
    amplitude: a tone of amplitude A sitting on a bin peaks at A^2/(2*ENBW),
    so A = sqrt(2 * excess * ENBW).
    """
    n = x.size
    if nperseg is None:
        # Enough segments for a stable noise floor -- the local-median floor
        # estimator needs the periodogram scatter beaten down -- while keeping
        # resolution fine enough to separate mains harmonics.  ~64 segments.
        nperseg = int(2 ** math.floor(math.log2(max(n / 32, 256))))
    nperseg = min(nperseg, n)
    step = max(int(nperseg * (1.0 - overlap)), 1)

    w = np.hanning(nperseg + 1)[:nperseg]              # periodic Hann
    u = np.sum(w ** 2)                                 # window power
    enbw = fs * u / (np.sum(w) ** 2)

    starts = range(0, n - nperseg + 1, step)
    acc = np.zeros(nperseg // 2 + 1)
    k = 0
    for s in starts:
        seg = x[s:s + nperseg]
        seg = seg - seg.mean()
        f = np.fft.rfft(seg * w)
        acc += (f.real ** 2 + f.imag ** 2)
        k += 1
    if k == 0:
        raise ValueError("record too short for a spectrum")

    psd = acc / (k * fs * u)
    psd[1:-1] *= 2.0                                   # one-sided
    freqs = np.fft.rfftfreq(nperseg, d=1.0 / fs)
    return freqs, psd, enbw, k


def running_median(y: np.ndarray, width: int) -> np.ndarray:
    """Median over a sliding window, edge-padded.

    The median is what makes this a usable noise-floor estimator: a coherent
    line occupies a handful of bins, so it cannot move the median of a window
    hundreds of bins wide, whereas a mean would be dragged upward by exactly
    the feature being searched for.
    """
    if width % 2 == 0:
        width += 1
    half = width // 2
    pad = np.pad(y, half, mode="edge")
    try:
        from numpy.lib.stride_tricks import sliding_window_view
        return np.median(sliding_window_view(pad, width), axis=-1)
    except ImportError:                                # numpy < 1.20
        return np.array([np.median(pad[i:i + width]) for i in range(y.size)])


def detrend_linear(x: np.ndarray) -> np.ndarray:
    """Remove a straight line.

    Thermal drift moves mu during a record; TN-14 section 2 bounds it with the
    R2 gate but does not eliminate it.  Left in, it inflates sigma and so
    biases rho low-to-high depending on sign.  Removing a linear term is the
    minimum that does not also remove real low-frequency noise.
    """
    n = x.size
    t = np.arange(n, dtype=np.float64)
    t -= t.mean()
    slope = float(np.dot(t, x - x.mean()) / np.dot(t, t))
    return x - (slope * t + x.mean())


def allan_dev(x: np.ndarray, fs: float, n_tau: int = 40
              ) -> tuple[np.ndarray, np.ndarray]:
    """Overlapping Allan deviation of a rate series.

        sigma^2(tau) = 1 / (2 tau^2 (N - 2m)) * sum (th[i+2m] - 2 th[i+m] + th[i])^2

    with th the integrated angle and tau = m/fs.  Overlapping rather than
    non-overlapping because it uses every available sample pair and so has
    markedly lower variance at long tau, where the bias-instability floor and
    the rate random walk live.
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    th = np.concatenate(([0.0], np.cumsum(x))) / fs     # integrated angle

    m_max = (n - 1) // 3
    if m_max < 1:
        return np.array([]), np.array([])
    ms = np.unique(np.round(np.logspace(0, math.log10(m_max), n_tau)
                            ).astype(np.int64))
    ms = ms[(ms >= 1) & (ms <= m_max)]

    taus, devs = [], []
    for m in ms:
        tau = m / fs
        d = th[2 * m:] - 2.0 * th[m:-m] + th[:-2 * m]
        if d.size < 2:
            continue
        var = np.sum(d * d) / (2.0 * tau * tau * d.size)
        taus.append(tau)
        devs.append(math.sqrt(var))
    return np.asarray(taus), np.asarray(devs)


# ==========================================================================
# Estimators (rule R3: fine stream only)
# ==========================================================================

class Stats:
    """Per-axis estimators, all in units of Delta unless the name says dps."""

    def __init__(self, x_lsb: np.ndarray, q_lsb: np.ndarray, fs: float):
        self.n = x_lsb.size
        self.fs = fs

        xd = detrend_linear(x_lsb)
        qd = detrend_linear(q_lsb.astype(np.float64))

        self.mu = float(x_lsb.mean())
        self.phi = float(self.mu % 1.0)

        # Primary sigma: detrended, so a slow thermal ramp does not masquerade
        # as noise.  The other two are cross-checks, reported so a disagreement
        # is visible rather than averaged away.
        self.sigma = float(xd.std(ddof=1))
        self.sigma_raw = float(x_lsb.std(ddof=1))
        # Successive-difference estimator: immune to any drift, but biased low
        # for band-limited noise because the AAF correlates neighbours.  Its
        # ratio to sigma is a useful colouring diagnostic, not a replacement.
        self.sigma_diff = float(np.diff(x_lsb).std(ddof=1) / math.sqrt(2.0))

        self.rho = self.sigma                        # sigma is already in Delta
        self.drift_lsb = float(x_lsb[-x_lsb.size // 20:].mean()
                               - x_lsb[:x_lsb.size // 20].mean())

        # eta: added power, normalised by the ideal quantiser variance.
        self.eta = float((qd.var(ddof=1) - xd.var(ddof=1)) / (1.0 / 12.0))
        self.eta_raw = float((q_lsb.astype(np.float64).var(ddof=1)
                              - x_lsb.var(ddof=1)) / (1.0 / 12.0))

        codes, counts = np.unique(q_lsb, return_counts=True)
        self.n_codes = int(codes.size)
        self.code_span = int(codes.max() - codes.min()) if codes.size else 0
        self.codes, self.counts = codes, counts

    @property
    def sigma_dps(self) -> float:
        return self.sigma * DELTA_DPS

    @property
    def asd_dps_rthz(self) -> float:
        """White-noise ASD implied by sigma and the sample rate, for a quick
        comparison against the datasheet's 2.8 mdps/rtHz.  Only meaningful if
        the spectrum really is flat in band -- check the PSD figure."""
        return self.sigma_dps / math.sqrt(self.fs / 2.0)


# ==========================================================================
# R4 line screening
# ==========================================================================

class Line:
    def __init__(self, f, ratio, amp_lsb, amp_dps):
        self.f, self.ratio = f, ratio
        self.amp_lsb, self.amp_dps = amp_lsb, amp_dps

    def __str__(self):
        return (f"{self.f:9.3f} Hz   x{self.ratio:7.1f} over floor   "
                f"{self.amp_dps * 1e3:9.4f} mdps = {self.amp_lsb:.4f} Delta")


def screen_lines(x_lsb: np.ndarray, fs: float, alpha: float = 0.01):
    """Find coherent lines in the fine spectrum.

    Method: Welch PSD, a local-median noise floor, and a threshold on the
    ratio.  With K averaged segments the periodogram ratio under the
    line-free null is Gamma(K, 1/K)-distributed, so rather than assume that
    shape we take the threshold from the EMPIRICAL null -- the bins below the
    90th percentile, which lines cannot reach -- and Bonferroni-correct across
    the number of bins tested.  That keeps the false-alarm rate honest without
    depending on the noise actually being white, which it is not: the AAF
    rolls the floor off inside the band.
    """
    freqs, psd, enbw, k = welch(x_lsb, fs)

    # Skip DC and the first few bins: detrending and the Hann window leave
    # skirts there that are not physical lines.
    lo = max(3, int(0.002 * freqs.size))
    f, p = freqs[lo:], psd[lo:]

    width = max(51, (f.size // 40) | 1)
    floor = running_median(p, width)
    floor = np.maximum(floor, np.finfo(float).tiny)
    ratio = p / floor

    # Empirical null from the quiet majority of bins.
    quiet = ratio[ratio <= np.percentile(ratio, 90.0)]
    if quiet.size < 32:
        quiet = ratio
    # Gamma-ish tail: use a log-space robust scale and a Bonferroni z.
    lr = np.log(quiet)
    med, mad = np.median(lr), np.median(np.abs(lr - np.median(lr)))
    sd = 1.4826 * mad if mad > 0 else lr.std()
    z = _norm_ppf(1.0 - alpha / max(f.size, 1))
    thresh = float(np.exp(med + z * sd))
    thresh = max(thresh, 6.0)          # never flag anything under 6x the floor

    idx = np.flatnonzero(ratio > thresh)

    # Collapse adjacent bins into one line and keep the local peak.
    lines = []
    for grp in _groups(idx):
        j = grp[np.argmax(ratio[grp])]
        excess = max(p[j] - floor[j], 0.0)
        # A coherent sinusoid of amplitude A has A^2/2 of power, spread over
        # roughly one equivalent noise bandwidth by the window.
        amp_lsb = math.sqrt(max(2.0 * excess * enbw, 0.0))
        lines.append(Line(float(f[j]), float(ratio[j]),
                          amp_lsb, amp_lsb * DELTA_DPS))

    lines.sort(key=lambda L: -L.amp_lsb)
    return dict(freqs=f, psd=p, floor=floor, ratio=ratio, thresh=thresh,
                lines=lines, enbw=enbw, n_avg=k)


def _groups(idx: np.ndarray):
    if idx.size == 0:
        return
    split = np.flatnonzero(np.diff(idx) > 2) + 1
    for grp in np.split(idx, split):
        yield grp


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF, Acklam's rational approximation (|err| < 1.15e-9).
    Here to avoid a scipy dependency for one number."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > ph:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# ==========================================================================
# Loading
# ==========================================================================

def load(path: str):
    rec = sdat.load(path)
    fs = rec.verify.f_board_hz
    if not (fs == fs) or fs <= 0:                      # NaN guard
        fs = float((rec.header.get("config") or {}).get("odr_nominal_hz") or 1.0)
    x = rec.gyro20.astype(np.float64) / FINE_PER_LSB   # input, in Delta
    q = rec.gyro16.astype(np.float64)                  # quantiser out, in Delta
    return rec, fs, x, q


def _banner(rec, fs, path):
    cfg = rec.header.get("config") or {}
    fw = rec.header.get("fw") or {}
    print(f"{os.path.basename(path)}")
    print(f"  fw {fw.get('version')} ({fw.get('tag')}), opt {fw.get('opt')}")
    print(f"  nominal ODR {cfg.get('odr_nominal_hz')} Hz, "
          f"measured {fs:.3f} Hz, {rec.n} samples, {rec.n / fs / 60:.2f} min")
    print(f"  AAF {cfg.get('aaf')}, UI_FILT_BW {cfg.get('ui_filt_bw')}, "
          f"FSR {cfg.get('fsr_dps')} dps, watermark "
          f"{cfg.get('fifo_watermark_bytes')} B")
    if not rec.verify.ok:
        print(f"  !! {len(rec.verify.problems)} verification problem(s) -- "
              f"this record is not admissible")


# ==========================================================================
# Commands
# ==========================================================================

def cmd_stats(args) -> int:
    rec, fs, x, q = load(args.file)
    _banner(rec, fs, args.file)

    t = rec.temp_c()
    print(f"  die temp {t.mean():.3f} C, span {t.max() - t.min():.3f} K, "
          f"drift {(t[-len(t)//20:].mean() - t[:len(t)//20].mean()):+.3f} K")

    gate = ((rec.header.get("gate") or {}).get("thermal_mk") or 0)
    if gate:
        span_mk = (t.max() - t.min()) * 1000.0
        verdict = "PASS" if span_mk <= gate else "FAIL -- R2 excision"
        print(f"  R2 gate {gate} mK: measured {span_mk:.0f} mK  {verdict}")

    print()
    print("  axis      mu(D)     phi     rho=sigma/D   sigma(mdps)   "
          "eta      codes")
    for i, ax in enumerate(AXES):
        s = Stats(x[:, i], q[:, i], fs)
        print(f"   {ax}   {s.mu:10.4f}  {s.phi:6.4f}   {s.rho:10.4f}   "
              f"{s.sigma_dps * 1e3:10.4f}   {s.eta:+7.4f}   {s.n_codes:5d}")

    print()
    print("  cross-checks (units of Delta)")
    for i, ax in enumerate(AXES):
        s = Stats(x[:, i], q[:, i], fs)
        print(f"   {ax}   sigma detrended {s.sigma:.4f}   raw {s.sigma_raw:.4f}"
              f"   successive-diff {s.sigma_diff:.4f}"
              f"   (diff/detrended {s.sigma_diff / s.sigma:.3f})")
    print("   diff/detrended below 1 means the noise is correlated sample to"
          " sample, i.e. the AAF is shaping it -- expected, not a fault.")
    return 0


def cmd_screen(args) -> int:
    rec, fs, x, q = load(args.file)
    _banner(rec, fs, args.file)

    axis = {"X": 0, "Y": 1, "Z": 2}[args.axis.upper()]
    s = Stats(x[:, axis], q[:, axis], fs)
    res = screen_lines(x[:, axis], fs, alpha=args.alpha)

    print()
    print(f"  R4 screen, gyro {args.axis.upper()}, fine (20-bit) stream")
    print(f"  Welch: {res['n_avg']} segments, ENBW {res['enbw']:.4f} Hz, "
          f"threshold {res['thresh']:.1f}x local median floor")
    print(f"  sigma {s.sigma:.4f} Delta = {s.sigma_dps * 1e3:.3f} mdps, "
          f"rho {s.rho:.4f}")

    lines = res["lines"]
    if not lines:
        print()
        print("  R4: PASS -- no coherent lines above threshold.")
        print("      Exact-theory tables apply.")
    else:
        print()
        print(f"  {len(lines)} candidate line(s):")
        for L in lines[:args.max_lines]:
            print(f"    {L}")
        if len(lines) > args.max_lines:
            print(f"    ... {len(lines) - args.max_lines} more")

        # The decision that matters is not "is there a line" but "is it big
        # enough to matter against the quantisation step".
        worst = lines[0].amp_lsb
        print()
        print(f"  largest line is {worst:.5f} Delta "
              f"({100.0 * worst / max(s.sigma, 1e-12):.2f}% of sigma)")
        if worst < 0.01:
            print("  R4: PASS (marginal) -- lines present but all below 0.01"
                  " Delta.")
            print("      Judgement call: record it, and state the bound in the"
                  " paper.")
        else:
            print("  R4: FAIL -- coherent lines are significant in band.")
            print("      Predictions must switch to the empirical-CF chain.")

    if args.fig:
        _fig_screen(res, s, rec, fs, args.axis.upper(), args.fig, args.file)
    return 0


def cmd_allan(args) -> int:
    rec, fs, x, q = load(args.file)
    _banner(rec, fs, args.file)
    print()
    curves = {}
    for i, ax in enumerate(AXES):
        taus, devs = allan_dev(x[:, i] * DELTA_DPS, fs)
        curves[ax] = (taus, devs)
        if devs.size:
            j = int(np.argmin(devs))
            # ARW read at tau = 1 s if the record reaches it.
            k = int(np.argmin(np.abs(taus - 1.0)))
            print(f"   {ax}   min ADEV {devs[j] * 1e3:8.4f} mdps at "
                  f"tau {taus[j]:8.3f} s   |   ADEV(1 s) "
                  f"{devs[k] * 1e3:8.4f} mdps  -> ARW "
                  f"{devs[k] * 60.0:.4f} deg/rt-hr")
    print()
    print("   min ADEV is the bias-instability floor; the tau^-1/2 slope at"
          " short tau is angle random walk.")
    if args.fig:
        _fig_allan(curves, rec, args.fig, args.file)
    return 0


def cmd_all(args) -> int:
    os.makedirs(args.figdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.file))[0]

    class A:
        pass
    a = A()
    a.file = args.file

    a.axis, a.alpha, a.max_lines = "X", 0.01, 15
    a.fig = os.path.join(args.figdir, f"{base}_screen.png")
    cmd_screen(a)
    print()
    cmd_stats(a)
    print()
    a.fig = os.path.join(args.figdir, f"{base}_allan.png")
    cmd_allan(a)

    rec, fs, x, q = load(args.file)
    _fig_overview(rec, fs, x, q,
                  os.path.join(args.figdir, f"{base}_overview.png"), args.file)
    print(f"\nfigures written to {args.figdir}")
    return 0


# ==========================================================================
# Figures -- for eyeballing, not for publication
# ==========================================================================

def _need_plt() -> bool:
    if plt is None:
        print("  (matplotlib not installed; skipping figures. "
              "pip install matplotlib)")
        return False
    return True


def _fig_screen(res, s, rec, fs, axis, out, path):
    if not _need_plt():
        return
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                                   gridspec_kw=dict(height_ratios=[3, 1]))

    f, p, floor = res["freqs"], res["psd"], res["floor"]
    # Amplitude spectral density in mdps/rtHz is the familiar view.
    asd = np.sqrt(p) * DELTA_DPS * 1e3
    ax1.loglog(f, asd, lw=0.6, label="fine (20-bit) ASD")
    ax1.loglog(f, np.sqrt(floor) * DELTA_DPS * 1e3, lw=1.2,
               label="local-median floor")
    for L in res["lines"][:25]:
        ax1.axvline(L.f, color="crimson", lw=0.6, alpha=0.5)
    ax1.set_ylabel("ASD  (mdps/$\\sqrt{Hz}$)")
    ax1.set_title(f"{os.path.basename(path)} -- R4 line screen, gyro {axis}\n"
                  f"$f_s$ = {fs:.2f} Hz, $\\rho$ = {s.rho:.4f}, "
                  f"{len(res['lines'])} candidate line(s)")
    ax1.grid(True, which="both", alpha=0.25)
    ax1.legend(loc="best", fontsize=9)

    ax2.semilogx(f, res["ratio"], lw=0.6)
    ax2.axhline(res["thresh"], color="crimson", ls="--", lw=1.0,
                label=f"threshold {res['thresh']:.1f}x")
    ax2.set_xlabel("frequency (Hz)")
    ax2.set_ylabel("PSD / floor")
    ax2.set_yscale("log")
    ax2.grid(True, which="both", alpha=0.25)
    ax2.legend(loc="best", fontsize=9)

    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"  figure -> {out}")


def _fig_allan(curves, rec, out, path):
    if not _need_plt():
        return
    fig, ax = plt.subplots(figsize=(8, 6))
    for name, (taus, devs) in curves.items():
        if devs.size:
            ax.loglog(taus, devs * 1e3, label=f"gyro {name}")
    if curves:
        t0 = next(iter(curves.values()))[0]
        if t0.size:
            # tau^-1/2 guide line through the first point.
            d0 = next(iter(curves.values()))[1][0] * 1e3
            ax.loglog(t0, d0 * (t0 / t0[0]) ** -0.5, "k:", lw=1,
                      label=r"$\tau^{-1/2}$ (white)")
    ax.set_xlabel(r"$\tau$ (s)")
    ax.set_ylabel("Allan deviation (mdps)")
    ax.set_title(f"{os.path.basename(path)} -- overlapping Allan deviation")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"  figure -> {out}")


def _fig_overview(rec, fs, x, q, out, path):
    if not _need_plt():
        return
    n = x.shape[0]
    dec = max(n // 20000, 1)
    t = np.arange(0, n, dec) / fs

    fig, axs = plt.subplots(2, 2, figsize=(13, 8))

    axs[0, 0].plot(t, x[::dec, 0], lw=0.4, label="fine / 16")
    axs[0, 0].plot(t, q[::dec, 0], lw=0.4, alpha=0.7, label="16-bit code")
    axs[0, 0].set_xlabel("t (s)")
    axs[0, 0].set_ylabel(r"gyro X  ($\Delta$)")
    axs[0, 0].set_title("time series -- the staircase is the quantiser")
    axs[0, 0].legend(fontsize=8)
    axs[0, 0].grid(alpha=0.25)

    tc = rec.temp_c()
    axs[0, 1].plot(np.arange(0, n, dec) / fs, tc[::dec], lw=0.8)
    axs[0, 1].set_xlabel("t (s)")
    axs[0, 1].set_ylabel("die temperature (C)")
    axs[0, 1].set_title(f"R2 thermal gate: span "
                        f"{(tc.max() - tc.min()) * 1e3:.0f} mK")
    axs[0, 1].grid(alpha=0.25)

    # Code histogram: the H0..H3 discriminant.
    codes, counts = np.unique(q[:, 0].astype(np.int64), return_counts=True)
    axs[1, 0].bar(codes, counts / counts.sum(), width=0.9)
    axs[1, 0].set_xlabel(r"16-bit code ($\Delta$)")
    axs[1, 0].set_ylabel("fraction")
    axs[1, 0].set_title(f"code histogram, gyro X -- {codes.size} codes occupied")
    axs[1, 0].grid(alpha=0.25)

    # Quantisation error against input phase: the shape here is the whole
    # argument.  A truncating quantiser gives a sawtooth; a rounder gives a
    # sawtooth shifted by half an LSB.
    err = q[:, 0] - x[:, 0]
    sub = slice(0, min(n, 200000))
    axs[1, 1].hist(err[sub], bins=200, density=True)
    axs[1, 1].set_xlabel(r"$Q(x) - x$   ($\Delta$)")
    axs[1, 1].set_ylabel("density")
    axs[1, 1].set_title("quantisation error distribution")
    axs[1, 1].grid(alpha=0.25)

    fig.suptitle(os.path.basename(path))
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"  figure -> {out}")


# ==========================================================================

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="R4 spectral screening and 19-bit estimators for .sdat.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("screen", help="R4 coherent-line screen")
    p.add_argument("file")
    p.add_argument("--axis", default="X", choices=list("XYZxyz"))
    p.add_argument("--alpha", type=float, default=0.01,
                   help="family-wise false-alarm rate across all bins")
    p.add_argument("--max-lines", type=int, default=15)
    p.add_argument("--fig")
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("stats", help="mu, phi, sigma, rho, eta per axis")
    p.add_argument("file")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("allan", help="overlapping Allan deviation")
    p.add_argument("file")
    p.add_argument("--fig")
    p.set_defaults(func=cmd_allan)

    p = sub.add_parser("all", help="everything, with figures")
    p.add_argument("file")
    p.add_argument("--figdir", default="figures")
    p.set_defaults(func=cmd_all)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
