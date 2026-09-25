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
# The page heading carries the fiscal year ("Fiscal Year Ending June 30, 2027"),
# which otherwise reads as a row with a figure of 2,027.
PAGE_HEADING = re.compile(r"Fiscal\s+Year\s+Ending", re.I)
# Six bare digits leading a row identify the account.
ACCOUNT_CODE = re.compile(r"^\d{6}$")
# Left-margin headings that name the fund a row belongs to.
FUND_HEADER = re.compile(r"\b(FUND|ASSESSMENT)\b", re.I)
# "Total <name>" names its block; a bare "Subtotal" closes one without naming it.
# Both end a block, and treating a subtotal as an ordinary row double-counts every
# figure above it.
TOTAL_LINE = re.compile(r"^\s*(?:TOTAL\s+(?P<named>.+?)|(?P<bare>SUB\s*-?\s*TOTAL))\s*$", re.I)
# Each statement restarts the hierarchy; rows never carry across one.
STATEMENT_START = re.compile(r"(REVENUE|EXPENDITURE)\s+SUMMARY", re.I)

ROW_TOLERANCE = 2.6      # points; words within this share a baseline
COLUMN_TOLERANCE = 18.0  # points; how far a figure may sit from a column centre
HEADER_MAX_X = 100.0     # labels left of this open a section
# The revenue pages set text tightly enough that pdfplumber's default gap of 3pt
# runs whole labels together ("TOTALWATERFUNDREVENUE"). Anything from 0.8 to 2.0
# splits both page styles correctly without breaking digits apart.
WORD_TOLERANCE = 1.5
# Pages whose text layer is unreadable can split the tables into two blocks.
# Blocks closer than this many pages are treated as one section.
MAX_BLOCK_GAP = 20


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
    # Words sharing a line rarely share an exact baseline, so ordering the page
    # by top-then-x0 can interleave them and scramble a label ("Water Sale of",
    # "WATER FUND REVENUE: TOTAL"). Grouping has already decided which words form
    # a line; within one, only horizontal position means anything.
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def read_lines(page, page_number):
    parsed = []
    for line in group_into_lines(page):
        kept = [w for w in line if not SEPARATOR.match(w["text"])]

        # An account code is six bare digits at the head of the row. Printed
        # amounts in these tables always carry thousands separators, so a
        # comma-less six-digit token in the leftmost position is a code and not
        # a figure. Left unclaimed it is read as an amount and corrupts the sum.
        code = None
        if len(kept) > 1 and ACCOUNT_CODE.match(kept[0]["text"]):
            code = kept[0]["text"]
            kept = kept[1:]

        figures = [w for w in kept if NUMERIC.match(w["text"])]
        label_words = [w for w in kept if w not in figures]
        label = " ".join(w["text"] for w in label_words).strip().rstrip(":").strip()
        if not label and not figures:
            continue
        if PAGE_HEADING.search(label):
            continue
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


def join_wrapped_labels(lines):
    """Read a label-only line as the tail of a label that wrapped."""
    merged = []
    pending = []
    for line in lines:
        if not line["figures"] and line["indent"] > HEADER_MAX_X:
            pending.append(line)
            continue
        if pending:
            if line["figures"] and line["indent"] > HEADER_MAX_X:
                # A wrapped label continues at the row's own indentation. One
                # standing further left is a heading over the rows below it,
                # and joining it would erase the boundary it marks.
                wraps = [p for p in pending if abs(p["indent"] - line["indent"]) <= 1.5]
                for heading in (p for p in pending if p not in wraps):
                    merged.append(dict(heading, figures=[], code=None))
                if wraps:
                    line = dict(line, label=" ".join([p["label"] for p in wraps] + [line["label"]]).strip())
            else:
                for held in pending:
                    merged.append(dict(held, figures=[], code=None))
            pending = []
        merged.append(line)
    for held in pending:
        merged.append(dict(held, figures=[], code=None))
    return merged


