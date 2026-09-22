#!/usr/bin/env python3
"""
render_answer_key.py — render the scanned answer-key pages of an IELTS PDF to
PNG, so a vision-capable model can read them.

Why this exists: `extract.py`'s `image_only_pages` heuristic (pages whose text
layer is under 5 characters) tells you where the answer key *starts*, but it
under-reports where it *ends* — a page can carry a small amount of real text
(a running header, a page number, a section title) while its main content is
still a scanned table or screenshot. Looping only over the literally-flagged
pages silently drops the last page of the key more often than you'd expect.

The rule established by hand-auditing ~40 passages this way: always render
from the first flagged image-only page through the PDF's true last page
(from `pdfinfo`), never stop at the last *flagged* page.

Usage:
    python scripts/render_answer_key.py "<in.pdf>" [--extracted work/<stem>.extracted.json] [-o work/keys] [-r 120]

If --extracted is omitted, this re-derives the image-only-page heuristic
itself (same rule as extract.py) so it can be run standalone on a PDF that
hasn't been extracted yet.

Requires: poppler-utils (pdfinfo, pdftoppm, pdftotext).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def true_last_page(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    m = re.search(r"^Pages:\s*(\d+)", out, re.M)
    if not m:
        raise RuntimeError(f"pdfinfo didn't report a page count for {pdf}")
    return int(m.group(1))


def image_only_pages_from_scratch(pdf: Path) -> list[int]:
    n = true_last_page(pdf)
    pages = []
    for i in range(1, n + 1):
        text = subprocess.run(
            ["pdftotext", "-layout", "-f", str(i), "-l", str(i), str(pdf), "-"],
            capture_output=True, text=True, check=True,
        ).stdout
        if len(text.strip()) < 5:
            pages.append(i)
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--extracted", help="path to <stem>.extracted.json (reuses its image_only_pages)")
    ap.add_argument("-o", "--outdir", default=None, help="directory for the PNGs (default: alongside a 'key' prefix in cwd)")
    ap.add_argument("-r", "--resolution", type=int, default=120)
    a = ap.parse_args()

    pdf = Path(a.pdf)
    last = true_last_page(pdf)

    if a.extracted:
        data = json.loads(Path(a.extracted).read_text(encoding="utf-8"))
        flagged = data.get("image_only_pages", [])
    else:
        flagged = image_only_pages_from_scratch(pdf)

    if not flagged:
        print(f"No image-only pages detected for {pdf.name} (nothing to render). "
              f"True page count is {last}; check manually if you still expect a scanned key.")
        return

    start = min(flagged)
    outdir = Path(a.outdir) if a.outdir else Path(".")
    outdir.mkdir(parents=True, exist_ok=True)
    prefix = outdir / f"{pdf.stem}_key"

    cmd = ["pdftoppm", "-r", str(a.resolution), "-f", str(start), "-l", str(last), "-png", str(pdf), str(prefix)]
    subprocess.run(cmd, check=True)

    rendered = sorted(outdir.glob(f"{pdf.stem}_key-*.png"))
    print(f"Rendered pages {start}-{last} of {last} (flagged: {flagged}) -> {len(rendered)} PNG(s):")
    for p in rendered:
        print(f"  {p}")
    print("\nRead every PNG above (View/Read tool) and cross-check each question's answer, "
          "evidence and reasoning against it before writing analysis.json. Do not stop at the "
          "last *flagged* page only — a scanned table can span pages this heuristic missed, "
          "which is exactly why this script renders through the true last page instead.")


if __name__ == "__main__":
    main()
