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
import itertools
import json
import re
from pathlib import Path

import pdfplumber

# Digits lost to the broken subset-font encoding.
UNREADABLE = re.compile(r"[ç-ô]")
# 2024-25 prints the full valuations with a dollar sign: "$5,296,329,457".
NUMERIC = re.compile(r"^\(?-?\$?[\d,ç-ô]+\)?$")
# A multiplier such as a growth factor ("1.0066"). It scales a figure; it is
# never an amount to be added.
FACTOR = re.compile(r"^\d*\.\d+$")
# A percentage, as printed in the "% change" column of the comparison
# summaries. Left in a label it breaks the match between "TOTAL DEPARTMENTAL:
# 4.6%" and the "Departmental Operating Expenditures" heading it closes.
PERCENT = re.compile(r"^\(?-?[\d,]*\.?\d+%\)?$")
# A dash standing in an amount column means nothing was budgeted.
PLACEHOLDER = re.compile(r"^[-–]$")
# A page number: a short bare integer standing alone on its line.
PAGE_NUMBER = re.compile(r"^\d{1,3}$")
# The tables print rules between columns as runs of "=" or "_". They carry no
# meaning and must not survive into a label, or a total line stops looking like one.
SEPARATOR = re.compile(r"^[=_\-–—]+$")
# The page heading carries the fiscal year ("Fiscal Year Ending June 30, 2027"),
# which otherwise reads as a row with a figure of 2,027.
PAGE_HEADING = re.compile(r"Fiscal\s+Year\s+Ending", re.I)
# Six bare digits leading a row identify the account.
ACCOUNT_CODE = re.compile(r"^\d{6}$")
# Left-margin headings that name the fund a row belongs to. "Assessment" alone
# is also a General Fund department, so only a special assessment district counts.
FUND_HEADER = re.compile(r"\bFUND\b|\bSPECIAL\s+ASSESSMENT\b", re.I)
# "Total <name>" names its block; a bare "Subtotal" closes one without naming it.
# Both end a block, and treating a subtotal as an ordinary row double-counts every
# figure above it.
TOTAL_LINE = re.compile(r"^\s*(?:TOTAL\s+(?P<named>.+?)|(?P<bare>SUB\s*-?\s*TOTAL))\s*$", re.I)
# Each statement restarts the hierarchy; rows never carry across one.
# The tax cap and tax limit schedules follow the expenditure tables but share
# nothing with them; each starts afresh.
TAX_LIMIT = re.compile(r"CONSTITUTIONAL\s+TAX\s+LIMIT", re.I)
STATEMENT_START = re.compile(
    r"(REVENUE|EXPENDITURE)\s+SUMMARY|PROPERTY\s+TAX\s+CAP\s+CALCULATION|CONSTITUTIONAL\s+TAX\s+LIMIT", re.I)

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
    if UNREADABLE.search(text) or FACTOR.match(text) or PERCENT.match(text):
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


def join_split_figures(line):
    """Rejoin a figure the PDF set in two touching pieces.

    The tax cap worksheet prints $136,270,267 as "1" and "36,270,267" with no
    gap at all between them, and a negative as "(" and "5,755,000)". Read apart,
    the leading digit becomes a figure of its own and the amount loses a hundred
    million dollars, or its sign. Columns sit tens of points apart, so pieces
    that touch are one figure.
    """
    joined = []
    for word in line:
        previous = joined[-1] if joined else None
        if (
            previous is not None
            and word["x0"] - previous["x1"] <= 0.5
            and re.fullmatch(r"\(?\d*", previous["text"])
            and re.match(r"[\d.,]", word["text"])
        ):
            joined[-1] = dict(previous, text=previous["text"] + word["text"], x1=word["x1"])
            continue
        joined.append(word)
    return joined


