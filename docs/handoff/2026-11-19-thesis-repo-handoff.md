# Handoff: experiment code, dataset verification, and repository cleanup

**Date:** 2026-11-19
**Repository:** https://github.com/vityasyyy/skripsi
**Base:** `main` at `b0c0f82`
**Status:** planning and cleanup; no experiment behavior changed. The frozen
instrument and analysis revisions remain the ones used for the thesis.

## Purpose

This document transfers the current state to:

1. the agent on the machine that holds the formal `formal-20261029` dataset, and
2. the successor session on the local machine.

Read this before changing code. The experiment gates are already green; the
remaining work is provenance, documentation, targeted refactoring, and the
thesis/deck corrections listed below.

## Decisions already made

- **Branches:** delete inactive and prunable branches; keep `main`. A backup
  bundle was created and all merged/closed branches were deleted on 2026-11-19.
- **Dataset:** the formal dataset is on another machine. Do not commit raw data.
  Verify it there, return checksums and a reproduction report.
- **RQ1:** rewrite RQ1 so it measures configuration equality only. Service
  health is a readiness/postcondition guardrail, not a comparative outcome.
- **Code:** targeted, behavior-preserving split later. Do not do a full rewrite
  before the defense. Refactoring does not require re-running the 210 cells, but
  behavior must be proven equivalent.
- **Title:** unchanged.
- **Theorem to preserve:** the collection instrument was frozen at
  `3572f3c`; the primary analysis was frozen at `a1d43ea`. Current code may be
  newer and must not be presented as the collection revision.

## Repository state (verified 2026-11-19)

- `main` tip: `b0c0f82 chore: refactor experiment code and align CS terminology (#45)`.
- Tags pushed:
  - `thesis-collection-20261029` -> `3572f3c`
  - `thesis-analysis-20261030` -> `a1d43ea`
  - `thesis-sensitivity-20261030` -> `6cfc99e`
- Branch backup outside the repo:
  `~/backups/skripsi-branches-2026-11-19.bundle` (27 MB, complete history).
  Verify with `git bundle verify ~/backups/skripsi-branches-2026-11-19.bundle`.
