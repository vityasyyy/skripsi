# Claim traceability — numerical claims to evidence

Scope: every numerical or direction claim in Bab IV, Bab V, both abstracts, and
the defense deck, plus the accounting claims that those numbers depend on. The
frozen output is `experiments/analysis-formal-20261029/live_analysis.json`
(referred to below as **LA**) and
`experiments/formal-20261029/formal-20261029.summary.json` (**SU**). The raw
evidence is `experiments/formal-20261029/formal-20261029.rows.jsonl` (**ROWS**)
and `.analysis.jsonl` (**ANA**). The batch manifest is **MAN**.

Deck references below identify the deck as a location, not a numbered slide; deck
slide numbers are not stable across revisions.

Status legend:

- **Frozen** — a direct field in a frozen output; the output hash is recorded in
  [`../../experiments/DATA.md`](../../experiments/DATA.md).
- **Test-locked** — the same behavior is pinned by an offline test; the observed
  value still comes from the frozen output.
- **Derived** — computed from frozen rows; no aggregate field exists. The query
  is given.
- **External** — literature or build metadata, not experiment output.
- **Gap** — no direct committed output/test; reported in
  [`verification-2026-11-19.md`](verification-2026-11-19.md) and the worker report.

Note on labels: `R1` and `R2` are internal data-phase labels in the frozen
analyzer and collection files. They are not manuscript metrics. The thesis calls
the check "pemeriksaan kecocokan konfigurasi" and the two blocks "blok waktu"
and "blok kecocokan".

Tests use synthetic fixtures. A passing test locks the algorithm, not the
observed batch numbers; the observed numbers are locked by the frozen outputs
and their SHA-256 manifest. `experiments/analysis/rq2_report.py` is a
post-freeze view over the same analyzer; its `--check-frozen` mode compares the
selected RQ fields to `live_analysis.json` and reports `PENDING` when that file
is absent. In this checkout the frozen rows and `live_analysis.json` are not
present, so numeric checks that depend on them are pending, not passed.

## 1. Collection accounting and exclusions

| Claim | Manuscript location | Frozen output / key | Code | Test | Raw evidence | Status |
|---|---|---|---|---|---|---|
| 210 planned cells = 7 × 2 × 15; 140 R2 + 70 R1 | Bab IV §Data yang Dianalisis, Table 4.1 (`tab:akuntansi-sel`); abstract; deck | `MAN.counts.total=210`, `MAN.runs` length 210; phase from `rep` | `run_matrix.build_plan()`, `phase_for()` | `test_reps_one_to_ten_are_r2_and_eleven_to_fifteen_are_r1`, `test_seed_reproduces_order_and_both_arms_share_scenarios` | MAN | Frozen + Test-locked |
| 210 terminal cells, 0 pending | Bab IV §Data yang Dianalisis, Table 4.1; Bab V §Kesimpulan; deck | `MAN.counts.terminal=210`, `MAN.counts.pending=0` | `run_matrix._counts()`, `run_batch()` | `test_summary_counts_censoring_and_exclusions` | MAN, ROWS | Frozen |
| 193 observed / 15 right-censored / 2 instrumentation-failure terminal cells | Bab IV §Data yang Dianalisis, Table 4.1; Bab V §Keterbatasan; deck | `MAN.counts.by_status` | `run_matrix._counts()` | `test_summary_counts_censoring_and_exclusions` | MAN, ROWS statuses | Frozen |
| 211 raw rows | Bab IV §Data yang Dianalisis, Table 4.1; Bab V §Kesimpulan; deck | ROWS length; `PROVENANCE.json.raw_rows=211` | `run_matrix._analysis_view()` | `test_rows_map_to_summarize_and_csv_without_losing_arm` | ROWS | Frozen |
| 207 analysis rows (192 observed, 15 right-censored) | Bab IV §Data yang Dianalisis, Table 4.1; Bab V §Kesimpulan; abstract; deck | ANA length; `PROVENANCE.json.analysis_rows=207`; `LA.batch.analysis_rows=207`; `LA.batch.r2_rows=137`, `r1_rows=70` | `run_matrix._analysis_view()`, `_analysis_row()` | `test_rows_map_to_summarize_and_csv_without_losing_arm` | ANA | Frozen |
| 4 excluded raw rows: 2 instrumentation + 1 retried baseline + 1 batch stop | Bab IV §Data yang Dianalisis; Bab V §Keterbatasan; abstract; deck | `LA.exclusions.by_reason = {status_not_analyzable: 3, batch_stop: 1}`; `LA.exclusions.rows` | `analyze_live._exclusions()`, `_classify_raw()` | `test_exclusions_are_minimal_and_outputs_never_echo_raw_values`, `test_classify_raw_reports_every_conservative_exclusion` | ROWS, ANA | Frozen |
| Analyzer taxonomy `status_not_analyzable=3` maps to C-r01, C-r08 attempt 0, G-r05; `batch_stop=1` maps to C-r02 | Bab IV §Data yang Dianalisis prose; [`formal-20261029-results.md`](formal-20261029-results.md); [`../../experiments/DATA.md`](../../experiments/DATA.md) | `LA.exclusions.rows[].{run_id,reason}` | `_exclusions()`, `_classify_raw()` | `test_classify_raw_reports_every_conservative_exclusion`, `test_issue_example_retry_identity_is_accepted` | ROWS, ANA | Frozen + Test-locked |
| C-r08 attempt 0 is `baseline_failure`; `-retry1` is observed and supplies the cell | Bab IV §Data yang Dianalisis; Bab V §Keterbatasan | `MAN.runs[].attempts`; ROWS attempt 0/1; ANA has only `-retry1` | `run_matrix._baseline_retryable()`, `_validate_attempt()`; `analyze_live._validate_raw_chain()` | `test_baseline_failure_retries_with_new_id_and_preserved_evidence`, `test_runner_retry_flows_through_analysis_view_into_analyzer`, `test_issue_example_retry_identity_is_accepted` | MAN, ROWS, ANA | Frozen + Test-locked |
| Manifest `state=stopped` despite 210 terminal cells | [`formal-20261029-results.md`](formal-20261029-results.md); [`../../experiments/DATA.md`](../../experiments/DATA.md) | `MAN.state`, `MAN.stop_reason`, `MAN.stop_run_id`, `MAN.counts` | `run_batch()` final state block | `test_resume_rejects_malformed_manifests`, `test_resume_rejects_each_manifest_identity_violation`, `test_summary_counts_censoring_and_exclusions` | MAN | Frozen |

