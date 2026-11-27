# StructuraRAG Architecture

## Product principle

StructuraRAG is a document-structuring and preprocessing system, not an LLM wrapper. Its core should be deterministic, inspectable, and testable. AI is an optional interpretation layer for ambiguous content—not a prerequisite for every file.

## Recommended pipeline

```text
Source file
    |
Format adapter (PDF / DOCX / TXT / HTML / XLSX / PPTX)
    |
Extraction + layout + provenance
    |
Canonical Document Representation (CDR)
    |
Rule engine (normalization, hierarchy, tables, sections)
    |
Confidence / unresolved-region detection
    |                         |
    | high confidence         | ambiguous
    |                         v
    |                    Optional AI assist
    |                         |
    +-----------+-------------+
                |
        Deterministic validation
                |
      Structure-aware chunking
                |
    DOCX / TXT / JSON / JSONL export
                |
       Optional embedding / index
```

## The three product modes

The diagram above is the target architecture, not a claim that every adapter is implemented. The current CLI accepts PDF only. It extracts page text, detected tables, raster images, and selected vector regions; the deterministic Rule-Based path reconstructs explicit hierarchy and emits DOCX, DSL TXT, a manifest, and heading-aware JSONL chunks. Embeddings and vector storage remain external.

The product interface exposes three choices, but they have different runtime requirements:

| Mode | Current state | Runtime contract |
|---|---|---|
| Rule-Based | Available | Local deterministic rules; no model credential |
| AI Lokal | Available | Ollama or an OpenAI-compatible endpoint controlled by the operator |
| AI Cloud | Gated | Intended Sign in with ChatGPT OAuth and eligible ChatGPT plan inference |

### Rule-Based

The baseline should own tasks that are explicit and reproducible: source order, page markers, table delimiters, normalization, known numbering patterns, validation, and serialization. The current implementation recognizes a small set of document-title and heading patterns. It is intentionally conservative and still requires a broader grammar and a labeled benchmark.

### AI Lokal

The current local provider speaks the OpenAI-compatible chat-completions protocol. It can call Ollama or another self-hosted model endpoint. On a local installation, the default is http://127.0.0.1:11434/v1. On Vercel, a model endpoint must be reachable from the hosted Function over HTTPS; a user's laptop loopback address is not reachable from Vercel.

### AI Cloud (OAuth)

The planned cloud mode is Sign in with ChatGPT. OAuth identity sign-in and permission to use a ChatGPT plan for inference are separate grants. Remote-hosted deployments must complete OpenAI's approval process for the hosted use case. The Vercel UI therefore keeps this option disabled until approval, token/session persistence, permission validation, refresh, revocation, and per-user authorization have been implemented and tested.

Do not treat a Codex CLI token or an identity-only OAuth token as a general API key. Never put access or refresh tokens in browser storage, logs, URLs, or source control.

## Deployment model

The local application uses SQLite and an in-process queue for a single-user local workflow. A completed local job can download the DOCX and a ZIP containing the DOCX, DSL TXT, JSONL chunks, and manifest. The Vercel application uses a separate stateless conversion route: it processes one small PDF per request in a temporary directory and returns DOCX by default, with an optional RAG Bundle ZIP. Vercel does not promise durable job history, retries, or background processing. Large/batch workloads require private object storage, a durable queue, and an independent worker service.

## What should be rule-based?

Use deterministic parsers and rules wherever the source contains explicit structure or stable conventions:

- File identification, decoding, normalization, and metadata extraction.
- PDF text/image/table extraction and page coordinates.
- DOCX headings, paragraphs, lists, tables, and hyperlinks.
- HTML DOM structure, headings, lists, tables, and semantic tags.
- TXT and Markdown headings, delimiters, and line structure.
- XLSX sheets, ranges, formulas/cached values, and cell coordinates.
- PPTX slide order, text boxes, tables, and speaker notes.
- Known legal numbering patterns such as BAB, Pasal, ayat, huruf, and angka.
- Page/slide/sheet provenance, chunk boundaries, schema validation, and output serialization.

Rule-based processing is predictable and inexpensive, but must not pretend to understand a structure that is not explicit. Store uncertain regions as unknown rather than inventing a hierarchy.

## Where can AI help?

Use an optional model only when deterministic signals are insufficient:

- Distinguishing headings from ordinary prose in inconsistent layouts.
- Resolving multi-column reading order or unusual document layouts.
- Interpreting noisy scanned tables and complex diagrams.
- Classifying ambiguous sections using surrounding context.
- Suggesting semantic labels when formatting conventions are absent.

AI output must be treated as a proposal. Validate it against extracted text, page geometry, allowed labels, numbering patterns, and source provenance. Preserve the original text and make every transformation traceable.

## Do we need to train a model?

Not initially. A trained classifier is justified only after building a labeled evaluation corpus and showing that the rule-based baseline fails on recurring cases.

A sensible progression is:

1. Establish deterministic parsers and explicit grammar rules.
2. Collect representative examples and manually label structural roles.
3. Measure a rule-based baseline by document type.
4. Route only low-confidence cases to optional AI.
5. Train a lightweight classifier only if enough stable labeled examples exist and it measurably improves accuracy, cost, latency, or offline operation.

Potential later models include a compact text classifier for paragraph roles or a layout-aware model for difficult page regions. Do not train a general-purpose language model for this preprocessing task.

## Canonical Document Representation

All format adapters should emit the same typed block model before labeling or chunking. A minimal block should carry:

| Field | Purpose |
|---|---|
| `document_id` | Stable document identity |
| `block_id` | Stable block identity |
| `block_type` | paragraph, heading, table, image, list, page break, etc. |
| `text` / `content` | Extracted text or structured payload |
| `source` | File name, format, page/slide/sheet, coordinates |
| `order` | Reading-order index |
| `parent_id` | Parent structural node, when known |
| `label` | Structural role and labeling method |
| `confidence` | Rule/AI confidence or null when unavailable |

Keep raw extraction separate from normalized text and inferred labels. Never discard the original content merely because a later stage has classified it.

## Structure-aware chunking

The current CLI includes a deterministic heading-aware chunker after DSL reconstruction. It groups adjacent blocks by active heading path and a configurable character budget; records source filename, page provenance, heading path, block types, and image-anchor metadata; and splits oversized detected tables by complete rows while repeating the detected column header. Each chunk is emitted as one JSON object in a JSONL sidecar.

The current chunker does not use a model tokenizer, add overlap, resolve semantic boundaries, or estimate retrieval quality. It is not yet backed by a typed Canonical Document Representation (CDR). For legal documents, prefer natural units (document → BAB → Pasal → ayat → item) and review every split against the source. Do not treat character count as a token budget.

## Quality gates

At minimum, evaluate:

- Text retention and exact preservation of numbers, dates, identifiers, and negations.
- Reading-order accuracy.
- Heading/section precision, recall, and F1 by label.
- Table row/column and cell-value accuracy.
- Source provenance completeness.
- Chunk boundary quality and token-budget compliance.
- Latency, memory use, API cost, and failure rate per provider.

The current repository implements a PDF-focused extraction pipeline, conservative Rule-Based reconstruction, optional LLM-assisted reconstruction, strict AI-output validation, a native Word DOCX renderer, DSL TXT, deterministic heading-aware JSONL chunks, and a source manifest. Multi-format CDR adapters, semantic/tokenizer-aware chunking, embeddings, vector storage, and retrieval remain future work.
