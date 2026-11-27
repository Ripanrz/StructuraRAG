from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from docx import Document

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Tools_Formatting.convert_pdf_batch import (  # noqa: E402
    _is_blank_raster,
    _reading_order_keyed,
    build_rag_chunks,
    fallback_page_dsl,
    is_noise,
    main,
    normalized,
    sha256_file,
    validate_llm_output,
    write_docx,
)


class DocumentPreprocessingTests(unittest.TestCase):
    def test_normalized_collapses_spacing_and_nonbreaking_spaces(self) -> None:
        self.assertEqual(normalized("  Pasal\u00a01  \n  ayat   (1) "), "Pasal 1\nayat (1)")

    def test_standalone_watermark_is_noise(self) -> None:
        self.assertTrue(is_noise(" E-Hukum ", set()))

    def test_substantive_text_mentioning_e_hukum_is_preserved(self) -> None:
        text = "Dokumen ini dipublikasikan melalui platform E-Hukum untuk masyarakat."
        self.assertFalse(is_noise(text, set()))

    def test_heuristic_fallback_preserves_table_cells(self) -> None:
        events = [
            {"kind": "text", "text": "BAB I KETENTUAN UMUM"},
            {"kind": "table", "rows": [["No", "Uraian"], ["1", "Ketentuan A"]]},
        ]
        dsl = fallback_page_dsl(1, events)
        self.assertIn("@PAGE 1", dsl)
        self.assertIn("@TABLE_START", dsl)
        self.assertIn("KOLOM: No | Uraian", dsl)
        self.assertIn("1 | Ketentuan A", dsl)
        self.assertIn("@TABLE_END", dsl)

    def test_rule_based_mode_labels_explicit_hierarchy(self) -> None:
        events = [{
            "kind": "text",
            "text": "PERATURAN MENTERI CONTOH\nBAB I KETENTUAN UMUM\nA. Ruang Lingkup\n1. Tujuan\nb. Ketentuan",
        }]
        dsl = fallback_page_dsl(1, events)
        self.assertIn("@h0 PERATURAN MENTERI CONTOH", dsl)
        self.assertIn("@h1 BAB I KETENTUAN UMUM", dsl)
        self.assertIn("@h2 A. Ruang Lingkup", dsl)
        self.assertIn("@h3 1. Tujuan", dsl)
        self.assertIn("@h4 b. Ketentuan", dsl)

    def test_validator_preserves_heading_text_and_legal_numbers(self) -> None:
        source = "Pasal 12 mengatur masa berlaku selama 2 tahun."
        events = {1: [{"kind": "text", "text": source}]}
        valid = "@PAGE 1\n@h2 Pasal 12\nMengatur masa berlaku selama 2 tahun."
        self.assertEqual(validate_llm_output(valid, events), valid)

    def test_validator_rejects_changed_article_number(self) -> None:
        source = "Pasal 12 mengatur masa berlaku selama 2 tahun."
        events = {1: [{"kind": "text", "text": source}]}
        changed = "@PAGE 1\n@h2 Pasal 13\nMengatur masa berlaku selama 2 tahun."
        with self.assertRaisesRegex(ValueError, "preservasi angka"):
            validate_llm_output(changed, events)

    def test_validator_requires_each_image_anchor_exactly_once(self) -> None:
        events = {
            1: [
                {"kind": "text", "text": "Gambar berikut menjelaskan struktur."},
                {"kind": "image", "token": "P1I1", "filename": "diagram.png", "anchor_y": 100.0},
            ]
        }
        missing = "@PAGE 1\n@h0 Dokumen\nGambar berikut menjelaskan struktur."
        with self.assertRaisesRegex(ValueError, "Marker gambar"):
            validate_llm_output(missing, events)

    def test_blank_raster_filter_detects_uniform_images_but_keeps_figures(self) -> None:
        blank = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
        blank.set_rect(blank.irect, (0, 0, 0))
        self.assertTrue(_is_blank_raster(blank.tobytes("png")))

        figure = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
        figure.set_rect(fitz.IRect(0, 0, 4, 8), (255, 0, 0))
        figure.set_rect(fitz.IRect(4, 0, 8, 8), (0, 255, 0))
        self.assertFalse(_is_blank_raster(figure.tobytes("png")))
        self.assertFalse(_is_blank_raster(b"not-an-image"))

    def test_two_column_reading_order_keeps_full_width_heading_between_regions(self) -> None:
        from Tools_Formatting.convert_pdf_batch import _reading_order_keyed

        events = [
            {"kind": "text", "text": "left-before", "y": 10, "x": 10, "_bbox": (10, 10, 200, 30)},
            {"kind": "text", "text": "right-before", "y": 12, "x": 320, "_bbox": (320, 12, 500, 30)},
            {"kind": "text", "text": "left-next", "y": 80, "x": 10, "_bbox": (10, 80, 200, 100)},
            {"kind": "text", "text": "right-next", "y": 82, "x": 320, "_bbox": (320, 82, 500, 100)},
            {"kind": "text", "text": "section-title", "y": 140, "x": 10, "_bbox": (10, 140, 500, 165)},
            {"kind": "text", "text": "left-after", "y": 190, "x": 10, "_bbox": (10, 190, 200, 210)},
            {"kind": "text", "text": "right-after", "y": 192, "x": 320, "_bbox": (320, 192, 500, 212)},
        ]
        ordered = _reading_order_keyed(events, 520)
        labels = [event["text"] for event in ordered]
        self.assertLess(labels.index("left-before"), labels.index("right-before"))
        self.assertLess(labels.index("right-before"), labels.index("section-title"))
        self.assertLess(labels.index("section-title"), labels.index("left-after"))
        self.assertLess(labels.index("left-after"), labels.index("right-after"))

    def test_rag_chunks_keep_heading_provenance_and_do_not_index_image_placeholder(self) -> None:
        dsl = (
            "@PAGE 1\n@h0 Document Title\n@h1 Chapter One\n"
            "First paragraph.\n@IMAGE [figure.png | page 1, y=100]\n"
            "Second paragraph.\n@PAGE 2\n@h1 Chapter Two\nThird paragraph."
        )
        chunks = build_rag_chunks(dsl, "source.pdf", max_chars=3500, document_id="a1b2c3")
        self.assertEqual(len(chunks), 2)
        self.assertIn("Document Title > Chapter One", chunks[0]["content"])
        self.assertNotIn("[Image anchor:", chunks[0]["content"])
        self.assertEqual(chunks[0]["metadata"]["source_pages"], [1])
        self.assertEqual(chunks[0]["metadata"]["image_anchors"][0]["filename"], "figure.png")
        self.assertEqual(chunks[1]["metadata"]["heading_path"][-1]["text"], "Chapter Two")

    def test_oversized_table_chunks_repeat_column_header_and_record_parts(self) -> None:
        rows = "\n".join(f"{number} | Entry {number} with enough description" for number in range(1, 31))
        dsl = (
            "@PAGE 1\n@h0 Document\n@h1 Data\n@TABLE_START\n"
            "KOLOM: Number | Description\n" + rows + "\n@TABLE_END"
        )
        chunks = build_rag_chunks(dsl, "table.pdf", max_chars=350, document_id="tablehash")
        table_chunks = [chunk for chunk in chunks if "table" in chunk["metadata"]["block_types"]]
        self.assertGreater(len(table_chunks), 1)
        self.assertTrue(all("KOLOM: Number | Description" in chunk["content"] for chunk in table_chunks))
        self.assertTrue(all(chunk["metadata"]["table_parts"] for chunk in table_chunks))
        self.assertEqual(
            [part["part"] for chunk in table_chunks for part in chunk["metadata"]["table_parts"]],
            list(range(1, len(table_chunks) + 1)),
        )

    def test_docx_renderer_uses_native_headings_tables_and_embedded_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
            image.set_rect(fitz.IRect(0, 0, 4, 8), (255, 0, 0))
            image.set_rect(fitz.IRect(4, 0, 8, 8), (0, 255, 0))
            image_path = root / "figure.png"
            image.save(image_path)
            output = root / "result.docx"
            dsl = (
                "@PAGE 1\n@h0 Document\n@h1 Section\nText paragraph.\n"
                "@TABLE_START\nKOLOM: A | B\n1 | 2\n@TABLE_END\n"
                "@IMAGE [figure.png | page 1, y=10]"
            )
            write_docx(dsl, output, {"figure.png": image_path})
            document = Document(output)
            paragraph_text = [paragraph.text for paragraph in document.paragraphs]
            self.assertIn("Document", paragraph_text)
            self.assertIn("Text paragraph.", paragraph_text)
            self.assertNotIn("@PAGE 1", paragraph_text)
            self.assertNotIn("@h0 Document", paragraph_text)
            self.assertEqual(len(document.tables), 1)
            self.assertEqual(document.tables[0].rows[1].cells[1].text, "2")
            self.assertEqual(len(document.inline_shapes), 1)

    def test_cli_single_pdf_writes_docx_dsl_chunks_and_manifest_without_ai_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.pdf"
            pdf = fitz.open()
            page = pdf.new_page()
            page.insert_text((72, 72), "SAMPLE REGULATION")
            page.insert_text((72, 110), "BAB I GENERAL")
            page.insert_text((72, 140), "1. Purpose and scope")
            page.insert_text((72, 170), "This is a deterministic test paragraph.")
            pdf.save(source)
            pdf.close()

            output_dir = root / "output"
            stdout = io.StringIO()
            with patch("sys.argv", [
                "convert_pdf_batch.py", "--input", str(source),
                "--output-dir", str(output_dir), "--provider", "heuristic",
                "--chunk-max-chars", "300",
            ]), contextlib.redirect_stdout(stdout):
                exit_code = main()

            self.assertEqual(exit_code, 0)
            self.assertIn("1 converted, 0 skipped, 0 failed", stdout.getvalue())
            docx_path = output_dir / "sample.docx"
            self.assertTrue(docx_path.is_file())
            self.assertTrue(docx_path.with_suffix(".txt").is_file())
            chunks_path = docx_path.with_suffix(".chunks.jsonl")
            self.assertTrue(chunks_path.is_file())
            self.assertTrue(docx_path.with_suffix(".manifest.json").is_file())
            chunks = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(chunks)
            self.assertEqual(chunks[0]["metadata"]["source_file"], "sample.pdf")
            self.assertFalse((output_dir / ".work" / "sample_images").exists())

    def test_sha256_file_hashes_incrementally_and_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.pdf"
            payload = b"StructuraRAG" * 1000
            path.write_bytes(payload)
            self.assertEqual(sha256_file(path), __import__("hashlib").sha256(payload).hexdigest())


if __name__ == "__main__":
    unittest.main()
