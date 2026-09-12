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
| Sections found | 29 |
| Sections reconciling on every column | 20 |
| Column totals matching exactly | 85 |
| Column totals disagreeing | 14 |
| Column totals incomplete (a figure could not be read) | 11 |
| Reconciliation rate | 85.9% |

The page range is found rather than configured: the tables are the longest run of pages
carrying a "REVENUE SUMMARY" or "EXPENDITURE SUMMARY" heading, ignoring the single mention on
the contents page. That section starts on a different page in every year.

Running the same parser over the five most recent adopted budgets:

| Budget | Pages found | Sections | Reconciling fully | Rate |
| --- | --- | --- | --- | --- |
| 2022-23 | 25-79 | 58 | 40 | 78.5% |
| 2023-24 | 25-83 | 60 | 32 | 69.7% |
| 2024-25 | 23-77 | 58 | 38 | 75.8% |
| 2025-26 | 38-77 | 28 | 14 | 66.0% |
| 2026-27 | 50-77 | 30 | 21 | 85.9% |

The parser runs on all five without modification and never silently produces a wrong figure:
a block that does not reconcile is reported as a mismatch. It is most accurate on 2026-27,
which it was developed against, so the earlier years carry more unexplained disagreements and
should be treated as unverified until those are examined.

Three parsing details matter for a future year's document. Column positions are measured per
page, because the tables do not set their columns identically throughout. Word spacing is split
at 1.5pt, because the revenue pages set text tightly enough that the default runs whole labels
together. Column rules printed as runs of `=` or `_` are discarded before a line is tested for
being a total.

Some figures are set in a subset font whose character map is wrong, so their digits arrive as
characters in U+00E7–U+00F4. There were 11 such figures. They are marked unreadable and left out
of sums; they are never guessed, and a sum missing one is reported as incomplete rather than as
a disagreement, because the damage is in the document and not in the parse.

The parser reproduces the $3 Public Works difference already recorded in the reconciliation
notes, this time from the PDF rather than the workbook, and surfaces a $1 difference in
Neighborhood & Business Development. The remaining disagreements are recorded in
`data/pdf_detail.json` and are not yet explained.

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

The demo is a prototype for reading the data, not a City service and not an audited financial
reporting system.

Official source links are recorded in `data/budget.json`. The application imports this normalized data at build time.