## 2. Configuration-match check (internal R1)

| Claim | Manuscript location | Frozen output / key | Code | Test | Raw evidence | Status |
|---|---|---|---|---|---|---|
| Median R1 B–F = 100 / 75 / 100 in both arms; A = 100 / 100 / 100 | Bab IV §Data yang Dianalisis; Lampiran A Table `tab:audit-kecocokan`; Bab V §Temuan Utama; abstract; deck | `LA.r1[scenario/arm/R1].{baseline,first,last}.median` | `analyze_live._r1_entries()`; `harness.score()`, `resource_results()` | `test_r1_descriptives_report_missing_values`, `test_synthetic_matrix_matches_the_frozen_summary` | ANA `r1_*`; per-run `samples.jsonl` | Frozen + Test-locked |
| G GitOps = 100 / 75 / 75; G imperative = 100 / 75 / 100 | Bab IV §Data yang Dianalisis; Lampiran A Table `tab:audit-kecocokan`; Bab V §Temuan Utama; abstract; deck | `LA.r1[G/gitops/R1].last.median=75`, `LA.r1[G/manual/R1].last.median=100` | `_r1_entries()`, `score()` | No test embeds the observed G values; algorithm tests cover scoring | ANA `r1_last` for G; per-run `samples.jsonl` | Frozen (no observed-value test) |
| A stays 100 because `/spec/replicas` is HPA-owned and excluded | Bab IV §Data yang Dianalisis; Bab V §Temuan Utama; abstract; deck | `LA.r1[A/*/*].{baseline,first,last}.median=100` | `declaration.selected_fields()`; `harness.build_contract()`, `recovery_manifest(hpa_owned=True)` | `test_hpa_owned_replicas_are_excluded_and_retained_separately` | ANA, `contract.json` | Frozen + Test-locked |
| F is a declared `Service/invenio-web` `targetPort` drift; F is outside B–E efficacy | Bab IV §Data yang Dianalisis; Bab V §Temuan Utama; abstract; deck | `LA.batch.efficacy_ineligible` contains F; `LA.batch.efficacy_ineligible_reason.F="visibility_boundary"`; `LA.notes[]` states current definition | `harness.inject()` F branch, `planned_mutations()`; `analyze_live.POPULATIONS` / `ROW_GROUPS` | `test_service_targetport_injection_patches_the_declared_service`, `test_service_targetport_drift_is_always_distinct`, `test_control_boundary_and_g_are_outside_efficacy` | `injection.json`, `contract.json`, ANA | Frozen + Test-locked |
| G is the only R1 asymmetry; its mechanism is unattributed | Bab IV §Data yang Dianalisis; Bab V §Temuan Utama; deck | `LA.r1[G/gitops/R1].last.median=75`; ANA `recovery_controller=unattributed` for all 15 G GitOps rows | `_r1_entries()`; runner row builder | `test_scenario_g_annotation_is_removed` (injection/cleanup only) | ANA R1 G rows, `imperative.json`/`postcondition.json` | Frozen; mechanism claim is interpretive |

