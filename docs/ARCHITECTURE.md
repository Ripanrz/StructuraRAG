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

Chunk after structural reconstruction, not at arbitrary page-call boundaries. Prefer natural units (for legal text: document → BAB → Pasal → ayat → item). Enforce a configurable token budget by splitting oversized nodes at the nearest safe child boundary. Preserve parent headings and provenance in every emitted chunk.

Do not merge unrelated sections simply to fill a token target. Use overlap only when a boundary genuinely needs additional context, and record the overlap policy so duplicated text can be recognized downstream.

## Quality gates

At minimum, evaluate:

- Text retention and exact preservation of numbers, dates, identifiers, and negations.
- Reading-order accuracy.
- Heading/section precision, recall, and F1 by label.
- Table row/column and cell-value accuracy.
- Source provenance completeness.
- Chunk boundary quality and token-budget compliance.
- Latency, memory use, API cost, and failure rate per provider.

The current repository implements a PDF-focused extraction pipeline, LLM-assisted reconstruction, a heuristic fallback, and DOCX/TXT/manifest output. The multi-format CDR and independent structure-aware chunker described here are target architecture, not claims about current capabilities.
