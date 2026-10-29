"""Tests for RepoGhost evidence assembly."""

from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from repoghost.evidence import collect_evidence, extract_search_terms
from repoghost.git_reader import GitReaderError


def run_git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        run_git(self.root, "init")
        run_git(self.root, "config", "user.name", "Test Maintainer")
        run_git(
            self.root,
            "config",
            "user.email",
            "maintainer@example.invalid",
        )

        (self.root / "tests").mkdir()

        (self.root / "cache.py").write_text(
            "def retry_request(client):\n"
            "    return client.fetch()\n",
            encoding="utf-8",
        )

        (self.root / "tests" / "test_cache.py").write_text(
            "def test_retry_request():\n"
            "    assert True\n",
            encoding="utf-8",
        )

        run_git(self.root, "add", ".")
        run_git(
            self.root,
            "commit",
            "-m",
            "Add request retry implementation and tests",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_report_contains_expected_sections(self) -> None:
        report = collect_evidence(
            self.root,
            "cache.py",
            1,
            2,
        )

        self.assertEqual(report["schema_version"], "1.0")
        self.assertEqual(report["target"]["file"], "cache.py")
        self.assertEqual(len(report["source_lines"]), 2)
        self.assertTrue(report["blame"])
        self.assertTrue(report["origin_commits"])
        self.assertTrue(report["related_commits"])
        self.assertIn("tests/test_cache.py", report["candidate_test_files"])
        self.assertTrue(report["limitations"])
        self.assertIn("committed_source_lines", report)
        self.assertIn("working_tree_status", report)
        self.assertIn("collection_warnings", report)
        json.dumps(report)

    def test_search_terms_are_deduplicated(self) -> None:
        terms = extract_search_terms(
            [
                {"content": "retry_request(client)"},
                {"content": "retry_request(client)"},
            ]
        )

        self.assertEqual(len(terms), len(set(terms)))
        self.assertIn("retry_request", terms)

    def test_report_does_not_claim_ai_inference(self) -> None:
        report = collect_evidence(
            self.root,
            "cache.py",
            1,
            2,
        )

        self.assertIn(
            "Commit history does not necessarily reveal author intent.",
            report["limitations"],
        )

    def test_report_shows_working_tree_and_head_versions(self) -> None:
        target = self.root / "cache.py"
        target.write_text(
            "def retry_request(client):\n"
            "    return client.fetch_updated()\n",
            encoding="utf-8",
        )

        report = collect_evidence(self.root, "cache.py", 1, 2)

        self.assertEqual(
            report["source_lines"][1]["content"],
            "    return client.fetch_updated()",
        )
        self.assertEqual(
            report["committed_source_lines"][1]["content"],
            "    return client.fetch()",
        )
        self.assertTrue(report["working_tree_status"])
        self.assertEqual(report["blame_source"], "working_tree")
        self.assertTrue(
            any(record["uncommitted"] for record in report["blame"])
        )

    def test_report_warns_when_history_search_fails(self) -> None:
        with patch(
            "repoghost.evidence.GitReader.search_history",
            side_effect=GitReaderError("simulated failure"),
        ):
            report = collect_evidence(self.root, "cache.py", 1, 2)

        self.assertTrue(report["collection_warnings"])
        self.assertIn("simulated failure", report["collection_warnings"][0])


if __name__ == "__main__":
    unittest.main()