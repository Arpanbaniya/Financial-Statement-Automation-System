# Financial Statement Automation System

Financial reports can be frustrating to analyze: figures are spread across PDFs and spreadsheets, labels vary, and a number is only useful if you know where it came from. I am building this project to turn those documents into organized, checked financial statements while keeping each figure tied to its source.

The goal is a workflow an analyst can inspect. If a line item is unclear or a statement does not balance, the system should show the issue for review instead of quietly making a guess.

## Where the project stands

This is an early foundation. The repository currently has a Next.js landing page, a FastAPI health endpoint, and the structure for the financial processing code. Document uploads, statement extraction, calculations, dashboards, and reports are still to come.

The planned workflow is:

1. Upload a financial statement in PDF, Excel, or CSV form.
2. Extract the statements and organize line items by company and reporting period.
3. Check totals, units, currencies, and accounting relationships.
4. Review uncertain mappings and keep a link to the source of each figure.
5. Explore ratios and trends, then export a workbook for further analysis.

## Run it locally

You will need Node.js 22 or 24, pnpm 11, and Python 3.12.

Start the web app:

```sh
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000).

Start the API in a second terminal. On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn api.index:app --reload --port 8000
```

On macOS or Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn api.index:app --reload --port 8000
```

The API responds at [http://localhost:8000/api/health](http://localhost:8000/api/health) with `{"status":"ok"}`. The web app and API run separately during local development.

## Checks

```sh
pnpm lint
pnpm typecheck
pnpm build
pnpm format:check
```

On Windows PowerShell, run the Python checks with:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

On macOS or Linux, use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`.

## Project layout

- `app/` — Next.js frontend
- `api/index.py` — FastAPI entry point
- `finance/`, `ingestion/`, `extraction/`, `normalization/`, `validation/`, `reports/` — space for the processing pipeline
- `tests/` — API tests
- `supabase/migrations/` — database migrations as the data layer is added

## License

MIT. See [LICENSE](LICENSE).