## 3. Timing — censoring, direction, and gaps

| Claim | Manuscript location | Frozen output / key | Code | Test | Raw evidence | Status |
|---|---|---|---|---|---|---|
| Timing censoring: detection 121/10/6, evidence 134/0/3, recovery 127/10/0 | Lampiran B §Pengamatan yang Berhenti Sebelum Peristiwa, Table B.5; deck | `SU.censoring.R2.*` | `run_matrix._censoring()` | `test_summary_counts_censoring_and_exclusions` | ANA status fields | Frozen + Test-locked |
| Validity censoring: detection 61/5/4, evidence 70/0/0, recovery 65/5/0 | Lampiran B §Pengamatan yang Berhenti Sebelum Peristiwa, Table B.5; deck | `SU.censoring.R1.*` | `run_matrix._censoring()` | `test_summary_counts_censoring_and_exclusions` | ANA status fields | Frozen + Test-locked |
| All 15 recovery censoring events (10 timing + 5 validity) are GitOps G | Bab IV §Waktu Deteksi/§Waktu Pemulihan; Bab V §Keterbatasan; deck | `SU.censoring.R2.recovery.right_censored=10`, `SU.censoring.R1.recovery.right_censored=5`; ANA rows with `recovery_status=right_censored` are all `gitops/G` | `_censoring()`; `_survival_entries()` | `test_censored_pair_falls_back_to_exploratory_mann_whitney`, `test_survival_table_reports_missing_and_excluded_endpoints` | ANA | Frozen + Test-locked |
| Four GitOps analysis rows have `t_e < t_d` | Bab IV §Waktu Deteksi/§Waktu Pemulihan | No aggregate field. Derived query below | `analyze_live._validate_timing()` allows signed differences | No test embeds the observed four rows | ANA | **Derived** |
| Detection/evidence median gaps for B and E are 4.0–4.3 s | Bab IV §Waktu Deteksi/§Waktu Pemulihan; Bab V §Temuan Utama; abstract; deck | `LA.efficacy[B/detection].effect.median_paired_difference=4.2747`; `B/evidence=4.0478`; `E/detection=4.2927`; `E/evidence=4.0441` | `_comparison()`, `_bootstrap_median()` | `test_complete_pairs_use_wilcoxon_signed_rank` | ANA | Frozen + Test-locked |
| Recovery median gaps: B 2.95, D 5.05, E 3.03 s | Bab IV §Waktu Deteksi/§Waktu Pemulihan; Bab V §Temuan Utama; deck | `LA.efficacy[B/recovery].effect.median_paired_difference=2.9462`; `D/recovery=5.0523`; `E/recovery=3.0314` | `_comparison()` | `test_complete_pairs_use_wilcoxon_signed_rank`, `test_bootstrap_is_deterministic_for_a_fixed_seed` | ANA | Frozen + Test-locked |
| Positive direction means the imperative arm is slower on the observed signal | Bab IV §Waktu Deteksi/§Waktu Pemulihan; Bab V §Temuan Utama; abstract; deck | `LA.efficacy[].effect.cliffs_delta` positive; `median_paired_difference` positive | `cliffs_delta()` computes P(manual > gitops) − P(manual < gitops); `_comparison()` uses `manual - gitops` | `test_complete_pairs_use_wilcoxon_signed_rank` | ANA | Frozen + Test-locked |
| Observation horizon is 300 s; values beyond are censored, not zero | Bab IV §Waktu Deteksi/§Waktu Pemulihan; Bab V §Keterbatasan; deck | ANA `censor_seconds=300.0`; `SU.censoring.*.right_censored` | `harness.parse_args(--timeout=300)`, row builder | `test_new_right_censored_row_requires_deadline_completion`, `test_kaplan_meier_and_rmst_never_impute_censored_as_zero` | ANA, ROWS | Frozen + Test-locked |

