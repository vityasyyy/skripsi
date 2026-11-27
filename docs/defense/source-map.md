# Thesis source map — section, code, freeze, command

This map connects each thesis-facing claim block to the code that produces it,
the frozen revision that owns the numbers, and the command that reproduces the
view. It does not replace `experiments/REVISIONS.md` or
[`claim-traceability.md`](claim-traceability.md).

The frozen analyzer and collection modules use `R1` and `R2` as internal
data-phase labels. The manuscript does not: it calls the check
"pemeriksaan kecocokan konfigurasi" and the two blocks "blok waktu" and
"blok kecocokan".

## Frozen identities

| Role | Tag | Commit | What it fixes |
|---|---|---|---|
| Collection apparatus | `thesis-collection-20261029` | `3572f3c1c11d3abc8b63882c4348b1b803d4256f` | Harness, sampler, scenarios, contract, collection runner |
| Primary analysis | `thesis-analysis-20261030` | `a1d43eaf0d349249f1eb0a8e880badebe4eb851d` | `analyze_live.py` and its frozen outputs |
| Sensitivity analysis | `thesis-sensitivity-20261030` | `6cfc99ec63a71825e88b53a96704c8c792891bd9` | `experiments/sensitivity/` |

The 80-cell follow-up session `matched1s-20261127b` (2026-11-27) is separate
from the three frozen tags above. Its identity is source
`2aff56d8021c3394929ac5a59f949db567bb2298`, render
`ffff8d73b5a7ba09324582928a1a5e6597c30f1430d185bc38dc852aac541efa`, and
analysis `experiments/analysis-matched1s-20261127b/` (local, gitignored). It is
not pooled with `formal-20261029`.

`HEAD` is post-collection. The primary numbers come from the frozen
`experiments/analysis-formal-20261029/live_analysis.json`; they are not produced
by rerunning the apparatus. The frozen rows and `live_analysis.json` are local
and gitignored, so a checkout without them can verify code and tests but cannot
recompute the observed values.

## Section map

| Thesis section | Claim block | Code path | Frozen owner | Reproduction |
|---|---|---|---|---|
| Bab III §Desain, §Beban Uji, §Protokol | Apparatus, 210 cells, baseline gate, reset, 60 s cooldown | `experiments/live/harness.py`, `experiments/live/run_matrix.py`, `experiments/live/declaration.py` | Collection `3572f3c` | `python3 -m unittest discover -s experiments/tests` |
| Bab III §Pemeriksaan Kecocokan Konfigurasi | Four selected resources; HPA-owned replicas excluded; score 100/75 | `experiments/live/declaration.py`, `experiments/live/harness.py` (`build_contract`, `score`) | Collection `3572f3c` | Inspector tests in `experiments/tests/test_live_harness.py` |
| Bab III §Waktu Deteksi, Bukti, Pemulihan | `t_0`, `t_d`, `t_e`, `t_r`; observation horizon; evidence asymmetry | `experiments/live/harness.py`, `experiments/live/timeline.py`, `experiments/live/sampling.py` | Collection `3572f3c` | Timeline and sampler tests |
| Bab IV §Data yang Dianalisis | 210 cells, 211 raw rows, 207 analysis rows, 4 exclusions; audit medians | `experiments/analysis/analyze_live.py` (`_exclusions`, `_r1_entries`) | Analysis `a1d43ea` | Frozen `live_analysis.json`; audit table in Lampiran A |
| Bab IV §Waktu Deteksi, §Waktu Pemulihan | Median detection and recovery times; interval explanation | `experiments/analysis/analyze_live.py`, `core.py`, `stats.py`, `survival.py`, `latex.py` | Analysis `a1d43ea` | Frozen `live_analysis.json` plus `rq2_report.py` |
| Bab IV §Kasus G | G description; GitOps recovery stops at 300 s; score 75 | `analyze_live.py` (`_r1_entries`, `_survival_entries`); runner G branch | Analysis `a1d43ea`; collection `3572f3c` | `live_analysis.json` (`r1`, `survival`) |
| Bab IV §Uji Tindak Lanjut dengan Selang Setara | 80-cell matched-interval follow-up: 79 analyzed, 1 instrumentation failure; detection/recovery medians | `experiments/analysis/analyze_live.py`, `experiments/live/run_matrix.py` | Follow-up session `matched1s-20261127b`; source `2aff56d8`; render `ffff8d73` | `experiments/analysis-matched1s-20261127b/live_analysis.json`, `live_tests.tex`, `live_effects.tex` |
| Bab V §Temuan Utama, §Rekomendasi | Interval-bound detection; mixed recovery; contextual recommendation | Analysis outputs and design records | Analysis `a1d43ea`; collection `3572f3c` | `live_analysis.json` |
| Bab V §Tindak Lanjut Selang Setara | Follow-up result: detection gap 4.2–4.3 s → 0.25–0.32 s; recovery mixed (B/E equal, C imperative, D GitOps) | `experiments/analysis/analyze_live.py` | Follow-up session `matched1s-20261127b` | `live_analysis.json`, `live_tests.tex` |
| Bab V §Biaya dan Overhead, §Aspek yang Tidak Diukur | What was not measured; metrics to collect | No code; design boundary | — | Thesis text only |
| Lampiran A §Audit Pemeriksaan Kecocokan Konfigurasi | Median audit table; no comparative test | `analyze_live._r1_entries` | Analysis `a1d43ea` | Frozen `live_analysis.json` |
| Lampiran A §Baris yang Dikecualikan | Four raw rows with IDs and reasons | `analyze_live._exclusions`, `_classify_raw` | Analysis `a1d43ea` | `live_analysis.json.exclusions` |
| Lampiran B §Tabel Uji Lengkap, §Tabel Ukuran Efek | 12 B–E tests; Holm p-values; Cliff's delta; bootstrap intervals | `analyze_live.py`, `core.py`, `stats.py` | Analysis `a1d43ea` | `live_tests.tex`, `live_effects.tex` |
| Lampiran B §Analisis Sensitivitas | C, repetition 2 re-inclusion; C recovery delta 0.75 to 0.64 | `experiments/sensitivity/c_r02_sensitivity.py` | Sensitivity `6cfc99e` | `python3 experiments/sensitivity/c_r02_sensitivity.py --out /tmp/c-r02.json` |
| Lampiran B §Pengamatan Berhenti Sebelum Peristiwa | Censoring counts; Kaplan–Meier; RMST | `analyze_live.py`, `survival.py` | Analysis `a1d43ea` | Frozen `live_survival.tex` |
| Lampiran B §Uji Tindak Lanjut Selang Setara | 12-row test table (11 testable); effect sizes; failed first attempt note | `experiments/analysis/analyze_live.py` | Follow-up session `matched1s-20261127b` | `live_tests.tex`, `live_effects.tex` |

