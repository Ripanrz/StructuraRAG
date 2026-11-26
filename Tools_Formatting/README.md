# StructuraRAG — PDF to Structured RAG Document Tools

I built this tool around a legal-document reference corpus stored locally in `docx-e-hukum`. Run commands from the StructuraRAG repository root.

## Observed gold standard

`analyze_gold_standard.py` reads all 20 reference DOCX files (ignoring Microsoft Office `~$` lock files) and writes:

- `gold_standard_summary.md`: human-readable format specification.
- `gold_standard_profile.json`: per-document counts, inline tag counts, representative table rows, and paragraph examples.

The corpus contains 33,493 paragraphs. They are all Word `Normal` paragraphs; tables and tags are serialized inline. Observed hierarchy stops at `@h5`; do not generate `@h6+` without new reference evidence. See the summary for exact counts and examples.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r Tools_Formatting\requirements.txt
```

## Authentication choices

### OpenAI API key

Set an API key in the current PowerShell session. The key is read only by this local script and is sent as a Bearer credential to the configured Responses API endpoint. Never put it in a source file or browser bundle.

```powershell
$env:OPENAI_API_KEY = "your-project-api-key"
$env:OPENAI_MODEL = "gpt-4.1"
python Tools_Formatting\convert_pdf_batch.py --provider openai --limit 1

# Aktifkan pemahaman visual tabel/layout dengan mengirim render halaman ke Responses API
python Tools_Formatting\convert_pdf_batch.py --provider openai --vision --limit 1
```

Set `OPENAI_BASE_URL` for a compatible gateway. A short-lived platform bearer credential can be supplied with `OPENAI_BEARER_TOKEN` where your organization issues one.

### Codex sign-in (OAuth managed by Codex CLI)

Install the Codex CLI and complete its supported sign-in flow once (`codex --login` / `codex login`, depending on CLI version). Then the converter calls `codex exec` in read-only mode for each small page group; it does not read or copy Codex's private token files.

```powershell
codex --login
python Tools_Formatting\convert_pdf_batch.py --provider codex --limit 1
```

The Codex path requires a locally installed, already authenticated CLI. It is separate from direct Responses API requests. A ChatGPT/Codex login is not a bearer API key for an arbitrary application; use the CLI adapter when the user wants Codex account authentication.

## Run the batch

The default input is `pdf-e-hukum` and output is a separate `docx-e-hukum-generated` directory, so source references are never overwritten.

```powershell
# Convert a pilot file first; output DOCX, matching TXT, manifest, and batch report
python Tools_Formatting\convert_pdf_batch.py --provider openai --limit 1

# Convert all PDFs
python Tools_Formatting\convert_pdf_batch.py --provider openai

# Use Codex CLI OAuth instead
python Tools_Formatting\convert_pdf_batch.py --provider codex

# Offline deterministic fallback (no LLM; lower structural accuracy)
python Tools_Formatting\convert_pdf_batch.py --provider heuristic

# If the source is scanned, install Tesseract with ind+eng language packs first
python Tools_Formatting\convert_pdf_batch.py --provider openai --ocr --limit 1
```

For reruns, existing DOCX outputs are skipped unless `--overwrite` is supplied. LLM errors stop conversion by default; `--allow-fallback` explicitly opts into lower-confidence local extraction and marks it accordingly. The LLM path checks page/image/table markers, refuses unsupported `h6+`, requires exactly one `@h0`, and checks source-token retention before creating a DOCX. Use `--pages-per-call N` to tune context/cost. Start with `--limit 1` to review output before processing all source files.

## Pipeline and fidelity

1. PyMuPDF extracts each page's text blocks, table cells, image bytes, and vertical coordinates. Repeated short margin text, timestamps, and `E-hukum` watermark text are filtered.
2. Ordered blocks are sent to the chosen model in page groups, with the extracted hierarchy profile and prior heading context. The prompt applies the observed sibling-consistency rule and forbids unsupported `h6+` levels.
3. The converter verifies all `@PAGE` markers, every image anchor token exactly once, balanced table markers, the maximum observed heading level, one main title, and minimum content retention. Invalid output stops by default; fallback must be explicitly enabled.
4. Images are embedded in the DOCX in the paragraph position of their `@IMAGE` anchor; source vertical coordinates are retained in that marker and manifest. DOCX image placement is thus anchored in reading order; it cannot promise the same absolute page coordinates after Word reflow.
5. The output keeps each tag in plain `Normal` paragraphs to match the reference files, with inline table DSL instead of Word table objects.

The quality target is faithful structured text for review. `--vision` additionally sends rendered pages to a vision-capable Responses API model and increases image-token usage. `--ocr` uses local Tesseract for pages with little/no embedded text and requires Indonesian and English language packs. Substantial clusters of vector drawings are rasterized as diagram images. The tool does not claim semantic correctness solely because an LLM returned valid tags; inspect conversion warnings and review sample output before a production-wide run.

## Main files

- `analyze_gold_standard.py` — corpus profiler.
- `convert_pdf_batch.py` — batch conversion with API-key, Codex CLI, and offline providers.
- `gold_standard_summary.md` — extracted reference contract.
- `gold_standard_profile.json` — full machine-readable findings.
