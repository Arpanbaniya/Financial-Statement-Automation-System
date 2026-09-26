# Financial Statement Automation System

Financial reports can be frustrating to analyze: figures are spread across PDFs and spreadsheets, labels vary, and a number is only useful if you know where it came from. I am building this project to turn those documents into organized, checked financial statements while keeping each figure tied to its source.

The goal is a workflow an analyst can inspect. If a line item is unclear or a statement does not balance, the system should show the issue for review instead of quietly making a guess.

## Where the project stands

The Next.js site and FastAPI routes run together under one origin. Supabase email/password accounts protect the dashboard, and each new account gets a profile row. Signed-in users can upload PDF, XLSX, and CSV documents directly to a private Supabase Storage bucket. Python modules can extract their content and identify likely income statements, balance sheets, and cash flow statements with source-linked evidence. Running those modules against uploaded files, analysis, and reports are still to come.

| Route                          | Current purpose                                |
| ------------------------------ | ---------------------------------------------- |
| `/`                            | Project landing page and API connection status |
| `/signup`                      | Create an email/password account               |
| `/login`                       | Sign in                                        |
| `/auth/callback`               | Complete the emailed signup link               |
| `/dashboard`                   | Private workspace and sign-out control         |
| `/api/health`                  | Public FastAPI availability check              |
| `/api/documents`               | Reserve an upload or list your documents       |
| `/api/documents/{id}/complete` | Verify a finished upload                       |

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

Copy `.env.example` to `.env.local` and fill in `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` from the Supabase project. Set `NEXT_PUBLIC_SITE_URL` to `http://localhost:3000` for local development. For document uploads, add `SUPABASE_SECRET_KEY` to `.env.local` and Vercel Production. This key must be available to the Python API and must never use the `NEXT_PUBLIC_` prefix. Set the public Supabase values and production site URL in Vercel too. `.env.local` is ignored by Git.

The publishable key identifies the Supabase project; it is safe to include in browser code because permissions still come from the signed-in user's JWT and database row-level security. The secret key bypasses row-level security and stays on the server. The API checks the user's session with Supabase Auth before using that key, then limits every database operation to that user's ID. The browser and server share the user's session through cookies, which the server verifies before showing the dashboard. The profile row is created by the Phase 3 database trigger when Supabase creates a user.

## How uploads work

The browser checks the extension, MIME type, file size, and a basic file signature, then calculates a SHA-256 fingerprint. `POST /api/documents` creates a `reserved` metadata row and returns a private path. The browser sends file bytes to Supabase Storage using a resumable upload with a real progress indicator. `POST /api/documents/{id}/complete` verifies that Storage reports the expected object, path, size, and MIME type before changing the row to `uploaded`. The API never receives the file bytes. Repeating a reservation for the same fingerprint reuses an unfinished reservation; a completed duplicate is rejected. Unfinished reservations expire after one hour and are cleaned during normal document requests.

The fingerprint helps spot accidental duplicates, but the API cannot independently verify file contents without downloading them. Detailed file inspection and processing belong to later phases. Uploaded files remain private under the account's own Storage path. The private bucket's 10 MB limit and Storage policies are set by the Phase 3 migration.

## Document ingestion foundation

`ingestion.ingest_document(source_bytes, filename="statement.pdf")` returns an `ExtractedDocument`. For PDFs, it reads text page by page and attempts to find tables with `pdfplumber`, keeping each table's page number. For XLSX files, it lists sheets, preserves cell positions and formulas, and groups populated rows into regions with cell ranges. It reads the workbook without evaluating formulas or macros. For CSV files, it detects common delimiters, keeps the original decoded text and every record, and records row numbers, line numbers, and the first row as a candidate header. It supports UTF-8, UTF-8 with BOM, UTF-16 with BOM, and Windows-1252; a warning flags the legacy encoding.

Each result records the reader and version used. Recoverable problems are returned as structured warnings; unreadable or unsupported files raise `IngestionError` with a stable code. The adapters read only from source bytes and impose limits on expanded workbooks and extracted content.

This is a Python building block, not an automatic processing job yet. An upload remains `uploaded` until a later phase connects extraction to the authenticated processing endpoint. No financial line item mapping or conclusions are made here. A PDF with no searchable text returns `needs_review` with an OCR warning because OCR is not supported yet; this result does not change the database document status by itself.

## Statement detection

`finance.detect_statements(extracted_document)` applies configurable heading and line-item rules. It returns one result per PDF page, populated Excel region, or CSV table, with a likely statement type, a bounded confidence score, the matched words and their source locations, and warnings. Familiar titles such as “Statement of Operations,” “Profit and Loss,” “Statement of Financial Position,” and “Statement of Cash Flows” are recognized. When evidence is weak or points to competing statement types, the result is `unknown` for review. The score is a rule-based indication of evidence strength, not a statistical probability.

Detection currently runs in Python only. It does not update the database or classify files as part of the upload flow. Periods, currency, line-item mapping, and accounting validation belong to later phases.

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
- `ingestion/` — source validation and common extracted-document types
- `extraction/` — PDF, XLSX, and CSV readers
- `finance/` — rule-based statement detection; later calculations
- `normalization/`, `validation/`, `reports/` — later processing packages
- `supabase/migrations/` — database and private storage setup
- `tests/` — API and ingestion tests with local fixtures

## License

MIT. See [LICENSE](LICENSE).
