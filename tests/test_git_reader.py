"""Tests for read-only Git evidence retrieval."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from repoghost.git_reader import GitReader, GitReaderError
from repoghost.repository import (
    RepositoryError,
    find_repository_root,
    resolve_target_file,
)


def run_git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class GitReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        run_git(self.root, "init")
        run_git(self.root, "config", "user.name", "RepoGhost Test")
        run_git(
            self.root,
            "config",
            "user.email",
            "repoghost-test@example.invalid",
        )

        self.file_path = self.root / "cache.py"
        self.file_path.write_text(
            "def fetch():\n"
            "    return 'initial'\n",
            encoding="utf-8",
        )

        run_git(self.root, "add", "cache.py")
        run_git(self.root, "commit", "-m", "Add initial fetch")

        self.initial_commit = run_git(
            self.root, "rev-parse", "HEAD"
        )

        self.file_path.write_text(
            "def fetch():\n"
            "    return 'updated'\n",
            encoding="utf-8",
        )

        run_git(self.root, "add", "cache.py")
        run_git(self.root, "commit", "-m", "Update fetch result")

        self.update_commit = run_git(
            self.root, "rev-parse", "HEAD"
        )

        self.reader = GitReader(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_repository_root_is_detected(self) -> None:
        self.assertEqual(
            find_repository_root(self.root),
            self.root.resolve(),
        )

    def test_read_lines_returns_requested_source(self) -> None:
        lines = self.reader.read_lines("cache.py", 1, 2)

        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["content"], "def fetch():")
        self.assertEqual(lines[1]["content"], "    return 'updated'")

    def test_blame_identifies_latest_change(self) -> None:
        records = self.reader.blame("cache.py", 2, 2)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["commit"], self.update_commit)
        self.assertEqual(records[0]["line_number"], 2)

    def test_commit_details_include_actual_diff(self) -> None:
        details = self.reader.commit_details(self.update_commit)

        self.assertEqual(details["hash"], self.update_commit)
        self.assertEqual(details["subject"], "Update fetch result")
        self.assertIn("-    return 'initial'", details["diff"])
        self.assertIn("+    return 'updated'", details["diff"])

    def test_related_commits_include_both_changes(self) -> None:
        commits = self.reader.related_commits(
            "cache.py", 1, 2, limit=10
        )

        hashes = [commit["hash"] for commit in commits]

        self.assertIn(self.update_commit, hashes)
        self.assertIn(self.initial_commit, hashes)

    def test_history_search_finds_changed_term(self) -> None:
        matches = self.reader.search_history(
            "cache.py", "updated", limit=10
        )

        self.assertTrue(
            any(match["hash"] == self.update_commit for match in matches)
        )

    def test_working_tree_and_committed_source_are_distinguished(self) -> None:
        self.file_path.write_text(
            "def fetch():\n"
            "    return 'working tree'\n",
            encoding="utf-8",
        )

        working = self.reader.read_lines("cache.py", 2, 2)
        committed = self.reader.read_committed_lines("cache.py", 2, 2)

        self.assertEqual(working[0]["content"], "    return 'working tree'")
        self.assertEqual(committed[0]["content"], "    return 'updated'")
        self.assertTrue(self.reader.working_tree_status("cache.py"))

    def test_invalid_line_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(GitReaderError, "has 2 lines"):
            self.reader.read_lines("cache.py", 1, 3)

    def test_git_command_failure_is_reported(self) -> None:
        with self.assertRaises(GitReaderError):
            self.reader.run_git("not-a-real-git-subcommand")

    def test_untracked_and_missing_targets_are_rejected(self) -> None:
        untracked = self.root / "untracked.py"
        untracked.write_text("value = 1\n", encoding="utf-8")

        with self.assertRaisesRegex(RepositoryError, "not tracked"):
            resolve_target_file(self.root, "untracked.py")

        with self.assertRaisesRegex(RepositoryError, "does not exist"):
            resolve_target_file(self.root, "missing.py")

    def test_target_outside_repository_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            outside_file = Path(outside) / "external.py"
            outside_file.write_text("value = 1\n", encoding="utf-8")

            with self.assertRaisesRegex(RepositoryError, "inside"):
                resolve_target_file(self.root, str(outside_file))


if __name__ == "__main__":
    unittest.main()