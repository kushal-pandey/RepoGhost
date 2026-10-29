# RepoGhost 👻

**Evidence-backed archaeology for Git repositories**

RepoGhost helps maintainers investigate unfamiliar code by assembling relevant
Git history, line attribution, commit metadata and diffs, lexical history
matches, and candidate test-file paths. It is designed to make the evidence
easier to inspect—not to infer historical intent from a commit message.

## Why RepoGhost?

Code outlives the people and context that introduced it. A delay, cache, branch,
or compatibility workaround may look unnecessary after its original bug report
or environment has disappeared. Removing it without checking its history can
reintroduce a regression; keeping it without understanding it adds maintenance
cost.

RepoGhost gives a developer one bounded, read-only investigation of the selected
file region. It presents current working-tree source separately from the source
at `HEAD`, and makes the underlying commits and diffs inspectable.

## Requirements and installation

- Python 3.11 or later
- Git available on `PATH`
- No third-party runtime dependencies

### Windows PowerShell

From the repository directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

### Unix-like shell

```sh
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Inspect a region

The target syntax is `FILE:START-END`; line numbers are one-based and a request
is limited to 200 lines.

```powershell
repoghost inspect src/cache.py:10-30
repoghost inspect src/cache.py:10-30 --repo C:\Projects\my-project
repoghost inspect src/cache.py:10-30 --json-out evidence.json
```

On Unix-like shells, quote targets if the filename or range needs it:

```sh
repoghost inspect 'src/cache.py:10-30' --repo ~/work/my-project
repoghost inspect 'src/cache.py:10-30' --json-out evidence.json
```

RepoGhost requires the target to be an existing, tracked file inside the
selected repository. Invalid paths and ranges are reported as CLI errors.

The report includes:

- The selected lines from the current working tree and from `HEAD`, plus the
  target's concise Git status.
- `git blame` line attribution, clearly distinguished from proof that the
  attributed commit introduced a bug.
- Commit metadata and bounded diff excerpts for origin commits.
- Recent commits touching the file, bounded lexical searches of historical
  diffs, and candidate test paths.
- Collection warnings and explicit limitations.

Candidate test paths are not test results: RepoGhost does not read or execute
repository tests. History search is lexical, not evidence of causation.

## Optional local Ollama explanation

The deterministic evidence collector and CLI do not use AI. To add an optional
explanation, install and start Ollama yourself, and ensure the selected model is
already available. RepoGhost does not install models, contact a hosted AI
service, or fall back to one.

```powershell
ollama pull qwen2.5:3b
python -m repoghost.ai_explainer evidence.json --out explanation.md
```

The pull command above is an explicit manual model-download step. Once Ollama
and the model are installed, explanations use Ollama's local `/api/generate`
HTTP endpoint. Choose another installed model and endpoint as needed:

```powershell
python -m repoghost.ai_explainer evidence.json `
  --model qwen2.5:3b `
  --endpoint http://localhost:11434 `
  --timeout 180 `
  --out explanation.md
```

Endpoints are restricted to loopback addresses (`localhost`, `127.0.0.1`, or
`::1`) so the evidence report is not sent to a remote API. Redirects are
disabled. The AI output must cite at least one commit found in the report;
abbreviated hashes are accepted only when they identify one report commit.
Recognized file paths and target-line references are checked against the
evidence. These checks detect unsupported references, not whether a cited
commit supports the adjacent claim or whether a candidate test's assertions
were correctly described. The model can still produce inaccurate explanations;
verify its hypotheses and suggested changes independently.

The Ollama feature is optional and is never needed for Git inspection, JSON
export, or the test suite. A local Ollama process/model is required only when
requesting an AI explanation.

## Reproducible example

Create a synthetic history in a new temporary directory:

```powershell
.\examples\create_bug_fixture.ps1 -Path "$env:TEMP\repoghost-bug-fixture"
```

The script stops rather than replacing an existing path; `-Force` requires
typing `REPLACE` before it removes the selected directory. The fixture has a
cache optimization, an initial test that verifies reuse but not mutation
isolation, and a later fix with a regression test. It is a teaching example,
not evidence of any real author's motivation.

```powershell
$demo = "$env:TEMP\repoghost-bug-fixture"
python -m unittest discover -s "$demo\tests" -v
repoghost inspect cache.py:1-12 --repo $demo --json-out "$demo\evidence.json"
python -m repoghost.ai_explainer "$demo\evidence.json" --out "$demo\explanation.md"
```

The last command is optional and requires a running local Ollama server with
the requested model already installed. A concise screen-recording walkthrough
is in [docs/DEMO.md](docs/DEMO.md).

## Status and roadmap

Implemented: the `inspect` CLI, bounded Git evidence collection, structured
JSON export, working-tree/`HEAD` comparison, optional local Ollama explanations
with report-backed citation checks, automated tests, and a reproducible
historical-bug fixture.

Planned: semantic test matching, broader evidence ranking, and evaluation
against real-world investigations. The optional AI layer is explanatory only;
it does not replace deterministic collection or make causal claims.

## Tests and CI

Run the test suite from the repository root:

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
repoghost --version
repoghost --help
python -m repoghost.ai_explainer --help
```

The tests use temporary Git repositories and mocked Ollama HTTP responses; they
do not require Ollama or download a model. GitHub Actions runs the same suite on
Python 3.11.

## Privacy, determinism, and limitations

- **Deterministic collection:** Git commands run locally without a shell and
  with bounded timeouts. RepoGhost does not execute repository code.
- **Local AI boundary:** Only the optional explainer sends the evidence JSON to
  a loopback Ollama endpoint. RepoGhost rejects remote endpoints and HTTP
  redirects. Your Ollama installation, model, and machine remain outside this
  project's control.
- **No internet requirement for inspection:** Once installed, core Git
  investigation makes no network requests. Package installation and obtaining
  Ollama/model files may require internet access.
- **No causal guarantee:** Blame, commit descriptions, nearby tests, and lexical
  matches do not establish why a change was made or prove a cause.
- **Bounded scope:** At most 200 lines are inspected; commit detail, history
  search, and candidate test listing are capped. Test paths are candidates
  only, and the AI citation checks do not guarantee factual correctness.

## License

MIT. See [LICENSE](LICENSE).