- Deleted: 27 remote branches (26 merged PRs plus closed PR #4) and 3 local
  integrated branches. No open PRs remain.
- Remaining: `main` and the handoff branch `docs/handoff-2026-11-19`.
- Working tree currently has five modified generated PDFs from the verification
  builds. They are not part of this handoff; keep or discard them deliberately.
- Last verified gates:
  - `make check-experiments`: 491 core + 8 sensitivity tests pass.
  - Coverage: 100% line and branch across the 10 measured runtime modules.
  - Ruff, mypy, ShellCheck, and `bash -n` clean.
  - Thesis compiles to 68 pages; defense deck compiles to 22 slides.

## Dataset verification (run on the machine that holds the data)

Goal: prove that the current analysis code reproduces the thesis tables from the
frozen raw data. This is read-only with respect to the cluster and source data.

### Expected files

Set `DATASET_DIR` to the directory containing the formal batch, for example
`/path/to/formal-20261029`. Expect at least:

```text
formal-20261029.analysis.jsonl   207 lines
formal-20261029.rows.jsonl       211 lines
formal-20261029.manifest.json
formal-20261029.summary.json
formal-20261029.csv              optional
analysis-formal-20261029/live_analysis.json
analysis-formal-20261029/live_*.tex
```

If a file is missing, stop and report which one. Do not synthesize it.

### 1. Inventory and checksums

```bash
export DATASET_DIR=/path/to/formal-20261029
export ANALYSIS_DIR=/path/to/analysis-formal-20261029

wc -l "$DATASET_DIR"/*.jsonl
find "$DATASET_DIR" -maxdepth 1 -type f -print0 \
  | sort -z | xargs -0 shasum -a 256 > "$DATASET_DIR/SHA256SUMS"
# Linux: use sha256sum instead of shasum -a 256

find "$ANALYSIS_DIR" -maxdepth 1 -type f -print0 \
  | sort -z | xargs -0 shasum -a 256 > "$ANALYSIS_DIR/SHA256SUMS"
```

Return both checksum files. Do not put secret values or credentials in the
report.

### 2. Re-run the analysis

```bash
OUT=$(mktemp -d /tmp/thesis-repro.XXXXXX)

python3 -B experiments/analysis/analyze_live.py \
  --in "$DATASET_DIR/formal-20261029.analysis.jsonl" \
  --rows "$DATASET_DIR/formal-20261029.rows.jsonl" \
  --out "$OUT" \
  --seed 20261029
```

The command must exit 0 and print the expected row/comparison counts. Do not add
`--force` unless the output directory already exists.

### 3. Compare against the frozen outputs

```bash
python3 -m json.tool "$ANALYSIS_DIR/live_analysis.json" > /tmp/expected.json
python3 -m json.tool "$OUT/live_analysis.json" > /tmp/actual.json
diff -u /tmp/expected.json /tmp/actual.json

for table in "$ANALYSIS_DIR"/*.tex; do
  name=$(basename "$table")
  diff -u "$table" "$OUT/$name" || true
done
```

Report:

- exact diff or `no differences`;
- if differences exist, the JSON paths and values that differ;
- whether row counts, p-values, effect sizes, and Holm decisions match;
- any missing or extra files.

Do not edit the expected outputs to make the diff pass. If the outputs differ,
the successor must decide whether the difference is a bug, a code drift, or an
intentional analysis revision.

### 4. Guardrails

- No cluster access, no `kubectl`, no mutation.
- Never print Secret values, tokens, or encrypted data.
- Do not delete or move the source dataset.
- Do not commit raw data. Commit only a checksum manifest and the report if the
  owner approves.
- If the dataset cannot be found, report `not found` and stop.

## Branch cleanup and policy

Cleanup executed on 2026-11-19 after creating the bundle:

- deleted 26 remote branches whose PRs were merged;
- deleted `fix/offline-experiment-pipeline` (PR #4 closed, superseded by #8);
- deleted 3 local branches whose content is in `main`;
- pruned remote-tracking refs.

There are no active feature branches and no open PRs. The only active branch is
`docs/handoff-2026-11-19`; merge it, then delete it.

Future branch policy:

1. Branch from `main` with a short `type/scope` name.
2. One PR per behavior change; squash merge after review and green required CI.
3. Delete the branch after merge.
4. Tag frozen experiment/analysis revisions; never rely on a long-lived branch
   as a provenance record.
5. A branch that must live longer than one week needs an owner and expiry note
   in the PR.

## Next actions for the successor

1. On the local machine: `git fetch --all --tags`, `git checkout main`,
   `git pull`, then read this document.
2. Confirm the tags and, if the bundle was copied, verify it.
3. Run or collect the dataset verification report from the other machine.
4. Wave 1: clean generated artifacts, archive stale planning/protocol docs, and
   reconcile the READMEs with the completed 29--30 October collection.
5. Wave 2: add `experiments/ARCHITECTURE.md`, `REVISIONS.md`, `DATA.md`, and the
   claim -> code -> test -> table traceability matrix. Fix the sensitivity
   default paths and audit the coverage exclusions.
6. Wave 3: rewrite RQ1 as a configuration-equality question, fix "207 sel" in
   Bab V, add the missingness footnote, and fix the deck wording/slides.
7. Wave 4: targeted behavior-preserving split only after Wave 2's equivalence
   evidence exists. Keep `harness.py` as a facade.
8. Wave 5: defense Q&A, fresh-context review, final gates.

## Do not do

- Do not re-run the 210 cells to justify a refactor.
- Do not change collection semantics and call it cleanup.
- Do not rewrite the thesis tables from synthetic outputs.
- Do not commit raw data, secrets, or the backup bundle.
- Do not merge code without the full gate and an equivalence check.
- Do not delete `bimbingan-snapshots` or the historical evidence.

## Key files and reading order

1. `experiments/live/README.md` (usage; update its stale status banner first).
2. `experiments/live/run_matrix.py:1156` (`run_batch`).
3. `experiments/live/harness.py:3563` (`LiveRunner.run`).
4. `experiments/live/declaration.py:100` (`loads`).
5. `experiments/analysis/analyze_live.py:1245` (`analyze`).
6. `experiments/tests/test_analysis_golden.py` (frozen statistics).
7. `content/skripsi/lampiran/lampiran-a.tex` (apparatus identity, commands).
8. `content/skripsi/chapters/bab5-kesimpulan-saran.tex:5` (the 207-cell wording).

## Open questions

- Exact dataset path and whether a sanitized subset may be published.
- Whether the thesis should report a descriptive postcondition-health sentence
  in addition to the RQ1 guardrail wording.
- Final scope of the targeted split (harness only, or harness + analyzer).
- Date of the defense and whether the approval-page tense/date must be updated.
