# Matched-interval follow-up — completed session (2026-11-27)

Status: completed and analyzed. 80 planned cells, 80 terminal, 79 analyzed,
1 instrumentation failure. This follow-up is separate from `formal-20261029`
and is not pooled with it.

## Purpose

`formal-20261029` measured a median detection gap of 4.2–4.3 s between
continuous GitOps observation and a 5 s imperative checker for B–E. That gap is
consistent with the checker cadence rather than controller responsiveness. This
follow-up asks one question:

> Does the 4.2–4.3 s detection gap shrink when the imperative checker runs at
> 1.0 s instead of the historical 5.0 s?

The sampler stays at 1.0 s. A remaining gap would point to mechanisms other than
checker cadence; a gap that collapses would support the cadence explanation.
This session is exploratory and does not replace or pool with `formal-20261029`.

## Results

Detection medians (seconds):

| Scenario | GitOps (n) | Imperative (n) | Difference (imperative − GitOps) |
|---|---:|---:|---:|
| B | 0.919 (10) | 1.239 (10) | 0.320 |
| C | 0.916 (10) | 1.226 (9) | 0.310 |
| D | 0.962 (2) | 1.213 (10) | not reported |
| E | 0.956 (10) | 1.227 (10) | 0.272 |

D detection is not reported because only 2 of 10 GitOps runs produced a
separate detection endpoint; the other 8 recovered before that signal was
recorded. The follow-up gap is about 0.25–0.32 s, compared with 4.2–4.3 s in the
5 s batch.

Recovery medians (seconds):

| Scenario | GitOps (n) | Imperative (n) | Difference (imperative − GitOps) |
|---|---:|---:|---:|
| B | 2.670 (10) | 2.636 (10) | −0.034 |
| C | 2.691 (10) | 1.633 (9) | −1.058 |
| D | 1.652 (10) | 2.669 (10) | +1.017 |
| E | 2.760 (10) | 2.603 (10) | −0.157 |

At 1 s: B and E are essentially equal, C favors the imperative mode by about
1.1 s, and D favors GitOps by about 1.0 s. The large 5 s recovery gaps shrink
but do not disappear uniformly.

Selected tests (full table in `live_tests.tex` and `live_effects.tex`):

- B detection: Wilcoxon, p=0.0020, Holm=0.0195, Cliff's δ=1.000 [1.000, 1.000], paired Δ=0.294 s.
- B recovery: Wilcoxon, p=0.0840, Holm=0.5879, δ=−0.520 [−0.980, 0.060], Δ=−0.033 s.
- C detection: Mann–Whitney, 9 vs 10, p<0.001, Holm=0.0034, δ=1.000 [1.000, 1.000].
- C recovery: Mann–Whitney, 9 vs 10, p<0.001, Holm=0.0042, δ=−0.978 [−1.000, −0.867].
- D detection: not estimable (GitOps n=2).
- D recovery: Wilcoxon, p=0.0020, Holm=0.0195, δ=1.000 [1.000, 1.000], Δ=1.026 s.
- E detection: Wilcoxon, p=0.0273, Holm=0.2188, δ=0.880 [0.520, 1.000], Δ=0.313 s.
- E recovery: Wilcoxon, p=0.0840, Holm=0.5879, δ=−0.520 [−1.000, −0.040], Δ=−0.175 s.

Evidence rows are diagnostic only: B p=0.625, C p=0.596, D p=0.111, E p=0.131;
all fail Holm. Do not use them as a headline.

## Design

| Item | Value |
|---|---|
| Batch ID / output | `matched1s-20261127b` under `experiments/live/runs/` |
| Planned / terminal / analyzed | 80 / 80 / 79 |
| Terminal status | 79 `observed`, 1 `instrumentation_failure` |
| Excluded rows | 1 (`matched1s-20261127b-imperative-C-r02`) |
| Scenarios | B, C, D, E |
| Modes | GitOps, imperative |
| Repetitions | 10 per scenario per mode (reps 1–10) |
| Cells | 4 scenarios × 2 modes × 10 reps = **80** |
| Imperative checker interval | **1.0 s** |
| Sampler interval | **1.0 s** |
| Run order | arms interleaved within each scenario/repetition pair |
| Cooldown | 60 s between terminal runs; 1 baseline retry per cell |
| Batch seed | `20261127` |
| Arm order | `imperative`, `gitops` |
| Scenario order | `E`, `B`, `C`, `D` |
| Source revision | `2aff56d8021c3394929ac5a59f949db567bb2298` |
| Render SHA-256 | `ffff8d73b5a7ba09324582928a1a5e6597c30f1430d185bc38dc852aac541efa` |
| Render file | `experiments/evidence-local/freeze-20261127/invenio-frozen-render.json` |
| Batch schema | 3 |
| Timing convention | `completed-observation-v1` |
| Claim status | exploratory single-case study |

