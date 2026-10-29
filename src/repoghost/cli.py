"""RepoGhost command-line interface."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from repoghost import __version__
from repoghost.evidence import collect_evidence
from repoghost.git_reader import GitReaderError
from repoghost.repository import (
    RepositoryError,
    find_repository_root,
    resolve_target_file,
)


def parse_target(value: str) -> tuple[str, int, int]:
    """Parse FILE:START-END, using the final colon as separator."""
    try:
        file_path, line_range = value.rsplit(":", 1)
        start_text, end_text = line_range.split("-", 1)

        start_line = int(start_text)
        end_line = int(end_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(
            "Target must use FILE:START-END, for example "
            "src/cache.py:10-30"
        ) from exc

    if not file_path.strip():
        raise argparse.ArgumentTypeError("File path cannot be empty.")

    if start_line < 1 or end_line < start_line:
        raise argparse.ArgumentTypeError(
            "Line numbers must be positive and START must not exceed END."
        )

    if end_line - start_line > 199:
        raise argparse.ArgumentTypeError(
            "A maximum of 200 source lines can be inspected at once."
        )

    return file_path, start_line, end_line


def render_report(report: dict[str, Any]) -> str:
    """Render a human-readable deterministic evidence report."""
    target = report["target"]
    lines: list[str] = []

    lines.append("")
    lines.append("  REPOGHOST // GIT ARCHAEOLOGY")
    lines.append("  " + "=" * 35)
    lines.append("")
    lines.append(f"  Repository : {report['repository']}")
    lines.append(f"  Target     : {target['file']}")
    lines.append(
        f"  Lines      : {target['start_line']}-{target['end_line']}"
    )

    lines.append("")
    lines.append("  WORKING-TREE SOURCE")
    lines.append("  " + "-" * 35)
    lines.append(
        "  Git status: "
        + (report["working_tree_status"] or "clean")
    )

    for item in report["source_lines"]:
        lines.append(
            f"  {item['line_number']:>5} | {item['content']}"
        )

    lines.append("")
    lines.append("  COMMITTED SOURCE (HEAD)")
    lines.append("  " + "-" * 35)

    if report["committed_source_lines"]:
        for item in report["committed_source_lines"]:
            lines.append(
                f"  {item['line_number']:>5} | {item['content']}"
            )
    else:
        lines.append("  Committed source is unavailable.")

    lines.append("")
    lines.append("  WORKING-TREE LINE ATTRIBUTION (GIT BLAME)")
    lines.append("  " + "-" * 35)
    lines.append(
        "  Blame attribution does not prove which commit introduced a bug."
    )

    if not report["blame"]:
        lines.append("  No blame records found.")
    else:
        for record in report["blame"]:
            if record.get("uncommitted"):
                lines.append(
                    f"  {record['line_number']:>5} | working tree "
                    f"(uncommitted) | {record.get('content', '')}"
                )
                continue

            short_hash = record["commit"][:12]
            summary = record.get("summary", "(no summary)")
            author = record.get("author", "Unknown author")

            lines.append(
                f"  {record['line_number']:>5} | "
                f"{short_hash} | {author} | {summary}"
            )

    lines.append("")
    lines.append("  ORIGIN COMMIT DETAILS")
    lines.append("  " + "-" * 35)

    if not report["origin_commits"]:
        lines.append("  No origin commit details available.")

    for commit in report["origin_commits"]:
        lines.append(f"  Commit : {commit['hash'][:12]}")

        if "error" in commit:
            lines.append(f"  Note   : {commit['error']}")
            continue

        lines.append(f"  Author : {commit['author']}")
        lines.append(f"  Date   : {commit['date']}")
        lines.append(f"  Subject: {commit['subject']}")

        diff = commit.get("diff", "")

        if diff:
            diff_lines = diff.splitlines()[:12]
            lines.append("  Diff excerpt:")

            for diff_line in diff_lines:
                lines.append(f"    {diff_line}")

            if len(diff.splitlines()) > 12:
                lines.append("    ...")

        lines.append("")

    lines.append("  RELATED COMMITS")
    lines.append("  " + "-" * 35)

    for commit in report["related_commits"]:
        lines.append(
            f"  {commit['hash'][:12]} | "
            f"{commit['date']} | {commit['subject']}"
        )

    lines.append("")
    lines.append("  SEARCHED HISTORY")
    lines.append("  " + "-" * 35)

    if report["history_matches"]:
        for match in report["history_matches"]:
            lines.append(
                f"  {match['hash'][:12]} | "
                f"term={match['matched_term']} | "
                f"{match['subject']}"
            )
    else:
        lines.append("  No lexical matches found.")

    lines.append("")
    lines.append("  CANDIDATE TEST FILES")
    lines.append("  " + "-" * 35)

    for path in report["candidate_test_files"][:20]:
        lines.append(f"  {path}")

    if not report["candidate_test_files"]:
        lines.append("  No candidate test files found.")

    lines.append("")
    lines.append("  LIMITATIONS")
    lines.append("  " + "-" * 35)

    for limitation in report["limitations"]:
        lines.append(f"  - {limitation}")

    if report["collection_warnings"]:
        lines.append("")
        lines.append("  COLLECTION WARNINGS")
        lines.append("  " + "-" * 35)

        for warning in report["collection_warnings"]:
            lines.append(f"  - {warning}")

    lines.append("")
    lines.append(
        "  STATUS: Evidence collected. Historical intent is not yet inferred."
    )
    lines.append("")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repoghost",
        description=(
            "Investigate the history behind mysterious code using "
            "verifiable Git evidence."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a file region and collect historical evidence.",
    )

    inspect_parser.add_argument(
        "target",
        type=parse_target,
        help="Target in FILE:START-END format.",
    )

    inspect_parser.add_argument(
        "--repo",
        default=".",
        help="Repository directory or a path inside the repository.",
    )

    inspect_parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional path for a JSON evidence report.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "inspect":
        try:
            file_argument, start_line, end_line = args.target

            repository_root = find_repository_root(args.repo)

            _, relative_path = resolve_target_file(
                repository_root,
                file_argument,
            )

            report = collect_evidence(
                repository_root,
                relative_path,
                start_line,
                end_line,
            )

            print(render_report(report))

            if args.json_out:
                output_path = args.json_out.expanduser().resolve()
                output_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                output_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                print(f"JSON evidence report saved to: {output_path}")

        except (
            RepositoryError,
            GitReaderError,
            OSError,
            ValueError,
        ) as exc:
            print(f"RepoGhost error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc


if __name__ == "__main__":
    main()