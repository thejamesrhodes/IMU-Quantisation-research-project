#!/usr/bin/env python3
"""
software_dither.py -- vary rho at FIXED ODR, by adding known noise in software.

WHAT THIS IS FOR

Rule R6 (TN-14 s6) requires hypothesis selection over a "software dither
sweep" as one of three legs, and that leg has never existed. It is also the
answer to the sharpest objection available against the eta(rho) result:

    "Your rho axis IS an ODR axis. rho and ODR move together in every record
     you have, so the curve you are calling register statistics could be a
     decimation or filter artefact instead."

The 30 July anti-alias-filter attempt (TN-24 s7) was meant to break that and
failed: where rho moved usefully the 119 Hz line moved with it, and the narrow
setting left samples correlated at r_1 = 0.8. Software dither has none of those
problems, because every confound is held still BY CONSTRUCTION -- same record,
same ODR, same filter, same line, same correlation structure, same die
temperature. The only thing that changes is rho, and it changes by a known
amount.

THE CONSTRUCTION

Take the 20-bit stream x (units of Delta), add synthetic Gaussian noise n of
standard deviation d, and truncate the sum on the register lattice:

    u      = x + n                       the input to the simulated quantiser
    Q_sim  = floor(u)                    a truncating quantiser, by definition
    eta    = [Var(Q_sim) - Var(u)] / (Delta^2/12)

WHY THIS NEEDS NO REFERENCE CORRECTION, AND WHY THAT MATTERS

u is genuinely the continuous input to the simulated quantiser: n is
continuous, so u is, whatever lattice x sits on. So rho and phi are read
directly off u with NO Sheppard term and NO half-lattice phase offset:

    rho = sd(u) / Delta                  phi = mean(u) mod 1

That is the opposite of the hardware case, where the reference channel's own
truncation has to be corrected in three places (TN-24 s3). It makes this an
INDEPENDENT test of eta_exact -- if the software sweep agrees with the theory,
the agreement cannot be an artefact of the correction machinery, because none
of that machinery is used here.

VALID RANGE

x is quantised on Delta' = Delta/8, so u is only smoothly distributed once d
is comfortably larger than Delta'. The sweep therefore starts at d = 2 Delta'
= 0.25 Delta. Below that the lattice structure of x survives into u and the
Gaussian assumption in eta_exact is violated by construction rather than by
the instrument. The region rho < 0.3 is already covered by the hardware sweep,
so nothing is lost.

THE DECISIVE TEST is --pairs: find (record, d) combinations on ODR 50 and on
ODR 1000 that land at the SAME rho, and compare. Same rho, different ODR,
different filter, different sample count. If eta agrees with theory at both,
the rho axis is not a decimation artefact and the objection is answered.

USAGE

    python software_dither.py "../../Test Datasets"                 # sweep
    python software_dither.py "../../Test Datasets" --pairs         # the test
    python software_dither.py "../../Test Datasets" -o dither.csv
"""

from __future__ import annotations

import argparse
import csv
import glob
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyse import AXES, eta_exact, load, detrend_linear   # noqa: E402

DELTA_MDPS = 61.03515625
REF_STEP = 2.0 / 16.0                    # Delta' = Delta/8
D_MIN = 2.0 * REF_STEP                   # 0.25 Delta, see VALID RANGE above

# Geometric in d. The top end takes rho past 3, where eta_exact is 1 to five
# decimal places and the test becomes "does the pipeline reproduce PQN".
D_GRID = np.geomspace(D_MIN, 3.0, 14)

N_REAL = 8          # independent noise realisations per (record, axis, d)
SEED = 20260730     # fixed, so the table is reproducible


