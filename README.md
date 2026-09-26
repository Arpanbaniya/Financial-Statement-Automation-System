# Financial Statement Automation System

Financial reports can be frustrating to analyze: figures are spread across PDFs and spreadsheets, labels vary, and a number is only useful if you know where it came from. I am building this project to turn those documents into organized, checked financial statements while keeping each figure tied to its source.

The goal is a workflow an analyst can inspect. If a line item is unclear or a statement does not balance, the system should show the issue for review instead of quietly making a guess.

## Where the project stands

The Next.js site and FastAPI routes run together under one origin. Supabase email/password accounts protect the dashboard, and each new account gets a profile row. Signed-in users can upload PDF, XLSX, and CSV documents directly to a private Supabase Storage bucket. Python modules can extract their content, identify likely statements, and suggest line-item mappings with source-linked evidence. Running those modules against uploaded files, analysis, and reports are still to come.

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

Detection currently runs in Python only. It does not update the database or classify files as part of the upload flow. Periods, currency, and accounting validation belong to later phases.

## Canonical financial fields

`normalization.taxonomy` defines 52 fields across the income statement, balance sheet, and cash flow statement. Each field has a stable machine name, a readable name, an accounting definition, example source labels, a sign convention, and an instant or duration basis. The same name can have a different role in different statements: `net_income` on an income statement is the period's final profit or loss, while `net_income` on a cash flow statement is an optional line in an indirect reconciliation.

The `required` flag identifies core fields this project will look for when judging completeness of a typical non-financial company statement. It is not a rule that every company must disclose that line. Sign notes describe the values the application will use after normalization; source files can display outflows and expenses differently. `get_field(statement_type, machine_name)` looks up an exact canonical key.

## Line-item mapping

`normalization.map_label(...)` compares an original line-item label with the taxonomy for a known statement type. It tries an exact display name or alias first, then a version with case, spacing, and punctuation normalized. It does not guess from partial phrases or spelling similarity. For example, “Sales” maps to `revenue`, while “Revenue growth” stays unresolved. Generic labels such as “Other” go to review, with possible fields listed when useful.

Each immutable mapping record keeps the original label, suggested field, method, confidence, source location, comparison evidence, and review status. `map_table_rows(...)` reads labels from an extracted table and keeps page, sheet, cell, row, and CSV line references. `correct_mapping(...)` returns a new accepted record with a reviewer ID and review time; it leaves the original extraction and earlier suggestion intact. Exact, normalized, and reviewer-selected decisions use confidence values of 0.97, 0.90, and 1.00 respectively. These are rule strengths or an explicit review decision, not statistical probabilities.

The database schema now has reviewer and review-time columns for mapping decisions. Original labels and source coordinates remain on the related financial line-item row. Mapping and corrections are Python building blocks for now; the authenticated processing and review endpoints still need to connect them to persistence, audit events, validation, and reports.

## Amounts and reporting periods

`normalization.normalize_amount(...)` reads comma-separated numbers, decimals, accounting parentheses, minus signs, and currency symbols. Pass the statement's reported unit, such as `"thousands"` or `"millions"`, to get an exact `Decimal` amount in ones. For example, `normalize_amount("(125.50)", unit="millions")` keeps `(125.50)` and returns `-125500000.00`. Blank cells and dashes remain missing; they never become zero. An unknown unit, invalid number, or unclear currency is marked for review. A missing unit is treated as actual/ones. `$` and `¥` need an explicit currency code because those symbols can represent more than one currency. The module never converts between currencies.

`normalization.normalize_period(...)` distinguishes a balance sheet's as-of date from an income or cash-flow statement's date range. It accepts explicit dates, full date ranges, headings such as `"Year ended December 31, 2025"`, and labels such as `"Q1 FY2025"`. For a fiscal label, pass `fiscal_year_end=(month, day)` to calculate exact dates. Without that calendar or explicit dates, the label stays unresolved for review. Annual, quarterly, six-month, nine-month, and other durations match the existing database period types. Both normalizers return the original input, normalized metadata, status, and warnings for later review.

These functions are available in Python now. The upload flow does not call them yet; a later processing phase will connect extraction, mapping, metadata normalization, persistence, and review.

## Financial validation

`validation.validate_statements(...)` checks accepted, normalized statement values and returns results with a check name, pass/warning/fail/unavailable status, expected and actual amounts, difference, tolerance, severity, source references, and a plain-English explanation. It checks the balance-sheet equation, gross profit, supported asset and liability subtotals, the beginning-to-ending cash bridge, duplicate periods, conflicting values, mixed units and currencies, and missing core fields. Current asset and liability subtotals, operating income, and the cash-flow category subtotal run only when the caller confirms the source presentation supports those formulas.

Values must already be scaled to ones and follow the taxonomy's sign conventions. Suggested or unresolved mappings are not used in arithmetic. Missing values, uncertain currencies, and unclear unit scales yield warnings or unavailable checks, rather than invented figures or currency conversion. The default tolerance is the larger of one unit and one millionth of the compared amount; callers can supply a stricter or looser `TolerancePolicy`. Validation never changes the input snapshots. Beginning and ending cash are optional cash-flow inputs with source references because they are not among the current canonical fields.

This is a Python engine for the future processing flow. Validation results are not yet saved to Supabase or shown in the dashboard. The database's existing result-status names differ from the Phase 13 Python statuses, so persistence will need an explicit mapping when that flow is connected.

## Financial ratios

`finance.calculate_ratios(...)` calculates 12 versioned ratios from accepted income and balance-sheet values: gross, operating, and net margins; return on assets and equity; current and simplified quick ratios; interest-bearing debt to equity; interest coverage; and asset, receivables, and inventory turnover. `finance.FORMULAS` holds each definition, required inputs, output unit, and missing/zero-denominator rules. Percent results are stored as percentage points, so `40` means 40%; turnover and coverage results use `times`.

Return and turnover ratios prefer opening and ending balance-sheet values from the exact dates around the income period. If an opening value is missing, they use the ending value with a warning. Zero denominators and missing or conflicting inputs produce an unavailable result, never an invented number. Results retain the formula ID, numerator, denominator, period, timestamp, warnings, and source references. The calculation timestamp is supplied by the caller so repeated runs are reproducible. The engine runs in Python today; metrics are not yet calculated during upload or shown in the dashboard.

## Changes over time and common-size statements

`finance.calculate_horizontal(...)` compares accepted amounts across matching periods. It defaults to year-over-year comparison and also supports explicit sequential comparison. It covers revenue, gross profit, operating income, net income, assets, interest-bearing debt, equity, operating cash flow, and free cash flow. Free cash flow uses operating cash flow plus signed capital expenditure, whose taxonomy convention is a negative outflow. The result keeps both reported values and their amount change. A zero or negative earlier value leaves percentage growth unavailable; a change from positive to negative gets a warning. Missing or duplicate comparison periods are not guessed.

`finance.calculate_common_size(...)` expresses income-statement lines as a percentage of revenue and balance-sheet lines as a percentage of total assets. A missing, zero, or negative base produces an unavailable result. Both functions keep formula IDs, dates, accepted source references, warnings, and a caller-supplied timestamp. They are Python building blocks and are not part of the upload or dashboard flow yet.

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
- `finance/` — statement detection, ratios, horizontal and common-size analysis
- `normalization/` — canonical fields, conservative label mapping, and amount/period normalization
- `validation/` — deterministic financial checks; `reports/` — later reports
- `supabase/migrations/` — database and private storage setup
- `tests/` — API and ingestion tests with local fixtures

## License

MIT. See [LICENSE](LICENSE).