def shift_figures_to_waiting_labels(lines):
    """Read a label-only line as a row whose figures print on the line below.

    The capital and debt blocks are set this way: a label sits alone, its figures
    print underneath, and the next label follows those figures. Every row from
    there to the end of the block is therefore one line out of step, including
    the block's subtotal and the fund total beneath it.

    Only a label at the indentation of the rows around it starts that shift; a
    label standing further left is the block's heading and never takes figures.
    Once started the shift carries through rows at any indentation, because the
    subtotal that closes the block is set further left than the rows above it.
    """
    merged = []
    candidate = None   # a label-only line that may own the figures below it
    waiting = None     # the label displaced by a shift already under way
    for line in lines:
        if not line["figures"] and line["indent"] > HEADER_MAX_X:
            if candidate is not None:
                merged.append(dict(candidate, figures=[], code=None))
            candidate = line
            continue

        if line["figures"]:
            if waiting is not None:
                merged.append(dict(waiting, figures=line["figures"]))
                waiting = dict(line, figures=[])
                continue
            if candidate is not None and abs(candidate["indent"] - line["indent"]) <= 1.5:
                merged.append(dict(candidate, figures=line["figures"]))
                candidate, waiting = None, dict(line, figures=[])
                continue

        if candidate is not None:
            merged.append(dict(candidate, figures=[], code=None))
            candidate = None
        merged.append(line)

    for held in (candidate, waiting):
        if held is not None:
            merged.append(dict(held, figures=[], code=None))
    return merged


def _exact_columns(lines):
    """How many printed totals the rows beneath them actually add up to.

    Scored through the same repairs the page will receive, or a reading whose
    benefit only appears after a later repair is judged on the wrong result.
    """
    report = reconcile(build_sections(resolve_columns(attach_split_totals(lines))))
    return sum(1 for s in report for c in s["columns"] if c["status"] == "exact")


def merge_wrapped_labels(lines):
    """Choose between the two readings of a label-only line, per page.

    A label-only line is either the tail of a wrapped label or a row whose
    figures print below it, and both sit at the same indentation, so geometry
    cannot tell them apart. The document can: whichever reading makes more of
    the page's printed totals add up is the one the page was set in.
    """
    wrapped = join_wrapped_labels(lines)
    shifted = shift_figures_to_waiting_labels(lines)
    if shifted == wrapped:
        return wrapped
    return shifted if _exact_columns(shifted) > _exact_columns(wrapped) else wrapped


def attach_split_totals(lines):
    """Repair a fund total whose figures print on the line below its label.

    On the fund expense pages the grand total's label sits on its own baseline
    and its figures print underneath, while the figures that share the label's
    baseline belong to the block above it. Read naively, the fund total takes the
    block's figures and the real total is left owned by nothing, to be summed
    into the next section as though it were an ordinary row.

    Both readings are geometrically plausible, so the document decides: the
    figures are swapped rather than discarded, and the displaced row stays as a
    member of the block. Only a fund-level total is repaired, and only when the
    row below carries no label of its own. Whether the repair was right is then
    settled by the same reconciliation every other section faces - if the swap is
    wrong, the block stops adding up and is reported as a mismatch.
    """
    out = []
    skip = False
    for index, line in enumerate(lines):
        if skip:
            skip = False
            continue
        following = lines[index + 1] if index + 1 < len(lines) else None
        if (
            TOTAL_LINE.match(line["label"])
            and line["indent"] <= HEADER_MAX_X
            and line["figures"]
            and following is not None
            and not following["label"]
            # A page number is also an unlabelled figure. A displaced total
            # carries a figure for every column the total line does.
            and len(following["figures"]) == len(line["figures"]) >= 2
        ):
            previous = out[-1] if out else None
            if (previous is not None and not previous["figures"]
                    and previous["label"] and previous["indent"] > HEADER_MAX_X):
                # A row label left waiting above the total owns these figures:
                # its figures printed on the total's baseline.
                out[-1] = dict(previous, figures=line["figures"])
            else:
                # Otherwise they close the block above, not an extra row inside
                # it; indented past the fund margin so they close that block
                # rather than the whole fund.
                out.append(dict(following, label="Subtotal", code=None,
                                indent=HEADER_MAX_X + 1, figures=line["figures"]))
            out.append(dict(line, figures=following["figures"], splitTotal=True))
            skip = True
            continue
        out.append(line)
    return out


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


def absorb_rolled_up_subtotals(subtotals, closing):
    """Drop subtotals that a later one already rolls up.

    These tables sometimes close several blocks and then print a combined figure
    for them before the fund total. Treating that combined figure as a sibling of
    the blocks it summarises counts them twice. If a trailing run of subtotals
    sums to the closing figure on every column both report, the closing figure
    supersedes them.
    """
    closing_values = closing["columns"]
    for start in range(len(subtotals)):
        run = subtotals[start:]
        if not run:
            continue
        matched = False
        for index, value in enumerate(closing_values):
            if value is None:
                continue
            total = 0
            seen = False
            for member in run:
                member_value = member["columns"][index] if index < len(member["columns"]) else None
                if member_value is not None:
                    total += member_value
                    seen = True
            if not seen:
                continue
            if abs(total - value) > 0.01:
                matched = False
                break
            matched = True
        if matched:
            return subtotals[:start]
    return subtotals


