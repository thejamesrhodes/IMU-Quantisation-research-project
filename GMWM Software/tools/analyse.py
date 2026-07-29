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
# The 20-bit hi-res field's gyro LSB is always zero (TN-19 s1), so the
# reachable lattice of x = gyro20/16 has spacing 2/16 Delta, not 1/16.
REF_STEP = 2.0 / FINE_PER_LSB          # 0.125 Delta

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


def drift_excursion(y: np.ndarray, fs: float, block_s: float = 2.0) -> float:
    """Signed excursion of the linear trend of `y` across the whole record.

    WHY NOT max - min.  The obvious statistic, and the one this file used until
    29 July 2026, is the sample range.  It is an extreme-value statistic: for
    N independent samples of a Gaussian it grows as roughly 8.5 sigma at
    N = 6e4, and it therefore measures the SENSOR's noise, not the quantity's
    drift.  Measured on r358768_off_0a: the raw range of the die temperature is
    823 mK, the per-sample sensor noise is 84 mK, and the actual linear drift
    across the record is 103 mK.  Seven eighths of the reported "temperature
    span" was the thermometer talking to itself.

    Worse, it is not comparable across the ODR axis, because the temperature
    channel is filtered with ODR: sigma_T measures 13 mK at ODR 25 and 120 mK
    at ODR 8000.  A gate on the range therefore tightens as ODR falls for a
    reason that has nothing to do with temperature -- which is precisely the
    part of the axis the paper depends on.

    Blocking to `block_s` first collapses the sensor noise by sqrt(n_block)
    before the line is fitted, so the trend is estimated from means rather
    than from samples.
    """
    n = y.size
    b = max(int(round(block_s * fs)), 1)
    nb = n // b
    if nb < 3:                       # too short to block: fall back to samples
        m, span = y.astype(np.float64), n / max(fs, 1e-9)
        j = np.arange(m.size, dtype=np.float64)
    else:
        m = y[:nb * b].reshape(nb, b).mean(axis=1).astype(np.float64)
        j = np.arange(nb, dtype=np.float64)
        span = nb
    jc = j - j.mean()
    slope = float(np.dot(jc, m - m.mean()) / np.dot(jc, jc))
    return slope * (j[-1] - j[0])


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

        # ---- the reference stream is a quantiser too -----------------------
        #
        # x is not the continuous input. It is the 20-bit hi-res field divided
        # by 16, and that field is ITSELF a truncating quantiser: TN-19 s1
        # established that the gyro LSB of the field is always zero, so the
        # reachable lattice has spacing REF_STEP = 2/16 = 0.125 Delta, and the
        # register is a floor, not a rounder.
        #
        # A truncator has a deterministic mean error of -step/2. So the mean of
        # the reference stream sits half a fine code BELOW the mean of the
        # quantity it is standing in for, and every phase read from it is low
        # by REF_STEP/2 = 1/16 Delta. Its variance likewise carries step^2/12
        # of its own quantisation noise, which is Sheppard (1898) applied to
        # the board's own reference channel -- the correction the board is
        # named after, needed one level below where anyone was looking for it.
        #
        # Measured effect, 29 July phase sweep (16 records x 3 axes, ODR 50):
        # residual against the exact theory falls from RMS 0.393 to 0.018 with
        # NO free parameters, and the same two corrections improve the
        # independent 28 July ODR axis by 76% out of sample.
        #
        # Raw phi/rho are retained so the change is auditable and so anything
        # computed before 29 July 2026 can still be reproduced.
        self.phi_ref = float((self.mu + REF_STEP / 2.0) % 1.0)

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
        # Sheppard on the reference channel: subtract the fine quantiser's own
        # variance before calling the result the input's. See phi_ref above.
        self.rho_ref = float(math.sqrt(max(self.sigma ** 2
                                           - REF_STEP ** 2 / 12.0, 0.0)))
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

        # Outlier diagnostics.
        #
        # A Gaussian record of this length should not reach beyond about 5
        # sigma: at N = 6e5, P(|z| > 5) predicts 0.36 samples.  So if the code
        # count implies a span of tens of LSB while sigma is near 1 LSB, the
        # record contains transients -- a knock, a footfall, a door -- and not
        # merely wide noise.  That distinction decides whether a record is
        # usable, and it cannot be seen in sigma alone because a handful of
        # large samples barely move it.
        #
        # The MAD-based scale is the discriminant: it ignores the tails, so
        # sigma/sigma_robust >> 1 means the tails are doing the work.
        med = float(np.median(xd))
        mad = float(np.median(np.abs(xd - med)))
        self.sigma_robust = 1.4826 * mad
        self.tail_ratio = (self.sigma / self.sigma_robust
                           if self.sigma_robust > 0 else float("nan"))
        z = np.abs(xd - med) / max(self.sigma_robust, 1e-12)
        self.n_over_6 = int(np.count_nonzero(z > 6.0))
        self.z_max = float(z.max()) if z.size else 0.0

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
# The exact-theory chain: eta(rho, phi) in closed form
# ==========================================================================