Derived query for the four signed rows:

```bash
python3 - <<'PY'
import json
rows = [json.loads(l) for l in open(
    "experiments/formal-20261029/formal-20261029.analysis.jsonl")]
print([r["run_id"] for r in rows
       if r["detection_seconds"] is not None
       and r["evidence_seconds"] is not None
       and r["evidence_seconds"] < r["detection_seconds"]])
PY
# ['formal-20261029-gitops-E-r04', 'formal-20261029-gitops-C-r04',
#  'formal-20261029-gitops-B-r02', 'formal-20261029-gitops-B-r06']
```

## 4. Timing — 12 B–E comparisons

All p-values are Holm-adjusted, two-sided, α = 0.05. The frozen fields are
`LA.efficacy[scenario/metric].holm_adjusted_p`, `.reject_holm`,
`.effect.cliffs_delta`, `.effect.cliffs_delta_ci`, and
`.effect.median_paired_difference`. The tests lock the families and algorithms.

| Claim | Manuscript location | Frozen output / key | Code | Test | Status |
|---|---|---|---|---|---|
| All 12 B–E comparisons have Holm-adjusted p < 0.05 (exploratory model) | Lampiran B §Tabel Uji Lengkap, Table B.2; Bab V §Temuan Utama; abstract; deck | `LA.efficacy[].reject_holm=true` | `analyze()`, `holm_adjust()` | `test_holm_adjustment_uses_predeclared_family`, `test_synthetic_matrix_matches_the_frozen_summary` | Frozen + Test-locked |
| Holm p range 0.0054–0.0195 | Lampiran B §Tabel Uji Lengkap, Table B.2; Bab V §Temuan Utama; abstract; deck | min/max of `LA.efficacy[].holm_adjusted_p` | `holm_adjust()` | same | Frozen + Test-locked |
| B detection: p=0.0176, δ=1.00 [1.00,1.00], Δ=4.27 s | Lampiran B Table B.2/B.3; deck | `LA.efficacy[B/detection]` | `_comparison()`, `wilcoxon_signed_rank()`, `cliffs_delta()` | `test_complete_pairs_use_wilcoxon_signed_rank` | Frozen + Test-locked |
| B evidence: p=0.0176, δ=1.00 [1.00,1.00], Δ=4.05 s | Lampiran B Table B.2/B.3; deck | `LA.efficacy[B/evidence]` | same | same | Frozen + Test-locked |
| B recovery: p=0.0195, δ=0.48 [−0.08,1.00], Δ=2.95 s; CI includes zero | Lampiran B Table B.2/B.3; Bab V §Temuan Utama; abstract; deck | `LA.efficacy[B/recovery]` | same | same | Frozen + Test-locked |
| C detection: p=0.0054, δ=1.00 [1.00,1.00], Mann–Whitney 8 vs 10 | Lampiran B Table B.2/B.3; deck | `LA.efficacy[C/detection].pairing={method:unpaired,n_gitops:8,n_manual:10}` | `_pairing()`, `mann_whitney_u()` | `test_censored_pair_falls_back_to_exploratory_mann_whitney` | Frozen + Test-locked |
| C evidence: p=0.0054, δ=1.00 [1.00,1.00], Mann–Whitney 8 vs 10 | Lampiran B Table B.2/B.3; deck | `LA.efficacy[C/evidence]` | same | same | Frozen + Test-locked |
| C recovery: p=0.0176, δ=0.75 [0.25,1.00], Mann–Whitney 8 vs 10 | Lampiran B Table B.2/B.3; Bab V §Temuan Utama; abstract; deck | `LA.efficacy[C/recovery]` | same | same | Frozen + Test-locked |
| D detection: p=0.0176, δ=1.00 [1.00,1.00], Mann–Whitney 4 vs 10 | Lampiran B Table B.2/B.3; deck | `LA.efficacy[D/detection].pairing={method:unpaired,n_gitops:4,n_manual:10,reason:missing_blocks}` | same | same | Frozen + Test-locked |
| D evidence: p=0.0054, δ=1.00 [1.00,1.00], Mann–Whitney 8 vs 10 | Lampiran B Table B.2/B.3; deck | `LA.efficacy[D/evidence]` | same | same | Frozen + Test-locked |
| D recovery: p=0.0176, δ=1.00 [1.00,1.00], Δ=5.05 s | Lampiran B Table B.2/B.3; Bab V §Temuan Utama; deck | `LA.efficacy[D/recovery]` | same | same | Frozen + Test-locked |
| E detection: p=0.0176, δ=1.00 [1.00,1.00], Δ=4.29 s | Lampiran B Table B.2/B.3; deck | `LA.efficacy[E/detection]` | same | same | Frozen + Test-locked |
| E evidence: p=0.0176, δ=1.00 [1.00,1.00], Δ=4.04 s | Lampiran B Table B.2/B.3; deck | `LA.efficacy[E/evidence]` | same | same | Frozen + Test-locked |
| E recovery: p=0.0176, δ=0.86 [0.64,1.00], Δ=3.03 s | Lampiran B Table B.2/B.3; Bab V §Temuan Utama; abstract; deck | `LA.efficacy[E/recovery]` | same | same | Frozen + Test-locked |
| C and D fallback to Mann–Whitney because complete pairs are insufficient | Lampiran B §Tabel Uji Lengkap; deck | `LA.efficacy[].pairing.{method,reason}` | `_pairing()` | `test_censored_pair_falls_back_to_exploratory_mann_whitney` | Frozen + Test-locked |
| Recovery effect is smaller than detection/evidence for B and C, not uniformly | Lampiran B Table B.3; Bab V §Temuan Utama; abstract; deck | `LA.efficacy[B/recovery].effect.cliffs_delta=0.48`, `C/recovery=0.75`; `D=1.00`, `E=0.86` | `_comparison()`, `cliffs_delta()` | `test_complete_pairs_use_wilcoxon_signed_rank` | Frozen + Test-locked |

