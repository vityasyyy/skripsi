# Verification report — 2026-11-19

Scope: Phase 0 verification of the completed formal batch and the documentation
branch `agent/thesis-docs-provenance`. This report records commands and observed
output. It does not authorize a live run.

## Environment

| Item | Value |
|---|---|
| Date | 2026-11-19 |
| Worktree | `/Users/miapalovaara/skripsi/.worktrees/2026-11-19/docs-provenance` |
| Branch | `agent/thesis-docs-provenance` |
| Base / HEAD | `b6a4e3eace970269bb0b0e2b3058f6a6a000d23a` |
| Python | 3.12.8 |
| Ruff | pinned 0.17.5 via `uv` (system 0.15.14 not used for the gate) |
| Shell | zsh on macOS |

## 1. Frozen tags

```bash
git for-each-ref --format='%(refname:short) %(objectname) %(*objectname)' \
  'refs/tags/thesis-*'
```

| Tag | Tag object | Commit |
|---|---|---|
| `thesis-collection-20261029` | `066ad19f9d7ee7b564d6cc55ce823e180e8f05ce` | `3572f3c1c11d3abc8b63882c4348b1b803d4256f` |
| `thesis-analysis-20261030` | `51aecc8ba97a9b5614d699cba200f6e6e42cb57c` | `a1d43eaf0d349249f1eb0a8e880badebe4eb851d` |
| `thesis-sensitivity-20261030` | `035916c60a672dd76d38fec8b974bd74354272aa` | `6cfc99ec63a71825e88b53a96704c8c792891bd9` |

All three are annotated tags. `git rev-parse '<tag>^{commit}'` returns the commit
in the table.

## 2. Dataset checksums

```bash
cd experiments/formal-20261029 && shasum -a 256 -c SHA256SUMS
cd experiments/analysis-formal-20261029 && shasum -a 256 -c SHA256SUMS
```

| Package | Files verified | Failures |
|---|---|---|
| `experiments/formal-20261029/` | 3,024 | 0 |
| `experiments/analysis-formal-20261029/` | 7 | 0 |

The batch package has 3,026 files total; `SHA256SUMS` and `PROVENANCE.json` are
the two provenance files not listed in their own checksum manifest. Both are
committed on this branch.

## 3. Analyzer output identity

```bash
rm -rf /tmp/analysis-rerun
python3 experiments/analysis/analyze_live.py \
  --in experiments/formal-20261029/formal-20261029.analysis.jsonl \
  --rows experiments/formal-20261029/formal-20261029.rows.jsonl \
  --out /tmp/analysis-rerun \
  --seed 20261029
diff -r experiments/analysis-formal-20261029 /tmp/analysis-rerun
```

Observed analyzer output:

```text
OK: 207 analysis rows, 4 excluded, 12 predeclared comparisons (12 testable) -> /tmp/analysis-rerun
```

Observed `diff -r` output:

```text
Only in experiments/analysis-formal-20261029: SHA256SUMS
```

No file contents differ. The seven frozen outputs are byte-identical. The
analyzer writes `live_analysis.json` plus six `.tex` tables; `SHA256SUMS` is
written by the archive step, not by the analyzer.

Reproduction requires `--seed 20261029`. The code default is `20261027`, so
omitting the flag produces different bootstrap output.

## 4. Tests and coverage

```bash
make check-experiments
```

Observed result: exit 0.

| Gate | Result |
|---|---|
| Core tests | 491 passed |
| Sensitivity tests | 8 passed |
| Coverage | 100% lines and branches; 4,478 statements, 1,862 branches, 10 modules |
| Ruff check | All checks passed |
| Ruff format check | 34 files already formatted |
| Mypy | No issues in 13 source files |
| ShellCheck | No findings |
| `bash -n` | No syntax errors |

The standalone commands in the worker brief also pass:

```bash
python3 -m unittest discover -s experiments/tests -q
# Ran 491 tests ... OK
python3 -m unittest discover -s experiments/sensitivity -p 'test_*.py' -q
# Ran 9 tests ... OK
```

## 5. Build counts

| Artifact | Value | Source |
|---|---|---|
| Thesis | 69 pages | `pdfinfo content/skripsi/main.pdf` |
| Thesis log | 0 overfull, 18 underfull | `content/skripsi/main.log` |
| Defense deck | 22 pages | `pdfinfo presentation/skripsi/main.pdf` |

This worker did not rebuild the thesis or deck; the counts are read from the
existing committed PDFs and the current thesis log.

## 6. Documentation link check

All Markdown links in the changed and new docs were resolved from each file's
directory. External URLs, anchors, and inline code were skipped.

```bash
python3 - <<'PY'
import pathlib, re, sys

files = [
    "README.md", "experiments/README.md", "experiments/live/README.md",
    "experiments/analysis/README.md", "experiments/LIVE-OBSERVER.md",
    "experiments/REVISIONS.md", "experiments/DATA.md",
    "experiments/ARCHITECTURE.md",
    "docs/reproducibility/claim-traceability.md",
    "docs/reproducibility/verification-2026-11-19.md",
    "docs/reproducibility/experiment-dossier.md",
    "docs/reproducibility/formal-20261029-results.md",
]
missing = []
for name in files:
    path = pathlib.Path(name)
    for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", path.read_text()):
        target = match.group(1).strip()
        if target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        target = target.split("#", 1)[0]
        if target and not (path.parent / target).resolve().exists():
            missing.append((name, target))
print(len(missing), "missing")
sys.exit(1 if missing else 0)
PY
```

Observed: **82 relative links checked; 0 missing**. The checked files are
`README.md`, `experiments/README.md`, `experiments/live/README.md`,
`experiments/analysis/README.md`, `experiments/LIVE-OBSERVER.md`,
`experiments/REVISIONS.md`, `experiments/DATA.md`,
`experiments/ARCHITECTURE.md`, and the four files under
`docs/reproducibility/`.

`git diff --check` reports no whitespace errors.

## 7. Lint caveat in the lead checkout

The lead checkout on `main` contains untracked local data and an untracked
launch script. Before this branch's `experiments/ruff.toml` change:

```bash
cd /Users/miapalovaara/skripsi
uv run --with-requirements experiments/requirements-dev.txt ruff check experiments
# Found 65 errors.
```

Breakdown:

- 60 findings under `experiments/evidence-local/**` (historical evidence copies;
  not tracked, not runtime code).
- 5 findings under `experiments/scripts/supervise-formal-20261029.py`
  (untracked launch script; `PLW1510` and `TRY300`).

After adding `evidence-local` to Ruff's `exclude`, the evidence-local findings
disappear; the 5 findings in the untracked launch script remain. The tracked
runtime code and tests pass Ruff, mypy, ShellCheck, and `bash -n`. The launch
script is outside this worker's scope; archive/remove it before claiming
`make check-experiments` green in the lead checkout, or add a scoped exclude if
it is intentionally retained.

This worktree has no untracked evidence or launch script, so
`make check-experiments` passes here end to end.

## 8. What was not verified

- No live cluster access and no new live run. The batch is historical data.
- Current code is not the collection revision (see
  [`../../experiments/REVISIONS.md`](../../experiments/REVISIONS.md)); the
  analyzer identity check verifies analysis reproduction, not apparatus replay.
- The thesis and deck were not rebuilt by this worker; page/slide and warning
  counts come from existing artifacts.
- The sensitivity values for C-r02 have no committed output file; they are
  reproducible with the tracked script. This is recorded as a traceability gap in
  [`claim-traceability.md`](claim-traceability.md).
