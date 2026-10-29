"""Tests for the optional local Ollama integration."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch

from repoghost.ai_explainer import (
    build_prompt,
    explain,
    validate_citations,
)


COMMIT = "a" * 40
EVIDENCE = {
    "schema_version": "1.0",
    "target": {
        "file": "src/cache.py",
        "start_line": 3,
        "end_line": 4,
    },
    "source_lines": [
        {"line_number": 3, "content": "def fetch(): pass"},
        {"line_number": 4, "content": "    return cache"},
    ],
    "blame": [{"commit": COMMIT, "filename": "src/cache.py"}],
    "origin_commits": [{"hash": COMMIT}],
    "candidate_test_files": ["tests/test_cache.py"],
}
ANSWER = (
    f"## Finding\nThe code changed in {COMMIT} at src/cache.py:4.\n"
    "## Evidence\nThe supplied lines show the cache return.\n"
    "## Possible explanation\nCaching may avoid repeated work.\n"
    "## What remains unknown\nThe author's motivation is unknown.\n"
    "## Suggested next checks\nReview tests/test_cache.py."
)


class AIExplainerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.evidence_path = Path(self.temp_dir.name) / "evidence.json"
        self.evidence_path.write_text(
            json.dumps(EVIDENCE),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def call_with_response(self, response: bytes) -> str:
        opener = Mock()
        opener.open.return_value = io.BytesIO(response)
        with patch(
            "repoghost.ai_explainer.build_opener",
            return_value=opener,
        ):
            return explain(self.evidence_path, "test-model")

    def test_valid_response_and_citations(self) -> None:
        answer = self.call_with_response(
            json.dumps({"response": ANSWER}).encode("utf-8")
        )

        self.assertEqual(answer, ANSWER)

    def test_empty_response_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "empty explanation"):
            self.call_with_response(b'{"response":"  "}')

    def test_invalid_response_json_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "invalid response JSON"):
            self.call_with_response(b"not-json")

    def test_connection_failure_is_reported(self) -> None:
        opener = Mock()
        opener.open.side_effect = URLError("connection refused")
        with patch("repoghost.ai_explainer.build_opener", return_value=opener):
            with self.assertRaisesRegex(RuntimeError, "Could not reach"):
                explain(self.evidence_path, "test-model")

    def test_timeout_is_reported(self) -> None:
        opener = Mock()
        opener.open.side_effect = TimeoutError()
        with patch("repoghost.ai_explainer.build_opener", return_value=opener):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                explain(self.evidence_path, "test-model", timeout=2)

    def test_missing_model_http_error_is_reported(self) -> None:
        opener = Mock()
        opener.open.side_effect = HTTPError(
            "http://localhost:11434/api/generate",
            404,
            "Not Found",
            None,
            io.BytesIO(b""),
        )
        with patch("repoghost.ai_explainer.build_opener", return_value=opener):
            with self.assertRaisesRegex(RuntimeError, "model 'test-model'"):
                explain(self.evidence_path, "test-model")

    def test_custom_local_endpoint_is_used_without_proxy(self) -> None:
        opener = Mock()
        opener.open.return_value = io.BytesIO(
            json.dumps({"response": ANSWER}).encode("utf-8")
        )
        with patch(
            "repoghost.ai_explainer.build_opener",
            return_value=opener,
        ) as build_opener:
            explain(
                self.evidence_path,
                "test-model",
                endpoint="http://127.0.0.1:12345",
            )

        self.assertEqual(
            opener.open.call_args.args[0].full_url,
            "http://127.0.0.1:12345/api/generate",
        )
        self.assertEqual(build_opener.call_args.args[0].proxies, {})

    def test_invalid_evidence_json_is_reported(self) -> None:
        self.evidence_path.write_text("{", encoding="utf-8")

        with self.assertRaises(json.JSONDecodeError):
            explain(self.evidence_path, "test-model")

    def test_non_object_evidence_json_is_rejected(self) -> None:
        self.evidence_path.write_text("[]", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "top-level object"):
            explain(self.evidence_path, "test-model")

    def test_fabricated_commit_hash_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "not uniquely present"):
            validate_citations(ANSWER.replace(COMMIT, "b" * 40), EVIDENCE)

    def test_missing_commit_citation_is_rejected(self) -> None:
        answer = "No commit hash is cited."

        with self.assertRaisesRegex(ValueError, "must cite at least one"):
            validate_citations(answer, EVIDENCE)

    def test_unambiguous_abbreviated_hash_is_accepted(self) -> None:
        validate_citations(
            f"Commit {COMMIT[:7]} changed src/cache.py:3.",
            EVIDENCE,
        )

    def test_ambiguous_abbreviated_hash_is_rejected(self) -> None:
        other_commit = "a" * 39 + "b"
        evidence = {
            **EVIDENCE,
            "related_commits": [{"hash": other_commit}],
        }

        with self.assertRaisesRegex(ValueError, "not uniquely present"):
            validate_citations(f"Commit {COMMIT[:7]} changed code.", evidence)

    def test_invalid_path_and_line_citations_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "file path not present"):
            validate_citations(
                f"Commit {COMMIT} changed src/fake.py:4.",
                EVIDENCE,
            )

    def test_path_with_spaces_is_validated_against_report(self) -> None:
        spaced_path = "src/cache folder.py"
        evidence = {
            **EVIDENCE,
            "target": {
                "file": spaced_path,
                "start_line": 3,
                "end_line": 4,
            },
            "blame": [{"commit": COMMIT, "filename": spaced_path}],
        }

        validate_citations(
            f"Commit {COMMIT} cites {spaced_path}:3.",
            evidence,
        )

    def test_dotted_code_symbol_is_not_mistaken_for_a_path(self) -> None:
        validate_citations(
            f"Commit {COMMIT} introduced a call to self.assertEqual.",
            EVIDENCE,
        )

        with self.assertRaisesRegex(ValueError, "outside the report"):
            validate_citations(
                f"Commit {COMMIT} changed src/cache.py:5.",
                EVIDENCE,
            )

    def test_remote_endpoint_is_rejected_before_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "Remote Ollama endpoints"):
            explain(
                self.evidence_path,
                "test-model",
                endpoint="https://example.com/api/generate",
            )

    def test_prompt_distinguishes_fact_hypothesis_and_unknown(self) -> None:
        prompt = build_prompt(EVIDENCE)

        self.assertIn("plausible", prompt)
        self.assertIn("unknowns", prompt)
        self.assertIn("Never state author intent as fact", prompt)
        self.assertIn("prefer a", prompt)
        self.assertIn("full hash", prompt)
        self.assertIn("only source of facts", prompt)


if __name__ == "__main__":
    unittest.main()
