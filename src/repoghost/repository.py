"""Repository discovery and target-path validation."""

from pathlib import Path
import subprocess


class RepositoryError(Exception):
    """Raised when a Git repository or target path is invalid."""


def find_repository_root(path: str | Path = ".") -> Path:
    """Return the root of the Git worktree containing path."""
    candidate = Path(path).expanduser().resolve()

    if not candidate.exists():
        raise RepositoryError(f"Path does not exist: {candidate}")

    if candidate.is_file():
        candidate = candidate.parent

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(candidate),
                "rev-parse",
                "--show-toplevel",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RepositoryError(
            "Git was not found. Install Git and ensure it is in PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RepositoryError("Git repository detection timed out.") from exc

    if result.returncode != 0:
        raise RepositoryError(
            "No Git worktree was found for the supplied path."
        )

    root = result.stdout.strip()

    if not root:
        raise RepositoryError("Git returned an empty repository root.")

    return Path(root).resolve()


def resolve_target_file(
    repository_root: Path,
    file_argument: str,
) -> tuple[Path, str]:
    """
    Resolve a repository-relative file.

    Returns:
        (absolute_path, repository_relative_path)
    """
    root = repository_root.resolve()
    if not file_argument or "\x00" in file_argument:
        raise RepositoryError("Target file path is empty or invalid.")

    try:
        supplied = Path(file_argument)

        if supplied.is_absolute():
            target = supplied.resolve()
        else:
            target = (root / supplied).resolve()
    except (OSError, ValueError) as exc:
        raise RepositoryError(f"Invalid target file path: {file_argument}") from exc

    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise RepositoryError(
            "The target file must be inside the repository root."
        ) from exc

    if not target.exists():
        raise RepositoryError(f"Target file does not exist: {relative}")

    if not target.is_file():
        raise RepositoryError(f"Target is not a regular file: {relative}")

    # Require a tracked file for this initial implementation.
    try:
        tracked = subprocess.run(
            [
                "git",
                "--literal-pathspecs",
                "-C",
                str(root),
                "ls-files",
                "--error-unmatch",
                "--",
                relative.as_posix(),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RepositoryError(
            "Git was not found. Install Git and ensure it is in PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RepositoryError("Git target validation timed out.") from exc

    if tracked.returncode != 0:
        raise RepositoryError(
            f"Target file is not tracked by Git: {relative.as_posix()}"
        )

    return target, relative.as_posix()