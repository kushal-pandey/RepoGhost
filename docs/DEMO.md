# RepoGhost 2–3 minute demo

This walkthrough creates a synthetic Git repository. It does not modify the
RepoGhost checkout or an existing demo repository.

## Prepare

From the RepoGhost checkout in PowerShell, create a fixture path that does not
already exist:

```powershell
$demo = Join-Path $env:TEMP "repoghost-recording"
.\examples\create_bug_fixture.ps1 -Path $demo
```

Install RepoGhost once from its checkout if needed:

```powershell
python -m pip install -e .
```

## Recording sequence

1. **Show the mysterious behavior** (about 20 seconds). Open
   `$demo\cache.py`. The function now returns a deep copy of a cached value;
   the extra copy suggests callers must not be able to mutate shared state.
2. **Inspect the history** (about 35 seconds). From any directory, run:

   ```powershell
   repoghost inspect cache.py:1-12 --repo $demo
   ```

   Point out the worktree and `HEAD` source, the line-attribution section, and
   the actual commit hashes and diff excerpts. Explain that blame is not by
   itself the commit that introduced a defect.
3. **Compare the commits** (about 25 seconds). In a terminal:

   ```powershell
   git -C $demo --no-pager log --oneline -- cache.py
   $fix = git -C $demo log -1 --format=%H --grep="Isolate callers from cached mutable values"
   git -C $demo --no-pager show --stat $fix
   git -C $demo --no-pager show $fix -- cache.py tests/test_cache.py
   ```

   The diff adds a defensive copy and a mutation-isolation test.
4. **Show the evidence export** (about 25 seconds):

   ```powershell
   repoghost inspect cache.py:1-12 --repo $demo --json-out "$demo\evidence.json"
   Get-Content "$demo\evidence.json"
   ```

   The JSON keeps the source, blame, commits, candidate test paths, limitations,
   and any collection warnings in structured fields.
5. **Run the final fixture tests** (about 20 seconds):

   ```powershell
   python -m unittest discover -s "$demo\tests" -v
   ```

   The earlier test checked cache reuse, not mutation isolation; the later
   regression test covers the missing case.
6. **Optional local explanation** (about 20 seconds):

   ```powershell
   python -m repoghost.ai_explainer "$demo\evidence.json" --out "$demo\explanation.md"
   Get-Content "$demo\explanation.md"
   ```

   This step requires Ollama to be running with the model already installed.
   The model's output is not part of deterministic collection and may be
   inaccurate even when its citations pass validation.

## Close with the evidence boundary

The fixture's commits and tests establish what this synthetic repository
contains and how its final tests behave. They do **not** establish any real
author's motivation. In a real repository, Git history is evidence to inspect,
not proof that a commit message states the full reason for a change.
