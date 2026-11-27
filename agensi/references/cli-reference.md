# StructuraRAG CLI reference

## Runtime and dependencies

- Python 3.12 is the tested repository runtime.
- CLI dependencies: PyMuPDF and python-docx.
- Poppler is not required.
- OCR is optional and needs Tesseract plus Indonesian (ind) and English (eng) trained data.
- Install: python -m pip install -r Tools_Formatting/requirements.txt

## Examples

Single PDF:

~~~bash
python Tools_Formatting/convert_pdf_batch.py --input "./input/source.pdf" --output-dir "./output" --provider heuristic
~~~

PDF directory (non-recursive):

~~~bash
python Tools_Formatting/convert_pdf_batch.py --input-dir "./input" --output-dir "./output" --provider heuristic
~~~

## Options

| Option | Default | Details |
|---|---|---|
| --input PDF | None | One PDF; mutually exclusive with --input-dir. |
| --input-dir DIR | repository pdf-e-hukum folder | Reads only direct child PDF files, sorted by filename. |
| --output-dir DIR | docx-e-hukum-generated | Destination for outputs and report. |
| --provider NAME | heuristic | heuristic, local, openai, codex. |
| --chunk-max-chars N | 3500 | Approximate character budget per chunk; min 300. |
| --pages-per-call N | 2 | Page extraction / AI batch size; min 1. |
| --model MODEL | OPENAI_MODEL or gpt-4.1 | Direct OpenAI or optional Codex model selection. |
| --base-url URL | OPENAI_BASE_URL or OpenAI API URL | Direct OpenAI Responses API base URL. |
| --timeout SECONDS | 300 | Timeout for providers that use this option. |
| --allow-fallback | off | Opt into low-confidence heuristic fallback after AI errors. |
| --ocr | off | OCR pages with fewer than 40 extractable text characters. |
| --vision | off | OpenAI-only rendered-page image analysis. May add cost and data transfer. |
| --overwrite | off | Replaces existing DOCX outputs and sidecars. |
| --limit N | no limit | Process at most N PDFs; must be >= 1. |

## Environment variables

Local / OpenAI-compatible endpoint:
- STRUCTURARAG_LOCAL_AI_BASE_URL — endpoint base URL; CLI appends /chat/completions.
- STRUCTURARAG_LOCAL_AI_MODEL — model ID/name.
- STRUCTURARAG_LOCAL_AI_API_KEY — optional bearer token.

Direct OpenAI adapter:
- OPENAI_API_KEY or OPENAI_BEARER_TOKEN.
- OPENAI_MODEL and OPENAI_BASE_URL.

Codex CLI:
- CODEX_MODEL — optional model selection.
- CODEX_CLI — optional executable override.

Credentials must remain outside source files, generated reports, and skill packages.

## Exit codes

- 0: no per-file errors recorded. Existing outputs may have been skipped.
- 1: one or more per-file conversion errors.
- 2: argument/input path error or no PDFs selected.

## Output artifacts

For each source PDF:
- .docx — structured Word document with native heading styles and tables, and embedded supported images.
- .txt — canonical DSL text with page/heading/table/image markers.
- .chunks.jsonl — deterministic heading-aware JSONL records for downstream RAG ingestion.
- .manifest.json — source SHA-256, artifact names, counts, provider, and warnings.
- batch-report.jsonl — append-only per-input execution report.
