from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "tools" / "build_agensi_package.py"
SPEC = importlib.util.spec_from_file_location("build_agensi_package", BUILDER_PATH)
builder = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(builder)


class AgensiPackageTests(unittest.TestCase):
    def test_skill_frontmatter_requires_name_and_description(self) -> None:
        builder.validate_frontmatter(
            "---\nname: sample-skill\ndescription: Convert PDF documents.\n---\n# Skill\n"
        )
        with self.assertRaisesRegex(ValueError, "description"):
            builder.validate_frontmatter("---\nname: sample-skill\n---\n# Skill\n")

    def test_builder_places_skill_at_archive_root_and_excludes_noise(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "skill"
            (source / "references").mkdir(parents=True)
            (source / "scripts").mkdir()
            (source / "__pycache__").mkdir()
            (source / "SKILL.md").write_text(
                "---\nname: sample-skill\ndescription: Convert PDFs to DOCX.\n---\n# Skill\n",
                encoding="utf-8",
            )
            (source / "LICENSE").write_text("MIT License\n", encoding="utf-8")
            (source / "references" / "guide.md").write_text("# Guide\n", encoding="utf-8")
            (source / "scripts" / "verify.py").write_text("print('ok')\n", encoding="utf-8")
            (source / "__pycache__" / "module.pyc").write_bytes(b"binary")
            output = root / "dist" / "skill.zip"

            report = builder.build_archive(source, output)
            self.assertTrue(output.is_file())
            self.assertEqual(report["file_count"], 4)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertIn("SKILL.md", names)
                self.assertIn("LICENSE", names)
                self.assertIn("references/guide.md", names)
                self.assertIn("scripts/verify.py", names)
                self.assertFalse(any("__pycache__" in name for name in names))
                self.assertIsNone(archive.testzip())

    def test_builder_rejects_scripts_at_or_above_twenty_kib(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "references").mkdir()
            (root / "scripts").mkdir()
            (root / "SKILL.md").write_text(
                "---\nname: sample-skill\ndescription: Example.\n---\n", encoding="utf-8"
            )
            (root / "references" / "guide.md").write_text("Guide", encoding="utf-8")
            (root / "scripts" / "large.py").write_text("x" * builder.MAX_SCRIPT_BYTES, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "smaller than 20 KB"):
                builder.build_archive(root, root / "out.zip")

    def test_builder_rejects_token_like_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "references").mkdir()
            (root / "scripts").mkdir()
            (root / "SKILL.md").write_text(
                "---\nname: sample-skill\ndescription: Example.\n---\n", encoding="utf-8"
            )
            (root / "references" / "guide.md").write_text("sk-" + "A" * 32, encoding="utf-8")
            (root / "scripts" / "verify.py").write_text("print('ok')", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "credential detected"):
                builder.build_archive(root, root / "out.zip")


if __name__ == "__main__":
    unittest.main()
