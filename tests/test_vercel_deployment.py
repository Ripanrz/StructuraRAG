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

    def test_vercel_host_allowlist_includes_production_and_custom_domains(self) -> None:
        with patch.dict(
            os.environ,
            {
                "VERCEL_URL": "structurarag-preview-123.vercel.app",
                "VERCEL_BRANCH_URL": "structurarag-git-main-ripan.vercel.app",
                "VERCEL_PROJECT_PRODUCTION_URL": "structurarag.vercel.app",
                "STRUCTURARAG_ALLOWED_HOSTS": "custom.example.com,https://documents.example.org",
            },
            clear=True,
        ):
            self.assertEqual(
                app_module._allowed_vercel_hosts(),
                {
                    "structurarag-preview-123.vercel.app",
                    "structurarag-git-main-ripan.vercel.app",
                    "structurarag.vercel.app",
                    "custom.example.com",
                    "documents.example.org",
                },
            )

    def test_vercel_converter_imports_tempfile_workspace_dependency(self) -> None:
        self.assertTrue(hasattr(app_module, "tempfile"))
        self.assertTrue(hasattr(app_module.tempfile, "TemporaryDirectory"))

    def test_converter_failure_diagnostics_explain_missing_output(self) -> None:
        detail = app_module._converter_failure_detail(
            returncode=0,
            report={},
            stderr="",
            stdout="",
            output_exists=False,
        )
        self.assertIn("exit code 0", detail)
        self.assertIn("DOCX tidak ditemukan", detail)

    def test_converter_failure_diagnostics_preserve_stderr(self) -> None:
        detail = app_module._converter_failure_detail(
            returncode=1,
            report={},
            stderr="PyMuPDF failed during extraction",
            stdout="",
            output_exists=False,
        )
        self.assertEqual(detail, "PyMuPDF failed during extraction")

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
