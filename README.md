<div align="center">
  <img src="webapp/static/logo.svg" alt="StructuraRAG logo" width="112">
  <h1>StructuraRAG</h1>
  <p><strong>Structure-aware PDF preprocessing for Retrieval-Augmented Generation.</strong></p>
  <p>Deterministic extraction first. AI assistance when needed.</p>
  <p>
    <a href="https://github.com/Ripanrz/StructuraRAG/actions/workflows/tests.yml">
      <img src="https://github.com/Ripanrz/StructuraRAG/actions/workflows/tests.yml/badge.svg" alt="GitHub Actions tests">
    </a>
    <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12">
    <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="MIT License">
    <img src="https://img.shields.io/badge/Input-PDF-DC5B32?style=flat-square" alt="PDF input">
    <img src="https://img.shields.io/badge/Primary%20output-DOCX-245A9A?style=flat-square" alt="DOCX output">
    <img src="https://img.shields.io/badge/RAG%20sidecar-JSONL-7652A5?style=flat-square" alt="JSONL chunks">
  </p>
</div>

---

## What it does

StructuraRAG preprocesses **PDF documents** into reviewable, structure-aware outputs for downstream Retrieval-Augmented Generation (RAG) pipelines.

The primary output is a **DOCX file**. For every successfully converted PDF, the CLI also writes:
- a DSL text sidecar (.txt) with page, heading, table, and image-anchor markers;
- deterministic heading-aware RAG chunks (.chunks.jsonl);
- a conversion manifest (.manifest.json) with source hash, counts, provider, and warnings;
- an append-only batch-report.jsonl for the CLI run.

The Rule-Based provider works locally without an AI API key. Optional AI providers can help classify ambiguous structure, but their output is checked against structural and content-preservation rules.

> **Scope:** PDF is the only implemented source input format. DOCX is an output and reference/profiling format. StructuraRAG does not currently create embeddings, a vector database, a retriever, or a complete RAG application.

## Output example

Input:

~~~text
input/
└── regulation.pdf
~~~

Output:

~~~text
structurarag-output/
├── regulation.docx
├── regulation.txt
├── regulation.chunks.jsonl
├── regulation.manifest.json
└── batch-report.jsonl
~~~

### Which output should I use?

| Artifact | Intended use |
|---|---|
| .docx | Main human-readable deliverable for review and editing. It uses Word heading styles, native Word tables for detected table blocks, and embedded supported images. |
| .txt | Canonical DSL representation. Useful for debugging, regression comparison, and inspecting structural markers. |
| .chunks.jsonl | Machine-readable, one-JSON-object-per-line chunks for a downstream RAG ingestion pipeline. |
| .manifest.json | Source SHA-256, page count, image list, chunk count, selected provider, and warnings. |
| batch-report.jsonl | Per-file status and errors for the CLI batch run. |

The JSONL sidecar is not a substitute for the DOCX. It is the additional output used to feed a separate embedding/indexing workflow.

## Installation

Tested runtime: **Python 3.12**.

### Windows PowerShell

~~~powershell
git clone https://github.com/Ripanrz/StructuraRAG.git
cd StructuraRAG
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r Tools_Formatting\requirements.txt
~~~

### macOS / Linux

~~~bash
git clone https://github.com/Ripanrz/StructuraRAG.git
cd StructuraRAG
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r Tools_Formatting/requirements.txt
~~~

The CLI dependency set is PyMuPDF and python-docx. Poppler is not required. Tesseract is optional and only required when --ocr is selected.

## Quick start: Rule-Based PDF → DOCX + RAG chunks

Convert one PDF:

~~~powershell
python Tools_Formatting\convert_pdf_batch.py --input ".\input\regulation.pdf" --output-dir ".\structurarag-output" --provider heuristic
~~~

Convert every PDF directly inside a folder (not recursive):

~~~powershell
python Tools_Formatting\convert_pdf_batch.py --input-dir ".\input-pdfs" --output-dir ".\structurarag-output" --provider heuristic
~~~

Rule-Based requires no login, API key, local model, or hosted inference endpoint.

### CLI options