def eta_exact(rho: float, phi: float, K: int = 400) -> float:
    r"""Added-power ratio for a TRUNCATING uniform quantiser, Gaussian input.

    With u = x/Delta and Q(x)/Delta = floor(u), the quantisation error has an
    exact Fourier representation -- the sawtooth series

        e = floor(u) - u + 1/2 = sum_{k>=1} sin(2 pi k u) / (pi k)

    so that Q = u - 1/2 + e and therefore

        eta = 12 [ 2 Cov(u, e) + Var(e) ].

    For Gaussian u with mean mu and standard deviation rho (both in units of
    Delta), every expectation reduces to values of the characteristic function
    on the quantiser's reciprocal lattice, g_k = exp(-2 pi^2 k^2 rho^2):

        Cov(u, e) = 2 rho^2 sum_k g_k cos(2 pi k phi)
        E[e]      = sum_k g_k sin(2 pi k phi) / (pi k)
        E[e^2]    = sum_{k,l} (A_{|k-l|} - A_{k+l}) / (2 pi^2 k l),
                    A_m = g_m cos(2 pi m phi),  A_0 = 1

    phi is the fractional part of mu and is EDGE-referenced, because the
    quantiser truncates. TN-12/13/14 reference mu to code centres, so their
    quoted phase is phi - 0.5; evaluated at phi = 0.5 this function reproduces
    TN-14 section 1.3 to three decimals at every tabulated rho, which is what
    fixes the convention (TN-20 section 2.2).

    The k = l terms contribute sum_k 1/(2 pi^2 k^2) -> 1/12 as K -> infinity,
    which is the classical Delta^2/12; truncating the series therefore biases
    eta low by about 12/(2 pi^2 K), and the tail is added back analytically
    rather than by brute force.
    """
    k = np.arange(1, K + 1, dtype=np.float64)
    g = np.exp(-2.0 * np.pi ** 2 * k ** 2 * rho ** 2)

    cov = 2.0 * rho ** 2 * float(np.sum(g * np.cos(2.0 * np.pi * k * phi)))
    e_mean = float(np.sum(g * np.sin(2.0 * np.pi * k * phi) / (np.pi * k)))

    m = np.arange(0, 2 * K + 2, dtype=np.float64)
    A = np.exp(-2.0 * np.pi ** 2 * m ** 2 * rho ** 2) * \
        np.cos(2.0 * np.pi * m * phi)
    A[0] = 1.0

    ki = np.arange(1, K + 1)
    kk, ll = np.meshgrid(ki, ki, indexing="ij")
    e_sq = float(np.sum((A[np.abs(kk - ll)] - A[kk + ll])
                        / (2.0 * np.pi ** 2 * kk * ll)))

    # Analytic tail of the k = l diagonal, sum_{k>K} 1/(2 pi^2 k^2).
    e_sq += 1.0 / (2.0 * np.pi ** 2 * K)

    return 12.0 * (2.0 * cov + e_sq - e_mean ** 2)


def eta_curve(rho, n_phi: int = 257):
    """(phi, eta) over one full period, for plotting or for a likelihood."""
    phi = np.linspace(0.0, 1.0, n_phi)
    return phi, np.array([eta_exact(rho, p) for p in phi])


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


