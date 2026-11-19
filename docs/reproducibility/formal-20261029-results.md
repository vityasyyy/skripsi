# Formal collection result — 2026-10-30

Status: collection complete; primary analysis frozen and reproduced identically
on 2026-11-19. This document reports the observed numbers. Provenance is in
[`../../experiments/REVISIONS.md`](../../experiments/REVISIONS.md), the dataset
inventory and checksums are in
[`../../experiments/DATA.md`](../../experiments/DATA.md), and claim-to-evidence
mapping is in [`claim-traceability.md`](claim-traceability.md).

## Completion

| Item | Value |
|---|---|
| Batch | `formal-20261029` |
| Planned cells | 210 |
| Terminal cells | **210** (pending 0) |
| Raw rows | 211 (210 cells + 1 pre-injection baseline retry) |
| Analysis rows | 207 |
| Excluded | 4 |
| GitOps revision | `81ddd259780e0e6aef333811a0126f86d70a094e` |
| Render SHA-256 | `a5efd711d661438590a730291c41b70d1c668b2672d51a54f68c0ff68e311703` |
| Thesis revision | `3572f3c1c11d3abc8b63882c4348b1b803d4256f` |
| Seed | `20261029` |
| Scenario order | `E, A, G, D, C, F, B` |
| Arm order | `gitops`, then `imperative` |
| Timing convention | `completed-observation-v1` |

## Exclusions (4 of 211 raw rows)

| Reason | Count | Affected run | Detail |
|---|---|---|---|
| Instrumentation failure | 2 | `gitops-C-r01`, `imperative-G-r05` | Collector produced no initial sample, or metrics-server was unavailable |
| Baseline failure, retried | 1 | `gitops-C-r08` attempt 0 | `invenio-bootstrap` was not Synced/Healthy before injection; `-retry1` is observed and analyzed |
| Batch stop | 1 | `gitops-C-r02` | Complete observed run; harness process exited non-zero, so the row is excluded conservatively |

The analyzer reports the same four rows with a coarser schema:
`status_not_analyzable = 3` (`C-r01`, the failed `C-r08` attempt, `G-r05`) and
`batch_stop = 1` (`C-r02`). The prose taxonomy splits the three
`status_not_analyzable` rows into two instrumentation failures and one baseline
failure. Do not read `status_not_analyzable = 3` as three instrumentation
failures.

Three cells have no analysis row; `gitops-C-r08` remains analyzed through its
retry. None of the four rows is a measured recovery outcome, and none was
imputed. `gitops-C-r02` is analyzed separately in the sensitivity section; the
primary analysis keeps 207 rows.

The batch manifest records `state: "stopped"` with
`stop_run_id: "formal-20261029-gitops-C-r01"` because three runs retain a
`stop_reason`. Collection completeness is read from `counts.terminal = 210` and
`counts.pending = 0`, not from `state`; see
[`../../experiments/DATA.md`](../../experiments/DATA.md).

## Efficacy — managed drift (B–E), R2 repetitions

Twelve predeclared comparisons, two-sided, Holm-corrected at α = 0.05.
**All twelve reject Holm.**

| Scenario | Metric | n | p (Holm) | Cliff's δ | δ 95% CI | Median paired Δ (s) |
|---|---|---|---|---|---|---|
| B | detection | 10 pairs | 0.0176 | 1.00 | [1.00, 1.00] | 4.27 |
| B | evidence | 10 pairs | 0.0176 | 1.00 | [1.00, 1.00] | 4.05 |
| B | recovery | 10 pairs | 0.0195 | 0.48 | [−0.08, 1.00] | 2.95 |
| C | detection | 8 v 10 | 0.0054 | 1.00 | [1.00, 1.00] | — |
| C | evidence | 8 v 10 | 0.0054 | 1.00 | [1.00, 1.00] | — |
| C | recovery | 8 v 10 | 0.0176 | 0.75 | [0.25, 1.00] | — |
| D | detection | 4 v 10 | 0.0176 | 1.00 | [1.00, 1.00] | — |
| D | evidence | 8 v 10 | 0.0054 | 1.00 | [1.00, 1.00] | — |
| D | recovery | 10 pairs | 0.0176 | 1.00 | [1.00, 1.00] | 5.05 |
| E | detection | 10 pairs | 0.0176 | 1.00 | [1.00, 1.00] | 4.29 |
| E | evidence | 10 pairs | 0.0176 | 1.00 | [1.00, 1.00] | 4.04 |
| E | recovery | 10 pairs | 0.0176 | 0.86 | [0.64, 1.00] | 3.03 |

