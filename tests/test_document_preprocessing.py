from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Tools_Formatting.convert_pdf_batch import (  # noqa: E402
    fallback_page_dsl,
    is_noise,
    normalized,
    validate_llm_output,
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


if __name__ == "__main__":
    unittest.main()
