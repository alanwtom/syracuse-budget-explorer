# Syracuse Budget Explorer

[![CI](https://github.com/alanwtom/syracuse-budget-explorer/actions/workflows/ci.yml/badge.svg)](https://github.com/alanwtom/syracuse-budget-explorer/actions/workflows/ci.yml)

A plain-language guide to the City of Syracuse's adopted budget for July 2026 to June 2027. It
shows where the money comes from, where it goes, what changed, and where each number comes from.

**Live site: <https://syracuse-budget-explorer-alans-project.vercel.app>**

An independent project by Alan Tom. Not affiliated with or endorsed by the City of Syracuse.

## What you can do

- See the six City funds and the total City budget.
- See where the money comes from and where it goes.
- See the biggest changes from last year.
- Search any of 916 budget lines and see its history back to 2021.
- Open any line to see which official document it comes from.

## Where the numbers come from

Two official City documents:

- **The adopted budget book** ([PDF](https://www.syr.gov/files/sharedassets/public/v/3/departments/budget/documents/budget-documents/08-12-fy27-final-adopted-budget.pdf)). The official adopted figures.
- **The City Auditor's budget spreadsheet** ([XLSX](https://www.syr.gov/files/content/public/v/94/departments/auditor-office/2026-city-budget-workbook.xlsx)). Each line's history, and the proposed budget.

The spreadsheet has more detail, but it is not the official budget, and the Auditor notes it can
differ from the budget book. So the site checks it against the book:

- The totals for all six City funds match the budget book.
- 151 lines match the budget book exactly. The site labels these "FY27 adopted".
- Every other line is labelled "FY27 proposed", with any final changes the book lists applied. The
  site never calls a line adopted unless the book prints that amount.

## Reading the budget book

The budget book is a PDF, so a program reads its tables (`scripts/extract_pdf_detail.py`). It does
not trust what it reads. It adds up every table and compares the result with the total the book
prints. A table that doesn't add up is reported, never quietly fixed.

It has been run on the last five budget books:

| Budget book | Tables found | Tables that add up | Totals matching |
| --- | --- | --- | --- |
| 2022-23 | 97 | 80 | 94.4% |
| 2023-24 | 106 | 86 | 93.3% |
| 2024-25 | 99 | 86 | 94.9% |
| 2025-26 | 75 | 45 | 93.3% |
| 2026-27 | 53 | 43 | 96.1% |

Every remaining difference was traced and is in the books themselves, not in how they are read.
Most are $1 to $3 of rounding. Twelve are real mistakes, such as a minus sign left off, a line left
out of a table but still counted in its total, or a wrong number on a line. The site lists all
twelve for residents.

Some figures in the 2025-26 and 2026-27 PDFs are set in a broken font and cannot be read (95 and
21 figures). They are marked unreadable and left out. They are never guessed.

How the parser works, and the full list of mistakes: [docs/how-the-parser-works.md](docs/how-the-parser-works.md).

## Limits

- This is not an audit.
- Lines the budget book does not confirm are proposals with final changes applied, not adopted
  amounts.
- The final amendments and the summary text are copied by hand from the budget book.
- The site has not yet been tested with residents. A plan for doing so is in
  [docs/usability-test-protocol.md](docs/usability-test-protocol.md).

## Run it

Needs Node 22.13 or later.

```sh
npm ci
npm run dev
```

Then open <http://localhost:3000>. No database or API keys are needed.

## Update the data

Needs Python 3.12. The PDF and spreadsheet are not stored in this repository; download them from
the City's site first.

```sh
python -m pip install -r scripts/requirements.txt
python scripts/extract_pdf_totals.py --pdf adopted.pdf
python scripts/extract_pdf_detail.py --pdf adopted.pdf
python scripts/ingest_budget.py --workbook budget.xlsx --output data/budget.json
python scripts/validate_budget.py
npm test
```

For a new budget year, also update the fund totals, amendments and year labels written into
`scripts/ingest_budget.py`. `extract_pdf_totals.py` checks the fund totals against the PDF.

## Checks

- `npm test` runs 81 tests.
- `python scripts/validate_budget.py` runs 21 checks on the data and fails if any breaks.
- GitHub Actions runs both, plus lint, a typecheck and a full build, on every push and pull
  request.

## Deploy

The site runs on Vercel:

```sh
npm run build
npx vercel deploy --prebuilt --prod
```

A GitHub workflow deploys automatically after CI passes, once a `VERCEL_TOKEN` repository secret
is added.

## Files

| Path | What it is |
| --- | --- |
| `app/page.tsx` | The site |
| `data/budget.json` | The data the site shows |
| `data/pdf_detail.json` | What the parser found in the 2026-27 budget book |
| `data/earlier_books/` | Totals the parser found in the four earlier books |
| `data/book_findings.json` | The budget-book mistakes shown on the site |
| `scripts/` | The parser, the data build and the checks |
| `docs/` | How the parser works, source notes, and the usability test plan |

## Credits

Built by Alan Tom with AI coding assistants (Codex and Claude).