def _block_name(text):
    """Reduce a heading or total label to the words that name its block.

    A heading and its total are not always worded alike: "Capital
    Appropriations & Debt Service" closes at "TOTAL CAPITAL APPROPRIATION AND
    DEBT SERVICE". The ampersand and plural endings are normalised away.
    """
    text = re.sub(r"^\s*TOTAL\s+", "", text or "", flags=re.I)
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text)
    words = [w[:-1] if len(w) > 3 and w.endswith("S") and not w.endswith("SS") else w
             for w in text.upper().split()]
    return " ".join(words)


def _matching_block(blocks, name):
    """The innermost open block this total closes, by name.

    An exact name wins over a partial one: "TOTAL DEPARTMENTAL INCOME" closes
    "Departmental Income", and only failing that does "TOTAL GENERAL FUND
    REVENUE" close the "GENERAL FUND" heading it begins with. A total that
    names no open heading closes the innermost block.
    """
    for exact in (True, False):
        for index in range(len(blocks) - 1, 0, -1):
            heading = blocks[index]["name"]
            if not heading:
                continue
            if exact and heading == name:
                return index
            if not exact and (name.startswith(heading + " ") or heading.startswith(name + " ")):
                return index
    # Naming no open heading, it closes the innermost block. Reaching further
    # back, to everything opened since the previous total, was tried and cost
    # the 2023-24 budget five points.
    return len(blocks) - 1


def build_sections(lines):
    """Walk the document in order, closing each block at the total that names it.

    Two kinds of nesting occur. Within a fund, an indented "Total <department>"
    or a bare "Subtotal" closes the rows above it, and indentation is enough to
    tell the levels apart.

    At the left margin it is not. On the revenue pages every heading and every
    total sits at the same indent: "Finance" and "Total Finance" line up exactly
    with "Departmental Income" and "TOTAL DEPARTMENTAL INCOME". There the name
    is what shows the nesting, so each margin heading opens a block and a margin
    total closes the block its name matches. Blocks opened inside it and never
    closed on their own are folded into it, and the total then counts as one row
    of the block that encloses it.
    """
    sections = []
    header = None
    # Account codes repeat across funds: 424010 is Interest on Deposits in both
    # the General and the Water fund. A row is only identified by fund and code
    # together, so the enclosing fund has to travel with it.
    fund = None
    statement = None
    blocks = [{"name": None, "members": []}]
    leaves = []      # rows under the current header, not yet closed by a total
    orphans = []     # rows whose header closed without printing a total
    subtotals = []   # department totals already closed inside this fund

    def flush():
        nonlocal leaves, orphans, subtotals
        blocks[-1]["members"].extend(subtotals + orphans + leaves)
        leaves, orphans, subtotals = [], [], []

    for line in lines:
        heading = STATEMENT_START.search(line["label"])
        if heading:
            kind = heading.group(1).upper()
            if kind != statement:
                # Revenue and expenditure statements never share a block.
                statement = kind
                blocks = [{"name": None, "members": []}]
                leaves, orphans, subtotals = [], [], []
            else:
                # The heading repeats on every page of a statement. A block
                # carries over the page break; only the rows are handed up.
                flush()
            header = None
            continue

        total_match = TOTAL_LINE.match(line["label"])
        if total_match and line["figures"]:
            name = (total_match.group("named") or total_match.group("bare")).strip()
            grand = line["indent"] <= HEADER_MAX_X
            if grand:
                flush()
                index = _matching_block(blocks, _block_name(name))
                members = [m for block in blocks[index:] for m in block["members"]]
                blocks = blocks[:index] if index > 0 else [{"name": None, "members": []}]
            else:
                members = leaves
            sections.append({
                "name": name,
                "page": line["page"],
                "level": "fund" if grand else "department",
                "header": header["label"] if header else None,
                "fund": fund,
                "printed": line["columns"],
                "rows": members,
                "coveredBySubtotals": sum(1 for m in members if m.get("closesBlock")),
            })
            closed = dict(line, closesBlock=True)
            if grand:
                blocks[-1]["members"].append(closed)
            else:
                subtotals = absorb_rolled_up_subtotals(subtotals, line) + [closed]
                leaves = []
            header = None
            continue

        if not line["figures"] and line["indent"] <= HEADER_MAX_X:
            if FUND_HEADER.search(line["label"]):
                fund = line["label"].strip()
            flush()
            blocks.append({"name": _block_name(line["label"]), "members": []})
            header = line
            continue

        if not line["figures"] and line["label"]:
            # A sub-heading inside the fund ("Special Objects of Expense") ends
            # the block above it even though it is indented past the fund
            # margin. Without this, rows above it are counted again in the
            # subtotal of the block it opens.
            orphans = orphans + leaves
            leaves = []
            continue

        if line["figures"]:
            leaves.append(dict(line, fund=fund))
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
        verified = bool([c for c in per_column if c["printed"] is not None]) and all(
            c["status"] == "exact" for c in per_column if c["printed"] is not None
        )
        results.append({
            "name": section["name"],
            "page": section["page"],
            "level": section["level"],
            "header": section["header"],
            "rowCount": len(section["rows"]),
            "coveredBySubtotals": section["coveredBySubtotals"],
            "unreadableFigures": sum(damaged),
            "verified": verified,
            "fund": section.get("fund"),
            "columns": per_column,
            # The line items themselves, so the extraction can feed something
            # other than a reconciliation report. A row inherits its section's
            # verified flag: a figure is only trustworthy if the block it sits
            # in adds up to the total the document prints for it.
            "rows": [
                {
                    "code": row["code"],
                    "label": row["label"],
                    "fund": row.get("fund"),
                    "page": row["page"],
                    "values": row["columns"],
                    "unreadable": any(f["unreadable"] for f in row["figures"]),
                }
                for row in section["rows"]
            ],
        })
    return results


