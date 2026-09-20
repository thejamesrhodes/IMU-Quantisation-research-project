#!/usr/bin/env python3
"""
check_public.py -- report every internal cross-reference in what git would publish.

    python check_public.py                 # summary
    python check_public.py --detail        # every hit, file:line

WHY THIS IS A REPORT AND NOT A FIX

The firmware and the analysis tools cite the project's own notes by number in
their comments. Those citations are load-bearing internally -- they are how a
change gets traced back to the measurement that forced it -- and a blind
regex pass over source comments is a good way to damage working code for no
gain. So this prints what is there and leaves the decision alone.

None of these disclose a result. They disclose that an internal numbering
scheme exists. Whether that matters before publication is a judgement, and it
is one this script deliberately does not make.

Run it before making a repository public, and again before any release.
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Assembled from fragments so this file does not match its own rule table.
_N = "T" + "N-"

PATTERNS = [
    ("note citation", _N + r"\s?\d+[A-Z]?"),
    ("superseded register", r"\bSUPERSEDED\.md\b"),
    ("corpus audit", r"CORPUS_" + "AUDIT"),
    ("handover", r"SESSION_" + "HANDOVER"),
    ("concept note", r"Concept" + r"[_ ]Note"),
    ("preprint scaffold", r"Preprint" + r"[_ ]Scaffold"),
    ("manuscript draft", r"Example_" + r"Full_Paper|Writing_" + r"Notes|"
                        r"Methods_" + r"Worked_Example"),
    ("pre-registered rule", r"\bRule R[1-8]\b|\bR[1-8] gate\b"),
    ("falsifier", r"\bF[1-4] falsifier\b"),
    ("run plan", r"plan_" + r"(night|phase|offset)"),
]

# Files whose job is to name the things being excluded. A rule table that did
# not contain the patterns it matches would not work, and an ignore file that
# did not name the files it ignores would not either. Listed explicitly rather
# than pattern-matched, so adding a new exemption is a deliberate act.
SELF_EXEMPT = {
    ".gitignore",
    "zenodo/check_public.py",
    "zenodo/build_deposit.py",
    "zenodo/RELEASE.md",
}

SKIP_DIRS = {".git", "__pycache__", "node_modules"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".pdf", ".zip", ".bin", ".hex", ".elf",
              ".step", ".stp", ".wrl", ".sdat", ".npz", ".ico", ".gz"}


def tracked_after_reignore() -> list:
    """Files git would keep if the current .gitignore were reapplied.

    `git check-ignore` skips files that are already tracked, so --no-index is
    required: without it this reports every tracked file as surviving, which
    is the trap that makes a manual check useless.
    """
    ls = subprocess.run(["git", "ls-files"], cwd=REPO, text=True,
                        capture_output=True)
    if ls.returncode:
        sys.exit("not a git repository, or git unavailable")
    tracked = [f for f in ls.stdout.splitlines() if f]

    ignored = set()
    for i in range(0, len(tracked), 200):
        chunk = tracked[i:i + 200]
        r = subprocess.run(["git", "check-ignore", "--no-index", "--stdin"],
                           cwd=REPO, text=True, capture_output=True,
                           input="\n".join(chunk))
        ignored.update(x for x in r.stdout.splitlines() if x)

    keep = [f for f in tracked if f not in ignored]

    # Untracked files that `git add .` would pick up.
    st = subprocess.run(["git", "status", "--porcelain", "--untracked=all"],
                        cwd=REPO, text=True, capture_output=True)
    for line in st.stdout.splitlines():
        if line.startswith("?? "):
            f = line[3:].strip().strip('"')
            if f not in ignored:
                keep.append(f)
    return sorted(set(keep))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", action="store_true")
    a = ap.parse_args(argv)

    files = tracked_after_reignore()
    rx = [(name, re.compile(p)) for name, p in PATTERNS]

    hits = []
    for f in files:
        if os.path.splitext(f)[1].lower() in BINARY_EXT:
            continue
        if f.replace(os.sep, "/") in SELF_EXEMPT:
            continue
        full = os.path.join(REPO, f)
        if not os.path.isfile(full):
            continue
        try:
            text = open(full, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for name, r in rx:
            for m in r.finditer(text):
                hits.append((f, text[:m.start()].count("\n") + 1,
                             name, m.group(0)))

    print(f"files git would publish : {len(files)}")
    print(f"exempt (rule tables)    : {len(SELF_EXEMPT)}")
    print(f"files with a reference  : {len({h[0] for h in hits})}")
    print(f"total references        : {len(hits)}")

    if not hits:
        print("\nclean.")
        return 0

    print("\nby kind:")
    for name, c in collections.Counter(h[2] for h in hits).most_common():
        print(f"  {name:<22} {c}")

    print("\nby file:")
    per = collections.Counter(h[0] for h in hits)
    for f, c in per.most_common(20):
        print(f"  {c:>4}  {f}")
    if len(per) > 20:
        print(f"        ... and {len(per) - 20} more files")

    if a.detail:
        print("\ndetail:")
        for f, ln, name, got in hits:
            print(f"  {f}:{ln}  [{name}]  {got}")
    else:
        print("\nrun with --detail for file:line of every hit")

    print("\nNone of these disclose a result. Decide whether an internal")
    print("numbering scheme appearing in code comments matters for your")
    print("release, and act or do not act deliberately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
