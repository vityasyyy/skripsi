# WORKER-REPORT — Bab-3 analysis pipeline (agent/exp-analysis)

## What changed

Built the Bab-3 analysis pipeline under `experiments/analysis/` (new directory;
no other paths touched). Branch: `agent/exp-analysis`.

File list (all new):

- `experiments/analysis/requirements.txt` — pinned minimums: `pandas>=2.2.0`,
  `scipy>=1.13.0`, `matplotlib>=3.8.0` (Python 3.12).
- `experiments/analysis/mockgen.py` — seeded (`--seed`, default 42) synthetic
  generator; gitops faster/lower-variance than manual by construction with
  per-scenario base means; writes exact header
  `subject,env,skenario,rep,t0,td,trci,t2,r1_t0,r1_t1,r1_t2,kubectl_cmds,notes`.
- `experiments/analysis/analyze.py` — `--in <csv> --out <dir>`; descriptives
  (mean/median/range/std) per metric per env per scenario; Mann-Whitney U
  two-sided α=0.05 manual vs gitops per metric per scenario; Cohen d
  (manual-minus-gitops) + Cliff delta with interpretation bands; writes
  `descriptives.tex`, `mannwhitney.tex`, `effects.tex` + one boxplot PNG per
  R2 sub-metric per scenario.
- `experiments/analysis/README.md` — schema, commands, real-runs replacement procedure.
- `experiments/analysis/outputs/` — generated artifacts: `mock_runs.csv`
  (420 data rows), 3 `.tex` files, 28 boxplot PNGs
  (`boxplot_{t0,td,trci,t2}_{A..G}.png`).

Assumptions (no blocking ambiguity; documenting choices):

1. `rep` 1..10 = R2 replicates, 11..15 = R1 replicates per
   (`subject`,`env`,`skenario`); all metric columns populated in every row so
   `analyze.py` pools subjects × reps → n=30 per (`skenario`,`env`) cell.
   Row count: (7×10 + 7×5) × 2 subjects × 2 envs = 420. Verified.
2. R2 sub-metrics for boxplots = `t0,td,trci,t2` (timing metrics) → 4×7=28 PNGs.
3. Cohen bands: |d|<0.2 negligible, <0.5 small, <0.8 medium, else large
   (refines the `<0.2 / ~0.5 / >0.8` spec); Cliff bands: <0.147 negligible,
   <0.33 small, <0.474 medium, else large (Romano et al.).

## Verification commands + outputs

All run in worktree root, no cluster commands used (none needed).

1. `pip install -r experiments/analysis/requirements.txt`
   → SUCCESS (pandas 2.3.3, scipy 1.17.1 already satisfied;
   installed matplotlib 3.11.2 + deps).
2. `python3 experiments/analysis/mockgen.py --seed 42 --out experiments/analysis/outputs/mock_runs.csv`
   → `Wrote 420 rows to experiments/analysis/outputs/mock_runs.csv (seed=42)`;
   header verified exact; `data_rows: 420` (421 lines incl. header).
3. `python3 experiments/analysis/analyze.py --in experiments/analysis/outputs/mock_runs.csv --out experiments/analysis/outputs`
   → `exit=0`; `OK: 112 descriptive cells, 56 MW tests, 28 boxplots`;
   `*.tex` count = 3, `*.png` count = 28. Spot check: scenario A `td`
   manual mean ≈30.5 vs gitops ≈15 (MW p≈2e-09, d≈2.0 large) — direction correct.
4. `git status --short` → only `?? experiments/` (+ this report); no
   `content/`, `docs/`, `experiments/scripts`, `experiments/subjects`, or other
   worktree touched.

## What remains

- Nothing for this work unit: acceptance met (pip install OK, 420-row header-exact
  CSV, analyze exit 0 with 3 `.tex` + PNGs, Conventional Commit below).
- Follow-up (out of scope, for thesis author): drop real `real_runs.csv` with the
  same header into `outputs/` and run `analyze.py --in ... --out outputs_real`;
  `\input` the `.tex` snippets from Bab-4.

## Escalation

None — no blockers. No questions requiring operator decision.