## 5. Sensitivity — excluded GitOps C, repetition 2

There is no committed sensitivity output file. The values are reproducible with
`python3 experiments/sensitivity/c_r02_sensitivity.py --out /tmp/c-r02-sensitivity.json`
(defaults: bootstrap 2000, seed 20261029). The script's plumbing is tested; the
observed values are not embedded in a test.

| Claim | Manuscript location | Output source | Code | Test | Status |
|---|---|---|---|---|---|
| C-r02 is complete and observed: detection 0.98 s, evidence 1.16 s, recovery 5.77 s, R1 100/75/100 | Lampiran B §Analisis Sensitivitas; Bab V §Temuan Utama | Sensitivity JSON `c_r02.*`; also ROWS | `c_r02_sensitivity.main()` | `test_main_prints_or_writes_the_sensitivity_report` (plumbing) | **Gap: no committed output**; reproducible |
| C sensitivity uses 10 imperative vs 9 GitOps; Mann–Whitney | Lampiran B Table B.4 (`tab:sensitivitas-c`) | Sensitivity JSON `sensitivity_c.*.n_manual/n_gitops` | `c_r02_sensitivity.main()`; `_comparison()` | same | **Gap: no committed output**; reproducible |
| C detection/evidence p=0.0003, Holm=0.0034, δ=1.00 [1.00,1.00] | Lampiran B Table B.4 | Sensitivity JSON `sensitivity_c.detection/evidence`, `holm_family` | same | same | **Gap** |
| C recovery p=0.0200, Holm=0.0391, δ=0.64 [0.11,1.00] | Lampiran B Table B.4; Bab V §Temuan Utama; abstract | Sensitivity JSON `sensitivity_c.recovery`, `holm_family` | same | same | **Gap** |
| B recovery Holm rises from 0.0195 to 0.0391 in the sensitivity family | Lampiran B Table B.4 footnote; Bab V §Temuan Utama | Sensitivity JSON `holm_family[B/recovery]` | same | same | **Gap** |
| All 12 sensitivity comparisons remain below α = 0.05 | Lampiran B §Analisis Sensitivitas; Bab V §Temuan Utama | Sensitivity JSON `holm_family[].holm_adjusted_p < 0.05` | same | same | **Gap** |

## 6. Boundary and interpretive claims

