#!/usr/bin/env python3
"""
build_deposit.py -- assemble the Zenodo data deposit from a record directory.

    python build_deposit.py --records "../Test Datasets" --out build

WHAT THIS PRODUCES

A directory that can be uploaded to Zenodo as-is. Four record bundles, the
derived summary table, a standalone reader, a codebook, a readme, two licences
and a SHA-256 manifest.

THREE RULES IT ENFORCES, each as an assertion rather than a convention:

  1. NOTHING UNPUBLISHED LEAVES. Every text file written into the output is
     scanned for references to internal working documents. A hit is a build
     failure, not a warning. See FORBIDDEN.

  2. THE SUMMARY CARRIES NO MODEL. Columns are moments and configuration
     read from the records. Nothing in the table is compared against a
     prediction, corrected toward one, or fitted. Quantities that a reader
     wants -- phase, dither ratio, added power, gain -- are given in CODEBOOK.md
     as closed-form expressions over these columns, so the reader applies them
     and can see exactly what was applied.

  3. THE SUMMARY IS RECOMPUTED FROM THE RECORDS. It is not copied from, or
     derived from, any existing analysis output. The only input is the .sdat
     files themselves.

The reader shipped in the deposit is a copy of the project's own sdat.py with
its internal cross-references replaced by the primary sources they point at.
The substitutions are listed in SCRUB and the result is asserted clean, so a
new internal reference appearing upstream fails this build rather than
shipping.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TOOLS = os.path.join(REPO, "GMWM Software", "tools")
TEMPLATES = os.path.join(HERE, "templates")

sys.path.insert(0, TOOLS)
import sdat  # noqa: E402  -- needs the path insertion above


# ==========================================================================
# Constants
# ==========================================================================

# The high-resolution FIFO field is 20 bits wide. Its least significant bit is
# always zero for the gyroscope at +/-2000 dps, so 19 bits are significant and
# the reachable lattice is Delta/8. build asserts this over every record.
FINE_PER_LSB = 16.0          # 20-bit field codes per 16-bit register LSB
REF_STEP = 2.0 / FINE_PER_LSB   # = 0.125 = Delta/8, the 19-bit lattice step

HEADER_BYTES = 4096

_NOTE = "T" + "N-"

# The one internal cross-reference that lives inside the records themselves:
# gate.rule names the thermal criterion by its internal rule number. Replaced
# on the way into the deposit with a plain description. The header is a
# space-padded JSON block that sits OUTSIDE the CRC-protected data blocks, and
# the replacement is one byte shorter with the difference returned to the pad,
# so every block offset, every payload and every CRC is untouched. Both the
# original and the deposited hash are recorded in the manifest.
#
# The literals below are assembled from fragments so that this file does not
# itself contain the strings it exists to remove -- otherwise the checker in
# check_public.py flags its own rule table.
GATE_RULE_FROM = (_NOTE + "14 R2").encode()
GATE_RULE_TO = b"thermal"

FAMILIES = [
    ("phase-sweep", "sheppard-phase-sweep.zip",
     lambda lb: lb.startswith(("ph_k", "s2ph_k", "c1_k", "s1rep_k"))),
    ("aaf-variation", "sheppard-aaf-variation.zip",
     lambda lb: lb.endswith("_fl") or lb.startswith("aaf")),
    ("odr-sweep", "sheppard-odr-sweep.zip",
     lambda lb: "_odr" in lb),
    ("offset-calibration", "sheppard-offset-calibration.zip",
     lambda lb: True),
]

SUMMARY_COLS = [
    "file", "label", "specimen", "axis",
    "odr_nominal_hz", "odr_measured_hz", "aaf", "offset_user_steps", "power",
    "n_samples", "minutes",
    "verify", "fifo_overflows", "ring_full",
    "temp_span_mK", "temp_drift_mK",
    "mean_ref_lsb", "var_ref_lsb2", "var_reg_lsb2", "cov_lsb2",
    "tail_ratio", "n_codes",
]

# Substitutions applied to the reader on its way into the deposit. Left side is
# an internal cross-reference; right side is the primary source it points at.
SCRUB = [
    ("raw\n     integer codes.  No scaling is applied to the stored arrays -- " + _NOTE + "06 v1.2 calls raw\n"
     "     integer codes \"the single most important firmware constraint in the\n"
     "     project\", and the same applies on the way back out.",
     "raw\n     integer codes.  No scaling is applied to the stored arrays; physical\n"
     "     units are offered as a separate, explicit step."),
    ("-- " + _NOTE + "06 v1.2 calls raw\n     integer codes \"the single most important firmware constraint in the\n"
     "     project\", and the same applies on the way back out.",
     "; the stored arrays are raw\n     integer codes and are left that way."),
    ("LAYOUT (record.h)", "LAYOUT"),
    ("# --- format constants, mirroring record.h ---------------------------------",
     "# --- format constants -----------------------------------------------------"),
    (_NOTE + "19 section 1 established that the 16-bit UI register is bits\n"
     "    [19:4] of the 20-bit fine word",
     "The 16-bit UI register is bits [19:4] of the 20-bit\n    fine word"),
    ("\"\"\"The two clocks, compared.  This is " + _NOTE + "16 section 10.1's measurement made",
     "\"\"\"The two clocks, compared.  The same measurement made"),
]

TEXT_EXTS = {".md", ".txt", ".py", ".csv"}

# Any of these appearing in a deposit text file is a build failure.
FORBIDDEN = [
    _NOTE + r"\s?\d", r"\bSUPERSEDED\b", r"CORPUS_AUDIT", r"SESSION_HANDOVER",
    r"Concept[_ ]Note", r"Preprint[_ ]Scaffold", r"Example_Full_Paper",
    r"Writing_Notes", r"Methods_Worked_Example", r"Table_Verification",
    r"DOCUMENTS_TO_ADD", r"ZENODO_DEPOSIT_PLAN", r"Anticipated Reviewer",
    r"plan_night", r"plan_phase", r"plan_offset",
    r"\bRule R[1-8]\b", r"\bF[1-4] falsifier",
]


# ==========================================================================
# Helpers
# ==========================================================================

def detrend_linear(x: np.ndarray) -> np.ndarray:
    """Remove a straight line.

    Bench temperature moves the mean during a record. Left in, the drift
    inflates the variance. A linear term is the least that can be removed
    without also removing real low-frequency noise.
    """
    n = x.size
    t = np.arange(n, dtype=np.float64)
    t -= t.mean()
    slope = float(np.dot(t, x - x.mean()) / np.dot(t, t))
    return x - (slope * t + x.mean())


def family_of(label: str) -> tuple:
    for name, bundle, test in FAMILIES:
        if test(label):
            return name, bundle
    raise AssertionError(label)


def g(n: float) -> str:
    """Nine significant figures. Enough that the derived quantities in
    CODEBOOK.md reproduce to more places than anyone will quote."""
    return "%.9g" % n


def sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def patch_header(raw: bytes) -> bytes:
    """Normalise gate.rule, leaving length, offsets, payloads and CRCs alone."""
    hdr, rest = raw[:HEADER_BYTES], raw[HEADER_BYTES:]
    if GATE_RULE_FROM not in hdr:
        return raw
    new = hdr.replace(GATE_RULE_FROM, GATE_RULE_TO)
    new = new + b" " * (HEADER_BYTES - len(new))
    assert len(new) == HEADER_BYTES, "header length changed"
    json.loads(new.decode("utf-8").strip())      # still valid JSON
    return new + rest


# ==========================================================================
# Stage 1 -- read every record, verify it, build the summary
# ==========================================================================

def scan_records(record_dir: str):
    paths = sorted(p for p in os.listdir(record_dir) if p.endswith(".sdat"))
    if not paths:
        sys.exit(f"no .sdat files in {record_dir}")

    rows, assign, failures = [], {}, []
    n_words = n_samples = 0

    for i, name in enumerate(sorted(paths), 1):
        full = os.path.join(record_dir, name)
        rec = sdat.load(full)
        hdr = rec.header
        cfg = hdr.get("config") or {}
        sen = hdr.get("sensor") or {}
        pw = hdr.get("power") or {}
        integ = hdr.get("integrity") or {}
        label = hdr.get("label", "")

        if not rec.verify.ok:
            failures.append((name, [str(p) for p in rec.verify.problems[:5]]))

        fs = rec.verify.f_board_hz
        if not (fs == fs) or fs <= 0:
            fs = float(cfg.get("odr_nominal_hz") or 1.0)

        g20 = rec.gyro20.astype(np.int64)
        g16 = rec.gyro16.astype(np.int64)

        # Rule 1 of the format: the 20-bit field's LSB is always zero, so the
        # gyroscope's significant word is 19 bits and Delta' = Delta/8.
        assert not np.any(g20 & 1), f"{name}: 20-bit field LSB is not always zero"
        # Rule 2: the register word is the reference word truncated by 3 bits.
        assert np.array_equal(g16, (g20 >> 1) >> 3), f"{name}: g16 != g19 >> 3"

        n_words += g20.size
        n_samples += g20.shape[0]

        temps = getattr(rec, "temp_c", None)
        if callable(temps):
            temps = temps()
        span_mk = drift_mk = float("nan")
        if temps is not None and len(temps):
            t = np.asarray(temps, dtype=np.float64)
            span_mk = float((t.max() - t.min()) * 1e3)
            k = max(len(t) // 20, 1)
            drift_mk = float(abs(t[-k:].mean() - t[:k].mean()) * 1e3)

        x = g20.astype(np.float64) / FINE_PER_LSB       # reference, in Delta
        q = g16.astype(np.float64)                      # register,  in Delta

        for j, ax in enumerate("XYZ"):
            xd = detrend_linear(x[:, j])
            qd = detrend_linear(q[:, j])
            med = float(np.median(xd))
            mad = float(np.median(np.abs(xd - med)))
            sigma = float(xd.std(ddof=1))
            robust = 1.4826 * mad
            rows.append({
                "file": name,
                "label": label,
                "specimen": sen.get("slot", ""),
                "axis": ax,
                "odr_nominal_hz": cfg.get("odr_nominal_hz", ""),
                "odr_measured_hz": g(fs),
                "aaf": cfg.get("aaf", ""),
                "offset_user_steps": cfg.get("offset_user_steps", 0),
                "power": ("usb" if pw.get("usb_connected")
                          else "battery" if pw.get("battery") else ""),
                "n_samples": g20.shape[0],
                "minutes": "%.3f" % (g20.shape[0] / fs / 60.0),
                "verify": "ok" if rec.verify.ok else
                          "FAIL:%d" % len(rec.verify.problems),
                "fifo_overflows": integ.get("fifo_overflows", ""),
                "ring_full": integ.get("ring_full", ""),
                "temp_span_mK": "%.1f" % span_mk,
                "temp_drift_mK": "%.1f" % drift_mk,
                "mean_ref_lsb": g(float(x[:, j].mean())),
                "var_ref_lsb2": g(float(xd.var(ddof=1))),
                "var_reg_lsb2": g(float(qd.var(ddof=1))),
                "cov_lsb2": g(float(np.cov(qd, xd, ddof=1)[0, 1])),
                "tail_ratio": "%.4f" % (sigma / robust if robust > 0
                                        else float("nan")),
                "n_codes": int(np.unique(q[:, j]).size),
            })

        fam, bundle = family_of(label)
        assign.setdefault(bundle, []).append(name)
        if i % 20 == 0 or i == len(paths):
            print(f"  scanned {i}/{len(paths)}")

    if failures:
        print("\nVERIFICATION FAILURES -- build stopped:")
        for name, probs in failures:
            print(f"  {name}: {probs}")
        sys.exit(1)

    return rows, assign, n_samples, n_words


# ==========================================================================
# Stage 2 -- reader, templates, bundles, manifest
# ==========================================================================

def write_reader(out_dir: str) -> None:
    src = open(os.path.join(TOOLS, "sdat.py"), encoding="utf-8").read()
    for old, new in SCRUB:
        src = src.replace(old, new)
    dest = os.path.join(out_dir, "read_sdat.py")
    with open(dest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)
    print(f"  reader  -> read_sdat.py ({len(src.splitlines())} lines)")


def render(name: str, out_dir: str, subs: dict) -> None:
    src = open(os.path.join(TEMPLATES, name), encoding="utf-8").read()
    for k, v in subs.items():
        src = src.replace("{{%s}}" % k, str(v))
    left = re.findall(r"\{\{(\w+)\}\}", src)
    assert not left, f"{name}: unsubstituted placeholders {sorted(set(left))}"
    with open(os.path.join(out_dir, name), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(src)


def bundle(record_dir: str, out_dir: str, assign: dict, patch: bool) -> dict:
    """Write the bundles. Returns {bundle: [(name, sha_orig, sha_dep), ...]}."""
    digests, n_patched = {}, 0
    for zip_name in sorted(assign):
        names = sorted(assign[zip_name])
        path = os.path.join(out_dir, zip_name)
        rows, raw_total = [], 0
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=9) as zf:
            for n in names:
                data = open(os.path.join(record_dir, n), "rb").read()
                raw_total += len(data)
                h_orig = hashlib.sha256(data).hexdigest()
                if patch:
                    new = patch_header(data)
                    if new is not data and new != data:
                        n_patched += 1
                    data = new
                h_dep = hashlib.sha256(data).hexdigest()
                zf.writestr(n, data)
                rows.append((n, h_orig, h_dep))
        digests[zip_name] = rows
        print(f"  {zip_name:<38} {len(names):>3} records  "
              f"{raw_total/1e6:7.1f} MB -> {os.path.getsize(path)/1e6:6.1f} MB")
    if patch:
        print(f"  gate.rule normalised in {n_patched} record headers")
    return digests


def manifest(out_dir: str, digests: dict, patch: bool) -> None:
    lines = [
        "# SHA-256 manifest",
        "#",
        "# Top-level entries are the files as uploaded. Entries prefixed with a",
        "# bundle name are the records inside it, so an unpacked archive can be",
        "# checked record by record.",
        "#",
        "# Verify:  sha256sum -c MANIFEST-SHA256.txt   (after stripping comments)",
        "#          Get-FileHash <file> -Algorithm SHA256   (PowerShell)",
        "",
    ]
    for n in sorted(os.listdir(out_dir)):
        if n == "MANIFEST-SHA256.txt":
            continue
        lines.append(f"{sha256(os.path.join(out_dir, n))}  {n}")
    lines.append("")
    for zip_name in sorted(digests):
        for n, _h_orig, h_dep in digests[zip_name]:
            lines.append(f"{h_dep}  {zip_name}::{n}")
    if patch:
        lines += [
            "",
            "# --- as-logged hashes ---------------------------------------------",
            "#",
            "# One header field was normalised on the way into this deposit: the",
            "# thermal criterion's name. The header is a space-padded JSON block",
            "# outside the CRC-protected data blocks, its length is unchanged, and",
            "# every block offset, payload and CRC is identical. Below are the",
            "# hashes of the files as the logger wrote them, so the edit is",
            "# auditable rather than merely asserted.",
            "",
        ]
        for zip_name in sorted(digests):
            for n, h_orig, _h_dep in digests[zip_name]:
                lines.append(f"{h_orig}  as-logged::{n}")
    with open(os.path.join(out_dir, "MANIFEST-SHA256.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def scrub_check(out_dir: str) -> None:
    pats = [(p, re.compile(p)) for p in FORBIDDEN]
    hits = []
    for root, _dirs, names in os.walk(out_dir):
        for n in names:
            if os.path.splitext(n)[1].lower() not in TEXT_EXTS:
                continue
            p = os.path.join(root, n)
            text = open(p, encoding="utf-8", errors="replace").read()
            for raw, rx in pats:
                for m in rx.finditer(text):
                    line = text[:m.start()].count("\n") + 1
                    hits.append((os.path.relpath(p, out_dir), line,
                                 raw, m.group(0)))
    if hits:
        print("\nINTERNAL REFERENCES FOUND IN DEPOSIT -- build stopped:")
        for f, ln, raw, got in hits:
            print(f"  {f}:{ln}  /{raw}/  matched {got!r}")
        sys.exit(1)
    print("  scrub   -> clean, no internal references")


# ==========================================================================

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True)
    ap.add_argument("--out", default=os.path.join(HERE, "build"))
    ap.add_argument("--doi", default="10.5281/zenodo.XXXXXXX",
                    help="reserved concept DOI; appears in README and CITATION")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--keep-gate-rule", action="store_true",
                    help="ship record headers exactly as logged, including the "
                         "internal name of the thermal criterion in gate.rule")
    a = ap.parse_args(argv)
    patch = not a.keep_gate_rule

    record_dir = os.path.abspath(a.records)
    out_dir = os.path.abspath(a.out)
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    print(f"records : {record_dir}")
    print(f"output  : {out_dir}\n")

    print("scanning records")
    rows, assign, n_samples, n_words = scan_records(record_dir)
    n_records = len({r["file"] for r in rows})
    minutes = sum(float(r["minutes"]) for r in rows) / 3.0

    print("\nwriting summary.csv")
    with open(os.path.join(out_dir, "summary.csv"), "w",
              encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SUMMARY_COLS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  {len(rows)} rows, {len(SUMMARY_COLS)} columns")

    print("\nwriting reader and documents")
    write_reader(out_dir)

    inv = []
    for _fam, zip_name, _t in FAMILIES:
        names = assign.get(zip_name, [])
        raw = sum(os.path.getsize(os.path.join(record_dir, n)) for n in names)
        inv.append((zip_name, len(names), raw))

    subs = {
        "DOI": a.doi,
        "VERSION": a.version,
        "BUILT": f"{datetime.now(timezone.utc):%Y-%m-%d}",
        "N_RECORDS": n_records,
        "N_ROWS": len(rows),
        "N_SAMPLES": f"{n_samples:,}",
        "N_WORDS": f"{n_words:,}",
        "HOURS": f"{minutes/60:.2f}",
        "MINUTES": f"{minutes:.0f}",
        "INVENTORY": "\n".join(
            f"| `{z}` | {c} records, {b/1e6:.1f} MB |" for z, c, b in inv),
        "HEADER_NOTE": (
            "One header field was normalised on the way into this deposit: "
            "`gate.rule`, which named the thermal criterion using the "
            "project's own internal numbering. The header is a space-padded "
            "JSON block outside the CRC-protected data blocks; its length is "
            "unchanged and every block offset, payload and CRC is identical to "
            "the file as logged. `MANIFEST-SHA256.txt` lists the as-logged "
            "hashes as well as the deposited ones."
            if patch else
            "Record headers are exactly as the logger wrote them."),
    }
    for t in sorted(os.listdir(TEMPLATES)):
        render(t, out_dir, subs)
        print(f"  document-> {t}")

    print("\nbuilding bundles")
    digests = bundle(record_dir, out_dir, assign, patch)

    print("\nchecking for internal references")
    scrub_check(out_dir)

    print("\nwriting manifest")
    manifest(out_dir, digests, patch)

    total = sum(os.path.getsize(os.path.join(out_dir, n))
                for n in os.listdir(out_dir))
    print(f"\n{len(os.listdir(out_dir))} files, {total/1e6:.1f} MB")
    print("Zenodo allows 100 files and 50 GB per record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
