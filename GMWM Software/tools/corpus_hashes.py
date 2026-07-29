#!/usr/bin/env python3
"""
corpus_hashes.py -- timestamp the corpus without publishing it.

    python corpus_hashes.py "C:\\path\\to\\corpus" -o "..\\..\\CORPUS-HASHES.txt"

THE PROBLEM THIS SOLVES

The research corpus is deliberately kept out of the public repository until
the preprint is out (see .gitignore, "Research corpus"). That is a reasonable
scoop-protection decision and it should not change.

But it means the pre-registered rules -- R1-R8, F1-F4, the predicted eta
table -- have no third-party timestamp. A referee asked to accept that they
predate the campaign is being asked to take it on trust, and local git commit
dates prove nothing because GIT_COMMITTER_DATE sets them to anything.

A cryptographic commitment fixes this without disclosing anything. Publish the
SHA-256 of each document now, in the PUBLIC repository. The hash reveals
nothing about the content. When the preprint appears, publish the documents;
anyone can then hash them and check they match what was committed to on the
earlier date, which GitHub's push record attests independently.

This is the standard commitment scheme and it costs one command. It is
strictly better than a private repository, because a private repository's
history is only checkable by someone you have already decided to trust.

WHAT IT DOES NOT DO

It does not prove the documents are CORRECT, or that they were not written
the day before. It proves only that their content is unchanged since the
commitment date. That is exactly the claim the paper needs and no more, and
it should be described that way and not oversold.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone

EXTS = {".md", ".tex", ".pdf", ".docx", ".py", ".bib", ".csv", ".txt"}


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", nargs="+",
                    help="folder(s) holding the documents to commit to")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--all-types", action="store_true",
                    help="hash every file, not just document types")
    a = ap.parse_args(argv)

    files = []
    for root_arg in a.corpus:
        if os.path.isfile(root_arg):
            files.append((os.path.basename(root_arg), root_arg))
            continue
        for root, _dirs, names in os.walk(root_arg):
            if ".git" in root.split(os.sep):
                continue
            for n in sorted(names):
                if a.all_types or os.path.splitext(n)[1].lower() in EXTS:
                    full = os.path.join(root, n)
                    files.append((os.path.relpath(full, root_arg), full))
    if not files:
        print("no files matched", file=sys.stderr)
        return 2

    files.sort()
    lines = [
        "# Corpus content commitment",
        "#",
        "# SHA-256 of each research document as of the date below. The files",
        "# themselves are not in this repository (see .gitignore, 'Research",
        "# corpus') and are withheld until the preprint appears.",
        "#",
        "# This commits to their CONTENT without disclosing it. When the",
        "# documents are published, hash them and compare: a match shows they",
        "# are unchanged since this file was pushed, and the push timestamp is",
        "# attested by GitHub rather than self-reported.",
        "#",
        "# It does NOT prove the documents are correct, nor that they were",
        "# written long before this date. It proves only that they have not",
        "# been altered since. That is the claim the paper needs.",
        "#",
        "# Verify:  sha256sum -c CORPUS-HASHES.txt   (after stripping comments)",
        "#          Get-FileHash <file> -Algorithm SHA256   (PowerShell)",
        "#",
        f"# generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}",
        f"# files    : {len(files)}",
        "",
    ]
    for rel, full in files:
        lines.append(f"{sha256(full)}  {rel.replace(os.sep, '/')}")

    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"{a.out}: {len(files)} file(s) committed to")
    for rel, _ in files[:8]:
        print(f"  {rel}")
    if len(files) > 8:
        print(f"  ... and {len(files) - 8} more")
    print("\nNow: git add, commit, push. The push is the timestamp.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