def read_lines(page, page_number):
    parsed = []
    for line in group_into_lines(page):
        line = join_split_figures(line)
        # A dash with no words to its right is an empty amount, not a rule or a
        # hyphen. Dropping it would leave the row looking like a heading.
        line = [
            dict(w, text="0") if PLACEHOLDER.match(w["text"])
            and not any(any(c.isalpha() for c in o["text"]) for o in line if o["x0"] > w["x0"])
            else w
            for w in line
        ]
        kept = [w for w in line if not SEPARATOR.match(w["text"])]

        # An account code is six bare digits at the head of the row. Printed
        # amounts in these tables always carry thousands separators, so a
        # comma-less six-digit token in the leftmost position is a code and not
        # a figure. Left unclaimed it is read as an amount and corrupts the sum.
        code = None
        if len(kept) > 1 and ACCOUNT_CODE.match(kept[0]["text"]):
            code = kept[0]["text"]
            kept = kept[1:]

        figures = [w for w in kept if NUMERIC.match(w["text"]) or FACTOR.match(w["text"])
                   or PERCENT.match(w["text"])]
        label_words = [w for w in kept if w not in figures]
        label = " ".join(w["text"] for w in label_words).strip().rstrip(":").strip()
        if not label and not figures:
            continue
        if PAGE_HEADING.search(label):
            continue
        if not label and len(figures) == 1 and PAGE_NUMBER.match(figures[0]["text"]):
            # Printed on the left on even pages, a page number becomes the first
            # column and pushes every figure on the page one column right.
            continue
        parsed.append({
            "page": page_number,
            "code": code,
            "label": label,
            "indent": round(min((w["x0"] for w in label_words), default=0.0), 1),
            "figures": [
                {"text": w["text"], "right": round(w["x1"], 1),
                 "unreadable": bool(UNREADABLE.search(w["text"])),
                 "factor": float(w["text"]) if FACTOR.match(w["text"]) else None,
                 "percent": bool(PERCENT.match(w["text"]))}
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
    edges = sorted(f["right"] for line in lines for f in line["figures"]
                   if not f["unreadable"] and not f.get("percent"))
    if not edges:
        return []
    bands = [[edges[0]]]
    for edge in edges[1:]:
        if edge - bands[-1][-1] <= 14:
            bands[-1].append(edge)
        else:
            bands.append([edge])
    bands.sort(key=len, reverse=True)
    # A number inside a label ("Legal Costs 207A") forms a band of its own. Taken
    # for a column it shifts every figure on the page one column over, so a band
    # far smaller than the page's real columns is not a column.
    # Only a well-filled page can tell a stray number from a sparse column: on a
    # short schedule a total carried into its own column may be the only figure
    # there.
    floor = max(2, len(bands[0]) // 4) if len(bands[0]) >= 8 else 1
    bands = [b for b in bands if len(b) >= floor] or bands[:1]
    chosen = sorted(bands[:expected], key=lambda b: sum(b) / len(b))
    return [sum(b) / len(b) for b in chosen]


def to_columns(line, centres):
    slots = [None] * len(centres)
    for figure in line["figures"]:
        index = min(range(len(centres)), key=lambda i: abs(centres[i] - figure["right"]))
        if abs(centres[index] - figure["right"]) <= COLUMN_TOLERANCE and slots[index] is None:
            slots[index] = to_number(figure["text"])
    return slots


def to_factor_columns(line, centres):
    slots = [None] * len(centres)
    for figure in line["figures"]:
        if figure.get("factor") is None:
            continue
        index = min(range(len(centres)), key=lambda i: abs(centres[i] - figure["right"]))
        if abs(centres[index] - figure["right"]) <= COLUMN_TOLERANCE and slots[index] is None:
            slots[index] = figure["factor"]
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
            resolved.append(dict(
                line,
                columns=to_columns(line, centres) if centres else [],
                factors=to_factor_columns(line, centres) if centres else [],
            ))
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
            if not exact and (
                name.startswith(heading + " ") or heading.startswith(name + " ")
                # "Cash Capital Appropriations & Debt Service" closes at "TOTAL
                # CAPITAL APPROPRIATION AND DEBT SERVICE": the same name, less
                # its first word.
                or heading.endswith(" " + name) or name.endswith(" " + heading)
            ):
                return index
    # Naming no open heading, it closes the innermost block. Reaching further
    # back, to everything opened since the previous total, was tried and cost
    # the 2023-24 budget five points.
    return len(blocks) - 1


def _totals(line, rows):
    """Whether a line equals the sum of these rows in every column it fills.

    A difference column printed without signs cannot be summed; there it is
    enough that the line's difference matches its own two years, as it would
    for any row of that table.
    """
    columns = line["columns"]
    compared = 0
    for index, value in enumerate(columns):
        if value is None:
            continue
        total = sum(r["columns"][index] for r in rows
                    if index < len(r["columns"]) and r["columns"][index] is not None)
        if total != value:
            unsigned = (index == 2 and columns[0] is not None and columns[1] is not None
                        and abs(abs(columns[1] - columns[0]) - abs(value)) <= 1)
            if not unsigned:
                return False
            continue
        compared += 1
    return compared >= 2


def _carried_total(line, rows):
    """Whether a one-figure line totals rows printed in another single column."""
    filled = [i for i, v in enumerate(line["columns"]) if v is not None]
    if len(filled) != 1:
        return False
    own = filled[0]
    used = {i for r in rows for i, v in enumerate(r["columns"]) if v is not None}
    if len(used) != 1 or own in used:
        return False
    other = used.pop()
    return sum(r["columns"][other] for r in rows) == line["columns"][own]


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
    opened_since = 1  # first block opened after the last total that closed blocks
    leaves = []      # rows under the current header, not yet closed by a total
    orphans = []     # rows whose header closed without printing a total
    subtotals = []   # department totals already closed inside this fund
    # Sub-headings inside a fund since the last department total, with their rows.
    # "Total Exclusions" closes both "Net Debt Exclusions" and "Net Capital
    # Exclusions", so a total can name more than the block directly above it.
    sub_blocks = []

    def flush():
        nonlocal leaves, orphans, subtotals, sub_blocks
        blocks[-1]["members"].extend(subtotals + orphans + leaves)
        leaves, orphans, subtotals, sub_blocks = [], [], [], []

    def close_department(line, name, members):
        nonlocal leaves, subtotals, sub_blocks
        sections.append({
            "name": name,
            "page": line["page"],
            "level": "department",
            "header": header["label"] if header else None,
            "fund": fund,
            "printed": line["columns"],
            "rows": members,
            "coveredBySubtotals": sum(1 for m in members if m.get("closesBlock")),
        })
        subtotals = absorb_rolled_up_subtotals(subtotals, line) + [dict(line, closesBlock=True)]
        leaves, sub_blocks = [], []

    for line in lines:
        heading = STATEMENT_START.search(line["label"])
        if heading:
            kind = " ".join((heading.group(1) or heading.group(0)).upper().split())
            if kind != statement:
                # Revenue and expenditure statements never share a block.
                statement = kind
                blocks = [{"name": None, "members": []}]
                opened_since = 1
                leaves, orphans, subtotals, sub_blocks = [], [], [], []
            # Otherwise the heading is just repeating at the top of a new page. A
            # page break is not a boundary in the table: "Total Public Works" can
            # sit on the page after its divisions, so the rows waiting for it
            # carry over untouched.
            continue

        total_match = TOTAL_LINE.match(line["label"])
        if total_match and line["figures"]:
            name = (total_match.group("named") or total_match.group("bare")).strip()
            grand = line["indent"] <= HEADER_MAX_X
            if not grand:
                members = leaves
                wanted = _block_name(name) if total_match.group("named") else None
                named_run = 0
                while wanted and len(blocks) - named_run > 1:
                    block_name = blocks[-1 - named_run]["name"] or ""
                    if block_name == wanted or block_name.endswith(" " + wanted):
                        named_run += 1
                    else:
                        break
                if named_run > 1:
                    # "Total Exclusions" closes "Net Debt Exclusions" and "Net
                    # Capital Exclusions" where the schedule sets both headings
                    # at the margin.
                    flush()
                    members = [m for block in blocks[-named_run:] for m in block["members"]]
                    blocks = blocks[:-named_run]
                    opened_since = len(blocks)
                    close_department(line, name, members)
                    header = None
                    continue
                if wanted and len(blocks) > 1 and blocks[-1]["name"] == wanted and (orphans or subtotals):
                    # "Total Public Works" names the margin heading it sits under,
                    # and that department has divisions under sub-headings. It
                    # closes every one of them, not just the last.
                    members = subtotals + orphans + leaves
                    orphans, subtotals = [], []
                    close_department(line, name, members)
                    header = None
                    continue
                if wanted and sub_blocks:
                    sub_blocks[-1]["rows"] = leaves
                    named = []
                    for block in reversed(sub_blocks):
                        if block["name"] == wanted or block["name"].endswith(" " + wanted):
                            named.insert(0, block)
                        else:
                            break
                    if len(named) > 1:
                        members = [row for block in named for row in block["rows"]]
                        # Those rows now belong to this total, not to the fund
                        # total above it, which would otherwise count them twice.
                        taken = {id(row) for row in members}
                        orphans = [row for row in orphans if id(row) not in taken]
                close_department(line, name, members)
                header = None
                continue
            flush()
            index = _matching_block(blocks, _block_name(name))
            members = [m for block in blocks[index:] for m in block["members"]]
            blocks = blocks[:index] if index > 0 else [{"name": None, "members": []}]
            opened_since = len(blocks)
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
            blocks[-1]["members"].append(dict(line, closesBlock=True))
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
            if sub_blocks:
                sub_blocks[-1]["rows"] = leaves
            orphans = orphans + leaves
            leaves = []
            sub_blocks.append({"name": _block_name(line["label"]), "rows": []})
            continue

        if (line["figures"] and leaves and sub_blocks
                and _block_name(line["label"]) == sub_blocks[-1]["name"]):
            # A row repeating its block's heading, after the rows of that block,
            # is the block's total: the tax limit schedule closes "Tax Levy"
            # this way rather than with the word "Total".
            close_department(line, line["label"], leaves)
            continue

        if not line["label"] and len(line["figures"]) == 1:
            # The tax limit schedule of 2025-26 prints the Tax Levy and
            # Exclusions totals with no label, one column right of their rows.
            # Such a line closes what it totals, whether just the rows above it
            # or everything opened since the last total. Like any total
            # recognised only by its sum, it is not reported as verified.
            since = [m for block in blocks[opened_since:] for m in block["members"]] + subtotals + orphans + leaves
            closed = False
            for rows, reach in ((leaves, False), (since, True)):
                if len(rows) >= 2 and _carried_total(line, rows):
                    if reach:
                        blocks = blocks[:max(opened_since, 1)]
                        orphans, subtotals = [], []
                    leaves, sub_blocks = [], []
                    blocks[-1]["members"].append(dict(line, closesBlock=True))
                    opened_since = len(blocks)
                    closed = True
                    break
            if closed:
                continue

        if (len(line["figures"]) >= 2 and leaves and (not line["label"] or len(leaves) >= 2)
                and _totals(line, leaves)):
            # Also a labelled line equal to every row above it in its block, in
            # every column: where a block's labels print a line out of step, its
            # subtotal carries a neighbour's label.
            # The book sometimes prints a block's total with no label, as in the
            # Federal Aid block of 2023-24. Read as a row it counts the block
            # twice. It closes the block instead. It is not reported as a
            # verified section: matching its own rows is how it was recognised.
            subtotals = absorb_rolled_up_subtotals(subtotals, line) + [dict(line, closesBlock=True)]
            leaves, sub_blocks = [], []
            continue

        if line["figures"]:
            leaves.append(dict(line, fund=fund))
    return sections


def _worksheet_identity(section, index, printed, total, previous):
    """Check a total that is not a plain sum against the arithmetic it shows.

    The tax cap and tax limit schedules are worksheets. Some totals there are
    carried into a further column than their rows, some subtract, and some are
    a running figure: the line above scaled by a growth factor, or the line
    above plus what follows. Each is checked against that one identity only;
    a total that satisfies none of them stays a mismatch.
    """
    columns = [row["columns"] for row in section["rows"]]
    here = [c[index] for c in columns if index < len(c) and c[index] is not None]
    if not here:
        # Rows in one column, their total carried into the next.
        others = [
            j for j in range(max((len(c) for c in columns), default=0))
            if j != index
            and (j >= len(section["printed"]) or section["printed"][j] is None)
            and any(j < len(c) and c[j] is not None for c in columns)
        ]
        if len(others) == 1:
            carried = sum(c[others[0]] for c in columns if others[0] < len(c) and c[others[0]] is not None)
            if carried == printed:
                return "carried into the total column"
    if printed < 0 and -total == printed:
        return "subtracted"
    before = previous["printed"][index] if previous and index < len(previous["printed"]) else None
    if before is not None:
        factors = [row["factors"][index] for row in section["rows"]
                   if index < len(row.get("factors") or []) and row["factors"][index] is not None]
        if len(factors) == 1 and abs(round(before * factors[0]) - printed) <= 1:
            return "growth factor applied to the line above"
        if before + total == printed:
            return "running total"
    return None


def _difference_column(section, index, printed):
    """Check a "$ Difference" column by what it claims to be.

    The comparison summaries print this year, last year and the difference
    between them. The 2024-25 book prints that difference without its sign, so
    a cut of $4,324 reads "4,324" and the column cannot be checked by adding it
    up. It can be checked row by row: every row's difference must equal its two
    years subtracted, and the total's must equal the two totals subtracted.
    """
    if index != 2 or len(section["printed"]) < 3:
        return None
    old, new = section["printed"][0], section["printed"][1]
    # The difference is worked out from unrounded amounts, so it can sit a
    # dollar away from the two rounded years it is printed beside.
    if old is None or new is None or abs(abs(new - old) - abs(printed)) > 1:
        return None
    checked = 0
    for row in section["rows"]:
        values = row["columns"]
        if len(values) < 3 or None in values[:3]:
            continue
        if abs(abs(values[1] - values[0]) - abs(values[2])) > 1:
            return None
        checked += 1
    return "each row's difference matches its two years, within $1 of rounding" if checked >= 2 else None


def _signed_fit(section, previous):
    """Find the signs a worksheet block adds its lines with, if it has one.

    The tax cap schedule does not always print a sign. "Plus Available
    Carryover" is taken away from the subtractions it sits among, and a tort
    exclusion claimed last year is taken away from a running total. A block of
    at most four lines is accepted when a single choice of signs, with or
    without the line above it as a starting figure, reproduces the printed
    total in every year column at once. A wrong total would have to match by
    coincidence in two columns simultaneously.
    """
    rows = [r["columns"] for r in section["rows"] if any(v is not None for v in r["columns"])]
    columns = [i for i, v in enumerate(section["printed"]) if v is not None]
    if not 1 <= len(rows) <= 4 or len(columns) < 2:
        return None
    starts = [None]
    if previous is not None:
        starts.append(previous["printed"])
    for start in starts:
        for signs in itertools.product((1, -1), repeat=len(rows)):
            fits = True
            for i in columns:
                total = sum(sign * (row[i] if i < len(row) and row[i] is not None else 0)
                            for sign, row in zip(signs, rows))
                if start is not None:
                    if i >= len(start) or start[i] is None:
                        fits = False
                        break
                    total += start[i]
                if abs(total) != abs(section["printed"][i]):
                    fits = False
                    break
            if fits:
                if start is not None:
                    return "running total, with a line taken away" if -1 in signs else "running total"
                return "lines added and taken away" if -1 in signs else "subtracted"
    return None


def reconcile(sections):
    results = []
    previous = None   # the department total just above, on the same page
    for section in sections:
        if previous is not None and previous["page"] != section["page"]:
            previous = None
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
            method = None
            if printed is None:
                status = "no printed total"
            elif difference == 0:
                status = "exact"
            elif blocked:
                status = "incomplete: unreadable figures excluded"
            else:
                method = _difference_column(section, index, printed)
                if method is None and section["level"] == "department":
                    method = _worksheet_identity(section, index, printed, total, previous)
                if method is None and section["level"] == "department":
                    method = _signed_fit(section, previous)
                status = "exact" if method else "mismatch"
            hint = None
            if status == "mismatch" and difference and abs(difference) > 3:   # not rounding
                # A book that drops a line's minus sign leaves a total short by
                # exactly twice that line. It stays a mismatch, since the page
                # says what it says, but the likely cause is named.
                for row in section["rows"]:
                    value = row["columns"][index] if index < len(row["columns"]) else None
                    if value and difference == 2 * value:
                        hint = f"adds up if {row['label'] or 'an unlabelled line'} ({value:,}) is negative"
                        break
            per_column.append({
                "column": index,
                "printed": printed,
                "summed": total,
                "difference": difference,
                "status": status,
                "method": method,
                "hint": hint,
                "rowsSummed": len(values),
            })
        verified = bool([c for c in per_column if c["printed"] is not None]) and all(
            c["status"] == "exact" for c in per_column if c["printed"] is not None
        )
        previous = section if section["level"] == "department" else None
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
    texts = {}
    for index, page in enumerate(pdf.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        if STATEMENT_START.search(text):
            hits.append(index + 1)
            texts[index + 1] = text
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
    # The final total of a section often prints a page after its last heading,
    # but nothing follows the constitutional tax limit: it is the last schedule,
    # and reaching past it picks up unrelated departmental tables.
    last = longest[-1]
    if TAX_LIMIT.search(texts.get(last, "")):
        return longest[0], last
    return longest[0], min(last + 2, len(pdf.pages))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", default="work/adopted.pdf")
    parser.add_argument("--first-page", type=int, default=None,
                        help="override the detected first page")
    parser.add_argument("--last-page", type=int, default=None,
                        help="override the detected last page")
    parser.add_argument("--output", default="data/pdf_detail.json")
    parser.add_argument("--compact", action="store_true",
                        help="keep section totals only, dropping the line items")
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
    if args.compact:
        # Enough to check a finding against, without every line of the book.
        payload["sections"] = [{k: v for k, v in section.items() if k != "rows"} for section in report]
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"]))


if __name__ == "__main__":
    main()
