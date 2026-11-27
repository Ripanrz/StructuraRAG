# Technical limitations and review checklist

## Implemented

- PDF is the only source format supported by the conversion CLI.
- PyMuPDF extracts page text, detected tables, embedded raster images, and selected vector-drawing regions.
- Repeated margin text and a few explicit standalone watermark/noise patterns are filtered.
- The deterministic Rule-Based path labels explicit title and numbering patterns.
- Optional AI providers may propose structure; strict page/image/table/text/number validation is applied to AI output.
- DOCX uses native Word heading styles and native Word tables; supported images are embedded at image anchors.
- DSL TXT and deterministic JSONL RAG chunks are generated as sidecars.
- The manifest records source hash, page count, image list, chunk count, provider, and warnings.

## Not implemented

- DOCX, XLSX, PPTX, HTML, or image input adapters.
- A universal reading-order engine for arbitrary multi-column, rotated, nested, or overlapping layouts.
- Perfect detection of borderless or visually drawn tables.
- Automatic OCR installation or OCR on Vercel.
- Image captioning, image OCR, multimodal chunk embeddings, or image retrieval.
- Tokenizer-aware chunk sizing, overlap, embedding generation, vector databases, retrieval, or reranking.
- Pixel-identical visual reproduction of the original PDF.
- Complete legal, regulatory, or semantic validation.

## Review checklist

1. Compare PDF page count with DSL @PAGE markers and manifest page count.
2. Check reading order, especially columns, sidebars, rotated text, footnotes, and page-spanning tables.
3. Verify numbers, dates, identifiers, negations, article/section references, and all table values.
4. Confirm DOCX contains expected headings, native tables, and embedded images.
5. Validate JSONL and preserve source_pages and heading_path metadata.
6. Review manifest warnings, batch-report errors, and scanned pages with insufficient text.
7. Never ingest unreviewed output as authoritative legal or regulated knowledge.

## Memory and performance

The converter processes extracted page events in page batches rather than retaining all pages' extracted block payloads. It still opens the PDF for page access and retains the final DSL and image path map until writing finishes. Very large PDFs, high-resolution images, and OCR can still consume substantial memory and disk. Split exceptional files into page ranges.
