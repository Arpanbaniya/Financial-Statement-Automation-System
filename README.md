# Financial Statement Automation System

Financial reports can be frustrating to analyze: figures are spread across PDFs and spreadsheets, labels vary, and a number is only useful if you know where it came from. I am building this project to turn those documents into organized, checked financial statements while keeping each figure tied to its source.

The goal is a workflow an analyst can inspect. If a line item is unclear or a statement does not balance, the system should show the issue for review instead of quietly making a guess.

## Where the project stands

The Next.js site and FastAPI health route run together under one origin. The site has public home, sign-in, and dashboard routes; authentication and private financial data are not active yet. A Supabase Free project has the database schema and private document bucket ready for later phases. Uploads, extraction, analysis, and reports are still to come.

| Route         | Current purpose                                       |
| ------------- | ----------------------------------------------------- |
| `/`           | Project landing page and API connection status        |
| `/login`      | Sign-in placeholder for the authentication phase      |
| `/dashboard`  | Empty workspace placeholder and API connection status |
| `/api/health` | Public FastAPI availability check                     |

The planned workflow is to upload a PDF, Excel, or CSV statement, organize its line items and periods, validate the numbers, review uncertain mappings, and produce analysis with links back to the source.

## Run it locally

You will need Node.js 22 or 24, pnpm 11, and Python 3.12.

Start the API in one terminal. On Windows PowerShell:

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

Start the web app in a second terminal:

```sh
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000). The page checks [http://localhost:3000/api/health](http://localhost:3000/api/health), which should return `{"status":"ok"}`. In local development, Next.js forwards `/api/*` to FastAPI on port 8000. On Vercel, `api/index.py` handles those paths on the same domain. No `vercel.json` or production localhost URL is needed.

## Environment variables

`.env.example` lists the public Supabase settings and later server-only settings. A local `.env.local` is ignored by Git. The Phase 4 pages do not use Supabase credentials yet; those values will be used when authentication is built. Keep database passwords and server keys out of browser code and the repository.

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

- `app/` — Next.js pages and shared UI
- `api/index.py` — FastAPI entry point
- `finance/`, `ingestion/`, `extraction/`, `normalization/`, `validation/`, `reports/` — processing pipeline packages
- `supabase/migrations/` — database and private storage setup
- `tests/` — API tests

## License

MIT. See [LICENSE](LICENSE).
