# E-Hukum RAG Document Tools

**A Structure-Aware Document Preprocessing and Conversion Pipeline for Retrieval-Augmented Generation (RAG).**

I develop this project to transform document content into structured, labeled, and context-preserving representations for downstream Retrieval-Augmented Generation (RAG) pipelines.

My primary focus is not merely extracting text, but preserving logical hierarchy, reading order, tables, page boundaries, images, and contextual relationships during preprocessing.

The current implementation focuses on legal PDF processing, supported by a gold-standard DOCX profiling tool and a local web interface. I designed the project with future multi-format ingestion and structure-aware chunking in mind.

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

| Component | Current capability |
|---|---|
| PDF extraction | Text, layout blocks, tables, and embedded images |
| Scanned PDF | Optional OCR using Tesseract |
| Visual interpretation | Optional page-image processing through the OpenAI provider |
| Structural labeling | LLM-assisted document hierarchy reconstruction |
| Table preservation | Inline table DSL |
| Image preservation | Image anchors and embedded DOCX images |
| CLI output | DOCX, TXT/DSL, JSON manifest, JSONL batch report |
| Gold-standard profiling | DOCX corpus analysis |
| Local interface | FastAPI-based single-user web application |

## Supported Input and Output Formats

### Implemented input

| Format | Support | Processing method |
|---|---|---|
| PDF | Implemented | PyMuPDF extraction |
| Scanned PDF | Optional | Tesseract OCR |
| PDF containing tables | Implemented | PyMuPDF table detection and extraction |
| PDF containing images | Implemented | Image extraction and positional anchors |
| DOCX reference corpus | Implemented | WordprocessingML-based structural profiling |

### Planned input extensions

- DOCX document ingestion
- TXT and Markdown parsing
- HTML document parsing
- XLSX spreadsheet extraction
- PPTX presentation extraction

These formats are architectural targets, not currently supported general-purpose input formats.

### Current output

- DOCX: structured Word document.
- TXT: plain-text DSL representation.
- JSON: conversion manifest.
- JSONL: batch processing report.

The local web application currently offers DOCX download; the CLI converter produces the additional TXT, manifest, and batch-report artifacts.

## Processing Workflow

My current PDF conversion pipeline follows these stages:

1. **Document ingestion:** I load PDF files and inspect their pages using PyMuPDF.
2. **Layout-aware extraction:** I extract text blocks, coordinates, tables, embedded images, and relevant vector drawing regions.
3. **Noise filtering:** I identify repeated page headers, footers, watermarks, timestamps, and other predefined noise patterns.
4. **Optional OCR:** I use Tesseract with Indonesian and English language data for eligible scanned pages when OCR is enabled.
5. **Structural reconstruction:** I send ordered page content, extracted layout information, reference rules, and previous heading context to the selected processing provider.
6. **Structural validation:** I validate page markers, image anchors, table markers, heading-depth restrictions, main-title count, and source-token retention.
7. **Document serialization:** I generate DOCX and matching TXT/DSL files, together with a conversion manifest and batch report.
8. **Human review:** I review the generated output and warnings before considering it suitable for a production knowledge base.

## Structural Representation

I use an inline DSL to represent document structure.

| Label | Meaning |
|---|---|
| `@PAGE` | Original source-page boundary |
| `@h0` | Main document title |
| `@h1` | Chapter or BAB |
| `@h2` | Lettered section |
| `@h3` | Numbered subsection |
| `@h4` | Lower-level item |
| `@h5` | Deeper-level item |
| `@TABLE_START` | Table beginning |
| `KOLOM:` | Table header |
| `@TABLE_END` | Table ending |
| `@IMAGE` | Image location and reference |

The hierarchy is derived from the audited E-Hukum reference corpus. The current profile supports heading levels through `@h5`; I do not generate deeper levels without supporting structural evidence.

Example:

```text
@PAGE 1
@h0 UNDANG-UNDANG REPUBLIK INDONESIA
@h1 BAB I KETENTUAN UMUM
@h2 Pasal 1

Isi ketentuan hukum ...

@TABLE_START
KOLOM: Nomor | Keterangan
1 | Ketentuan pertama
2 | Ketentuan kedua
@TABLE_END
```

This is an illustrative DSL example, not a claim that every converted document has exactly this structure.

## Processing Providers

| Provider | Description |
|---|---|
| `openai` | Uses the OpenAI Responses API with an API key or supported bearer credential |
| `codex` | Uses an authenticated local Codex CLI session |
| `heuristic` | Uses deterministic local rules as a lower-confidence fallback |

