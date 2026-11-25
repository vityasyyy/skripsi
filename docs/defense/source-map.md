# Thesis source map — section, code, freeze, command

This map connects each thesis-facing claim block to the code that produces it,
the frozen revision that owns the numbers, and the command that reproduces the
view. It does not replace `experiments/REVISIONS.md` or
[`claim-traceability.md`](claim-traceability.md).

## Frozen identities

| Role | Tag | Commit | What it fixes |
|---|---|---|---|
| Collection apparatus | `thesis-collection-20261029` | `3572f3c1c11d3abc8b63882c4348b1b803d4256f` | Harness, sampler, scenarios, contract, collection runner |
| Primary analysis | `thesis-analysis-20261030` | `a1d43eaf0d349249f1eb0a8e880badebe4eb851d` | `analyze_live.py` and its frozen outputs |
| Sensitivity analysis | `thesis-sensitivity-20261030` | `6cfc99ec63a71825e88b53a96704c8c792891bd9` | `experiments/sensitivity/` |

`HEAD` is post-collection. The primary numbers come from the frozen
`experiments/analysis-formal-20261029/live_analysis.json`; they are not produced
by rerunning the apparatus. The frozen rows and `live_analysis.json` are local
and gitignored, so a checkout without them can verify code and tests but cannot
recompute the observed values.

## Section map

| Thesis section | Claim block | Code path | Frozen owner | Reproduction |
|---|---|---|---|---|
| Bab III §Desain, §Beban Uji, §Protokol | Apparatus, 210 cells, baseline gate, reset, 60 s cooldown | `experiments/live/harness.py`, `experiments/live/run_matrix.py`, `experiments/live/declaration.py` | Collection `3572f3c` | `python3 -m unittest discover -s experiments/tests` |
| Bab III §Pemeriksaan Validitas Manipulasi | R1 contract, four selected resources, HPA-owned replicas excluded | `experiments/live/declaration.py`, `experiments/live/harness.py` (`build_contract`, `score`) | Collection `3572f3c` | Inspector tests in `experiments/tests/test_live_harness.py` |
| Bab III §Waktu Deteksi, Bukti, Pemulihan | `t_0`, `t_d`, `t_e`, `t_r`; censoring; evidence asymmetry | `experiments/live/harness.py`, `experiments/live/timeline.py`, `experiments/live/sampling.py` | Collection `3572f3c` | Timeline and sampler tests |
| Bab IV §Validitas Manipulasi | R1 medians; B–F convergence; G = 75 on GitOps | `experiments/analysis/analyze_live.py` (`_r1_entries`) | Analysis `a1d43ea` | `rq2_report.py` (below); audit table in Lampiran A |
| Bab IV §Waktu Deteksi, Bukti, Pemulihan | Censoring counts, 12 B–E tests, Holm p-values, Cliff's δ, paired gaps | `experiments/analysis/analyze_live.py`, `core.py`, `stats.py`, `survival.py`, `latex.py` | Analysis `a1d43ea` | Frozen `live_analysis.json` plus `rq2_report.py` |
| Bab IV §Analisis Sensitivitas | C-r02 re-inclusion; C recovery δ 0.75 → 0.64 | `experiments/sensitivity/c_r02_sensitivity.py` | Sensitivity `6cfc99e` | `python3 experiments/sensitivity/c_r02_sensitivity.py --out /tmp/c-r02.json` |
| Bab IV/V §Batas Klaim, §Kasus Batas G | Block order, pseudoreplicates, G unattributed | `experiments/analysis/analyze_live.py` notes; `experiments/live/run_matrix.py` order | Analysis `a1d43ea`; collection `3572f3c` | `live_analysis.json` (`batch`, `notes`, `r1`) |
| Lampiran A §Audit R1 | Median audit table; no comparative test | `analyze_live._r1_entries`; counts at 100/75/50/25 from `rq2_report.recovery_completeness` when frozen rows are present | Analysis `a1d43ea`; post-freeze view (PR1) | `rq2_report.py` (below) |
| Lampiran A §Catatan Perubahan dari Proposal | Title/F/G definition history | No code; pre-collection decisions | Collection freeze boundary | `git show 3572f3c:docs/...` and the appendix text |
| Deck slides 4, 8–9, 11–16 | One RQ, validity check, timing result, claim boundaries | `presentation/skripsi/contents/slides.tex`; diagrams in `presentation/skripsi/diagrams/` | Numbers from analysis `a1d43ea` | `make presentation-skripsi` |

## Thesis-facing timing view

`experiments/analysis/rq2_report.py` is a thin view over the frozen analyzer.
It does not change `analyze_live.py`, `core.py`, `stats.py`, `survival.py`,
`latex.py`, or any collection module. It selects `batch`, `exclusions`,
`overview`, `survival`, `efficacy`, and `families`; derives the descriptive
repair interval `t_r - t_d`; and reports the R1 recovery predicate as counts.

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
`recovery_completeness.tex`. There is deliberately no R1 comparative table.

`--check-frozen` compares the six selected analyzer fields with the frozen
`live_analysis.json` and exits non-zero on mismatch. When the frozen file is
absent, it prints `PENDING`, records `frozen_check: pending`, and exits 2; it
does not claim a match. Exit 0 means `match` or a disabled check, 1 means a
mismatch or invalid input, and 2 means the frozen comparison was skipped.

### Historical schema alias

The frozen schema stores the imperative arm as `env=manual`. That alias is part
of the frozen data and is never renamed in place. The view maps it for display:

- analysis field: `env=manual`
- display field: `arm=imperative`
- preserved audit field: `legacy_env=manual`

The analyzer's `overview` and `survival` entries use the same historical alias;
`rq2_report.py` is the only layer that renames it. Do not "fix" the alias in
the frozen analyzer or in the collection rows.

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
make presentation-skripsi-diagrams
make skripsi
make presentation-skripsi
make check-experiments
make thesis-style
```
