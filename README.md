# Syracuse Budget Explorer

A resident-facing view of the City of Syracuse FY2026–27 adopted budget.

The site answers four questions:

- Where does the money come from?
- Where does it go?
- What changed?
- Why did it change?

## Run locally

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

## Refresh the data

The reusable ingestion path is:

```text
budget.xlsx → scripts/ingest_budget.py → data/budget.json → website
```

Run the parser with the latest City Auditor workbook:

```bash
python3 scripts/ingest_budget.py \
  --workbook /path/to/2026-city-budget-workbook.xlsx \
  --output data/budget.json
```

The parser reads account history from the workbook. It applies the final FY27 amendments from the adopted budget PDF. Formal adopted fund totals are kept as a separate, reconciled layer because the Auditor notes that workbook figures can differ from the formal budget.

The current source links are stored in `data/budget.json` and point to the official Syracuse budget page, adopted PDF, Auditor workbook, and Open Data Portal.

## Deploy

This is a standard React/Vinext site. It does not require ChatGPT Sites, a database, or an API key.

For Vercel:

1. Import the GitHub repository.
2. Keep the build command as `npm run build`.
3. Set the output directory to `.output` if Vercel asks for one.
4. Deploy.

The site is also suitable for a City-managed host. The UI reads the normalized JSON at build time, so the City can replace the source files and rerun the parser without changing the page structure.
