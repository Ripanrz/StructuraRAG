# Deploy StructuraRAG to Vercel

This repository contains a Vercel-compatible FastAPI entrypoint. The Vercel deployment uses a separate **stateless request/response path**; it does not use the local SQLite job queue or background thread.

## What works on Vercel today

- Rule-Based PDF conversion (offline from AI providers).
- AI Lokal through an HTTPS Ollama or OpenAI-compatible endpoint reachable by the Vercel Function.
- DOCX returned directly to the browser.
- Optional HTTP Basic protection using a Vercel environment variable.

The following are not yet available on the hosted Vercel path:

- ChatGPT plan OAuth inference. Remote-hosted use requires OpenAI approval and a dedicated persistent OAuth/session implementation.
- Large-document asynchronous jobs and durable job history.
- OCR unless a separately packaged and tested OCR runtime is added.
- Multi-user accounts and per-user document history.

## 1. Deploy from GitHub

1. Push the latest main branch to GitHub.
2. Open the Vercel dashboard and choose **Add New → Project**.
3. Import **Ripanrz/StructuraRAG**.
4. Set the Root Directory to the repository root, shown as a single dot.
5. Let Vercel detect the Python/FastAPI application. Do not add a Node.js build command.
6. Keep the Python version at 3.12 (pinned in .python-version).
7. Deploy.

The project includes:

- index.py: Vercel FastAPI entrypoint.
- requirements.txt: root-level Python dependencies.
- vercel.json: function duration and files required by the converter.
- webapp/app.py: FastAPI application and stateless Vercel conversion route.

## 2. Set environment variables

Open **Vercel → Project → Settings → Environment Variables**.

Before deploying, enable **Automatically expose System Environment Variables** in the project's environment-variable settings. The application relies on Vercel's `VERCEL=1` flag to activate its serverless routes and on the `VERCEL_URL` / `VERCEL_PROJECT_PRODUCTION_URL` values to validate the request host. If these system variables are not exposed, the app can incorrectly start in local-only mode and return 403/404 responses.

Recommended minimum:

| Variable | Value | Required |
|---|---|---|
| STRUCTURARAG_ACCESS_PASSWORD | A long unique password | Strongly recommended before public use |
| STRUCTURARAG_ACCESS_USERNAME | structurarag or your own username | Optional |
| STRUCTURARAG_ALLOWED_HOSTS | Comma-separated additional domains, if any | Only for extra aliases not exposed by Vercel system variables |
| STRUCTURARAG_VERCEL_MAX_UPLOAD_BYTES | 4194304 | Default is 4 MiB |
| STRUCTURARAG_VERCEL_CONVERT_TIMEOUT | 240 | Default is 240 seconds |
| STRUCTURARAG_PAGES_PER_CALL | 1 | Default is 1 |

The default Vercel function accepts small PDFs and processes them synchronously. The Function response is returned directly to the browser as DOCX; uploaded and generated documents are not persisted by this route.

**Important:** do not expose the app publicly without setting STRUCTURARAG_ACCESS_PASSWORD or enabling Vercel Deployment Protection. The optional Basic Auth middleware protects the page and API routes. Keep this password in Vercel Environment Variables, never in source code.

The host guard automatically permits Vercel's `VERCEL_URL`, `VERCEL_BRANCH_URL`, and `VERCEL_PROJECT_PRODUCTION_URL` system domains. Add only any additional custom alias to `STRUCTURARAG_ALLOWED_HOSTS`; these system variables are populated when **Automatically expose System Environment Variables** is enabled for the project.

## 3. Verify the deployment

After deployment, open:

- https://YOUR-PROJECT.vercel.app/
- https://YOUR-PROJECT.vercel.app/api/health

The health endpoint should report:

- runtime: "vercel"
- providers.heuristic.available: true
- providers.local.configured: false until an endpoint is configured
- providers.cloud_oauth.available: false until the hosted OAuth use case is approved and implemented

Select **Rule-Based · Offline**, upload a small text-based PDF, and download the DOCX result.

## 4. Enable AI Lokal on Vercel

Vercel cannot reach http://127.0.0.1:11434 on your personal laptop. A hosted Function runs remotely. For AI Lokal on Vercel, run Ollama or another OpenAI-compatible model server on a machine/VPS that is securely reachable over HTTPS.

Example Ollama setup on the model host:

~~~bash
ollama pull qwen2.5:7b-instruct
ollama serve
~~~

Expose the model only through an authenticated HTTPS gateway or private tunnel. Do not publish an unauthenticated Ollama port to the public internet.

Then add these Vercel environment variables:

| Variable | Example |
|---|---|
| STRUCTURARAG_LOCAL_AI_BASE_URL | https://YOUR-SECURE-MODEL-HOST/v1 |
| STRUCTURARAG_LOCAL_AI_MODEL | qwen2.5:7b-instruct |
| STRUCTURARAG_LOCAL_AI_API_KEY | Gateway bearer token (if required) |

