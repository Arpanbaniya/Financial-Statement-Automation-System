# Financial Statement Automation System

[Live site](https://financial-statement-automation-syst.vercel.app/) · [![CI](https://github.com/Arpanbaniya/Financial-Statement-Automation-System/actions/workflows/ci.yml/badge.svg)](https://github.com/Arpanbaniya/Financial-Statement-Automation-System/actions/workflows/ci.yml)

Upload a PDF, Excel workbook, or CSV statement. The app extracts source lines, maps known financial fields, checks the figures, and builds an Excel report. Unclear values go to a review queue. Original files stay private in Supabase Storage.

## What it does

- Private accounts, uploads, and document deletion
- Source-linked statements with currency, unit, and period checks
- Validation, ratios, working capital, cash flow, and Excel export
- Optional Groq explanations; financial calculations remain deterministic

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

This is a portfolio project, not investment advice. Use public or synthetic statements for the demo. Scanned PDFs may need OCR, and multi-column statements require choosing the correct amount column before processing.

[Interview notes](docs/interview-prep.txt) cover the accounting, analysis, data, security, and AI choices.

MIT licensed.
