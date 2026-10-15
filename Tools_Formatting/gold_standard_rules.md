# Gold-standard structure rules

Extracted from the document-format audit; this file intentionally contains structural conventions only, not source-document text.

## Paragraph and hierarchy conventions

- Emit plain paragraphs with inline DSL tags; the reference DOCX paragraphs use Word `Normal` style rather than native heading styles.
- Preserve each original page boundary as `@PAGE <number>` and maintain source reading order.
- The observed hierarchy ends at `@h5`. Do not invent `@h6` or deeper levels.
- `@h0` is the main document title; generated output must contain exactly one.
- `@h1` marks `BAB` sections with Roman numerals.
- `@h2` marks lettered sections; `@h3` marks numbered subsections; `@h4` and `@h5` mark evidenced lower-level items.
- Classify headings from explicit markers and consistent sibling patterns. Keep unmatched prose as ordinary paragraphs; do not promote it based on visual guesswork alone.

## Table DSL

- Each generated table must use balanced `@TABLE_START` and `@TABLE_END` markers.
- Preserve merged/group-label rows when present rather than forcing them into the column header.
- Use `KOLOM:` for the header row when the source supports identifying one.
- Separate cells in data rows with `|`, preserve row order and empty cells, and do not invent values.

## Images and fidelity

- Preserve the source page and reading-order position of image anchors. Image markers are a documented extension because the audited corpus did not contain an observed image marker convention.
- Preserve substantive wording, identifiers, numbers, and punctuation. Remove only clearly repeated page furniture/noise.
- Structural validation does not prove legal-text accuracy; output requires human review.
