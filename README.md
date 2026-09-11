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

## Evidence and limits

This is a portfolio prototype, not an audited financial reporting system. There are 916 records in the current export. Formal summary values and amendment definitions are manually transcribed from the cited budget PDF; the parser does not automatically extract or verify the PDF. Account detail has not been fully reconciled to formal totals. Residuals may reflect source differences, grouping or parser issues and require source review. The interface reports these limits.

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
