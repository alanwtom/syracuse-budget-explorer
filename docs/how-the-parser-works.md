# How the parser works

`scripts/extract_pdf_detail.py` reads the tables in a Syracuse adopted budget book (PDF).

## The idea

Every table in the budget book ends in a total the book prints itself. The parser reads the lines,
adds them up, and compares the sum with that printed total. If they match, the table was read
correctly. If they don't, the table is reported as a mismatch with its page number. A mismatch is
never quietly fixed.

Two rules are never broken:

- A figure that can't be read is left out and marked unreadable. It is never guessed.
- A total is only called a match when the arithmetic actually holds.

## What it handles

Each of these was found because a total failed to add up.

**Finding the tables**
- The tables start on a different page every year, so they are found by their headings
  ("REVENUE SUMMARY", "EXPENDITURE SUMMARY") rather than by page number.
- The tax cap and tax limit pages are treated as separate schedules.

**Reading a line**
- Words on the same line are put in left-to-right order, even when their heights differ slightly.
- A gap wider than 1.5pt separates two words, because some pages set text so tightly that the usual
  3pt rule runs whole labels together.
- Six-digit account codes are separated from the amounts.
- Page numbers, the "Fiscal Year Ending" heading, and column rules (`===`, `___`) are ignored.
- Percentages are kept out of labels.
- Numbers split into touching pieces (`1` + `36,270,267`) are rejoined, and so are negatives
  (`(` + `5,755,000)`).
- A dash in an amount column means zero.
- A dollar sign before a number is allowed.

**Finding the columns**
- Column positions are measured on each page separately, because they move between pages.
- A stray number inside a label (such as "207" in "Legal Costs 207A") is not treated as a column.

**Grouping lines into tables**
- Totals close the block above them. "Subtotal" counts as a total.
- Where indentation shows the nesting, it is used. Where it doesn't, as on the revenue pages
  where every heading and total sits at the same margin, a total closes the heading with the same
  name. For example, "TOTAL DEPARTMENTAL INCOME" closes "Departmental Income". Names are compared
  loosely, so `&` matches `AND`, plurals match singulars, and an extra first word is allowed.
- A sub-heading such as "Special Objects of Expense" ends the block above it.
- A table can continue onto the next page.
- A label printed on its own line, with its figures on the line below, is handled. Where that can't
  be told apart from a wrapped label, the parser reads the page both ways and keeps the reading
  where more totals add up.
- A total printed with no label, or under the wrong label, is recognised because it equals every
  line above it in every column. It is counted once and is not itself reported as a match.

**Totals that are formulas, not sums**

These appear on the tax cap and tax limit pages. Each is checked against its own formula and no
other:

- the line above multiplied by a growth factor
- a running total
- a subtraction printed as a negative
- a total printed one column to the right of its lines
- lines added and taken away, where the sign isn't printed. At most four lines, and one set of
  signs has to work in every year column at once.

A wrong figure still fails. There are tests for that.

**A "$ Difference" column printed without signs** (2024-25) is checked line by line. Each difference
has to match its two years, within $1 of rounding.

## Results

| Budget book | Tables found | Tables that add up | Totals matching | Unreadable figures |
| --- | --- | --- | --- | --- |
| 2022-23 | 97 | 80 | 94.4% | 0 |
| 2023-24 | 106 | 86 | 93.3% | 0 |
| 2024-25 | 99 | 86 | 94.9% | 0 |
| 2025-26 | 75 | 45 | 93.3% | 95 |
| 2026-27 | 53 | 43 | 96.1% | 21 |

"Totals matching" counts each year column of each table separately.

## Mistakes in the budget books

Every difference over $3 was traced. For actual spending, figures were also checked against the
City Auditor's spreadsheet, which records actual spending from 2021 to 2025 line by line. All of
these mistakes are in the books.

| Book | Page | Mistake |
| --- | --- | --- |
| 2026-27 | 71 | A Water Fund subtotal for 2025 spending is $47,594 less than its lines. |
| 2025-26 | 74 | Sewer "Bad Debt Expense" is printed as $14,933. The total needs −$14,933. |
| 2024-25 | 56 | State Highway Aid is printed as $351,286. The book's total and the Auditor both say $375,476. |
| 2024-25 | 38–39 | The Equity Compliance division ($145,415) is printed under Neighborhood & Business Development but counted in Executive's total. |
| 2024-25 | 68 | The 2023 special objects total is $9,708 higher than its lines, which match the Auditor. |
| 2023-24 | 27, 56 | Service Kill Fees ($40,000) is missing from the Finance table but counted in its total. The 2022-23 book lists it. |
| 2023-24 | 57 | Code Enforcement's 2022 revenue total is $11,307 higher than its lines, which match the Auditor. |
| 2023-24 | 71 | "Police General Services" is printed as $619. The total needs −$619. |
| 2023-24 | 59 | Public Works revenue for 2022 includes $125 that is on no line. |
| 2022-23 | 27 | Sale of Tax Property ($15,123) is missing from the Finance table but counted in its total. The 2023-24 book lists it. |
| 2022-23 | 57 | Public Works revenue totals include $111 and $125 that are on no line. |
| 2022-23 | 75 | Downtown "Transportation" is printed as $247. The total needs −$247. |

The rest are $1 to $3 of rounding: 14, 15, 9, 8 and 6 tables, from 2022-23 to 2026-27.

When a total is short by exactly twice one of its lines, the report notes that the line probably
lost its minus sign. Page numbers are the PDF's own page numbers, which can differ from the
numbers printed in the book.

## How the site uses it

- **Confirmed lines.** A spreadsheet line is marked "FY27 adopted" when the budget book prints the
  same amount, in a table that adds up. Lines are matched on fund and account code together,
  because the same code can appear in more than one fund. 151 lines match, and none conflict.
- **Mistakes shown to residents** come from `data/book_findings.json`. The validator checks each one
  against its book's report. If a mistake stops showing up, the build fails, so the site can't
  keep showing a claim that no longer holds.

## Limits

- The rules were found in these five books. A future book may lay a table out differently. If so,
  its totals will stop adding up and it will show up as a mismatch, not as a wrong number.
- Only the 2026-27 book feeds the site's numbers. The earlier books are used for finding mistakes.

The exact PDFs the parser read are archived in the
[budget-books release](https://github.com/alanwtom/syracuse-budget-explorer/releases/tag/budget-books).
Each file's fingerprint matches the one recorded in its report.

Notes comparing the spreadsheet with the budget book's fund totals are in
[reconciliation.md](reconciliation.md).
