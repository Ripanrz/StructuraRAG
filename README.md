<div align="center">
  <img src="webapp/static/logo.svg" alt="StructuraRAG logo" width="112">
  <h1>StructuraRAG</h1>
  <p><strong>Structure-aware document preprocessing for Retrieval-Augmented Generation.</strong></p>
  <p>Deterministic parsing first. AI assistance when needed.</p>
  <p><a href="https://github.com/Ripanrz/StructuraRAG/actions/workflows/tests.yml"><img src="https://github.com/Ripanrz/StructuraRAG/actions/workflows/tests.yml/badge.svg" alt="Regression tests"></a></p>
</div>

---

I develop StructuraRAG as a format-aware document preprocessing engine that converts source files into structurally labeled, context-preserving representations for downstream Retrieval-Augmented Generation (RAG) pipelines. Its design separates deterministic parsing and validation from optional AI-assisted interpretation.

My primary focus is not merely extracting text, but preserving logical hierarchy, reading order, tables, page boundaries, images, and contextual relationships during preprocessing.

The current implementation is PDF-first and includes a legal-document reference profiler, a CLI converter, and a local web interface. The architecture is intended to grow into multi-format ingestion and independent structure-aware chunking.

> **Current scope:** PDF is the implemented source-document conversion format. DOCX is used as a reference and profiling format. General DOCX, TXT, HTML, XLSX, and PPTX input conversion is not yet implemented.

## Core Objectives

I aim to build a document preprocessing system that can:

- Extract textual and visual content from source documents.
- Preserve document structure and logical reading order.
- Identify and label hierarchical sections and subsections.
- Preserve tables, images, page boundaries, and relevant metadata.
- Convert extracted content into a consistent intermediate representation.
- Split documents according to meaningful structural boundaries.
- Export structured results into formats suitable for downstream RAG pipelines.

## Current Implementation

| Component | Current status |
|---|---|
| PDF extraction | Implemented with PyMuPDF |
| PDF tables and images | Extracted with layout anchors |
| Scanned PDF OCR | Optional Tesseract in supported local environments |
| Rule-Based labeling | Deterministic title, BAB, lettered, and numeric patterns |
| AI Lokal | Ollama / OpenAI-compatible chat-completions endpoint |
| AI Cloud OAuth | Planned; remote-hosted ChatGPT plan inference requires OpenAI approval |
| Output | DOCX, DSL TXT, JSON manifest, JSONL report from the CLI |
| Web application | Local queue plus stateless Vercel conversion endpoint |

**Input scope:** PDF is the only implemented source-conversion format. DOCX is used as the reference/profiling format. General DOCX, TXT, HTML, XLSX, and PPTX ingestion are roadmap items, not implemented features.

## Processing Providers

StructuraRAG offers three user-facing modes:

| Mode | How it works | AI login |
|---|---|---|
| **Rule-Based** | Deterministic extraction and conservative structure rules | Not required |
| **AI Lokal** | Ollama or another OpenAI-compatible model endpoint I control | Not required when the model server is open locally; endpoint auth may be configured |
| **AI Cloud** | Intended to use Sign in with ChatGPT OAuth for eligible cloud inference | OAuth required; currently gated for Vercel hosting |

The CLI retains direct OpenAI API-key and Codex CLI adapters for development/compatibility. They are not the primary three-mode product interface.

The current Rule-Based engine recognizes explicit title and numbering patterns, but it is not yet a complete grammar for every legal-document layout. Unrecognized lines remain ordinary paragraphs rather than receiving speculative labels.


## Installation

I use Python 3.12 and PowerShell for the local workflow.

~~~powershell
git clone https://github.com/Ripanrz/StructuraRAG.git
cd StructuraRAG

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
~~~


## Command-Line Usage

### Rule-Based (offline)

~~~powershell
python Tools_Formatting\convert_pdf_batch.py --provider heuristic --limit 1
~~~

### AI Lokal (Ollama)

~~~powershell
ollama pull qwen2.5:7b-instruct
ollama serve

$env:STRUCTURARAG_LOCAL_AI_BASE_URL = "http://127.0.0.1:11434/v1"
$env:STRUCTURARAG_LOCAL_AI_MODEL = "qwen2.5:7b-instruct"
python Tools_Formatting\convert_pdf_batch.py --provider local --limit 1
~~~