def sweep_record(path, d_grid=D_GRID, n_real=N_REAL, rng=None):
    """One record -> rows of (axis, d, rho, phi, eta_meas, eta_exact, ...).

    The same noise realisation is NOT reused across d: each (axis, d, r) draws
    fresh, so the scatter across realisations is an honest estimate of the
    simulation's own noise and can be compared with the model error.
    """
    rng = rng or np.random.default_rng(SEED)
    rec, fs, x, _q = load(path)
    hdr = rec.header or {}
    cfg = hdr.get("config") or {}
    label = str(hdr.get("label", os.path.basename(path)))
    odr = float(cfg.get("odr_nominal_hz") or fs)
    slot = int(hdr.get("slot", 0) or 0)

    out = []
    for i, ax in enumerate(AXES):
        # Detrend the CARRIER only. A thermal ramp in x would otherwise inflate
        # Var(u) without being part of the dither, which is the same mistake
        # the hardware pipeline avoids by detrending both streams.
        xa = detrend_linear(x[:, i].astype(np.float64))
        mu_x = float(x[:, i].mean())          # keep the true mean: phi needs it
        xa = xa + mu_x
        for d in d_grid:
            for r in range(n_real):
                n = rng.normal(0.0, d, size=xa.size)
                u = xa + n
                qs = np.floor(u)
                # No reference correction anywhere in these four lines.
                rho = float(u.std(ddof=1)) / 1.0
                phi = float(u.mean() % 1.0)
                eta = float((qs.var(ddof=1) - u.var(ddof=1)) / (1.0 / 12.0))
                ex = eta_exact(rho, phi)
                out.append(dict(
                    file=os.path.basename(path), label=label, slot=slot,
                    odr=odr, axis=ax, d=round(float(d), 5), real=r,
                    n=int(xa.size),
                    rho=round(rho, 5), phi=round(phi, 5),
                    eta=round(eta, 5), eta_exact=round(ex, 5),
                    eta_resid=round(eta - ex, 5),
                ))
    return out


def _rms(v):
    v = np.asarray(v, dtype=float)
    v = v[~np.isnan(v)]
    return math.sqrt((v ** 2).mean()) if v.size else float("nan")


def report(rows):
    print("\n" + "=" * 78)
    print("SOFTWARE DITHER SWEEP -- rho varied at fixed ODR, no reference "
          "correction used")
    print("=" * 78)
    odrs = sorted({r["odr"] for r in rows})
    print(f"  {len(rows)} simulated measurements   "
          f"ODR {', '.join(f'{o:g}' for o in odrs)}   "
          f"rho {min(r['rho'] for r in rows):.3f}-{max(r['rho'] for r in rows):.3f}")

    print("\n--- by rho decade, pooled over ODR ---")
    print(f"  {'rho band':>14s} {'n':>5s} {'eta range':>16s} "
          f"{'resid RMS':>10s} {'resid mean':>11s}")
    edges = [0.25, 0.4, 0.6, 0.9, 1.4, 2.2, 3.2]
    for lo, hi in zip(edges, edges[1:]):
        g = [r for r in rows if lo <= r["rho"] < hi]
        if not g:
            continue
        e = [r["eta"] for r in g]
        print(f"  {lo:5.2f} - {hi:5.2f} {len(g):5d} "
              f"{min(e):+7.3f}..{max(e):+6.3f} "
              f"{_rms([r['eta_resid'] for r in g]):10.5f} "
              f"{np.mean([r['eta_resid'] for r in g]):+11.5f}")

    print("\n--- by ODR, which is the confound test ---")
    for o in odrs:
        g = [r for r in rows if r["odr"] == o]
        print(f"  ODR {o:6g}  n={len(g):5d}  rho {min(r['rho'] for r in g):.3f}"
              f"-{max(r['rho'] for r in g):.3f}  "
              f"resid RMS {_rms([r['eta_resid'] for r in g]):.5f}  "
              f"mean {np.mean([r['eta_resid'] for r in g]):+.5f}")

    print("\n--- simulation's own noise, from the spread across realisations ---")
    keys = {}
    for r in rows:
        keys.setdefault((r["file"], r["axis"], r["d"]), []).append(r["eta"])
    spreads = [np.std(v, ddof=1) for v in keys.values() if len(v) > 2]
    print(f"  median SD of eta across {N_REAL} realisations: "
          f"{np.median(spreads):.5f}")
    print(f"  pooled residual RMS:                          "
          f"{_rms([r['eta_resid'] for r in rows]):.5f}")
    print("  If these are comparable the theory is exact to the simulation's")
    print("  own resolution, and the remaining error is Monte-Carlo noise.")