def channels(rec):
    """All six mechanical channels, for cross-referencing a suspected line.

    The accelerometer is the bench-motion witness (TN-14 section 4.1) and costs
    nothing: FIFO_HIRES_EN forces a 20-byte packet whether accel is enabled or
    not, so it is already in every record. A real vibration must appear in the
    accel channels; an electrical artefact or an in-die spur need not. That is
    the cheapest available test of whether a line is coming through the mount.

    Gyro channels are returned in units of Delta, accel in raw fine codes --
    only the frequencies and the presence pattern matter here, not the scaling.
    """
    out = {}
    for i, ax in enumerate(AXES):
        out[f"gyro {ax}"] = rec.gyro20[:, i].astype(np.float64) / FINE_PER_LSB
    for i, ax in enumerate(AXES):
        out[f"accel {ax}"] = rec.accel20[:, i].astype(np.float64)
    return out


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
    pw = rec.header.get("power") or {}
    sen = rec.header.get("sensor") or {}
    print(f"  slot {sen.get('slot')}, SPI {sen.get('spi_hz', '?')} Hz, "
          f"battery {pw.get('battery')}, USB {pw.get('usb_connected')}")
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

    print()
    print("  tails and transients")
    for i, ax in enumerate(AXES):
        s = Stats(x[:, i], q[:, i], fs)
        flag = ""
        if s.tail_ratio > 1.15 or s.z_max > 8.0:
            flag = "   <-- transients, inspect the time series"
        print(f"   {ax}   sigma/sigma_robust {s.tail_ratio:5.3f}   "
              f"codes {s.n_codes:4d} spanning {s.code_span:4d} D   "
              f"max |z| {s.z_max:6.2f}   samples >6 sigma {s.n_over_6:6d}{flag}")
    print("   A clean Gaussian record of this length should not exceed about")
    print("   5 sigma. A code span far wider than ~10x sigma means the record")
    print("   contains knocks or footfalls, not merely wide noise.")
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

        # Coherent lines are variance, so they inflate sigma and therefore
        # rho -- and rho is the campaign's independent variable.  A sinusoid of
        # amplitude A carries A^2/2 of power, so subtracting the detected lines
        # gives the sigma the sensor would show on a quiet bench.  This is a
        # diagnostic, NOT a licence to analyse contaminated records: rule R4
        # switches the prediction chain, it does not permit subtraction.
        line_var = sum(L.amp_lsb ** 2 / 2.0 for L in lines)
        clean_var = max(s.sigma ** 2 - line_var, 0.0)
        rho_clean = math.sqrt(clean_var)
        print(f"  line power {line_var:.4f} Delta^2 of "
              f"{s.sigma ** 2:.4f} total ({100.0 * line_var / s.sigma ** 2:.1f}%)")
        print(f"  rho would be {rho_clean:.4f} on a bench without these lines "
              f"(measured {s.rho:.4f})")
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


def cmd_trace(args) -> int:
    """Screen all six channels and cross-tabulate the lines found.

    The question a single-channel screen cannot answer is WHERE a line comes
    from. This one can, because the answer is written in the presence pattern:

      - in all three accel axes and all three gyro axes -> the mount is moving;
        the source is mechanical and external, and isolation will fix it
      - in the gyro axes but NOT in accel -> not bench motion. Either genuine
        rotation (rare at a fixed frequency) or something inside the part or
        its supply, in which case moving the board will not help
      - in ONE channel only -> not a physical rotation or translation at all;
        treat as an electrical or in-die artefact of that channel

    Amplitudes across channels are not comparable (gyro is in Delta, accel in
    fine codes), so the table reports the ratio to each channel's own local
    noise floor, which is dimensionless and directly says how far the line
    stands out where it appears.
    """
    rec, fs, x, q = load(args.file)
    _banner(rec, fs, args.file)

    chans = channels(rec)
    found = {}
    for name, sig in chans.items():
        if float(np.std(sig)) < 1e-9:
            print(f"  {name}: constant -- channel disabled, skipping")
            continue
        res = screen_lines(sig, fs, alpha=args.alpha)
        found[name] = res

    # Cluster line frequencies across channels. One bin of tolerance is not
    # enough: the peak can sit either side of the true frequency in different
    # channels, so allow a few bins.
    tol = max(fs / 65536.0 * 4.0, 0.5)
    clusters = []
    for name, res in found.items():
        for L in res["lines"]:
            for c in clusters:
                if abs(c["f"] - L.f) <= tol:
                    c["hits"][name] = L
                    c["f"] = float(np.mean([c["f"], L.f]))
                    break
            else:
                clusters.append(dict(f=L.f, hits={name: L}))
    clusters.sort(key=lambda c: -max(h.ratio for h in c["hits"].values()))

    names = list(found.keys())
    print()
    print("  line presence across channels (ratio to that channel's floor)")
    print("     frequency  " + "".join(f"{n:>11}" for n in names))
    for c in clusters:
        row = f"  {c['f']:10.3f} Hz"
        for n in names:
            L = c["hits"].get(n)
            row += f"{L.ratio:11.0f}" if L else f"{'-':>11}"
        print(row)

    print()
    for c in clusters[:6]:
        g = sum(1 for n in c["hits"] if n.startswith("gyro"))
        a = sum(1 for n in c["hits"] if n.startswith("accel"))
        if a >= 2 and g >= 2:
            verdict = ("in BOTH sensors -- either the mount is moving, or it "
                       "is a shared-clock spur. Run `compare` to settle it.")
        elif a >= 2 and g <= 1:
            verdict = ("MECHANICAL translation -- accel sees it, gyro barely "
                       "does. Isolation will fix it.")
        elif a == 0 and g >= 2:
            verdict = ("gyro only -- not translation. Either rotational "
                       "vibration about a point near the accel, or electrical.")
        elif a == 0 and g == 1:
            verdict = ("single gyro channel -- not a physical rotation; "
                       "treat as electrical or in-die.")
        else:
            verdict = "mixed; needs a longer record to decide."
        print(f"  {c['f']:9.3f} Hz  gyro {g}/3, accel {a}/3  ->  {verdict}")

    print()
    print("  NOTE: presence in the accelerometer does NOT by itself prove")
    print("  mechanical origin. Accel and gyro are sampled by the same")
    print("  internal clock, so a spur in that clock domain appears in both.")
    print("  The decisive test is `compare` against a record from the other")
    print("  specimen: the two parts have independent RC oscillators, so an")
    print("  internal spur scales with the sample-rate ratio and an external")
    print("  one does not.")
    return 0


