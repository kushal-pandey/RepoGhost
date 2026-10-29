"""Evidence collection and report assembly."""

import re
from pathlib import Path
from typing import Any

from repoghost.git_reader import GitReader, GitReaderError


STOP_WORDS = {
    "return", "raise", "class", "def", "self", "none", "true",
    "false", "pass", "else", "elif", "from", "import", "with",
    "while", "break", "continue", "try", "except", "finally",
    "async", "await", "for", "in", "and", "or", "not", "if",
    "this", "that", "then", "when", "where", "what", "into",
}


def extract_search_terms(lines: list[dict[str, Any]]) -> list[str]:
    """Extract useful identifiers from source lines."""
    combined = " ".join(line["content"] for line in lines)

    candidates = re.findall(
        r"[A-Za-z_][A-Za-z0-9_]{2,}",
        combined,
    )

    terms: list[str] = []

    for term in candidates:
        normalized = term.lower()

        if normalized in STOP_WORDS:
            continue

        if normalized not in terms:
            terms.append(normalized)

        if len(terms) >= 8:
            break

    return terms


def collect_evidence(
    repository_root: Path,
    relative_path: str,
    start_line: int,
    end_line: int,
) -> dict[str, Any]:
    """Collect a deterministic evidence bundle for a target region."""
    reader = GitReader(repository_root)

    source_lines = reader.read_lines(
        relative_path,
        start_line,
        end_line,
    )

    collection_warnings: list[str] = []
    try:
        committed_source_lines = reader.read_committed_lines(
            relative_path,
            start_line,
            end_line,
        )
    except GitReaderError as exc:
        committed_source_lines = []
        collection_warnings.append(
            f"Committed source could not be read: {exc}"
        )

    working_tree_status = reader.working_tree_status(relative_path)
    blame_records = reader.blame(
        relative_path,
        start_line,
        end_line,
    )

    unique_hashes = list(
        dict.fromkeys(
            record["commit"]
            for record in blame_records
            if not record.get("uncommitted")
        )
    )

    # Avoid attempting to retrieve commit details for an uncommitted
    # or otherwise unavailable revision.
    commit_details: list[dict[str, str]] = []

    for commit_hash in unique_hashes[:10]:
        try:
            commit_details.append(
                reader.commit_details(commit_hash)
            )
        except GitReaderError as exc:
            collection_warnings.append(
                f"Commit details unavailable for {commit_hash}: {exc}"
            )
            commit_details.append(
                {
                    "hash": commit_hash,
                    "error": str(exc),
                }
            )

    related_commits = reader.related_commits(
        relative_path,
        start_line,
        end_line,
        limit=10,
    )

    search_terms = extract_search_terms(source_lines)

    history_matches: list[dict[str, Any]] = []

    for term in search_terms[:5]:
        try:
            matches = reader.search_history(
                relative_path,
                re.escape(term),
                limit=5,
            )
        except GitReaderError as exc:
            collection_warnings.append(
                f"History search for '{term}' failed: {exc}"
            )
            continue

        for match in matches:
            history_matches.append(
                {
                    **match,
                    "matched_term": term,
                }
            )

    # Deduplicate by commit while preserving discovery order.
    seen: set[str] = set()
    deduplicated_history: list[dict[str, Any]] = []

    for match in history_matches:
        commit_hash = match["hash"]

        if commit_hash not in seen:
            seen.add(commit_hash)
            deduplicated_history.append(match)

    test_files = reader.tracked_test_files(limit=100)

    return {
        "schema_version": "1.0",
        "repository": str(repository_root.resolve()),
        "target": {
            "file": relative_path,
            "start_line": start_line,
            "end_line": end_line,
        },
        "source_lines": source_lines,
        "committed_source_lines": committed_source_lines,
        "working_tree_status": working_tree_status,
        "blame_source": "working_tree",
        "blame": blame_records,
        "origin_commits": commit_details,
        "related_commits": related_commits,
        "history_matches": deduplicated_history[:20],
        "search_terms": search_terms,
        "candidate_test_files": test_files,
        "collection_warnings": collection_warnings,
        "limitations": [
            "Commit history does not necessarily reveal author intent.",
            "Blame attributes lines in the selected file version; it does "
            "not by itself identify the commit that introduced a defect.",
            "Candidate test files have not yet been semantically matched "
            "to the target code.",
            "Search matches are lexical, not proof of a causal relationship.",
            "AI citation validation checks references against this report; "
            "it does not guarantee that an explanation is factually correct.",
        ],
    }