def detect_page_range(pdf):
    """Find the budget-summary tables without being told where they are.

    Each statement page carries a "REVENUE SUMMARY" or "EXPENDITURE SUMMARY"
    heading. The contents page mentions those words once in isolation, so the
    tables are the longest consecutive run of pages that carry them. The section
    starts at a different page in every fiscal year, so it has to be found rather
    than configured.
    """
    hits = []
    for index, page in enumerate(pdf.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        if STATEMENT_START.search(text):
            hits.append(index + 1)
    if not hits:
        return None
    runs = [[hits[0]]]
    for page_number in hits[1:]:
        if page_number - runs[-1][-1] <= 2:
            runs[-1].append(page_number)
        else:
            runs.append([page_number])

    # A lone hit is the contents page or a stray mention, not a table.
    blocks = [r for r in runs if len(r) > 1] or runs

    # Some years set a stretch of pages in a font that extracts as nothing
    # readable, splitting the tables into two blocks with a gap between them.
    # Blocks close together belong to the same section.
    merged = [blocks[0]]
    for block in blocks[1:]:
        if block[0] - merged[-1][-1] <= MAX_BLOCK_GAP:
            merged[-1] = merged[-1] + block
        else:
            merged.append(block)
    longest = max(merged, key=lambda b: b[-1] - b[0])
    # The final total of a section often prints a page after its last heading.
    return longest[0], min(longest[-1] + 2, len(pdf.pages))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", default="work/adopted.pdf")
    parser.add_argument("--first-page", type=int, default=None,
                        help="override the detected first page")
    parser.add_argument("--last-page", type=int, default=None,
                        help="override the detected last page")
    parser.add_argument("--output", default="data/pdf_detail.json")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise SystemExit(str(pdf_path) + " not found.")
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    all_lines = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        detected = detect_page_range(pdf)
        if detected is None and (args.first_page is None or args.last_page is None):
            raise SystemExit("No budget-summary pages found; pass --first-page and --last-page.")
        first = args.first_page or detected[0]
        last = min(args.last_page or detected[1], len(pdf.pages))
        args.first_page, args.last_page = first, last
        for index in range(first - 1, last):
            all_lines += attach_split_totals(
                merge_wrapped_labels(read_lines(pdf.pages[index], index + 1)))

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
            "sectionsVerified": sum(
                1 for s in report
                if [c for c in s["columns"] if c["printed"] is not None]
                and all(c["status"] == "exact" for c in s["columns"] if c["printed"] is not None)),
            "sectionsUncheckable": sum(
                1 for s in report if not [c for c in s["columns"] if c["printed"] is not None]),
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