## Thesis-facing timing view

`experiments/analysis/rq2_report.py` is a thin view over the frozen analyzer.
It does not change `analyze_live.py`, `core.py`, `stats.py`, `survival.py`,
`latex.py`, or any collection module. It selects `batch`, `exclusions`,
`overview`, `survival`, `efficacy`, and `families`; derives the descriptive
repair interval `t_r - t_d`; and reports the configuration-match predicate as
counts.

```bash
python3 experiments/analysis/rq2_report.py \
  --in experiments/formal-20261029/formal-20261029.analysis.jsonl \
  --rows experiments/formal-20261029/formal-20261029.rows.jsonl \
  --frozen experiments/analysis-formal-20261029/live_analysis.json \
  --out experiments/analysis-rq2-formal-20261029 \
  --bootstrap 2000 --seed 20261029 --alpha 0.05 \
  --check-frozen
```

Outputs: `rq2_analysis.json`, `rq2_overview.tex`, `rq2_survival.tex`,
`rq2_tests.tex`, `rq2_effects.tex`, `rq2_repair.tex`,
`recovery_completeness.tex`. There is deliberately no comparative table for the
configuration-match check.

`--check-frozen` compares the six selected analyzer fields with the frozen
`live_analysis.json` and exits non-zero on mismatch. When the frozen file is
absent, it prints `PENDING`, records `frozen_check: pending`, and exits 2; it
does not claim a match. Exit 0 means `match` or a disabled check, 1 means a
mismatch or invalid input, and 2 means the frozen comparison was skipped.

### Historical schema alias

The frozen schema stores the imperative mode as `env=manual`. That alias is part
of the frozen data and is never renamed in place. The view maps it for display:

- analysis field: `env=manual`
- display field: `arm=imperative`
- preserved audit field: `legacy_env=manual`

The analyzer's `overview` and `survival` entries use the same historical alias;
`rq2_report.py` is the only layer that renames it. Do not "fix" the alias in the
frozen analyzer or in the collection rows.

## Frozen inspector commands

```bash
git rev-parse 'thesis-collection-20261029^{commit}'
git rev-parse 'thesis-analysis-20261030^{commit}'
git rev-parse 'thesis-sensitivity-20261030^{commit}'
git status --short
```

Rebuild the thesis-facing artifacts:

```bash
make skripsi-diagrams
make skripsi
make check-experiments
make thesis-style
```
