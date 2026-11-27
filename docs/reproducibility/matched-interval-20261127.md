# Matched-interval follow-up — launch packet (2026-11-27)

Status: prepared for review; **not approved and not run**. The worker did not
execute any `--live` command and did not mutate the cluster. The lead runs the
launch command only after review and final approval.

## Purpose

`formal-20261029` measured a median detection gap of 4.2–4.3 s between
continuous GitOps observation and a 5 s imperative checker for B–E (the
evidence gap was about 4.0 s). That gap is consistent with the checker cadence
rather than controller responsiveness. This follow-up asks one question:

> Does the 4.2–4.3 s detection gap shrink when the imperative checker runs at
> 1.0 s instead of the historical 5.0 s?

The sampler stays at 1.0 s. A remaining gap would point to mechanisms other than
checker cadence; a gap that collapses would support the cadence explanation.
This batch is exploratory and does not replace or pool with `formal-20261029`.

## Design

| Item | Value |
|---|---|
| Scenarios | B, C, D, E (managed drift; the B–E efficacy family) |
| Modes | GitOps, imperative |
| Repetitions | 10 per scenario per mode (R2 block, reps 1–10) |
| Cells | 4 scenarios × 2 modes × 10 reps = **80** |
| Run order | arms interleaved within each scenario/repetition pair |
| Imperative checker interval | **1.0 s** |
| Sampler interval | 1.0 s |
| Cooldown | 60 s between terminal runs; 1 baseline retry per cell |
| Batch seed | `20261027` (the launch command omits `--seed`, so the default applies) |
| Arm order | `imperative`, `gitops` |
| Scenario order | `C`, `D`, `E`, `B` |
| Stack / render | same frozen stack and render as `formal-20261029` |
| Source revision | `81ddd259780e0e6aef333811a0126f86d70a094e` |
| Render SHA-256 | `a5efd711d661438590a730291c41b70d1c668b2672d51a54f68c0ff68e311703` |
| Batch ID / output | `matched1s-20261127` under `experiments/live/runs/` |
| Batch schema | 3 (manifest and summary record the interval and interleave flag) |

Arms are interleaved to reduce period effects. `formal-20261029` ran every
GitOps cell before every imperative cell, so time-varying node load, HPA state,
or time-of-day effects were confounded with the arm. Alternating arms inside
each scenario/repetition pair spreads those effects across both arms. It does
not remove carryover: the 60 s cooldown and the per-run arm restore/equivalence
gate stay in force, and the pair is a sequencing unit, not a paired
same-subject observation. The planned arm order inside each pair is fixed by the
seed draw (`imperative`, then `gitops`).

Repetition numbers keep the frozen phase mapping: reps 1–10 are R2. This batch
has no R1 reps, so its summary will show 80 planned R2 cells and 0 R1 cells.

## Frozen identity

The render and source are the same artefacts used by `formal-20261029`; the
batch is new. The batch ID and output directory are new, and
`experiments/formal-20261029/` must remain untouched.

## Exact launch command

```bash
python3 experiments/live/run_matrix.py \
  --live --confirm-single-stack --production-like \
  --arms gitops imperative --scenarios B C D E --reps 10 \
  --imperative-interval 1.0 --interleave-arms \
  --batch-id matched1s-20261127 \
  --namespace invenio --app invenio-bootstrap \
  --render-file experiments/evidence-local/freeze-20261029/invenio-frozen-render.json \
  --source-revision 81ddd259780e0e6aef333811a0126f86d70a094e \
  --render-sha256 a5efd711d661438590a730291c41b70d1c668b2672d51a54f68c0ff68e311703 \
  --out experiments/live/runs/matched1s-20261127
```

Do not run this command until the pre-launch checklist passes and the lead has
approved it.

## Pre-launch checklist

- [ ] `kubectl get nodes` — every node `Ready`.
- [ ] `kubectl get applications -n argocd` — every application `Synced` and
      `Healthy`.
- [ ] `kubectl get deploy,hpa -n invenio` — deployments and HPA healthy; node
      memory and CPU under the 70% gate from `experiments/LIVE-OBSERVER.md`
      (raw metrics-server usage over `Node.status.allocatable`, not rounded
      `kubectl top`).
- [ ] `INVENIO_TOKEN` is exported from a private file; it must never appear in
      argv or logs.
- [ ] The frozen render file exists and its SHA-256 is
      `a5efd711d661438590a730291c41b70d1c668b2672d51a54f68c0ff68e311703`.
- [ ] Dry-run first: the 80-cell plan is correct and writes no cluster state.

Dry-run (no `--live`, no render requirement, no cluster writes):

```bash
python3 experiments/live/run_matrix.py \
  --arms gitops imperative --scenarios B C D E --reps 10 \
  --imperative-interval 1.0 --interleave-arms \
  --batch-id matched1s-20261127-dry \
  --namespace invenio --app invenio-bootstrap \
  --out /tmp/matched1s-dry
```

Expected dry-run result: 80 planned rows, `mode: dry_run`, `mutations_executed:
0`, 79 cooldowns recorded with `applied: false`, interval `1.0`, and
`interleave_arms: true`. The manifest should alternate arms in every adjacent
pair (for example `imperative-C-1`, `gitops-C-1`, `imperative-C-2`, ...).
The runner refuses an existing output directory, so use a fresh `--out` (for
example `$(mktemp -d)/matched1s-dry`) or remove the previous dry-run directory
before rerunning.
The runner tests pin the legacy 210-run order and batch ID, the interleaved
80-cell order, the harness argument, and the resume checks.

## Expected duration

Estimate only, not a measurement. Historical `formal-20261029` per-run wall
times for B–E, repetitions 1–10 (median seconds, GitOps / imperative):

| Scenario | GitOps | Imperative |
|---|---:|---:|
| B | 51.3 | 54.8 |
| C | 15.8 | 17.0 |
| D | 60.0 | 59.6 |
| E | 42.8 | 54.5 |

Ten repetitions of the eight cells total about 3,560 s of runs; 79 cooldowns at
60 s add about 4,740 s. That is roughly **2.3 h**, and the faster checker may
shorten the imperative runs slightly. Plan for **2.5–3 h** including preflight,
buffer, and any baseline retry. The historical batch also contained a multi-hour
manual pause, which this estimate excludes. The C GitOps median includes the
`C-r01` instrumentation failure because it is the final attempt for that cell;
excluding it would lower the estimate by about ten seconds.

## Analysis command

```bash
python3 experiments/analysis/analyze_live.py \
  --in experiments/live/runs/matched1s-20261127/matched1s-20261127.analysis.jsonl \
  --rows experiments/live/runs/matched1s-20261127/matched1s-20261127.rows.jsonl \
  --out experiments/analysis-matched1s-20261127 \
  --bootstrap 2000 --seed 20261127 --alpha 0.05
```

## Boundary and reporting rules

- This is a follow-up, **not a replacement** for `formal-20261029`.
- Do **not** pool these rows with `formal-20261029` rows, manifests, or
  analysis outputs. They are separate batches with different checker cadence.
- Report the period/interleaving rationale with the results: interleaving
  reduces, but does not eliminate, order and time effects; the arms still run
  sequentially on one stack and share its failure domain.
- The 1.0 s checker is an intervention, not the historical protocol. Any
  comparison with the 5.0 s batch must state that the cadence changed.
- If the batch stops, preserve it and inspect the manifest; do not silently
  retry failed cells. Only a pre-injection baseline failure is retryable.
