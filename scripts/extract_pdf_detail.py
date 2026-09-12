#!/usr/bin/env python3
"""Extract line-item detail from a Syracuse adopted-budget PDF.

The budget tables are hierarchical: a section header sits at the left margin, its
line items are indented, and an indented "Total <section>:" line closes the block.
Summing every numeric row would double-count, so rows are grouped by indentation
and each block is reconciled against the total the document itself prints.

Reconciliation is the accuracy measure. A block that does not sum to its printed
total is reported as a mismatch rather than emitted as though it were correct.

Some figures are set in a subset font whose ToUnicode map is wrong, so their
digits arrive as characters in U+00E7..U+00F4. Those values are marked unreadable
and excluded from sums; they are never guessed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import pdfplumber

# Digits lost to the broken subset-font encoding.
UNREADABLE = re.compile(r"[ç-ô]")
NUMERIC = re.compile(r"^\(?-?[\d,ç-ô]+\)?$")
# The tables print rules between columns as runs of "=" or "_". They carry no
# meaning and must not survive into a label, or a total line stops looking like one.
SEPARATOR = re.compile(r"^[=_\-–—]+$")
TOTAL_LINE = re.compile(r"^\s*TOTAL\s+(.+?)\s*$", re.I)
# Each statement restarts the hierarchy; rows never carry across one.
STATEMENT_START = re.compile(r"(REVENUE|EXPENDITURE)\s+SUMMARY", re.I)

ROW_TOLERANCE = 2.6      # points; words within this share a baseline
COLUMN_TOLERANCE = 18.0  # points; how far a figure may sit from a column centre
HEADER_MAX_X = 100.0     # labels left of this open a section
# The revenue pages set text tightly enough that pdfplumber's default gap of 3pt
# runs whole labels together ("TOTALWATERFUNDREVENUE"). Anything from 0.8 to 2.0
# splits both page styles correctly without breaking digits apart.
WORD_TOLERANCE = 1.5


def to_number(text):
    """Parse a printed figure. Parenthesised values are negative."""
    if UNREADABLE.search(text):
        return None
    negative = text.strip().startswith("(")
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    return -int(digits) if negative else int(digits)


def group_into_lines(page, tolerance=ROW_TOLERANCE):
    words = sorted(page.extract_words(x_tolerance=WORD_TOLERANCE),
                   key=lambda w: (round(w["top"], 1), w["x0"]))
    lines = []
    current = []
    baseline = None
    for word in words:
        if baseline is None or abs(word["top"] - baseline) <= tolerance:
            current.append(word)
            baseline = word["top"] if baseline is None else baseline
        else:
            lines.append(current)
            current, baseline = [word], word["top"]
    if current:
        lines.append(current)
    return lines


def read_lines(page, page_number):
    parsed = []
    for line in group_into_lines(page):
        kept = [w for w in line if not SEPARATOR.match(w["text"])]
        figures = [w for w in kept if NUMERIC.match(w["text"])]
        label_words = [w for w in kept if w not in figures]
        label = " ".join(w["text"] for w in label_words).strip().rstrip(":").strip()
        if not label and not figures:
            continue
        code = None
        match = re.match(r"^(\d{6})\s+(.*)$", label)
        if match:
            code, label = match.group(1), match.group(2)
        parsed.append({
            "page": page_number,
            "code": code,
            "label": label,
            "indent": round(min((w["x0"] for w in label_words), default=0.0), 1),
            "figures": [
                {"text": w["text"], "right": round(w["x1"], 1),
                 "unreadable": bool(UNREADABLE.search(w["text"]))}
                for w in figures
            ],
        })
    return parsed


def merge_wrapped_labels(lines):
    """Join a label-only line onto the following line when the label wrapped.

    A wrapped label prints at the same indentation as the row it belongs to and
    carries no figures of its own.
    """
    merged = []
    pending = []
    for line in lines:
        if not line["figures"] and line["indent"] > HEADER_MAX_X:
            pending.append(line["label"])
            continue
        if pending:
            if line["figures"] and line["indent"] > HEADER_MAX_X:
                line = dict(line, label=" ".join(pending + [line["label"]]).strip())
            else:
                for text in pending:
                    merged.append(dict(line, label=text, figures=[], code=None))
            pending = []
        merged.append(line)
    return merged


def column_centres(lines, expected=4):
    """Infer column positions from the right edges of readable figures."""
    edges = sorted(f["right"] for line in lines for f in line["figures"] if not f["unreadable"])
    if not edges:
        return []
    bands = [[edges[0]]]
    for edge in edges[1:]:
        if edge - bands[-1][-1] <= 14:
            bands[-1].append(edge)
        else:
            bands.append([edge])
    bands.sort(key=len, reverse=True)
    chosen = sorted(bands[:expected], key=lambda b: sum(b) / len(b))
    return [sum(b) / len(b) for b in chosen]


def to_columns(line, centres):
    slots = [None] * len(centres)
    for figure in line["figures"]:
        index = min(range(len(centres)), key=lambda i: abs(centres[i] - figure["right"]))
        if abs(centres[index] - figure["right"]) <= COLUMN_TOLERANCE and slots[index] is None:
            slots[index] = to_number(figure["text"])
    return slots


def resolve_columns(lines):
    """Attach column-aligned values to every line, using each page's own layout.

    Column positions drift between pages, so centres inferred across the whole
    document misfile figures on any page that sets its table differently. Each
    page is measured on its own.
    """
    by_page = {}
    for line in lines:
        by_page.setdefault(line["page"], []).append(line)
    resolved = []
    for page in sorted(by_page):
        page_lines = by_page[page]
        centres = column_centres(page_lines)
        for line in page_lines:
            resolved.append(dict(line, columns=to_columns(line, centres) if centres else []))
    return resolved


def build_sections(lines):
    """Walk the document in order, closing each block at the total that names it.

    The tables nest two deep. An indented "Total <department>:" closes the leaf
    rows above it; a left-margin "TOTAL <fund>" closes the departments below it.
    A fund total therefore sums the department subtotals already closed, plus any
    leaf rows in its span that no department total covered. Summing leaves alone
    would double-count everything that has a subtotal.
    """
    sections = []
    header = None
    leaves = []      # rows under the current header, not yet closed by a total
    orphans = []     # rows whose header closed without printing a total
    subtotals = []   # department totals already closed inside this fund
    for line in lines:
        # A new statement ("REVENUE SUMMARY - ADOPTED BUDGET") starts a fresh
        # accounting context. Without this, rows from the preceding statement
        # leak into the first total of the next one.
        if STATEMENT_START.search(line["label"]):
            header, leaves, orphans, subtotals = None, [], [], []
            continue

        total_match = TOTAL_LINE.match(line["label"])
        if total_match and line["figures"]:
            grand = line["indent"] <= HEADER_MAX_X
            members = (subtotals + orphans + leaves) if grand else leaves
            sections.append({
                "name": total_match.group(1).strip(),
                "page": line["page"],
                "level": "fund" if grand else "department",
                "header": header["label"] if header else None,
                "printed": line["columns"],
                "rows": members,
                "coveredBySubtotals": len(subtotals) if grand else 0,
            })
            if grand:
                subtotals, orphans, leaves = [], [], []
            else:
                subtotals = subtotals + [line]
                leaves = []
            header = None
            continue

        if not line["figures"] and line["indent"] <= HEADER_MAX_X:
            # The previous header ended without a total of its own, so its rows
            # stay eligible for the enclosing fund total but must not be counted
            # toward the next department's.
            orphans = orphans + leaves
            header, leaves = line, []
            continue

        if line["figures"]:
            leaves.append(line)
    return sections


def reconcile(sections):
    results = []
    for section in sections:
        columns = [row["columns"] for row in section["rows"]]
        per_column = []
        # A cell is unreadable only when a figure was printed and could not be
        # decoded. An empty cell is not damage, and counting it as such would
        # overstate the problem.
        damaged = [sum(1 for f in row["figures"] if f["unreadable"]) for row in section["rows"]]
        width = max([len(section["printed"])] + [len(c) for c in columns] or [0])
        for index in range(width):
            printed = section["printed"][index] if index < len(section["printed"]) else None
            values = [c[index] for c in columns if index < len(c) and c[index] is not None]
            total = sum(values)
            # A sum missing an unreadable figure is incomplete, not wrong. Calling
            # it a mismatch would blame the parse for damage in the document.
            blocked = any(f["unreadable"] for row in section["rows"] for f in row["figures"])
            difference = None if printed is None else total - printed
            if printed is None:
                status = "no printed total"
            elif difference == 0:
                status = "exact"
            elif blocked:
                status = "incomplete: unreadable figures excluded"
            else:
                status = "mismatch"
            per_column.append({
                "column": index,
                "printed": printed,
                "summed": total,
                "difference": difference,
                "status": status,
                "rowsSummed": len(values),
            })
        results.append({
            "name": section["name"],
            "page": section["page"],
            "level": section["level"],
            "header": section["header"],
            "rowCount": len(section["rows"]),
            "coveredBySubtotals": section["coveredBySubtotals"],
            "unreadableFigures": sum(damaged),
            "columns": per_column,
        })
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", default="work/adopted.pdf")
    parser.add_argument("--first-page", type=int, default=50)
    parser.add_argument("--last-page", type=int, default=76)
    parser.add_argument("--output", default="data/pdf_detail.json")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise SystemExit(str(pdf_path) + " not found.")
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    all_lines = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        last = min(args.last_page, len(pdf.pages))
        for index in range(args.first_page - 1, last):
            all_lines += merge_wrapped_labels(read_lines(pdf.pages[index], index + 1))

    all_lines = resolve_columns(all_lines)
    sections = build_sections(all_lines)
    report = reconcile(sections)

    exact = sum(1 for s in report for c in s["columns"] if c["status"] == "exact")
    mismatched = sum(1 for s in report for c in s["columns"] if c["status"] == "mismatch")
    incomplete = sum(1 for s in report for c in s["columns"] if c["status"].startswith("incomplete"))
    comparable = exact + mismatched
    unreadable = sum(s["unreadableFigures"] for s in report)

    payload = {
        "sourcePdfSha256": digest,
        "pageRange": [args.first_page, args.last_page],
        "summary": {
            "sections": len(report),
            "sectionsClean": sum(1 for s in report
                                 if all(c["status"] in ("exact", "no printed total") for c in s["columns"])),
            "columnsExact": exact,
            "columnsMismatched": mismatched,
            "columnsIncomplete": incomplete,
            "reconciliationRate": round(exact / comparable, 4) if comparable else None,
            "unreadableFigures": unreadable,
        },
        "sections": report,
    }
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"]))


if __name__ == "__main__":
    main()