def cmd_compare(args) -> int:
    """Decide internal vs external origin using two specimens.

    Each ICM runs from its own RC oscillator, and the two differ by a few
    tenths of a percent. Anything generated inside the part -- a clock spur, a
    charge-pump artefact, a drive-loop beat -- is therefore at a frequency
    PROPORTIONAL to that part's sample rate, while anything arriving from
    outside sits at the same absolute frequency in both records.

    So for each line, compare

        f2 / f1     against     fs2 / fs1

    Agreement to within a bin means internal; equality of f2 and f1 instead
    means external. This is a far stronger test than the accelerometer
    cross-check, because it does not depend on how the disturbance couples.
    """
    ra, fsa, xa, _ = load(args.file_a)
    rb, fsb, xb, _ = load(args.file_b)

    ax = {"X": 0, "Y": 1, "Z": 2}[args.axis.upper()]
    res_a = screen_lines(xa[:, ax], fsa, alpha=args.alpha)
    res_b = screen_lines(xb[:, ax], fsb, alpha=args.alpha)

    ratio = fsb / fsa
    bin_a = fsa / 65536.0
    print(f"  A: {os.path.basename(args.file_a)}   fs {fsa:.3f} Hz")
    print(f"  B: {os.path.basename(args.file_b)}   fs {fsb:.3f} Hz")
    print(f"  sample-rate ratio fsB/fsA = {ratio:.6f} "
          f"({100.0 * (ratio - 1.0):+.4f}%)")
    print()
    print("     f_A (Hz)    f_B (Hz)   fB/fA      expected if internal  verdict")

    for La in res_a["lines"]:
        f_int = La.f * ratio                    # where it would sit if internal
        f_ext = La.f                            # where it would sit if external
        best, kind = None, ""
        for Lb in res_b["lines"]:
            if abs(Lb.f - f_int) <= max(3 * bin_a, 0.5):
                best, kind = Lb, "INTERNAL to the part (scales with its clock)"
                break
            if abs(Lb.f - f_ext) <= max(3 * bin_a, 0.5):
                best, kind = Lb, "EXTERNAL (same absolute frequency)"
                break
        if best is None:
            print(f"  {La.f:10.3f}         --         --                 "
                  f"{f_int:10.3f}   absent from B")
        else:
            print(f"  {La.f:10.3f} {best.f:11.3f} {best.f / La.f:9.6f}  "
                  f"{f_int:18.3f}   {kind}")
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


SUMMARY_COLS = [
    "file", "label", "slot", "odr_nom", "f_meas", "aaf", "offset_user",
    "battery", "n", "minutes", "verify", "overflows", "ring_full",
    "temp_span_mK", "temp_drift_mK", "gate_mK", "gate", "mu_drift_D",
    "axis", "mu_D", "phi", "rho", "phi_ref", "rho_ref",
    "eta", "eta_exact", "eta_resid", "sigma_mdps", "codes", "tail_ratio",
    "line_Hz", "line_D", "line_pct_var", "rho_clean",
    "adev_min_mdps", "adev_tau_s", "arw_deg_rthr",
]


