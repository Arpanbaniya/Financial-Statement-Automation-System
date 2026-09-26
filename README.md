# Financial Statement Automation System

Financial reports can be frustrating to analyze: figures are spread across PDFs and spreadsheets, labels vary, and a number is only useful if you know where it came from. I am building this project to turn those documents into organized, checked financial statements while keeping each figure tied to its source.

The goal is a workflow an analyst can inspect. If a line item is unclear or a statement does not balance, the system should show the issue for review instead of quietly making a guess.

## Where the project stands

The Next.js site and FastAPI health route run together under one origin. Supabase email/password accounts protect the dashboard, and each new account gets a profile row. A Supabase Free project has the database schema and private document bucket ready for later phases. Uploads, extraction, analysis, and reports are still to come.

| Route            | Current purpose                                |
| ---------------- | ---------------------------------------------- |
| `/`              | Project landing page and API connection status |
| `/signup`        | Create an email/password account               |
| `/login`         | Sign in                                        |
| `/auth/callback` | Complete the emailed signup link               |
| `/dashboard`     | Private workspace and sign-out control         |
| `/api/health`    | Public FastAPI availability check              |

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

Open [http://localhost:3000](http://localhost:3000). The page checks [http://localhost:3000/api/health](http://localhost:3000/api/health), which should return `{"status":"ok"}`. In local development, Next.js forwards `/api/*` to FastAPI on port 8000. On Vercel, `vercel.json` routes `/api/*` to the FastAPI function in `api/index.py` on the same domain. No production localhost URL is used.

## Environment variables

Copy `.env.example` to `.env.local` and fill in `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` from the Supabase project. Set `NEXT_PUBLIC_SITE_URL` to `http://localhost:3000` for local development. Set the same Supabase values and the production site URL in Vercel. `.env.local` is ignored by Git.

The publishable key identifies the Supabase project; it is safe to include in browser code because permissions still come from the signed-in user's JWT and database row-level security. A service-role key bypasses row-level security and must stay on the server. Phase 5 does not need one. The browser and server share the user's session through cookies, which the server verifies before showing the dashboard. The profile row is created by the Phase 3 database trigger when Supabase creates a user.

Supabase allows both the local and production `/auth/callback` URLs as Auth redirects. Its default confirmation email returns to the matching site; the browser client stores the session in cookies before opening the dashboard. Keep database passwords and server keys out of browser code and the repository.

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
