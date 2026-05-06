import json
import unittest
from unittest.mock import Mock, patch

from engine import generator


class PreflightOllamaTests(unittest.TestCase):
    def test_preflight_accepts_installed_models(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "models": [
                {"name": "qwen2.5:14b"},
                {"name": "llama3.1:8b-instruct-q4_K_M"},
            ]
        }

        with patch("engine.generator.requests.get", return_value=response) as mock_get:
            result = generator.preflight_ollama()

        mock_get.assert_called_once()
        self.assertIn("qwen2.5:14b", result["available_models"])

    def test_preflight_reports_missing_models(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"models": [{"name": "mistral:latest"}]}

        with patch("engine.generator.requests.get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "required model\\(s\\) are missing"):
                generator.preflight_ollama()

    def test_preflight_reports_unreachable_server(self):
        with patch("engine.generator.requests.get", side_effect=generator.requests.RequestException("boom")):
            with self.assertRaisesRegex(RuntimeError, "Could not reach Ollama"):
                generator.preflight_ollama()


if __name__ == "__main__":
    unittest.main()
