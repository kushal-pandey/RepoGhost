[CmdletBinding()]
param(
    [string]$Path = (Join-Path ([System.IO.Path]::GetTempPath()) "repoghost-bug-fixture"),
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$script:RepoPath = [System.IO.Path]::GetFullPath($Path)
$script:CommitNumber = 0
$volumeRoot = [System.IO.Path]::GetPathRoot($script:RepoPath)

if ($script:RepoPath.TrimEnd('\') -eq $volumeRoot.TrimEnd('\')) {
    throw "Refusing to use a filesystem root as the fixture path."
}

if (Test-Path -LiteralPath $script:RepoPath) {
    if (-not $Force) {
        throw "Path already exists: $script:RepoPath. Choose another path or pass -Force to confirm replacement."
    }

    $confirmation = Read-Host "Type REPLACE to delete and recreate '$script:RepoPath'"
    if ($confirmation -cne "REPLACE") {
        throw "Fixture replacement was not confirmed."
    }

    Remove-Item -LiteralPath $script:RepoPath -Recurse -Force
}

New-Item -ItemType Directory -Path $script:RepoPath | Out-Null

function Invoke-Git {
    param([string[]]$GitArgs)

    & git -C $script:RepoPath @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed (exit $LASTEXITCODE): git -C '$script:RepoPath' $($GitArgs -join ' ')"
    }
}

function Write-Utf8File {
    param(
        [string]$RelativePath,
        [string]$Content
    )

    $filePath = Join-Path $script:RepoPath $RelativePath
    $parentPath = Split-Path -Parent $filePath
    New-Item -ItemType Directory -Force -Path $parentPath | Out-Null
    [System.IO.File]::WriteAllText(
        $filePath,
        $Content,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Save-StoryCommit {
    param([string]$Message)

    Invoke-Git @("add", "--all")
    $script:CommitNumber++
    $commitDate = [DateTimeOffset]::new(
        2026, 1, 1, 0, 0, 0, [TimeSpan]::Zero
    ).AddMinutes($script:CommitNumber).ToString("yyyy-MM-ddTHH:mm:ssZ")
    $previousAuthorDate = $env:GIT_AUTHOR_DATE
    $previousCommitterDate = $env:GIT_COMMITTER_DATE

    try {
        $env:GIT_AUTHOR_DATE = $commitDate
        $env:GIT_COMMITTER_DATE = $commitDate
        Invoke-Git @(
            "-c", "user.name=RepoGhost Demo",
            "-c", "user.email=repoghost@example.invalid",
            "-c", "commit.gpgsign=false",
            "commit", "-m", $Message
        )
    }
    finally {
        if ($null -eq $previousAuthorDate) {
            Remove-Item Env:GIT_AUTHOR_DATE -ErrorAction SilentlyContinue
        }
        else {
            $env:GIT_AUTHOR_DATE = $previousAuthorDate
        }

        if ($null -eq $previousCommitterDate) {
            Remove-Item Env:GIT_COMMITTER_DATE -ErrorAction SilentlyContinue
        }
        else {
            $env:GIT_COMMITTER_DATE = $previousCommitterDate
        }
    }
}

Invoke-Git @("init", "--quiet")

Write-Utf8File "cache.py" @'
def get_cached(key, factory):
    """Return a value produced for this key."""
    return factory()


def clear_cache():
    pass
'@

Write-Utf8File "tests/test_cache.py" @'
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cache import clear_cache, get_cached


class CacheTests(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_returns_factory_result(self):
        self.assertEqual(get_cached("user", lambda: {"name": "Ada"}), {"name": "Ada"})


if __name__ == "__main__":
    unittest.main()
'@

Save-StoryCommit "Add uncached request helper"

Write-Utf8File "cache.py" @'
_cache = {}


def get_cached(key, factory):
    """Reuse the first value created for a key."""
    if key not in _cache:
        _cache[key] = factory()
    return _cache[key]


def clear_cache():
    _cache.clear()
'@

Write-Utf8File "tests/test_cache.py" @'
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cache import clear_cache, get_cached


class CacheTests(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_returns_factory_result(self):
        self.assertEqual(get_cached("user", lambda: {"name": "Ada"}), {"name": "Ada"})

    def test_reuses_value_for_same_key(self):
        calls = []

        def factory():
            calls.append(1)
            return {"name": "Ada"}

        first = get_cached("user", factory)
        second = get_cached("user", factory)

        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
'@

Save-StoryCommit "Reuse cached request values"

Write-Utf8File "cache.py" @'
from copy import deepcopy

_cache = {}


def get_cached(key, factory):
    """Return a copy so callers cannot mutate the cached value."""
    if key not in _cache:
        _cache[key] = factory()
    return deepcopy(_cache[key])


def clear_cache():
    _cache.clear()
'@

Write-Utf8File "tests/test_cache.py" @'
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cache import clear_cache, get_cached


class CacheTests(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_returns_factory_result(self):
        self.assertEqual(get_cached("user", lambda: {"name": "Ada"}), {"name": "Ada"})

    def test_reuses_value_for_same_key(self):
        calls = []

        def factory():
            calls.append(1)
            return {"items": ["first"]}

        first = get_cached("user", factory)
        second = get_cached("user", factory)

        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)

    def test_mutation_does_not_change_cached_value(self):
        original = {"items": ["first"]}
        first = get_cached("user", lambda: original)
        first["items"].append("caller mutation")

        later = get_cached("user", lambda: {})
        self.assertEqual(later, original)


if __name__ == "__main__":
    unittest.main()
'@

Save-StoryCommit "Isolate callers from cached mutable values"

Write-Host ""
Write-Host "Created repeatable RepoGhost history fixture at: $script:RepoPath"
Write-Host "From that directory, run: python -m unittest discover -s tests -v"
