#!/usr/bin/env python3
"""Extract the adopted budget's all-funds revenue summary from the PDF.

The formal fund totals used by the explorer were transcribed by hand. This script
reads them back out of the adopted PDF so the transcription can be checked rather
than trusted, and records the page and the PDF's checksum alongside the values.

It does not replace the workbook ingestion. It verifies the six numbers that the
workbook cannot supply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader

# Row labels in the order the summary table prints them. "INTERUND" is the
# source document's own spelling; matching it loosely would risk a false hit.
ROW_LABELS = [
    ("general-fund", "General Fund"),
    ("sidewalk-fund", "Municipal Sidewalk Fund"),
    ("water-fund", "Water Fund"),
    ("sewer-fund", "Sewer Fund"),
    ("downtown-assessment", "Downtown Special Assessment Fund"),
    ("crouse-marshall", "Crouse-Marshall Special Assessment Fund"),
    ("interfund", "LESS INTERUND REVENUES"),
]

ANCHOR = "ALL FUNDS - TOTAL REVENUES"
NUMBER = re.compile(r"\(?\$?([\d,]{4,})\)?")


def parse_amount(token: str) -> float:
    """Return a signed amount. Parenthesised figures are negative."""
    negative = token.strip().startswith("(")
    digits = token.replace(",", "").replace("$", "").strip("()")
    return -float(digits) if negative else float(digits)


def find_summary_page(reader: PdfReader) -> tuple[int, str]:
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        if ANCHOR in text and "NET TOTAL" in text:
            return index + 1, text
    raise SystemExit(f"Could not find a page containing {ANCHOR!r}. The PDF layout may have changed.")


def parse_summary(text: str) -> dict:
    """Read the FY26 adopted and FY27 adopted columns off the summary table.

    Each labelled line carries the two FY26 columns inline. The FY27 column is
    printed afterwards as a bare block of numbers in the same row order, so it is
    matched positionally and then checked against the table's own net total. A
    misaligned parse fails that arithmetic instead of returning plausible values.
    """
    fy26: dict[str, float] = {}
    for key, label in ROW_LABELS:
        match = re.search(re.escape(label) + r"[^\n\d(]*((?:\(?[\d,]+\)?[ \t]*){1,2})", text)
        if not match:
            raise SystemExit(f"Row {label!r} not found on the summary page.")
        numbers = NUMBER.findall(match.group(1))
        if not numbers:
            raise SystemExit(f"Row {label!r} carried no figures.")
        fy26[key] = parse_amount(match.group(1).split()[0])

    tail = text[text.index("NET TOTAL"):]
    blocks = [line.strip() for line in tail.splitlines() if NUMBER.fullmatch(line.strip() or "x")]
    amounts = [parse_amount(line) for line in blocks]
    # The trailing run is the FY27 column: one figure per row, then the net.
    expected = len(ROW_LABELS) + 1
    if len(amounts) < expected:
        raise SystemExit(f"Expected at least {expected} figures after NET TOTAL, found {len(amounts)}.")
    fy27_block = amounts[-expected:]

    fy27 = {key: value for (key, _), value in zip(ROW_LABELS, fy27_block)}
    net = fy27_block[-1]

    computed = sum(fy27[key] for key, _ in ROW_LABELS)
    if abs(computed - net) > 0.01:
        raise SystemExit(
            f"Parsed rows sum to {computed:,.0f} but the table's net total is {net:,.0f}. "
            "The column alignment is wrong; refusing to emit values."
        )
    return {"fy26Adopted": fy26, "fy27Adopted": fy27, "netFy27Adopted": net}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", default="work/adopted.pdf")
    parser.add_argument("--output", default="data/pdf_totals.json")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise SystemExit(f"{pdf_path} not found. Download the adopted budget PDF first.")

    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    reader = PdfReader(str(pdf_path))
    page_number, text = find_summary_page(reader)
    parsed = parse_summary(text)

    result = {
        "source": "FY2026-27 adopted budget PDF",
        "sourcePdfSha256": digest,
        "sourcePage": page_number,
        "sourcePageNote": (
            f"Physical page {page_number} of the adopted PDF; the printed page number is 14 lower. "
            "Extracted from the ALL FUNDS - TOTAL REVENUES summary."
        ),
        **parsed,
    }
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"page": page_number, "net": parsed["netFy27Adopted"], "output": args.output}))


if __name__ == "__main__":
    main()
