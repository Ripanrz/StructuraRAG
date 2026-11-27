# StructuraRAG — PDF Processing Tools

The CLI is a PDF-to-DOCX converter with additional RAG-preparation sidecars. Run commands from the repository root.

## Main Rule-Based workflow

~~~powershell
python Tools_Formatting\convert_pdf_batch.py --input ".\input\source.pdf" --output-dir ".\structurarag-output" --provider heuristic --chunk-max-chars 3500
~~~

The primary output is DOCX. A successful conversion also writes:
- source.txt: DSL structure with page, heading, table, and image-anchor markers;
- source.chunks.jsonl: deterministic heading-aware chunks for downstream RAG ingestion;
- source.manifest.json: source hash, output names, page/image/chunk counts, provider, and warnings;
- batch-report.jsonl: append-only execution report for the CLI run.

Rule-Based runs without API keys or a local/hosted model.

## CLI reference

| Option | Meaning |
|---|---|
| --input PDF | One input PDF; mutually exclusive with --input-dir. |
| --input-dir DIR | Convert PDFs directly inside a directory (not recursive). |
| --output-dir DIR | Output location. |
| --provider NAME | heuristic, local, openai, or codex. |
| --chunk-max-chars N | Approximate chunk content budget in characters (default 3500, min 300). |
| --pages-per-call N | Extraction/AI batch size (default 2, min 1). |
| --model MODEL | Direct OpenAI model or optional Codex CLI model. |
| --base-url URL | Direct OpenAI Responses API base URL. |
| --timeout SECONDS | Provider timeout where supported. |
| --allow-fallback | Explicitly permit low-confidence Rule-Based fallback after AI errors. |
| --ocr | Optional Tesseract OCR on pages with insufficient text. |
| --vision | OpenAI-only page-image interpretation. May add cost. |
| --overwrite | Replace existing outputs. |
| --limit N | Process at most N PDFs (>=1). |

There is no format selector; every successful conversion automatically writes DOCX, TXT, JSONL chunks, and manifest.

## Processing modes

| Mode | Provider | Requirements |
|---|---|---|
| Rule-Based | heuristic | PyMuPDF + python-docx; no AI key |
| AI Lokal | local | Ollama or OpenAI-compatible server; optional bearer token |
| OpenAI API adapter | openai | OpenAI API credential |
| Codex CLI adapter | codex | Locally installed and authenticated Codex CLI |

## Structure and validation

The pipeline extracts page text blocks, detected tables, embedded raster images, and selected vector drawing regions. It orders extracted events using page coordinates and a conservative two-column heuristic, filters repeated margin noise and some blank/background assets, and applies deterministic heading patterns documented in gold_standard_rules.md.

AI output is validated for ordered page markers, image-anchor retention, balanced table markers, heading depth no deeper than h5, source text retention, and numeric token preservation.

These checks reduce common errors but do not establish semantic accuracy. Reading order for complex layouts, table boundaries, image placement, and legal details must be reviewed.

## RAG chunk schema

JSONL chunks include chunk_id, document_id, content, and metadata:
- source filename and page provenance;
- heading hierarchy;
- content block types;
- image-anchor metadata;
- sequence;
- table continuation part metadata when a table was split.

Chunk size is measured in characters, not tokenizer tokens. No overlap, embeddings, vector database, retriever, or reranker is implemented. See agensi/references/rag-chunk-schema.md.

## Optional AI Lokal

~~~powershell
$env:STRUCTURARAG_LOCAL_AI_BASE_URL = "http://127.0.0.1:11434/v1"
$env:STRUCTURARAG_LOCAL_AI_MODEL = "qwen2.5:7b-instruct"
$env:STRUCTURARAG_LOCAL_AI_API_KEY = "your-endpoint-token"
python Tools_Formatting\convert_pdf_batch.py --input ".\input\source.pdf" --output-dir ".\output" --provider local
~~~

## Dependencies

Install CLI dependencies:

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r Tools_Formatting\requirements.txt
~~~

PyMuPDF and python-docx are Python dependencies. Poppler is not required. Tesseract is optional and installed separately for OCR with ind and eng language data.
