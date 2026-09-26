# Financial Statement Automation System

An in-progress app for uploading financial statements, checking the numbers, and downloading an Excel report.

[Live site](https://financial-statement-automation-syst.vercel.app/)

The site has sign-in, private uploads, and a dashboard. The Python code handles extraction, validation, ratios, reports, and SEC filing data. Uploads are not yet processed into saved statements automatically, so the analysis pages need accepted data before they can show results.

## Run locally

You need Python 3.12, Node.js, and pnpm. Copy `.env.example` to `.env.local` and add your Supabase values.

In one terminal:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn api.index:app --reload --port 8000
```

In another terminal:

```powershell
pnpm install
pnpm dev
```

Open `http://localhost:3000`. Keep `SUPABASE_SECRET_KEY` server-side. To use the optional SEC adapter, set `SEC_USER_AGENT` to a name and contact email.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest
pnpm lint
pnpm typecheck
```

MIT licensed. See [LICENSE](LICENSE).