def _summarise(path, screen_axis=0, fast=False):
    """Every number that matters from one record, as rows -- one per axis.

    Returns [] rather than raising if the file cannot be read: a summary run
    over a night's output must not stop at the first bad record, because the
    bad ones are usually the interesting ones.
    """
    try:
        rec, fs, x, q = load(path)
    except Exception as e:                                 # noqa: BLE001
        return [{"file": os.path.basename(path), "label": f"LOAD FAILED: {e}"}]

    hdr = rec.header
    cfg = hdr.get("config") or {}
    sen = hdr.get("sensor") or {}
    pw = hdr.get("power") or {}
    integ = hdr.get("integrity") or {}
    gate = (hdr.get("gate") or {}).get("thermal_mk") or 0

    t = rec.temp_c()
    span_mk = (t.max() - t.min()) * 1000.0          # retained as a diagnostic
    drift_mk = abs(drift_excursion(t, fs)) * 1000.0  # what R2 is actually about

    # Line screen once, on one axis: Welch over a few million samples times
    # three axes times sixteen records is minutes of CPU for information that
    # is the same line in each channel.
    try:
        res = screen_lines(x[:, screen_axis], fs)
        s0 = Stats(x[:, screen_axis], q[:, screen_axis], fs)
        if res["lines"]:
            L = res["lines"][0]
            line_hz, line_d = L.f, L.amp_lsb
            lp = sum(l.amp_lsb ** 2 / 2.0 for l in res["lines"])
            line_pct = 100.0 * lp / max(s0.sigma ** 2, 1e-12)
            rho_clean = math.sqrt(max(s0.sigma ** 2 - lp, 0.0))
        else:
            line_hz = line_d = line_pct = 0.0
            rho_clean = s0.sigma
    except Exception:                                      # noqa: BLE001
        line_hz = line_d = line_pct = rho_clean = float("nan")

    rows = []
    for i, ax in enumerate(AXES):
        s = Stats(x[:, i], q[:, i], fs)
        # Allan is O(N x n_tau) and dominates the runtime on multi-million
        # sample records -- 5M samples times 40 taus times three axes is a
        # minute per file. It is not needed for the eta/rho/phi results, so it
        # is skippable.
        taus, devs = ((np.array([]), np.array([])) if fast else
                      allan_dev(x[:, i] * DELTA_DPS, fs))
        if devs.size:
            j = int(np.argmin(devs))
            k = int(np.argmin(np.abs(taus - 1.0)))
            adev_min, adev_tau, arw = devs[j] * 1e3, taus[j], devs[k] * 60.0
        else:
            adev_min = adev_tau = arw = float("nan")

        rows.append({
            "file": os.path.basename(path),
            "label": hdr.get("label", ""),
            "slot": sen.get("slot", ""),
            "odr_nom": cfg.get("odr_nominal_hz", ""),
            "f_meas": round(fs, 3),
            "aaf": cfg.get("aaf", ""),
            "offset_user": cfg.get("offset_user_steps", 0),
            "battery": pw.get("battery", ""),
            "n": rec.n,
            "minutes": round(rec.n / fs / 60.0, 2),
            "verify": "ok" if rec.verify.ok else
                      f"FAIL:{len(rec.verify.problems)}",
            "overflows": integ.get("fifo_overflows", ""),
            "ring_full": integ.get("ring_full", ""),
            "temp_span_mK": round(span_mk, 1),
            "temp_drift_mK": round(drift_mk, 1),
            "gate_mK": gate,
            # R2 is evaluated on the DRIFT, not the sample range -- see
            # drift_excursion().  Records summarised before 29 July 2026 were
            # gated on the range and several "failures" were the thermometer's
            # own noise; re-run `summary` without --resume to restate them.
            "gate": ("n/a" if not gate else
                     ("pass" if drift_mk <= gate else "FAIL")),
            # The direct measurement of the thing R2 exists to bound. TN-14
            # s2.2 reasons temperature -> phase through the ZRO tempco; this
            # skips the middle term and catches every cause of phase drift,
            # including the mechanical and gradient-driven ones the tempco
            # does not describe. Budget at ODR 25 is 0.021 Delta.
            "mu_drift_D": round(abs(drift_excursion(x[:, i], fs)), 4),
            "axis": ax,
            "phi_ref": round(s.phi_ref, 4),
            "rho_ref": round(s.rho_ref, 4),
            "eta_exact": round(eta_exact(s.rho_ref, s.phi_ref), 4),
            "eta_resid": round(s.eta - eta_exact(s.rho_ref, s.phi_ref), 4),
            "mu_D": round(s.mu, 4),
            "phi": round(s.phi, 4),
            "rho": round(s.rho, 4),
            "sigma_mdps": round(s.sigma_dps * 1e3, 4),
            "eta": round(s.eta, 4),
            "codes": s.n_codes,
            "tail_ratio": round(s.tail_ratio, 3),
            "line_Hz": round(line_hz, 3),
            "line_D": round(line_d, 4),
            "line_pct_var": round(line_pct, 2),
            "rho_clean": round(rho_clean, 4),
            "adev_min_mdps": round(adev_min, 4),
            "adev_tau_s": round(adev_tau, 3),
            "arw_deg_rthr": round(arw, 4),
        })
    return rows


