"""Tests for user-facing target parsing and CLI errors."""

from argparse import ArgumentTypeError
from contextlib import redirect_stderr
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from repoghost.cli import main, parse_target


def run_git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class CLITests(unittest.TestCase):
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
        (self.root / "sample.py").write_text(
            "first = 1\nsecond = 2\n",
            encoding="utf-8",
        )
        run_git(self.root, "add", "sample.py")
        run_git(self.root, "commit", "-m", "Add sample")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_parse_target_rejects_bad_ranges(self) -> None:
        for value in (
            "sample.py:0-2",
            "sample.py:3-2",
            "sample.py:1-x",
            "sample.py:1-201",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ArgumentTypeError):
                    parse_target(value)

    def test_malformed_target_uses_argparse_error_not_traceback(self) -> None:
        stderr = io.StringIO()
        with patch.object(
            sys,
            "argv",
            ["repoghost", "inspect", "sample.py:bad"],
        ):
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("Target must use FILE:START-END", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_out_of_file_range_is_a_clear_cli_error(self) -> None:
        stderr = io.StringIO()
        with patch.object(
            sys,
            "argv",
            [
                "repoghost",
                "inspect",
                "sample.py:1-3",
                "--repo",
                str(self.root),
            ],
        ):
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    main()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("file has 2 lines", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
