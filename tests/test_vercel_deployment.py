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

    def test_vercel_config_includes_converter_and_static_files(self) -> None:
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        function = config["functions"]["index.py"]
        self.assertEqual(function["maxDuration"], 300)
        includes = function["includeFiles"]
        self.assertTrue(any("Tools_Formatting/**" in item for item in includes))
        self.assertTrue(any("webapp/static/**" in item for item in includes))

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