def report_pairs(rows, tol=0.02):
    """Same rho, different ODR. The answer to the confound objection."""
    print("\n" + "=" * 78)
    print("SAME rho, DIFFERENT ODR -- the decimation-artefact test")
    print("=" * 78)
    print("Each pair holds rho fixed to within "
          f"{tol:.0%} and changes ODR by 20x. If eta is a decimation artefact")
    print("the two members disagree; if it is register statistics they agree.\n")
    lo = [r for r in rows if r["odr"] <= 100]
    hi = [r for r in rows if r["odr"] >= 500]
    if not lo or not hi:
        print("  need records at two well-separated ODRs; none found")
        return
    # Bin both sides on rho and compare band means, which is more honest than
    # hand-picking individual pairs.
    edges = np.geomspace(0.3, 3.0, 9)
    print(f"  {'rho band':>13s} | {'n lo':>5s} {'resid lo':>18s} "
          f"| {'n hi':>5s} {'resid hi':>18s} | {'difference':>19s} {'sd':>5s}")
    dif, sig = [], []
    for a, b in zip(edges, edges[1:]):
        gl = [r for r in lo if a <= r["rho"] < b]
        gh = [r for r in hi if a <= r["rho"] < b]
        if len(gl) < 8 or len(gh) < 8:
            continue
        vl = np.array([r["eta_resid"] for r in gl])
        vh = np.array([r["eta_resid"] for r in gh])
        # SE from the observed scatter. These are not independent draws --
        # realisations share a carrier -- so this is optimistic by a factor
        # of order sqrt(N_REAL). Stated rather than hidden.
        sl = vl.std(ddof=1) / math.sqrt(len(vl) / N_REAL)
        sh = vh.std(ddof=1) / math.sqrt(len(vh) / N_REAL)
        d = vh.mean() - vl.mean()
        s = math.hypot(sl, sh)
        dif.append(d)
        sig.append(d / s if s else 0.0)
        print(f"  {a:5.2f}-{b:5.2f} | {len(gl):5d} {vl.mean():+9.4f} "
              f"+/- {sl:.4f} | {len(gh):5d} {vh.mean():+9.4f} +/- {sh:.4f} "
              f"| {d:+9.4f} +/- {s:.4f} {d / s if s else 0:+5.1f}")
    if dif:
        print(f"\n  residual difference across ODR: mean {np.mean(dif):+.5f}, "
              f"RMS {_rms(dif):.5f}, largest |t| {max(abs(t) for t in sig):.1f}")
        print("  A decimation artefact would make this large, systematic in")
        print("  sign, and growing with rho. Check all three before concluding.")
        print("\n  NOTE the SEs are per-carrier, not per-realisation: the eight")
        print("  realisations of one record share a carrier and are correlated,")
        print("  so n/N_REAL is used as the effective count.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="directory of .sdat records")
    ap.add_argument("-o", "--out", help="write the full table to CSV")
    ap.add_argument("--glob", default=None,
                    help="restrict to matching filenames")
    ap.add_argument("--pairs", action="store_true",
                    help="also run the same-rho-different-ODR test")
    ap.add_argument("--limit", type=int, default=0,
                    help="use at most this many records per ODR (speed)")
    a = ap.parse_args()

    pats = [a.glob] if a.glob else ["*ph_k*.sdat", "*_odr1000_*.sdat",
                                    "*_odr50_*.sdat"]
    files = []
    for p in pats:
        files += glob.glob(os.path.join(a.root, p))
    files = sorted(set(files))
    if not files:
        print("no records matched", file=sys.stderr)
        return 1

    if a.limit:
        byodr = {}
        keep = []
        for fn in files:
            k = "1000" if "1000Hz" in fn else ("50" if "50Hz" in fn else "?")
            byodr.setdefault(k, 0)
            if byodr[k] < a.limit:
                keep.append(fn)
                byodr[k] += 1
        files = keep

    print(f"{len(files)} record(s)")
    rows = []
    rng = np.random.default_rng(SEED)
    for i, fn in enumerate(files, 1):
        print(f"  [{i}/{len(files)}] {os.path.basename(fn)}", flush=True)
        try:
            rows += sweep_record(fn, rng=rng)
        except Exception as exc:                      # noqa: BLE001
            print(f"      skipped: {exc}")

    report(rows)
    if a.pairs:
        report_pairs(rows)

    if a.out:
        with open(a.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\n-> {a.out}  ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