| Option | Description |
|---|---|
| --input PDF | Convert one PDF file. Mutually exclusive with --input-dir. |
| --input-dir DIR | Convert direct child PDF files in a directory. Defaults to pdf-e-hukum in the repository root. |
| --output-dir DIR | Output directory. Defaults to docx-e-hukum-generated. |
| --provider NAME | heuristic (default), local, openai, or codex. |
| --chunk-max-chars N | Approximate character budget per RAG chunk. Default 3500, minimum 300. This is not a tokenizer-based token limit. |
| --pages-per-call N | Page batch size for extraction and AI requests. Default 2, minimum 1. |
| --model MODEL | Model name for the direct OpenAI adapter or optional Codex model selection. |
| --base-url URL | Base URL for the direct OpenAI Responses API adapter. |
| --timeout SECONDS | Timeout for providers that use the option. Default 300. |
| --allow-fallback | Opt into low-confidence heuristic fallback when an AI request fails. The manifest records a warning. |
| --ocr | OCR pages with fewer than 40 extractable text characters. Requires Tesseract and ind + eng language data. |
| --vision | Send rendered page images to the direct OpenAI adapter. Only valid with --provider openai; may increase data transfer and cost. |
| --overwrite | Replace existing DOCX outputs and sidecars. Without it, existing DOCX files are skipped. |
| --limit N | Process at most N PDFs, sorted by filename. Must be at least 1. |

There is no --format flag: DOCX, DSL TXT, JSONL chunks, and manifest are written automatically after a successful conversion.

Exit codes:
- 0: no per-file errors were recorded. Existing DOCX files may have been skipped.
- 1: one or more selected PDFs failed.
- 2: invalid arguments, missing input directory, or no PDFs selected.

## RAG chunk structure

Each line in <source>.chunks.jsonl is an independent JSON object:

~~~json
{
  "chunk_id": "a3e31d5c8b21-00001",
  "document_id": "a3e31d5c8b21",
  "content": "Document title > Chapter one\n\nThe body text of this chunk...",
  "metadata": {
    "source_file": "regulation.pdf",
    "source_pages": [1, 2],
    "heading_path": [
      {"level": 0, "text": "Document title"},
      {"level": 1, "text": "Chapter one"}
    ],
    "block_types": ["paragraph", "table"],
    "image_anchors": [],
    "sequence": 1,
    "table_parts": []
  }
}
~~~

Design notes:
- document_id is derived from the SHA-256 of the source PDF contents.
- chunk_id combines the document ID and a zero-padded sequence.
- source_pages preserves page provenance.
- heading_path repeats the active hierarchy so a chunk can be interpreted independently.
- oversized detected tables are split by complete rows; a detected KOLOM: header is repeated in continuation chunks and table_parts records the continuation index;
- image anchors are metadata only; image bytes, captions, OCR, and visual embeddings are not included in chunk content;
- chunks are grouped by heading path and character budget; overlap is not added automatically.

Use .chunks.jsonl as a text-and-metadata input for your own embedding and vector-index layer. Choose the embedding model and vector database separately.

## Processing modes

| Mode | Provider value | Authentication | Behavior |
|---|---|---|---|
| Rule-Based | heuristic | None | Deterministic extraction and conservative explicit-pattern heading labeling. |
| AI Lokal | local | Optional endpoint bearer token | Calls Ollama or another OpenAI-compatible /chat/completions endpoint. |
| OpenAI API adapter | openai | OpenAI API credential | Direct OpenAI Responses API adapter for developer use. |
| Codex CLI adapter | codex | Local Codex CLI sign-in | Compatibility adapter for local CLI workflows. |

### Ollama / OpenAI-compatible endpoint

~~~powershell
ollama pull qwen2.5:7b-instruct
ollama serve
$env:STRUCTURARAG_LOCAL_AI_BASE_URL = "http://127.0.0.1:11434/v1"
$env:STRUCTURARAG_LOCAL_AI_MODEL = "qwen2.5:7b-instruct"
python Tools_Formatting\convert_pdf_batch.py --input ".\input\regulation.pdf" --output-dir ".\output" --provider local
~~~

