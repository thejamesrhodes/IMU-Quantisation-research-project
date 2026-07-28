#!/usr/bin/env python3
"""
pdf_to_text.py -- make a PDF greppable.

Writes <name>.txt next to every PDF given, with a page marker before each page
so a hit can be traced back to a page number in the original:

    ===== PAGE 37 =====

Why this exists: the register maps and FIFO packet formats in DS-000347 are
the source of record for a dozen firmware constants, and the corpus audit
found that relying on second-hand values was a real source of error. Having
the datasheet as text in the repository means a value can be checked against
the source in seconds rather than being carried as a [verify] item for weeks.

    pip install pypdf
    python pdf_to_text.py "..\\datasheets\\ds-000347-icm-42688-p-v1.6.pdf"

With no arguments it converts every PDF in ../datasheets/.
"""

from __future__ import annotations

import glob
import os
import sys

try:
    from pypdf import PdfReader
except ImportError:
    try:
        from PyPDF2 import PdfReader          # older installs
    except ImportError:
        print("error: pypdf is required:  pip install pypdf", file=sys.stderr)
        sys.exit(1)


def convert(path: str) -> str:
    reader = PdfReader(path)
    out = os.path.splitext(path)[0] + ".txt"
    with open(out, "w", encoding="utf-8") as fh:
        for i, page in enumerate(reader.pages, start=1):
            fh.write(f"\n===== PAGE {i} =====\n")
            try:
                fh.write(page.extract_text() or "")
            except Exception as exc:                      # noqa: BLE001
                fh.write(f"[extraction failed: {exc}]")
    return out


def main() -> int:
    args = sys.argv[1:]
    if not args:
        here = os.path.dirname(os.path.abspath(__file__))
        default = os.path.join(os.path.dirname(here), "..", "datasheets")
        args = sorted(glob.glob(os.path.join(os.path.normpath(default), "*.pdf")))
        if not args:
            print("no PDFs found; pass one as an argument", file=sys.stderr)
            return 1

    for path in args:
        if not os.path.isfile(path):
            print(f"skipping, not found: {path}", file=sys.stderr)
            continue
        out = convert(path)
        pages = len(PdfReader(path).pages)
        size = os.path.getsize(out)
        print(f"{os.path.basename(path)}: {pages} pages -> "
              f"{os.path.basename(out)} ({size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
