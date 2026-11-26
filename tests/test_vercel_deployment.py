from __future__ import annotations

import importlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

app_module = importlib.import_module("webapp.app")

ROOT = Path(__file__).resolve().parents[1]


class VercelDeploymentContractTests(unittest.TestCase):
    def test_vercel_entrypoint_exports_fastapi_app(self) -> None:
        entrypoint = (ROOT / "index.py").read_text(encoding="utf-8")
        self.assertIn("from webapp.app import app", entrypoint)

    def test_vercel_app_routes_and_bundled_files_exist(self) -> None:
        routes = {route.path for route in app_module.app.routes}
        self.assertIn("/", routes)
        self.assertIn("/api/health", routes)
        self.assertIn("/api/convert", routes)
        self.assertTrue((ROOT / "Tools_Formatting" / "convert_pdf_batch.py").is_file())
        self.assertTrue((ROOT / "webapp" / "static" / "index.html").is_file())
        self.assertTrue((ROOT / "webapp" / "static" / "logo.svg").is_file())

    def test_vercel_config_uses_string_globs_and_bundles_runtime_files(self) -> None:
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        function = config["functions"]["index.py"]
        self.assertEqual(function["maxDuration"], 300)

        includes = function["includeFiles"]
        excludes = function["excludeFiles"]
        self.assertIsInstance(includes, str)
        self.assertIsInstance(excludes, str)
        self.assertIn("Tools_Formatting/**", includes)
        self.assertIn("webapp/static/**", includes)
        self.assertIn("tests/**", excludes)
        self.assertIn("docs/**", excludes)

    def test_root_requirements_are_flat_and_cover_vercel_runtime(self) -> None:
        lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        active_lines = [
            line.partition("#")[0].strip()
            for line in lines
            if line.partition("#")[0].strip()
        ]
        self.assertFalse(
            any(line.startswith(("-r ", "--requirement")) for line in active_lines),
            "Vercel root requirements must not rely on nested -r includes.",
        )

        packages = {
            line.split("[", 1)[0].split(">=", 1)[0].split("==", 1)[0].lower()
            for line in active_lines
        }
        self.assertTrue(
            {"fastapi", "python-multipart", "pymupdf", "python-docx"}.issubset(packages)
        )

    def test_vercel_local_model_requires_https_endpoint(self) -> None:
        with patch.object(app_module, "IS_VERCEL", True):
            with patch.dict(os.environ, {"STRUCTURARAG_LOCAL_AI_BASE_URL": "http://localhost:11434/v1"}):
                self.assertFalse(app_module._local_ai_configured())
            with patch.dict(os.environ, {"STRUCTURARAG_LOCAL_AI_BASE_URL": "https://models.example.com/v1"}):
                self.assertTrue(app_module._local_ai_configured())

    def test_local_runtime_defaults_to_ollama_endpoint(self) -> None:
        with patch.object(app_module, "IS_VERCEL", False):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("STRUCTURARAG_LOCAL_AI_BASE_URL", None)
                self.assertEqual(
                    app_module._local_ai_base_url(),
                    "http://127.0.0.1:11434/v1",
                )


if __name__ == "__main__":
    unittest.main()
