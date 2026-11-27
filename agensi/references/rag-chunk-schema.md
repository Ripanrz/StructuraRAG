# RAG chunk JSONL schema

Each line in source.chunks.jsonl is one independent JSON object.

~~~json
{
  "chunk_id": "a3e31d5c8b21-00001",
  "document_id": "a3e31d5c8b21",
  "content": "Document title > Chapter one\n\nThe body text of this chunk...",
  "metadata": {
    "source_file": "source.pdf",
    "source_pages": [1, 2],
    "heading_path": [
      {"level": 0, "text": "Document title"},
      {"level": 1, "text": "Chapter one"}
    ],
    "block_types": ["paragraph", "table"],
    "image_anchors": [
      {"filename": "page_0001_image_001.png", "details": "page 1, y=120.0"}
    ],
    "sequence": 1,
    "table_parts": []
  }
}
~~~

## Design

- document_id is derived from the SHA-256 of the input PDF, so it is tied to file contents rather than only the basename.
- chunk_id combines document_id with a zero-padded sequence number.
- source_pages records page provenance.
- heading_path repeats active structural hierarchy so a chunk can be interpreted independently.
- block_types identifies paragraph/table/image-anchor events represented in the chunk.
- image_anchors are metadata only. They do not contain image bytes, captions, OCR text, or visual embeddings.
- Oversized detected tables are split by complete rows; a detected column header is repeated in each continuation part and table_parts records the continuation index.
- Chunk budget is measured in characters, not model tokens. Heading prefixes can add a small amount to body length.
- No overlap is added automatically. Chunks are grouped by heading path and the configured character budget.

## Downstream ingestion

A downstream RAG pipeline can use content as the text payload and preserve metadata as provenance. Select an embedding model and vector database separately. JSONL is not an embedding index.
