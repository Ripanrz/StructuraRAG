# StructuraRAG — Local Web Interface

Local web interface for StructuraRAG's current PDF-to-structured-DOCX workflow. It uploads one PDF, queues conversion, reports status, and serves the resulting DOCX. I can choose an offline rule-based baseline, Codex CLI, or OpenAI API. The web worker passes the selected provider to `Tools_Formatting/convert_pdf_batch.py`.

## Run on Windows

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r Tools_Formatting\requirements.txt
python -m pip install -r webapp\requirements.txt
# Optional: authenticate first only if I choose the Codex AI provider
# codex login
# codex login status
.\webapp\start.ps1
```

Open <http://127.0.0.1:8000>. Keep the terminal open while the site is in use. A job and its artifacts are stored under `.webapp-data/`; do not commit this directory. The web process is intentionally bound to loopback and has no multi-user authentication. This prototype currently supports PDF uploads only. The rule-based provider can run without AI credentials.

For the OpenAI provider, I configure `OPENAI_API_KEY` or `OPENAI_BEARER_TOKEN` in the local server environment. The key is never entered into the browser. The Codex provider requires a local authenticated CLI session. The rule-based provider requires neither.

Optional settings:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `CODEX_MODEL` | Codex CLI default | Explicit Codex CLI model, if desired |
| `CODEX_CLI` | `codex` | Override Codex executable name/path |
| `STRUCTURARAG_MAX_UPLOAD_BYTES` | 50 MiB | Local upload limit |
| `STRUCTURARAG_PAGES_PER_CALL` | 2 | PDF pages sent per AI request |
| `STRUCTURARAG_ENABLE_OCR` | `0` | Set to `1` after Tesseract and `ind+eng` data are installed |
| `STRUCTURARAG_WEB_DATA_DIR` | `.webapp-data` | Local job database and document storage path |

The previous `KMS_MAX_UPLOAD_BYTES`, `KMS_PAGES_PER_CALL`, `KMS_ENABLE_OCR`, and `KMS_WEB_DATA_DIR` names remain supported as backward-compatible aliases.

## OAuth and hosting boundary

The app does not copy Codex credentials into the browser or source tree. When I choose Codex, the local CLI performs sign-in and the server checks `codex login status`. When I choose OpenAI, the server reads the configured environment credential. Rule-based mode does not contact an AI provider. This is a single-user local deployment.

This is **not yet safe to expose directly to the public internet or deploy as a complete Vercel app**. Vercel Functions are ephemeral/serverless, impose a 4.5 MB request/response limit, and do not provide this app's persistent queue/worker model. A proper online version needs an authenticated web tier, durable storage/database, and a long-running worker. Using a ChatGPT plan OAuth flow in a remotely hosted private app also requires OpenAI eligibility/access; local CLI login does not confer that permission. Do not put CLI token files or OAuth refresh tokens in GitHub, browser storage, or ordinary Vercel environment variables.

Until those are available, use the local version over `127.0.0.1`. Vercel can host a future UI once it is separated from the worker and connected to durable infrastructure; connecting the current local app to Vercel alone would not make its conversion jobs work online.

## Quality and review

The converter validates structural markers before emitting DOCX, but an LLM can still misread legal text, tables, or hierarchy. Review the generated DOCX and its warnings before treating it as a trusted knowledge-base source. Use one pilot PDF first.
