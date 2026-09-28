# Financial Statement Automation System

[Live site](https://financial-statement-automation-syst.vercel.app/) · [![CI](https://github.com/Arpanbaniya/Financial-Statement-Automation-System/actions/workflows/ci.yml/badge.svg)](https://github.com/Arpanbaniya/Financial-Statement-Automation-System/actions/workflows/ci.yml)

Upload a trial balance as CSV or Excel, review the account categories, and generate an income statement and balance sheet. Add opening balances and a cash movement schedule to generate a reconciled cash flow statement. You can also extract and analyze existing PDF, Excel, and CSV statements.

## What it does

- Private accounts, uploads, and document deletion
- Debit/credit checks, account mapping, and retained earnings reconciliation
- Financial charts, ratios, working capital, and Excel reports with source schedules
- Groq explanations with an automatic deterministic fallback

Next.js is the interface, FastAPI handles document processing and reports, and Supabase stores the files and data. Uploads go directly from the browser to private Storage. The server checks ownership before processing or deletion.

## Run locally

Use Python 3.12, Node.js 24, and pnpm 11. Copy `.env.example` to `.env.local` and fill in your own Supabase project values. Apply the SQL migrations in `supabase/migrations` before using uploads.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
pnpm install
```

Run `pnpm dev` for the site and `python -m uvicorn api.index:app --reload --port 8000` in a second terminal for its API. On Vercel, the Python API is deployed with the site.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

Start with **Generate statements** in the dashboard. The CSV template lists the supported columns. Use a complete adjusted pre-closing trial balance for income generation; a post-closing trial balance provides only the balance sheet. Convert Excel formulas to values before uploading. Cash flow stays unavailable when the supporting data does not reconcile.

This MVP produces general-purpose reports, not jurisdiction-specific statutory filings. Scanned PDFs need OCR before extraction.

[Interview notes](docs/interview-prep.txt) cover the accounting, analysis, data, security, and AI choices.

MIT licensed.