def cmd_summary(args) -> int:
    """One table for a whole night. This is the thing to send for review."""
    import csv
    import glob as _glob

    files = []
    for spec in args.path:
        if os.path.isdir(spec):
            files += sorted(_glob.glob(os.path.join(spec, "*.sdat")))
        else:
            files += sorted(_glob.glob(spec))
    if not files:
        print("no .sdat files found")
        return 2

    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(files[0])), "summary.csv")

    # Resume support. A night's worth of multi-million-sample records takes
    # minutes, and losing all of it because the last file failed is a bad
    # trade for the few lines this costs.
    done = set()
    rows = []
    if args.resume and os.path.exists(out):
        for r in csv.DictReader(open(out, encoding="utf-8")):
            rows.append(r)
            done.add(r.get("file", ""))
        print(f"  resuming: {len(done)} file(s) already summarised",
              file=sys.stderr)

    for i, f in enumerate(files, 1):
        if os.path.basename(f) in done:
            continue
        print(f"  [{i}/{len(files)}] {os.path.basename(f)}", file=sys.stderr)
        rows += _summarise(f, fast=args.fast)

        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=SUMMARY_COLS,
                               extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)

    # Compact console table: the columns you actually read first.
    print()
    # mu_D is in the table as well as phi. phi wraps at 1, so a shift of 10.24
    # LSB is indistinguishable from 0.24 -- which is exactly the ambiguity that
    # made the first OFFSET_USER check inconclusive. mu does not wrap.
    print(f"{'label':<14}{'slot':>4}{'ODR':>6}{'aaf':>7}{'off':>4}{'ax':>3}"
          f"{'mu_D':>11}{'rho':>8}{'rho_cln':>9}{'phi':>7}{'eta':>9}"
          f"{'codes':>6}{'line_D':>8}{'gate':>6}{'verify':>8}")
    for r in rows:
        if "axis" not in r:
            print(f"{r.get('label','?'):<14}  {r.get('file','')}")
            continue
        aaf = str(r["aaf"]).replace("Hz_default", "").replace("Hz_floor", "f")
        print(f"{r['label']:<14}{r['slot']:>4}{r['odr_nom']:>6}{aaf:>7}"
              f"{r['offset_user']:>4}{r['axis']:>3}{r['mu_D']:>11.4f}"
              f"{r['rho']:>8.4f}{r['rho_clean']:>9.4f}{r['phi']:>7.4f}"
              f"{r['eta']:>9.4f}{r['codes']:>6}{r['line_D']:>8.4f}"
              f"{r['gate']:>6}{r['verify']:>8}")

    print()
    print(f"{len(files)} record(s) -> {out}")
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

    p = sub.add_parser("trace", help="locate a line: screen all six channels")
    p.add_argument("file")
    p.add_argument("--alpha", type=float, default=0.01)
    p.set_defaults(func=cmd_trace)

    p = sub.add_parser("summary",
                       help="one CSV table for a whole night's records")
    p.add_argument("path", nargs="+",
                   help="a directory, or .sdat files / globs")
    p.add_argument("-o", "--out", help="CSV path (default summary.csv)")
    p.add_argument("--fast", action="store_true",
                   help="skip Allan deviation; much faster on large records")
    p.add_argument("--resume", action="store_true",
                   help="keep rows already in the CSV and only add new files")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("compare",
                       help="internal vs external, using two specimens")
    p.add_argument("file_a")
    p.add_argument("file_b")
    p.add_argument("--axis", default="X", choices=list("XYZxyz"))
    p.add_argument("--alpha", type=float, default=0.01)
    p.set_defaults(func=cmd_compare)

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