### Direct OpenAI API adapter (developer use)

~~~powershell
$env:OPENAI_API_KEY = "your-api-key"
python Tools_Formatting\convert_pdf_batch.py --provider openai --limit 1
~~~

The API-key adapter is separate from the planned ChatGPT OAuth Cloud mode. Never put credentials in source code or browser JavaScript.

### Optional OCR

After installing Tesseract with Indonesian and English language data:

~~~powershell
python Tools_Formatting\convert_pdf_batch.py --provider heuristic --ocr --limit 1
~~~

The converter uses pdf-e-hukum as its default input directory and docx-e-hukum-generated as its default output directory. Both paths can be changed with the input/output directory arguments. Existing DOCX files are skipped unless overwrite is explicitly enabled.


## Run the Local Web Application

~~~powershell
.\webapp\start.ps1
~~~

Open http://127.0.0.1:8000.

Rule-Based works without AI credentials. For AI Lokal, start Ollama and set STRUCTURARAG_LOCAL_AI_BASE_URL and STRUCTURARAG_LOCAL_AI_MODEL in the same terminal before launching the application.

The local app supports a SQLite-backed job queue and recent job history. It currently accepts PDF input only.


## Project Structure

~~~text
StructuraRAG/
├── index.py
├── requirements.txt
├── vercel.json
├── .python-version
├── .env.example
├── Tools_Formatting/
│   ├── analyze_gold_standard.py
│   ├── convert_pdf_batch.py
│   ├── gold_standard_rules.md
│   └── requirements.txt
├── docs/
│   ├── ARCHITECTURE.md
│   └── VERCEL_DEPLOYMENT.md
├── tests/
│   ├── test_document_preprocessing.py
│   └── test_vercel_deployment.py
├── .github/workflows/tests.yml
└── webapp/
    ├── app.py
    ├── start.ps1
    ├── requirements.txt
    └── static/
        ├── index.html
        └── logo.svg
~~~


## Quality Assurance and Limitations

The converter validates page markers, image-anchor integrity, balanced table markers, heading-depth limits, main-title count for AI output, source-token retention, and preservation of numeric tokens.

These checks reduce risk but do not prove semantic correctness. Review legal wording, negations, article references, dates, quantities, tables, and reading order before using output as a trusted knowledge source.

The Rule-Based provider now recognizes explicit title/BAB/letter/number patterns, but ambiguous headings are deliberately left as paragraphs. A complete independent structure-aware chunking engine, CDR, embedding generation, vector-database integration, and multi-format ingestion are not yet implemented. Pages grouped into model calls are processing batches, not final RAG chunks.


## Tests

~~~powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
~~~

GitHub Actions runs the regression tests on pushes and pull requests to main.


## Deploy to Vercel

The repository includes a root FastAPI entrypoint and Vercel configuration. Rule-Based is available without an AI provider; AI Lokal works when Vercel can reach a secure HTTPS model endpoint.

1. Import Ripanrz/StructuraRAG in Vercel.
2. Keep the Root Directory at the repository root.
3. Let Vercel detect the Python/FastAPI runtime and deploy.
4. Set STRUCTURARAG_ACCESS_PASSWORD before sharing the URL.
5. Open /api/health and test a small PDF using Rule-Based.

The hosted route processes synchronously, accepts 4 MiB by default, returns DOCX directly, and does not persist uploaded documents or job history. Large PDFs need an external worker/storage design.

See [the full Vercel deployment guide](docs/VERCEL_DEPLOYMENT.md) for environment variables, AI Lokal HTTPS setup, password protection, limits, and OAuth prerequisites.

## Privacy and Deployment

The local application is single-user and binds to loopback. The Vercel application is stateless for conversion requests. Set password protection or Vercel Deployment Protection before sharing the hosted URL. Keep API keys and model endpoint credentials in server-side environment variables.

The AI Cloud option uses the intended Sign in with ChatGPT OAuth path. It remains disabled for remote Vercel hosting until OpenAI approves remote-hosted ChatGPT plan inference and the complete secure token/session implementation is delivered. OAuth identity sign-in alone does not grant plan-based inference.

