"""Read-only Git history collection for RepoGhost."""

from pathlib import Path
import re
import subprocess
from typing import Any


class GitReaderError(Exception):
    """Raised when a Git evidence query fails."""


class GitReader:
    """Collect bounded evidence from a local Git repository."""

    def __init__(self, repository_root: Path, timeout: int = 15):
        self.root = repository_root.resolve()
        self.timeout = timeout

    def run_git(self, *args: str) -> str:
        """Run a bounded Git command without invoking a shell."""
        command = [
            "git",
            "--no-pager",
            "--literal-pathspecs",
            "-C",
            str(self.root),
            *args,
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GitReaderError(
                "Git was not found. Install Git and ensure it is in PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise GitReaderError(
                f"Git command timed out: {args[0] if args else 'unknown'}"
            ) from exc

        if result.returncode != 0:
            error = result.stderr.strip() or "Unknown Git error"
            raise GitReaderError(error[:1000])

        return result.stdout

    def read_lines(
        self,
        relative_path: str,
        start_line: int,
        end_line: int,
    ) -> list[dict[str, Any]]:
        """Read the requested lines from the working-tree file."""
        file_path = (self.root / relative_path).resolve()

        try:
            file_path.relative_to(self.root)
        except ValueError as exc:
            raise GitReaderError("File path escapes the repository.") from exc

        try:
            content = file_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise GitReaderError(
                f"Unable to read target file: {exc}"
            ) from exc

        lines = content.splitlines()

        if start_line < 1 or end_line < start_line:
            raise GitReaderError("Invalid line range.")

        if end_line > len(lines):
            raise GitReaderError(
                f"Requested line {end_line}, but the file has "
                f"{len(lines)} lines."
            )

        return [
            {
                "line_number": number,
                "content": lines[number - 1],
            }
            for number in range(start_line, end_line + 1)
        ]

    def read_committed_lines(
        self,
        relative_path: str,
        start_line: int,
        end_line: int,
    ) -> list[dict[str, Any]]:
        """Read the requested lines from the current commit."""
        output = self.run_git("show", f"HEAD:{relative_path}")
        lines = output.splitlines()

        if start_line < 1 or end_line < start_line:
            raise GitReaderError("Invalid line range.")

        if end_line > len(lines):
            raise GitReaderError(
                f"Requested committed line {end_line}, but HEAD has "
                f"{len(lines)} lines."
            )

        return [
            {
                "line_number": number,
                "content": lines[number - 1],
            }
            for number in range(start_line, end_line + 1)
        ]

    def working_tree_status(self, relative_path: str) -> str:
        """Return the concise Git status for a target path."""
        return self.run_git(
            "status",
            "--porcelain",
            "--untracked-files=no",
            "--",
            relative_path,
        ).strip()

    def blame(
        self,
        relative_path: str,
        start_line: int,
        end_line: int,
    ) -> list[dict[str, Any]]:
        """Return the commits responsible for the requested lines."""
        output = self.run_git(
            "blame",
            "--line-porcelain",
            "-L",
            f"{start_line},{end_line}",
            "--",
            relative_path,
        )

        records: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for line in output.splitlines():
            # Porcelain header:
            # <commit> <original-line> <final-line> [group-size]
            match = re.match(
                r"^([0-9a-f^]{40,64}) (\d+) (\d+)(?: (\d+))?$",
                line,
            )

            if match:
                commit = match.group(1).lstrip("^")
                current = {
                    "commit": commit,
                    "original_line": int(match.group(2)),
                    "line_number": int(match.group(3)),
                    "uncommitted": set(commit) == {"0"},
                }
                records.append(current)
                continue

            if current is None:
                continue

            if line.startswith("author "):
                current["author"] = line[len("author "):]
            elif line.startswith("author-time "):
                current["author_timestamp"] = int(
                    line[len("author-time "):]
                )
            elif line.startswith("summary "):
                current["summary"] = line[len("summary "):]
            elif line.startswith("filename "):
                current["filename"] = line[len("filename "):]
            elif line.startswith("\t"):
                current["content"] = line[1:]

        return records

    def commit_details(self, commit: str) -> dict[str, str]:
        """Retrieve commit metadata and the actual diff."""
        if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            raise GitReaderError("Invalid commit hash.")

        metadata = self.run_git(
            "show",
            "-s",
            "--format=%H%n%an%n%aI%n%s%n%b",
            commit,
        ).splitlines()

        while len(metadata) < 5:
            metadata.append("")

        diff = self.run_git(
            "show",
            "--format=",
            "--no-ext-diff",
            "--no-renames",
            "--unified=3",
            "--no-color",
            commit,
            "--",
        )

        return {
            "hash": metadata[0],
            "author": metadata[1],
            "date": metadata[2],
            "subject": metadata[3],
            "body": "\n".join(metadata[4:]),
            "diff": diff[:20_000],
        }

    def related_commits(
        self,
        relative_path: str,
        start_line: int,
        end_line: int,
        limit: int = 10,
    ) -> list[dict[str, str]]:
        """Find recent commits touching the target file."""
        limit = max(1, min(limit, 50))

        output = self.run_git(
            "log",
            f"-n{limit}",
            "--format=%H%x1f%an%x1f%aI%x1f%s",
            "--follow",
            "--",
            relative_path,
        )

        commits: list[dict[str, str]] = []

        for line in output.splitlines():
            fields = line.split("\x1f", 3)

            if len(fields) != 4:
                continue

            commit_hash, author, date, subject = fields

            commits.append(
                {
                    "hash": commit_hash,
                    "author": author,
                    "date": date,
                    "subject": subject,
                }
            )

        return commits

    def search_history(
        self,
        relative_path: str,
        search_pattern: str,
        limit: int = 10,
    ) -> list[dict[str, str]]:
        """Search historical diffs for a bounded regular expression."""
        if len(search_pattern) > 120:
            raise GitReaderError("Search pattern is too long.")

        if "\x00" in search_pattern:
            raise GitReaderError("Search pattern contains a null byte.")

        limit = max(1, min(limit, 50))

        output = self.run_git(
            "log",
            f"-n{limit}",
            "--format=%H%x1f%an%x1f%aI%x1f%s",
            f"-G{search_pattern}",
            "--",
            relative_path,
        )

        results: list[dict[str, str]] = []

        for line in output.splitlines():
            fields = line.split("\x1f", 3)

            if len(fields) != 4:
                continue

            commit_hash, author, date, subject = fields

            results.append(
                {
                    "hash": commit_hash,
                    "author": author,
                    "date": date,
                    "subject": subject,
                }
            )

        return results

    def tracked_test_files(self, limit: int = 100) -> list[str]:
        """List tracked files whose paths resemble test files."""
        output = self.run_git("ls-files")

        candidates = [
            line
            for line in output.splitlines()
            if re.search(
                r"(^|/)(tests?|specs?)(/|$)|"
                r"(^|/)(test_[^/]+\.py|[^/]+_test\.py|"
                r"[^/]+\.test\.[^/]+|[^/]+\.spec\.[^/]+)$",
                line,
                re.IGNORECASE,
            )
        ]

        return candidates[:max(1, min(limit, 500))]