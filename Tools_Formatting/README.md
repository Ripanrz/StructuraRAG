# StructuraRAG — PDF Processing Tools

This directory contains the PDF extraction and conversion engine plus the profiler for the legal-document reference corpus. Run commands from the StructuraRAG repository root.

## Current processing modes

| Mode | Provider value | Authentication | Purpose |
|---|---|---|---|
| Rule-Based | `heuristic` | None | Deterministic extraction, normalization, conservative heading rules, tables, and source markers |
| AI Lokal | `local` | Local model endpoint, optional bearer token | Uses Ollama or another OpenAI-compatible chat-completions endpoint |
| AI Cloud API (developer adapter) | `openai` | OpenAI API key | Direct API integration for development; not the planned ChatGPT OAuth product option |
| Codex CLI (legacy adapter) | `codex` | Local Codex CLI sign-in | Compatibility adapter for the existing local CLI workflow |

The CLI defaults to Rule-Based. The web application exposes Rule-Based, AI Lokal, and a gated AI Cloud OAuth option. ChatGPT OAuth for remote-hosted inference is not enabled until OpenAI approves the hosted use case and the full session/token flow is implemented.

## Gold-standard profiler

`analyze_gold_standard.py` reads the local `docx-e-hukum` reference corpus (ignoring Microsoft Office lock files) and writes:

- `gold_standard_summary.md`: human-readable format specification.
- `gold_standard_profile.json`: per-document counts, inline tag counts, representative table rows, and paragraph examples.

The audited corpus contains 33,493 paragraphs across 20 reference DOCX files. All inspected paragraphs use Word `Normal` style; the table DSL is serialized inline. The observed hierarchy stops at `@h5`; do not generate deeper levels without new reference evidence.

## Install

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r Tools_Formatting\requirements.txt
~~~

## Rule-Based mode (offline, no AI login)

~~~powershell
python Tools_Formatting\convert_pdf_batch.py --provider heuristic --limit 1
~~~

The deterministic baseline preserves page boundaries, text order, tables, image anchors, and explicit hierarchy patterns it can recognize. Current title/heading rules are deliberately conservative:

- `@h0`: short uppercase document-title candidate on the first page.
- `@h1`: explicit `BAB` numbering.
- `@h2`: explicit uppercase lettered section.
- `@h3`: explicit numeric heading.
- `@h4`: explicit lowercase lettered item.
- `@h5`: explicitly recognized deeper Roman-numbered item.

If a line does not match a reliable pattern, the engine leaves it as a normal paragraph rather than inventing a heading. This baseline is deterministic but is not yet a complete grammar for every legal-document layout. Review results and test against a labeled corpus before production use.

## AI Lokal (Ollama / OpenAI-compatible endpoint)

For a local Ollama server, first install and run a model:

~~~powershell
ollama pull qwen2.5:7b-instruct
ollama serve
~~~

Configure the model endpoint in the current PowerShell session:

~~~powershell
$env:STRUCTURARAG_LOCAL_AI_BASE_URL = "http://127.0.0.1:11434/v1"
$env:STRUCTURARAG_LOCAL_AI_MODEL = "qwen2.5:7b-instruct"

python Tools_Formatting\convert_pdf_batch.py --provider local --limit 1
~~~

If the endpoint requires authentication, configure `STRUCTURARAG_LOCAL_AI_API_KEY`. The provider uses the OpenAI-compatible `/chat/completions` endpoint. Local inference keeps document content on the model host you control; confirm your model server does not forward requests to an external provider.

## AI Cloud API adapter (developer use)

This provider uses the OpenAI Responses API directly. It is separate from ChatGPT OAuth and requires an API credential:

~~~powershell
$env:OPENAI_API_KEY = "your-api-key"
$env:OPENAI_MODEL = "gpt-4.1"

python Tools_Formatting\convert_pdf_batch.py --provider openai --limit 1
~~~

Optional visual page interpretation:

~~~powershell
python Tools_Formatting\convert_pdf_batch.py --provider openai --vision --limit 1
~~~

Never store API keys in source code, browser bundles, or Git.

## Codex CLI compatibility adapter

The existing Codex CLI adapter is retained for local compatibility:

~~~powershell
codex login
python Tools_Formatting\convert_pdf_batch.py --provider codex --limit 1
~~~

A Codex sign-in is not a general-purpose API key and does not automatically authorize a remotely hosted application to use a ChatGPT plan. See [Vercel deployment and OAuth boundaries](../docs/VERCEL_DEPLOYMENT.md).

## Batch usage

Default input: `pdf-e-hukum`  
Default output: `docx-e-hukum-generated`

~~~powershell
# One-file pilot using the offline baseline
python Tools_Formatting\convert_pdf_batch.py --provider heuristic --limit 1

# Process all PDFs using the local model
python Tools_Formatting\convert_pdf_batch.py --provider local

# Process all PDFs using the direct OpenAI API adapter
python Tools_Formatting\convert_pdf_batch.py --provider openai

# If scanned PDFs are present, install Tesseract with ind+eng language packs first
python Tools_Formatting\convert_pdf_batch.py --provider heuristic --ocr --limit 1
~~~

Existing DOCX outputs are skipped unless `--overwrite` is supplied. LLM errors stop conversion by default; `--allow-fallback` explicitly opts into the low-confidence deterministic baseline. Use `--pages-per-call N` to tune context and cost.

## Pipeline and fidelity

1. PyMuPDF extracts page text blocks, coordinates, table cells, embedded images, and substantial vector drawing regions.
2. Repeated margin furniture and explicitly recognized standalone watermark/metadata blocks are filtered. Substantive paragraphs containing the same words are retained.
3. Rule-Based labels only explicit patterns. AI providers may reconstruct ambiguous hierarchy using the audited reference rules and previous heading context.
4. Structural checks validate page markers, image anchors, table-marker balance, heading depth, title count (for AI output), source-token retention, and preservation of numeric tokens.
5. Images are inserted into DOCX at their image-anchor paragraph. Word reflow means absolute source-page coordinates are not guaranteed after DOCX serialization.

These checks reduce common errors but do not prove semantic accuracy. Inspect legal wording, references, tables, numbering, and conversion warnings before ingestion into a trusted knowledge base.

## Output files

The CLI creates:

- `.docx`: structured Word document.
- `.txt`: DSL representation.
- `.manifest.json`: source/output metadata and warnings.
- `batch-report.jsonl`: batch conversion status.

The hosted Vercel endpoint currently returns DOCX directly and does not persist per-job files.

## Main files

- `analyze_gold_standard.py` — reference-corpus profiler.
- `convert_pdf_batch.py` — PDF-to-DSL/DOCX conversion.
- `gold_standard_rules.md` — structural reference contract.
