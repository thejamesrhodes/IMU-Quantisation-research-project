#!/usr/bin/env python3
"""
make_numbers.py -- write paper/numbers.tex from summary.csv.

    python make_numbers.py "..\\..\\Test Datasets\\summary.csv" \\
                           -o "..\\..\\paper\\numbers.tex"

WHY THIS EXISTS

Every number that reaches the prose comes from here, and none is typed. In
three weeks this project moved a headline residual from 0.393 to 0.018,
restated every R2 verdict, and turned up a 4.9 sigma disagreement in a step
size. A draft with hand-typed numbers would already be wrong in several
places and would give no signal that it was.

So: \\input{numbers.tex} in main.tex, write \\phaseResidRMS{} in the text, and
a rerun of analyse.py propagates to the PDF on the next build. If a macro is
missing the build FAILS -- which is the correct behaviour, because the
alternative is a stale number that compiles quietly.

PROVENANCE. The file carries the git commit and the summary.csv hash in a
comment header, so a PDF can always be traced to the data that produced it.
That is the claim the Zenodo deposit has to support.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np


def _f(row, key, default=float("nan")):
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return default


def git_commit(path):
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=path, capture_output=True, text=True,
                             timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=path,
                               capture_output=True, text=True, timeout=20)
        tag = out.stdout.strip() or "unknown"
        if dirty.stdout.strip():
            tag += "-dirty"
        return tag
    except Exception:                                       # noqa: BLE001
        return "unknown"


def collect(rows):
    """Every macro the paper is allowed to cite, in one place."""
    ph = [r for r in rows if str(r.get("label", "")).startswith("ph_k")]
    odr = [r for r in rows
           if str(r.get("label", "")).startswith(("s1_odr", "s2_odr"))]
    odr_lo = [r for r in odr if _f(r, "rho_ref") < 0.9]     # eta not saturated

    n = {}
    n["nRecords"] = len({r["file"] for r in rows})
    n["nAxisMeas"] = len(rows)
    n["nSpecimens"] = len({r["slot"] for r in rows})

    if ph:
        res = np.array([_f(r, "eta_resid") for r in ph])
        eta = np.array([_f(r, "eta") for r in ph])
        phi = np.array([_f(r, "phi_ref") for r in ph])
        rho = np.array([_f(r, "rho_ref") for r in ph])
        n["nPhasePoints"] = len(ph)
        n["nPhaseSteps"] = len({r["offset_user"] for r in ph})
        n["phaseResidRMS"] = f"{np.sqrt(np.mean(res ** 2)):.4f}"
        n["phaseResidMax"] = f"{np.abs(res).max():.4f}"
        n["etaRangeLo"] = f"{eta.min():+.3f}"
        n["etaRangeHi"] = f"{eta.max():+.3f}"
        n["etaSpan"] = f"{np.ptp(eta):.2f}"
        n["phiLo"] = f"{phi.min():.3f}"
        n["phiHi"] = f"{phi.max():.3f}"
        n["phaseRho"] = f"{rho.mean():.3f}"
        n["residPctOfRange"] = f"{100 * np.sqrt(np.mean(res ** 2)) / np.ptp(eta):.1f}"

    if odr_lo:
        r2 = np.array([_f(r, "eta_resid") for r in odr_lo])
        n["odrResidRMS"] = f"{np.sqrt(np.mean(r2 ** 2)):.4f}"
        n["nOdrPoints"] = len(odr)
    if odr:
        rho = np.array([_f(r, "rho_ref") for r in odr])
        rho = rho[np.isfinite(rho) & (rho > 0)]
        n["rhoLo"] = f"{rho.min():.3f}"
        n["rhoHi"] = f"{rho.max():.3f}"
        n["rhoDecades"] = f"{np.log10(rho.max() / rho.min()):.2f}"

    # --- values that are NOT in summary.csv ------------------------------
    # These come from named sources. Each is tagged so that anything with no
    # provenance is visible rather than quietly authoritative.
    n["vzeroFourTotal"] = "450"          # TN-19 s1, discriminating samples
    n["refImprovement"] = "76\\%"        # TN-23 s3, out-of-sample
    n["refResidBefore"] = "0.393"        # TN-23 s2
    n["arwSpan"] = "$\\times 4.7$"       # F11
    n["histMaxDisc"] = "0.005"           # TN-23 s3
    n["biasInstLo"] = "0.006"            # TN-22 s4
    n["biasInstHi"] = "0.051"            # TN-22 s4
    n["stepSizeSweep"] = "0.499151"      # TN-23 s5
    n["stepSizeLadder"] = "0.499513"     # TN-21 s1
    n["deltaMdps"] = "61.035"            # 2000/32768 dps
    return n


HAND = {"vzeroFourTotal", "refImprovement", "refResidBefore", "arwSpan",
        "histMaxDisc", "biasInstLo", "biasInstHi", "stepSizeSweep",
        "stepSizeLadder", "deltaMdps"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)

    with open(a.csv, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("axis")]
    if not rows:
        print("no axis rows in the csv", file=sys.stderr)
        return 2

    digest = hashlib.sha256(open(a.csv, "rb").read()).hexdigest()[:16]
    repo = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(a.csv))))
    n = collect(rows)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("% GENERATED BY make_numbers.py -- DO NOT EDIT BY HAND.\n"
                 "% Any edit here is overwritten on the next build and will\n"
                 "% put the paper out of step with the data.\n%\n")
        fh.write(f"% source   : {os.path.basename(a.csv)}\n")
        fh.write(f"% sha256   : {digest}\n")
        fh.write(f"% commit   : {git_commit(repo)}\n")
        fh.write(f"% generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%MZ}\n")
        fh.write(f"% records  : {n.get('nRecords')}   "
                 f"axis-measurements: {n.get('nAxisMeas')}\n\n")

        fh.write("% --- derived from summary.csv " + "-" * 42 + "\n")
        for k, v in sorted(n.items()):
            if k in HAND:
                continue
            fh.write(f"\\newcommand{{\\{k}}}{{{v}}}\n")
        fh.write("\n% --- from named sources, NOT from the csv "
                 + "-" * 30 + "\n")
        fh.write("% Update these by hand when the source note changes, and\n"
                 "% keep the citation beside each one.\n")
        for k in sorted(HAND):
            if k in n:
                fh.write(f"\\newcommand{{\\{k}}}{{{n[k]}}}\n")

    derived = len([k for k in n if k not in HAND])
    print(f"{a.out}: {derived} macros from data, {len(HAND)} from notes")
    print(f"  sha256 {digest}   commit {git_commit(repo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