Positive median paired differences are in the direction of the imperative arm being
slower. Detection and evidence differences cluster near 4.0–4.3 s, consistent with
the imperative checker's poll interval rather than a property of the controller.
Recovery effect sizes are smaller than detection/evidence for B (δ 0.48) and C
(δ 0.75), which is the more interesting result: ending the drift is less separable
than noticing it.

`C` used Mann–Whitney for all three metrics (8 GitOps observations). `D` used
Mann–Whitney for detection (4 GitOps observations) and evidence (8), while D
recovery remained paired (10 pairs). Complete pairs were insufficient for the
unpaired rows, per the frozen fallback rule. This is reported, not silently
substituted.

## R1 — selected-field equality, repetitions 11–15

Medians per arm, all five repetitions present:

| Scenario | GitOps base/first/last | Imperative base/first/last |
|---|---|---|
| A | 100 / 100 / 100 | 100 / 100 / 100 |
| B | 100 / 75 / 100 | 100 / 75 / 100 |
| C | 100 / 75 / 100 | 100 / 75 / 100 |
| D | 100 / 75 / 100 | 100 / 75 / 100 |
| E | 100 / 75 / 100 | 100 / 75 / 100 |
| F | 100 / 75 / 100 | 100 / 75 / 100 |
| **G** | **100 / 75 / 75** | 100 / 75 / 100 |

Drift is detected at 75 and restored to 100 in both arms for B–F. Scenario A
remains 100 throughout. **G is the sole asymmetry**: GitOps never returned the
SealedSecret to 100, while imperative did. A remains 100 consistently with HPA
owning replicas and `/spec/replicas` being excluded from the declaration.

## Censoring

| Phase | Metric | Observed | Right-censored | Unobserved before stop |
|---|---|---|---|---|
| R2 | detection | 121 | 10 | 6 |
| R2 | evidence | 134 | 0 | 3 |
| R2 | recovery | 127 | 10 | 0 |
| R1 | detection | 61 | 5 | 4 |
| R1 | evidence | 70 | 0 | 0 |
| R1 | recovery | 65 | 5 | 0 |

All 15 recovery censoring events (10 in R2 and 5 in R1) are GitOps scenario G.
No censored value was imputed; no missing endpoint was treated as a censored
observation.

## Interpretation boundaries

- This is an **exploratory single-case sequential study**. No confirmatory claim is
  made, and no universal GitOps superiority is asserted.
- Only B–E enter efficacy. A is the HPA control, F a separately reported declared
  Service drift, G a descriptive non-Argo case. G is excluded from efficacy by the
  frozen method even though its batch rows carry `efficacy_eligible=true`.
- Detection latency is dominated by mechanism cadence: GitOps samples continuously,
  the imperative checker polls. The ~4 s gap measures that design difference, not
  controller responsiveness alone.
- One stack, one shared failure domain, sequential arms. Order effects are mitigated
  by seeded order, baseline gates, resets and cooldowns, not eliminated.
- R3 unmeasured. Off-site copy deferred. Cross-host clock uncertainty handled
  conservatively, not certified.

## F label in the output schema

F is a declared `Service/invenio-web` `targetPort` drift. The analyzer keeps the
output key `visibility_boundary` for F as a retained schema label; the current
definition is stated in the analyzer notes and in the thesis prose. The key
does not mean that F is an unmanaged object. F stays outside the B–E efficacy
family because the twelve-hypothesis family was fixed before collection, not
because of the old label. Results are unaffected.

## Artifacts and reproduction

- Batch: `experiments/formal-20261029/` (local, gitignored; `SHA256SUMS` and
  `PROVENANCE.json` are committed).
- Analysis: `experiments/analysis-formal-20261029/` (local, gitignored;
  `live_analysis.json`, `live_overview.tex`, `live_tests.tex`,
  `live_effects.tex`, `live_r1.tex`, `live_survival.tex`,
  `live_exclusions.tex`). Seven output hashes are recorded in
  [`../../experiments/DATA.md`](../../experiments/DATA.md).
- Stopped earlier attempt (4 cells, discarded):
  `experiments/evidence-local/formal-stop-20261030/` (local historical archive).

The frozen analysis reproduces identically:

```bash
python3 experiments/analysis/analyze_live.py \
  --in experiments/formal-20261029/formal-20261029.analysis.jsonl \
  --rows experiments/formal-20261029/formal-20261029.rows.jsonl \
  --out /tmp/formal-20261029-rerun \
  --bootstrap 2000 --seed 20261029 --alpha 0.05
```

The only expected `diff -r` difference is the `SHA256SUMS` file that the
analyzer does not write. Sensitivity for `gitops-C-r02` is reproduced with
`python3 experiments/sensitivity/c_r02_sensitivity.py`; that output is not
committed. See [`verification-2026-11-19.md`](verification-2026-11-19.md) for
the exact evidence.