| Claim | Manuscript location | Frozen output / key | Code | Test | Raw evidence | Status |
|---|---|---|---|---|---|---|
| R3 is not measured; no attribution claim | Bab IV §Kasus G; Bab V §Keterbatasan; deck | `LA.r3.status="not_measured"`, `.statement="R3: not measured"` | `analyze()` | `test_control_boundary_and_g_are_outside_efficacy` | ANA `r3_status` | Frozen + Test-locked |
| One stack, sequential arms, fixed order `gitops, imperative`; effects not isolated | Bab IV §Dapatkah Hasil Ini Dipercaya; Bab V §Keterbatasan; deck | `LA.batch.stack_isolated=false`; `MAN.arm_order`, `MAN.scenario_order` | `run_matrix.run_batch()` sequential loop | `test_seed_reproduces_order_and_both_arms_share_scenarios`, `test_plan_keeps_one_stack_and_records_dry_run_metadata` | MAN | Frozen + Test-locked |
| A is an HPA control, not ArgoCD efficacy evidence | Bab IV §Data yang Dianalisis; Bab V §Temuan Utama; deck | `LA.batch.efficacy_ineligible` contains A; `LA.overview[A/*].population="hpa_control"` | `analyze()`, `POPULATIONS` | `test_control_boundary_and_g_are_outside_efficacy` | ANA | Frozen + Test-locked |
| G is descriptive, non-Argo, not pooled into efficacy | Bab IV §Data yang Dianalisis, §Kasus G; Bab V §Temuan Utama, §Keterbatasan; deck | `LA.batch.efficacy_ineligible` contains G; `LA.batch.population_by_scenario.G="descriptive_non_argo"` | `analyze()` | `test_control_boundary_and_g_are_outside_efficacy` | ANA | Frozen + Test-locked |
| 15 repetitions per cell are not a per-scenario power guarantee | Bab IV §Dapatkah Hasil Ini Dipercaya; Bab V §Keterbatasan | Design claim, not an output field | `run_matrix.build_plan()` | `test_reps_one_to_ten_are_r2_and_eleven_to_fifteen_are_r1` | MAN | **No numeric output**; design limitation |
| Imperative checker nominal interval is 5 s; sampler nominal interval is 1 s | Bab IV §Waktu Deteksi/§Waktu Pemulihan; Bab V §Temuan Utama, §Keterbatasan; deck | Design parameters, not result fields | `harness.parse_args(--imperative-interval=5.0, --sample-interval=1)` | `test_argument_parsers...` | MAN, row metadata | Design parameter |
| 300 s observation horizon | Bab IV §Data yang Dianalisis–§Waktu Deteksi; Bab V §Keterbatasan; deck | ANA `censor_seconds=300.0` | `harness.parse_args(--timeout=300.0)` | `test_new_right_censored_row_requires_deadline_completion` | ANA | Frozen + Test-locked |

## 7. External literature and build metadata

These are not experiment outputs and must not be traced to the frozen analysis.

| Claim | Location | Source | Status |
|---|---|---|---|
| 719 configuration defects in 2,260 Kubernetes scripts; 533 (74.1%) caused crash/wrong operation/outage | Deck slide 2 | Zhang et al. (2026), external literature; see `content/skripsi/references.bib` | **External** |
| Security misconfiguration categories in open-source manifests | Deck slide 2 | Rahman et al. (2023), external literature | **External** |
| Thesis is 73 pages; 0 overfull, 17 underfull | Repository status | `content/skripsi/main.log` build output | **External build metadata** |
| Deck is 23 slides | Repository status | `presentation/skripsi/main.pdf` metadata | **External build metadata** |

## 8. Summary of gaps

1. **Sensitivity values** (C-r02) have no committed output file. They are
   reproducible from the tracked script and frozen rows, but the exact values in
   Bab IV are not pinned by a checksum. This is the main traceability gap.
2. **Four signed `t_e < t_d` rows** have no aggregate field; the query is in §3.
3. **G's observed last R1 value** is frozen but not embedded in an observed-value
   test; the scoring algorithm is tested.
4. **Tests are synthetic.** They prove algorithm behavior, not the observed batch
   numbers. The observed numbers are pinned by `live_analysis.json` and the
   SHA-256 manifest.

No other numerical claim in Bab IV, Bab V, the abstracts, or the deck lacks a
direct frozen output or a documented derivation.