The heuristic provider is intended for extraction diagnostics, not as an equivalent replacement for LLM-assisted structural reconstruction.

## Installation

I use Python and PowerShell for the current local workflow.

```powershell
git clone https://github.com/Ripanrz/e-hukum-rag-converter.git
cd e-hukum-rag-converter

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -r Tools_Formatting\requirements.txt
python -m pip install -r webapp\requirements.txt
```

Install the Codex CLI if I intend to use the Codex provider, then authenticate it:

```powershell
codex login
codex login status
```

## Command-Line Usage

### OpenAI provider

I configure the API credential in my current PowerShell session:

```powershell
$env:OPENAI_API_KEY = "your-api-key"

python Tools_Formatting\convert_pdf_batch.py --provider openai --limit 1
```

### Codex provider

```powershell
python Tools_Formatting\convert_pdf_batch.py --provider codex --limit 1
```

### Offline heuristic provider

```powershell
python Tools_Formatting\convert_pdf_batch.py --provider heuristic --limit 1
```

### Enable OCR

After installing Tesseract and its Indonesian and English language data:

```powershell
python Tools_Formatting\convert_pdf_batch.py --provider openai --ocr --limit 1
```

### Enable visual page interpretation

```powershell
python Tools_Formatting\convert_pdf_batch.py --provider openai --vision --limit 1
```

### Process all available PDF documents

```powershell
python Tools_Formatting\convert_pdf_batch.py --provider openai
```

By default, the converter uses `pdf-e-hukum` as its input directory and `docx-e-hukum-generated` as its output directory. Existing DOCX files are skipped unless I explicitly supply `--overwrite`.

## Run the Local Web Application

I start the local application from the project root:

```powershell
codex login
.\webapp\start.ps1
```

I then open http://127.0.0.1:8000.

The web application provides local PDF uploading, background conversion jobs, status tracking, warning notifications, DOCX download, and recent job history. It currently uses the local Codex CLI session and accepts PDF input only.

## Project Structure

```text
e-hukum-rag-converter/
├── Tools_Formatting/
│   ├── analyze_gold_standard.py
│   ├── convert_pdf_batch.py
│   ├── gold_standard_rules.md
│   ├── requirements.txt
│   └── README.md
├── webapp/
│   ├── app.py
│   ├── start.ps1
│   ├── requirements.txt
│   ├── README.md
│   └── static/
│       └── index.html
├── .gitignore
└── README.md
```

## Quality Assurance and Limitations

I use structural checks to reduce the risk of content loss and malformed output. These checks include source-page marker verification, image-anchor integrity, balanced table-marker counts, heading-level restrictions, main-title validation, and minimum source-token retention.

These checks do not establish complete semantic accuracy. LLM-generated heading classifications, legal terminology, numerical references, tables, and reading order still require human review.

The current version does not provide a complete independent semantic chunking engine, embedding generation, vector-database integration, or production-grade multi-user deployment. Page groups sent to a model are processing batches, not final RAG chunks.

## Roadmap

- [ ] Implement a unified intermediate document representation.
- [ ] Add DOCX, TXT, Markdown, and HTML input adapters.
- [ ] Add XLSX and PPTX extraction modules.
- [ ] Formalize the structural labeling grammar.
- [ ] Implement hierarchy-aware chunking.
- [ ] Add chunk-level metadata and provenance tracking.
- [ ] Introduce configurable token limits and overlap policies.
- [ ] Add JSON and JSONL chunk export.
- [ ] Add parser-specific regression tests.
- [ ] Evaluate extraction fidelity and structural accuracy.
- [ ] Improve job management and production deployment readiness.

## Privacy and Deployment

I designed the current web application for single-user local execution. It binds to loopback and does not provide production-grade multi-user authentication.

Source documents, generated files, local job data, and credential material must not be committed to the repository. I review `git status` before committing changes.

A public deployment requires authentication, authorization, durable storage, a persistent worker architecture, resource limits, and an appropriate credential-management strategy. The existing local application is not a ready-to-deploy public Vercel service.

## Project Philosophy

I believe reliable RAG begins with reliable document understanding.

A document should not be reduced to an arbitrary collection of text fragments. Its structure, hierarchy, references, and contextual relationships are part of the information itself.

My goal is to build a preprocessing engine that preserves these relationships as much as possible before documents enter downstream retrieval and generation systems.

---

**Developed by [Ripanrz](https://github.com/Ripanrz)**
