# Bab-3 Analysis Pipeline

Synthetic data generator + comparative statistics for the Bab-3 drift experiments
(manual `kubectl` vs GitOps/ArgoCD). No cluster access needed.

## Data schema (CSV header, exact)

```
subject,env,skenario,rep,t0,td,trci,t2,r1_t0,r1_t1,r1_t2,kubectl_cmds,notes
```

| Column | Meaning |
|---|---|
| `subject` | Workload subject: `S1` / `S2` |
| `env` | Deployment paradigm: `manual` / `gitops` |
| `skenario` | Drift scenario: `A`–`G` (7 scenarios) |
| `rep` | Replication index `1..15` per (`subject`,`env`,`skenario`); `1..10` = R2 replicates, `11..15` = R1 replicates |
| `t0` | Drift-injection latency (s) |
| `td` | Time to detection (s) — R2 |
| `trci` | Time to root-cause identification (s) — R2 |
| `t2` | Time to full recovery (s) — R2 |
| `r1_t0` | Consistency at baseline (0–1) — R1 |
| `r1_t1` | Consistency in drifted state (0–1) — R1 |
| `r1_t2` | Consistency after recovery (0–1) — R1 |
| `kubectl_cmds` | Count of imperative `kubectl` commands used in the run |
| `notes` | Free text (`mock seed=… R1/R2` for synthetic data) |

Design: 7 scenarios × (10 R2 + 5 R1) reps × 2 subjects × 2 envs = **420 rows**.
`analyze.py` pools subjects × reps per (`skenario`, `env`) → n=30 per cell for mock data.

## Commands

```bash
pip install -r experiments/analysis/requirements.txt

python3 experiments/analysis/mockgen.py --seed 42 --out experiments/analysis/outputs/mock_runs.csv

python3 experiments/analysis/analyze.py --in experiments/analysis/outputs/mock_runs.csv --out experiments/analysis/outputs
```

Outputs in the `--out` dir:

- `descriptives.tex` — mean/median/std/range per metric per env per scenario
- `mannwhitney.tex` — Mann-Whitney U (two-sided, α=0.05) manual vs gitops per metric per scenario
- `effects.tex` — Cohen d (manual-minus-gitops) + Cliff delta with interpretation bands
- `boxplot_<metric>_<skenario>.png` — one per R2 sub-metric (`t0,td,trci,t2`) per scenario (28 PNGs)

`analyze.py` exit code is 0 on success; it validates required columns and fails otherwise.

Effect-size bands: Cohen `|d|<0.2` negligible, `<0.5` small, `<0.8` medium, else large;
Cliff `|δ|<0.147` negligible, `<0.33` small, `<0.474` medium, else large.

## Replacing mock data with real runs

1. Run the real experiment protocol (see Bab-3) and record each run as one CSV row
   with the exact header above. Keep `rep` numbering per (`subject`,`env`,`skenario`).
2. Save it e.g. as `experiments/analysis/outputs/real_runs.csv`
   (do not overwrite `mock_runs.csv`; keep mock output for reproducibility checks).
3. Re-run the analyzer unchanged:

```bash
python3 experiments/analysis/analyze.py --in experiments/analysis/outputs/real_runs.csv --out experiments/analysis/outputs_real
```

No code change is needed as long as the header and value types match.
`notes` can carry run anomalies (e.g. `pod-evicted-retry`) and `kubectl_cmds`
should be counted from shell history / audit log for manual runs (0–2 expected for gitops).
