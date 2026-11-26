# StructuraRAG — Web Interface

The web application exposes three product choices:

1. **Rule-Based** — offline deterministic processing, with no AI login.
2. **AI Lokal** — Ollama or another OpenAI-compatible model endpoint that I control.
3. **AI Cloud** — intended to use Sign in with ChatGPT OAuth. This is currently gated for remote Vercel hosting until OpenAI approves the hosted ChatGPT plan inference use case and the full OAuth/session implementation is completed.

The application supports PDF uploads only.

## Run locally on Windows

From the repository root in PowerShell:

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
.\webapp\start.ps1
~~~

Open http://127.0.0.1:8000.

Rule-Based works immediately. The local app uses a SQLite-backed job queue and writes job artifacts under `.webapp-data/`. This local queue is deliberately not used by Vercel.

## Configure AI Lokal

Install Ollama, then pull and run a chat model:

~~~powershell
ollama pull qwen2.5:7b-instruct
ollama serve
~~~

Configure the endpoint before launching StructuraRAG:

~~~powershell
$env:STRUCTURARAG_LOCAL_AI_BASE_URL = "http://127.0.0.1:11434/v1"
$env:STRUCTURARAG_LOCAL_AI_MODEL = "qwen2.5:7b-instruct"
.\webapp\start.ps1
~~~

If the endpoint requires a bearer token, set `STRUCTURARAG_LOCAL_AI_API_KEY` in the same server environment. The browser never receives this credential.

Supported endpoint contract: OpenAI-compatible `POST /chat/completions`.

## Local application settings

| Variable | Default | Purpose |
|---|---|---|
| `STRUCTURARAG_LOCAL_AI_BASE_URL` | `http://127.0.0.1:11434/v1` locally | Model API base URL |
| `STRUCTURARAG_LOCAL_AI_MODEL` | `qwen2.5:7b-instruct` | Local model name |
| `STRUCTURARAG_LOCAL_AI_API_KEY` | Empty | Optional model endpoint bearer token |
| `STRUCTURARAG_MAX_UPLOAD_BYTES` | 50 MiB | Local upload limit |
| `STRUCTURARAG_PAGES_PER_CALL` | 2 | PDF pages per AI request |
| `STRUCTURARAG_ENABLE_OCR` | `0` | Enables local Tesseract OCR when set to `1` |
| `STRUCTURARAG_WEB_DATA_DIR` | `.webapp-data` | SQLite jobs and local files |

Legacy `KMS_*` variables remain accepted as backward-compatible aliases where implemented.

## Deploy to Vercel

The root-level `index.py`, `requirements.txt`, and `vercel.json` are configured for Vercel's Python/FastAPI runtime. Vercel uses a stateless endpoint:

- `POST /api/convert` accepts a PDF and selected provider.
- The function uses a temporary directory for each request.
- DOCX is returned directly to the browser.
- No Vercel SQLite queue or in-process background thread is used.
- Default upload size is 4 MiB; conversion timeout is 240 seconds.
- The Vercel UI does not promise document history or persistent file storage.

Follow the complete [Vercel deployment guide](../docs/VERCEL_DEPLOYMENT.md) for GitHub import, environment variables, password protection, AI Lokal HTTPS setup, limits, and the ChatGPT OAuth approval boundary.

## Cloud OAuth status

The Cloud AI entry is intentionally visible but disabled. OpenAI documents identity sign-in separately from permission to use a user's ChatGPT plan for model inference. Remotely hosted apps need to complete the OpenAI approval/interest process before ChatGPT plan inference can be enabled.

Do not copy Codex CLI token files or refresh tokens into Vercel environment variables. Do not store OAuth credentials in browser storage. Once the hosted use case is approved, the OAuth flow must use state/nonce and PKCE validation, verified identity/permissions, encrypted server-side token storage, refresh/revocation handling, and per-user access controls.

See the official [Sign in with ChatGPT documentation](https://developers.openai.com/siwc/token-sharing-open-source).

## Privacy and deployment boundary

The local app binds to loopback and is a single-user prototype. The Vercel version is stateless for conversion requests but is not a full multi-user SaaS application. Set `STRUCTURARAG_ACCESS_PASSWORD` or enable Vercel Deployment Protection before sharing the hosted URL. Use HTTPS for external model endpoints and never expose an unauthenticated Ollama port to the public internet.

For large PDFs, lengthy OCR, or batch workloads, use an object store, persistent queue, and worker service. Do not rely on temporary files, SQLite, or background threads for durable hosted jobs.