The local provider sends requests to /chat/completions using the OpenAI-compatible protocol. The API key stays in the server environment and is not sent to browser JavaScript. After adding environment variables, redeploy and select **AI Lokal**.

For a local desktop deployment, the default endpoint is http://127.0.0.1:11434/v1; configure Ollama on the same machine as the StructuraRAG server.

## 5. Cloud AI and ChatGPT OAuth

The intended Cloud AI option is **Sign in with ChatGPT**, not a browser-stored API key.

There is an important platform/permission distinction:

- ChatGPT OAuth identity sign-in does not, by itself, grant access to a user's ChatGPT plan for model inference.
- OpenAI documents ChatGPT plan usage for eligible open-source clients, but states that paid or remotely hosted applications should complete its interest/approval process.
- StructuraRAG on Vercel is a remotely hosted service. Do not copy a local Codex CLI token, refresh token, or undocumented credential file into Vercel.
- Therefore the Cloud OAuth option is shown as pending and intentionally disabled on this deployment until the remote-hosted use case is approved.

Before enabling it:

1. Review the official [Sign in with ChatGPT overview](https://developers.openai.com/siwc/token-sharing-open-source).
2. Contact OpenAI through the approval/interest process described for remote-hosted usage.
3. Obtain confirmation of the supported hosted OAuth flow, allowed scopes, client registration, callback URLs, and usage terms.
4. Implement Authorization Code + PKCE, state/nonce validation, ID-token validation, token refresh, revocation, and per-user session handling according to the approved flow.
5. Store OAuth credentials encrypted in a persistent database with strict per-user access controls. Never store them in browser local storage, source control, logs, or a shared unencrypted JSON file.
6. Enable the Cloud OAuth selector only after the full flow and inference entitlement have been tested.

Until these steps are completed, use Rule-Based or AI Lokal on Vercel. This is deliberate: the app must not present ordinary OAuth sign-in as proof that ChatGPT plan inference is authorized.

## 6. Vercel limits and the large-file path

The current hosted route is deliberately conservative:

- Default upload limit: 4 MiB, below the standard Vercel Function request-body limit.
- Synchronous processing timeout: 240 seconds, with maxDuration configured to 300 seconds.
- DOCX is returned directly; the hosted route does not promise persistent history.
- Output is subject to the Vercel Function response-size limit.

Vercel announced a 20 MiB request-body public beta on November 20, 2026. It requires opting in with VERCEL_SUPPORT_LARGE_REQUEST_BODY=1 and Performance (4 GB) memory. That does not remove the response-size limit, nor does it turn this synchronous route into a durable job system. I recommend keeping the 4 MiB default until the large-upload path is separately tested.

For large PDFs, lengthy OCR, or batch processing, use a durable worker architecture with object storage (private Blob or S3-compatible storage), a persistent queue, and a worker service. Do not rely on in-process threads, SQLite, or the temporary filesystem for durable Vercel jobs.

## 7. Local development and deployment commands

Install dependencies:

~~~bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

python -m pip install -r requirements.txt
~~~

Run the local app:

~~~bash
python -m uvicorn webapp.app:app --host 127.0.0.1 --port 8000
~~~

Optional Vercel CLI deployment:

~~~bash
npm install -g vercel
vercel login
vercel
~~~

After checking the preview deployment, deploy production:

~~~bash
vercel --prod
~~~

You can also connect the GitHub repository in Vercel for automatic preview deployments and production deploys from the configured branch.

## Troubleshooting

| Symptom | Likely reason | Action |
|---|---|---|
| 404 or import error | Vercel root directory is wrong | Set Root Directory to repository root |
| Missing pymupdf or docx | Root requirements.txt not used | Redeploy and inspect build logs |
| 413 on upload | PDF exceeds request-size limit | Reduce PDF size or use a durable direct-upload/worker design |
| 504 on conversion | Runtime exceeds configured timeout | Use a smaller PDF or external worker |
| AI Lokal unavailable | URL not set, not HTTPS, or unreachable | Configure a secure reachable model endpoint |
| ChatGPT OAuth unavailable | Hosted inference entitlement not approved/implemented | Follow the Cloud OAuth approval steps above |
| Missing static page/logo | Bundled paths are incomplete | Keep webapp/static/** included in vercel.json |

## Security checklist

- [ ] Set STRUCTURARAG_ACCESS_PASSWORD or enable Vercel Deployment Protection.
- [ ] Use HTTPS for external model endpoints.
- [ ] Keep model keys and OAuth secrets in Vercel Environment Variables.
- [ ] Do not store uploaded legal documents in a public Blob store.
- [ ] Review model-host access logs and data-retention policy.
- [ ] Do not enable ChatGPT plan OAuth before written approval for remote-hosted use.
