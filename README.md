# Syracuse Budget Explorer

[![CI](https://github.com/alanwtom/syracuse-budget-explorer/actions/workflows/ci.yml/badge.svg)](https://github.com/alanwtom/syracuse-budget-explorer/actions/workflows/ci.yml)

**Live demo: <https://syracuse-budget-explorer-alans-project.vercel.app>**

An independent civic-data project by **Alan Tom**, built with AI assistance. Not affiliated with or endorsed by the City of Syracuse.

## The problem

Residents should be able to ask where public money goes and follow an answer back to the record. The official budget book and Auditor workbook offer different views: formal adopted totals in one, historical account detail and proposals in the other.

## What this project demonstrates

- A Python workbook ingestion path that retains sheet, row, account and department references.
- A React interface for comparing funds, finding large changes, searching accounts and examining history.
- Explicit source boundaries: formal adopted totals stay separate from workbook proposals and calculated amendment adjustments.
- Data checks that expose unresolved differences instead of silently certifying them.

The most important design decision was to preserve those distinctions. A workbook proposal is not automatically an adopted account amount. Where a final amendment maps to a workbook line, the interface labels the result **adjusted proposal**. An amendment without a matching line is labeled **amendment only**, not a full account total.

## A two-minute demonstration

1. Open Overview and explain why gross fund shares and the net City headline have different denominators.
2. Choose Explore lines and search `overtime`. Open Police Field Services – Sworn.
3. Compare the FY26 budget, FY26 estimate and FY27 workbook proposal. Explain why these are different measures; do not present a proposal as verified adopted spending.
4. Follow the workbook sheet and row reference. Open About this project to show checks and unresolved differences.
5. Use Copy view link to preserve filters. Opening a line also places its identifier in the URL.

## Verification findings

Source inspection exposed subtotal rows whose labels contained account codes, and unnumbered debt/transfer lines that the original parser omitted. The revised parser keeps numeric leaf rows and excludes their parent subtotals. Regression fixtures cover both cases. Water, Sewer and Sidewalk revenue and expense detail now match the transcribed formal totals; General Fund revenue matches, while expense detail retains a $3 difference. The General Fund residual traces to the Public Works stated total versus its detail. Crouse-Marshall has a documented scope difference. Downtown has both scope differences and conflicting workbook/PDF assessment figures. See [reconciliation notes](docs/reconciliation.md) for exact references.

## Reading the PDF

`scripts/extract_pdf_detail.py` parses the adopted budget's line-item tables directly from the
PDF. The tables nest two deep: a fund or category sits at the left margin, its departments are
indented, and each block closes with a total the document itself prints. Summing every numeric
row would double-count, so rows are grouped by indentation and each block is checked against
its own printed total.

That check is the accuracy measure, and it is reported rather than assumed:

| | |
| --- | --- |
| Sections found | 53 |
| Sections verified against their printed total | 43 |
| Column totals matching exactly | 174 |
| Column totals disagreeing | 7 |
| Column totals incomplete (a figure could not be read) | 4 |
| Column reconciliation rate | 96.1% |

The page range is found rather than configured: the tables are the longest run of pages
carrying a "REVENUE SUMMARY" or "EXPENDITURE SUMMARY" heading, ignoring the single mention on
the contents page. That section starts on a different page in every year.

Running the same parser over the five most recent adopted budgets:

| Budget | Pages found | Sections | Sections verified | Column rate |
| --- | --- | --- | --- | --- |
| 2022-23 | 25-79 | 85 | 59 | 81.4% |
| 2023-24 | 25-83 | 90 | 62 | 84.3% |
| 2024-25 | 23-77 | 87 | 62 | 84.0% |
| 2025-26 | 38-77 | 69 | 32 | 81.5% |
| 2026-27 | 50-77 | 53 | 43 | 96.1% |

A section counts as verified only when the document prints a total for it and every column of
that total matches the rows summed beneath it. Sections with nothing to check against are
counted separately and are currently zero, so the rate cannot be improved by finding fewer
things to verify.

The parser runs on all five without modification and never silently produces a wrong figure:
a block that does not reconcile is reported as a mismatch. It is most accurate on 2026-27,
which it was developed against, so the earlier years carry more unexplained disagreements and
should be treated as unverified until those are examined.

### What the PDF now contributes to the interface

The explorer's account history comes from the workbook, which the PDF does not carry. The PDF
supplies a second, authoritative reading of the adopted figures. Rows are matched on fund and
account code together, because a code such as 424010 appears in more than one fund, and only
rows from PDF sections that reconcile to their own printed totals are used.

151 account rows currently carry the same FY27 figure in both sources, and none disagree.
Opening such a row in the explorer shows which page of the budget book confirms it. A row
without a confirmation is not thereby wrong; the PDF simply does not print a reconciling figure
for it.

Three parsing details matter for a future year's document. Column positions are measured per
page, because the tables do not set their columns identically throughout. Word spacing is split
at 1.5pt, because the revenue pages set text tightly enough that the default runs whole labels
together. Column rules printed as runs of `=` or `_` are discarded before a line is tested for
being a total.

Some figures are set in a subset font whose character map is wrong, so their digits arrive as
characters in U+00E7–U+00F4. There are 21 such figures in the sections parsed. They are marked unreadable and left out
of sums; they are never guessed, and a sum missing one is reported as incomplete rather than as
a disagreement, because the damage is in the document and not in the parse.

Every remaining disagreement in the 2026-27 budget is in the budget book itself. In each case
every other column of the same rows matches exactly, so the rows are being read correctly and it
is the printed total that differs:

| Page | Section | Column | Difference |
| --- | --- | --- | --- |
| 50 | Real property tax items | FY25 actual | $1 |
| 54 | Departmental income | FY25 actual | $1 |
| 61 | Downtown special assessment revenue | FY25 actual | $1 |
| 65 | Neighborhood & Business Development | FY26 adopted | $1 |
| 66 | Public Works | FY27 adopted | $3 |
| 71 | Water fund special objects of expense | FY25 actual | $47,594 |
| 77 | Five-year full valuation | Taxable value | $1 |

The $3 Public Works difference is the one already recorded in the reconciliation notes from the
workbook; the parser found it again, independently, in the PDF. The Water fund figure is the only
one larger than rounding: the book prints a subtotal of $7,463,788 for rows that add up to
$7,511,382.

These differences are carried into the site data as `bookDifferences`, and the "Can you trust
these numbers?" summary tells residents how many there are, which are rounding, and where the
larger one is.

On the fund expense pages a grand total's label prints on its own baseline with its figures
underneath, while the figures beside the label belong to the block above. Read naively the Water
fund's total came out as $6,971,623, its capital block, instead of the $33,175,883 the budget
book prints. The figures are now swapped rather than discarded, and the displaced row stays as
the closing subtotal of its block, so Water and Municipal Sidewalk report their published
totals. A page number is also an unlabelled figure, so the repair only applies when the row
below carries a figure for every column the total does.

The capital and debt blocks compound this: a row's label sits alone with its figures printed
underneath, so every row from there to the end of the block is one line out of step. Read as
wrapped text, "Serial Bond Principal & Interest" was swallowed by the row below it and its
$5,826,623 handed to its neighbour.

A label-only line is either the tail of a wrapped label or a row awaiting its figures, and both
sit at the same indentation, so geometry cannot separate them. The document decides: each page
is read both ways and the reading under which more of that page's printed totals add up is the
one kept. Reading it wholesale in either direction was worse than reading it in neither, which
is what made the per-page choice necessary.

Two more faults sat on the Sidewalk and Sewer expense pages. A sub-heading such as "Special
Objects of Expense" is indented past the fund margin, so it was not treated as a boundary and
the operating line above it was counted again inside the next subtotal. And the page heading
"Fiscal Year Ending June 30, 2027" was being read as a row worth 2,027, which is exactly the
difference that had kept the Water and Sewer totals from matching.

Every fund's expense total now reconciles exactly.

On the revenue pages every heading and every total sits at the same left margin, so indentation
cannot show nesting: "Finance" and "Total Finance" line up exactly with "Departmental Income"
and "TOTAL DEPARTMENTAL INCOME". There the name does. Each margin heading opens a block, and a
margin total closes the block whose heading it names, after normalising the ampersand and plural
endings, since "Capital Appropriations & Debt Service" closes at "TOTAL CAPITAL APPROPRIATION
AND DEBT SERVICE".

The property tax cap and constitutional tax limit pages are worksheets rather than tables. Some
figures print in two touching pieces, so $136,270,267 reads as "1" and "36,270,267" and a
negative loses its sign; pieces with no gap between them are rejoined. Some totals there are not
sums at all: a subtotal scaled by a growth factor, a running total, a subtraction shown as a
negative, or rows in one column with their total carried into the next. Each such total is
checked against that one identity and no other. The identities hold in both year columns of
the 2025-26 and 2026-27 schedules, and a wrong figure still fails them.

## Evidence and limits

This is a portfolio prototype, not an audited financial reporting system. There are 916 records in the current export. The six formal fund totals and the inter-fund adjustment are read back out of the adopted PDF by `scripts/extract_pdf_totals.py` and checked against the exported values, so those figures are verified rather than trusted; a regression test confirms the check fails when a total is wrong. Amendment definitions and the narrative remain manually transcribed, and account-level PDF detail is not yet extracted. Account detail has not been fully reconciled to formal totals. Residuals may reflect source differences, grouping or parser issues and require source review. The interface reports these limits.

Project owner: Alan Tom. In this review pass, Alan requested a hiring-focused audit and directed the follow-up implementation. Codex assisted source inspection, parser and interface changes, regression tests, documentation and deployment preparation. This describes the observed collaboration; it does not claim that Alan manually wrote every line. This repository documents the resulting decisions, checks and limits; it does not claim resident adoption, measured time savings or production use. Mobile and keyboard smoke checks are not a full accessibility certification.

## Run locally

Requires Node 22.13+ and Python 3 with `openpyxl` for workbook ingestion.

```sh
npm ci
npm run dev
```

Open http://localhost:3000. There is no database or API key requirement.

## Refresh and validate

```sh
python -m pip install -r scripts/requirements.txt
python scripts/extract_pdf_totals.py --pdf /path/to/adopted.pdf --output data/pdf_totals.json
python scripts/ingest_budget.py --workbook /path/to/workbook.xlsx --output data/budget.json
python scripts/validate_budget.py
npm test
npm run lint
npx tsc --noEmit
npm run build
npm start
```

For a new fiscal year, update the manually maintained formal totals, amendment definitions, narrative, year keys and source metadata in the ingestion script as well as supplying a new workbook. Replacing the workbook alone is insufficient.

Continuous integration runs the regression tests, the validator, lint, the typecheck and the
production build on every push to `main` and on every pull request. A `check` fails the build;
a `review` does not, because an unresolved source difference is a finding to report rather than
a defect to fix.

The validator checks unique IDs, finite values, change arithmetic, amendment record coverage and formal-total arithmetic. It reports every fund's account-detail residual separately. `check` is a failing invariant; `review` is an unresolved reconciliation difference. Neither is proof that source documents are accurate.

## Deployment

The cross-platform build generates Vercel Build Output at `.vercel/output` via Nitro's Vercel
preset. The live demo above is deployed from that prebuilt output:

```sh
npm run build
npx vercel deploy --prebuilt --prod
```

A GitHub Actions workflow deploys automatically once CI passes on `main`, so the demo cannot
drift behind the repository the way it did when deploying was manual. It requires a
`VERCEL_TOKEN` repository secret; without one the job reports that it skipped rather than
failing. The project and organisation ids are already set as secrets.

The demo is a prototype for reading the data, not a City service and not an audited financial
reporting system.

Official source links are recorded in `data/budget.json`. The application imports this normalized data at build time.