The render differs from the formal `81ddd259780e0e6aef333811a0126f86d70a094e`
render in one object: `HorizontalPodAutoscaler/invenio-web-hpa` now uses only
the CPU metric. The four selected analysis resources
(`Deployment/invenio-web`, `ConfigMap/invenio-app-config-6dg2chdbh4`,
`Service/invenio-web`, `SealedSecret/invenio-app-secrets`) are byte-identical to
the formal render. State this apparatus change with the results.

Arms are interleaved to reduce period effects. `formal-20261029` ran every
GitOps cell before every imperative cell, so time-varying node load, HPA state,
or time-of-day effects were confounded with the arm. Alternating arms inside
each scenario/repetition pair spreads those effects across both modes. It does
not remove carryover: the 60 s cooldown and the per-run arm restore/equivalence
gate stay in force, and the pair is a sequencing unit, not a paired
same-subject observation. The arm order inside each pair is fixed by the seed
draw (`imperative`, then `gitops`).

## Failed first attempt and exclusion

The first attempt `matched1s-20261127` stopped before injection at
`matched1s-20261127-imperative-E-r01` with `instrumentation_failure`:
`frozen source revision does not match the observed Argo revision`. The live
source revision had moved from `81ddd259780e0e6aef333811a0126f86d70a094e` to
`2aff56d8021c3394929ac5a59f949db567bb2298`. Its manifest records 1 terminal and
79 pending. The attempt is preserved as evidence and is not analyzed. The
completed session is `matched1s-20261127b`.

In the completed session, one row is excluded:
`matched1s-20261127b-imperative-C-r02` (imperative, scenario C, repetition 2),
`status_not_analyzable`, with error
`kubectl get Deployment failed: Unable to connect to the server: context deadline exceeded`.
The failure occurred before injection (`t0` and baseline are null), so the cell
is an instrumentation failure, not a censored observation. It is not retried and
no value is imputed.

## Commands

Launch command (recorded parameters; the manifest records seed `20261127`):

```bash
python3 experiments/live/run_matrix.py \
  --live --confirm-single-stack --production-like \
  --arms gitops imperative --scenarios B C D E --reps 10 \
  --imperative-interval 1.0 --interleave-arms \
  --seed 20261127 \
  --batch-id matched1s-20261127b \
  --namespace invenio --app invenio-bootstrap \
  --render-file experiments/evidence-local/freeze-20261127/invenio-frozen-render.json \
  --source-revision 2aff56d8021c3394929ac5a59f949db567bb2298 \
  --render-sha256 ffff8d73b5a7ba09324582928a1a5e6597c30f1430d185bc38dc852aac541efa \
  --out experiments/live/runs/matched1s-20261127b
```

Analysis command:

```bash
python3 experiments/analysis/analyze_live.py \
  --in experiments/live/runs/matched1s-20261127b/matched1s-20261127b.analysis.jsonl \
  --rows experiments/live/runs/matched1s-20261127b/matched1s-20261127b.rows.jsonl \
  --out experiments/analysis-matched1s-20261127b \
  --bootstrap 2000 --seed 20261127 --alpha 0.05
```

The analysis output is local and gitignored. It contains seven files:
`live_analysis.json`, `live_overview.tex`, `live_exclusions.tex`, `live_r1.tex`,
`live_survival.tex`, `live_tests.tex`, and `live_effects.tex`. Rerun to a fresh
directory and compare:

```bash
diff -r experiments/analysis-matched1s-20261127b /tmp/matched1s-20261127b-rerun
```

## Boundary and reporting rules

- This is a follow-up, **not a replacement** for `formal-20261029`.
- Do **not** pool these rows with `formal-20261029` rows, manifests, or
  analysis outputs. They are separate batches with different checker cadence
  and a different render.
- Report the period/interleaving rationale with the results: interleaving
  reduces, but does not eliminate, order and time effects; the arms still run
  sequentially on one stack and share its failure domain.
- The 1.0 s checker is an intervention, not the historical protocol. Any
  comparison with the 5.0 s batch must state that the cadence changed.
- The web HPA is CPU-only in this render. The four selected analysis resources
  are identical to the formal render, but the apparatus is not fully identical.
- D detection has only two observed GitOps values; do not report a D detection
  difference. D recovery is testable and has ten values per mode.
- One cell is an instrumentation failure preserved as an exclusion. Do not
  silently retry failed cells; only a pre-injection baseline failure is
  retryable.
- The session is exploratory: one stack, one apparatus, one sequential order.
  No population or causal claim.