Optional bearer token:

~~~powershell
$env:STRUCTURARAG_LOCAL_AI_API_KEY = "your-endpoint-token"
~~~

### Direct OpenAI adapter

~~~powershell
$env:OPENAI_API_KEY = "your-api-key"
$env:OPENAI_MODEL = "gpt-4.1"
python Tools_Formatting\convert_pdf_batch.py --input ".\input\regulation.pdf" --output-dir ".\output" --provider openai
~~~

Never commit credentials, put them in prompts or documents, or include them in a skill ZIP. Remote AI providers receive extracted content; review endpoint data-retention and privacy terms before sending confidential documents.

## Rule-Based structure conventions

The deterministic baseline recognizes a limited set of explicit forms:
- @h0: short uppercase title candidate on the first page;
- @h1: explicit BAB numbering;
- @h2: uppercase lettered section;
- @h3: numeric heading;
- @h4: lowercase lettered item;
- @h5: deeper Roman-numbered item when detected.

Unmatched lines remain ordinary paragraphs rather than receiving speculative heading labels. The baseline is intentionally conservative and is not a universal grammar for every document layout.

## OCR

OCR is optional. After installing Tesseract and Indonesian (ind) and English (eng) language data:

~~~powershell
python Tools_Formatting\convert_pdf_batch.py --input ".\input\scanned.pdf" --output-dir ".\output" --provider heuristic --ocr
~~~

Tesseract is a system dependency and is not installed by pip. The Vercel path does not include a tested OCR runtime.

## Verification and tests

Run the regression suite:

~~~powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
~~~

GitHub Actions runs these tests on pushes and pull requests to main.

The Agensi skill package also includes a standard-library-only verifier for DOCX, DSL, chunks, manifests, and batch reports. See agensi/SKILL.md.

## Web application and Vercel

The FastAPI web interface accepts PDF files. The local app maintains a SQLite-backed job queue and job history. Completed local jobs can download both the primary DOCX and a RAG Bundle ZIP (DOCX, DSL TXT, JSONL chunks, and manifest). The Vercel route is stateless and synchronous: DOCX is the default response, with an optional RAG Bundle ZIP. It does not persist job history or generated artifacts after the request ends.

Vercel defaults:
- maximum PDF upload: 4 MiB;
- synchronous conversion timeout: 240 seconds (function max duration 300 seconds);
- AI Lokal requires an HTTPS endpoint reachable by the Vercel Function;
- Rule-Based can run without model credentials.

Use an external worker and private object storage for larger files, OCR-heavy jobs, or durable batch processing. See docs/VERCEL_DEPLOYMENT.md.

## Limitations and fidelity

- PDF is the only implemented input adapter.
- The reading-order heuristic uses text/table geometry and a conservative two-column rule. Arbitrary columns, sidebars, rotated text, footnotes, overlapping blocks, and complex reading sequences still need review.
- PDF table extraction depends on PyMuPDF detection. Borderless, merged, or visually drawn tables may not be recognized.
- Some vector and page-background graphics are filtered; image-heavy layouts require visual review.
- DOCX is a structured review representation, not a pixel-identical copy of the PDF.
- AI structural validation checks markers, text retention, and numbers but cannot prove semantic correctness.
- The tool does not implement embedding generation, vector storage, retrieval, reranking, or answer generation.

For legal, regulatory, financial, or safety-critical documents, review dates, numbers, identifiers, negations, article references, table cells, and reading order before ingestion into a trusted knowledge base.

## Project layout

~~~text
StructuraRAG/
├── LICENSE
├── README.md
├── requirements.txt
├── index.py
├── Tools_Formatting/
│   ├── convert_pdf_batch.py
│   ├── analyze_gold_standard.py
│   ├── gold_standard_rules.md
│   └── requirements.txt
├── agensi/
│   ├── SKILL.md
│   ├── LICENSE
│   ├── references/
│   └── scripts/verify_outputs.py
├── docs/
├── tests/
└── webapp/
~~~

## License

StructuraRAG is distributed under the MIT License. See LICENSE. Third-party dependencies remain subject to their respective licenses.
