# StructuraRAG — Local Web Interface

Local web interface for StructuraRAG's current PDF-to-structured-DOCX workflow. It uploads one PDF, queues conversion, reports status, and serves the resulting DOCX. The worker invokes `Tools_Formatting/convert_pdf_batch.py --provider codex` and therefore uses the authenticated Codex CLI session on the same machine.

## Run on Windows

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r Tools_Formatting\requirements.txt
python -m pip install -r webapp\requirements.txt
codex login
codex login status
.\webapp\start.ps1
```

Open <http://127.0.0.1:8000>. Keep the terminal open while the site is in use. A job and its artifacts are stored under `.webapp-data/`; do not commit this directory. The web process is intentionally bound to loopback and has no multi-user authentication. This prototype currently supports PDF uploads only.

Optional settings:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `CODEX_MODEL` | Codex CLI default | Explicit Codex CLI model, if desired |
| `CODEX_CLI` | `codex` | Override Codex executable name/path |
| `KMS_MAX_UPLOAD_BYTES` | 50 MiB | Local upload limit |
| `KMS_PAGES_PER_CALL` | 2 | PDF pages sent to Codex per request |
| `KMS_ENABLE_OCR` | `0` | Set to `1` after Tesseract and `ind+eng` data are installed |
| `KMS_WEB_DATA_DIR` | `.webapp-data` | Local job database and document storage path |

## OAuth and hosting boundary

The app does not copy Codex credentials into the browser or source tree. The local Codex CLI performs ChatGPT OAuth and the server checks `codex login status` before conversion. This is a single-user local deployment.

This is **not yet safe to expose directly to the public internet or deploy as a complete Vercel app**. Vercel Functions are ephemeral/serverless, impose a 4.5 MB request/response limit, and do not provide this app's persistent queue/worker model. A proper online version needs an authenticated web tier, durable storage/database, and a long-running worker. Using a ChatGPT plan OAuth flow in a remotely hosted private app also requires OpenAI eligibility/access; local CLI login does not confer that permission. Do not put CLI token files or OAuth refresh tokens in GitHub, browser storage, or ordinary Vercel environment variables.

Until those are available, use the local version over `127.0.0.1`. Vercel can host a future UI once it is separated from the worker and connected to durable infrastructure; connecting the current local app to Vercel alone would not make its conversion jobs work online.

## Quality and review

The converter validates structural markers before emitting DOCX, but an LLM can still misread legal text, tables, or hierarchy. Review the generated DOCX and its warnings before treating it as a trusted knowledge-base source. Use one pilot PDF first.
