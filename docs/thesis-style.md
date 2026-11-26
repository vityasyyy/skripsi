# Thesis style rules

Scope: `content/skripsi/main.tex`, `content/skripsi/chapters/`,
`content/skripsi/lampiran/`, and diagram captions in
`content/skripsi/diagrams/*.tex`. The presentation deck is a separate artifact
and is not audited by this ruleset.

## Terminology

| Use | Avoid | Note |
|---|---|---|
| prosedur imperatif otomatis (first use), then mode imperatif / prosedur imperatif | manual, baseline manual, mode manual | No human timing is measured. "manual" survives only in the proposal change log. |
| satu pertanyaan penelitian with two timing metrics: detection and recovery | RQ1 / RQ2 / tiga metrik utama | Detection is `t_d - t_0`; recovery is `t_r - t_0`. Evidence is a diagnostic. |
| pemeriksaan kecocokan konfigurasi | R1 / validitas manipulasi | The check verifies that the four selected resources match the declaration; it is not a comparative outcome. |
| selang pengamatan / interval pemeriksaan | cadence | The 5 s checker and 1 s recorder are the design fact. |
| mode | arm | One treatment in the comparison. |
| percobaan | run | One execution of the protocol for one cell. |
| sesi pengumpulan | batch | One collection protocol run. |
| angka acak untuk urutan | seed, in prose | The exact value stays in Lampiran A. |
| pengamatan berhenti sebelum peristiwa terjadi | penyensoran | A censored observation is not a failure and is never zero. |
| pemeriksaan pengaman | guardrail | Health is checked before injection and after recovery. |
| pemeriksaan setelah pemulihan | postcondition | Health is not scored or compared. |
| ditetapkan sebelum pengujian dan tidak diubah | pembekuan, dibekukan | The apparatus identity is fixed, not frozen. |
| protokol yang sama dipakai di semua pengujian | pembakuan protokol | No need for the nominalisation. |
| detik in Indonesian prose and tables, s in the English abstract | mixed units | Do not write "det" or "sec". |

## Claims

- The detection result is about the observation interval. Do not write
  "GitOps lebih cepat" without the qualifier "pada sinyal yang teramati di
  bawah selang pengamatan masing-masing." The 4.2–4.3 s gap is close to the
  1 s versus 5 s interval difference.
- Recovery is mixed: B and C are smaller and B is not a clear advantage; D is
  the largest; E is moderate but more consistent than B. A single summary
  number is not enough.
- G is descriptive and unattributed. Do not generalise it to ArgoCD failure or
  to a permissions problem.
- The conclusion is contextual. Do not claim population estimates, universal
  superiority, or equivalence.
- Cost and qualitative aspects were not measured. Present them as things to
  measure, never as findings.

## Statistics split

- Bab IV: plain narrative and simple median tables. No p-values, confidence
  intervals, Greek letters, test names, Holm, Cliff's delta, Kaplan–Meier,
  RMST, pseudoreplicates, or censoring terminology.
- Bab III: one compact paragraph naming the tests and pointing to Lampiran B.
- Lampiran B: definitions, full 12-row test table, effect-size table,
  sensitivity table, censoring/survival, and "Cara Membaca Hasil".
- Lampiran A: apparatus identity, commands, schema, raw IDs, seed, audit table,
  and exclusion table.

## Typography

- Indonesian decimal comma (`0,48`), English decimal point (`0.48`).
- One space after punctuation; no space before punctuation; no double spaces in
  prose.
- Use `mis.`, `yaitu`, `dsb.` in Indonesian prose, not `e.g.`, `i.e.`, `etc.`.
- Keep quotes consistent; do not mix curly and straight quotes in one paragraph.
- Prefer a concrete noun over "tersebut". The audit reports the count.

## Report-only audit

```bash
make thesis-style
```

`scripts/check_thesis_style.py` is stdlib-only and always exits 0. It reports
counts and `file:line` for banned phrases, term drift, label collisions, Latin
abbreviations, prose double spaces, and "tersebut" occurrences.

Lines that must mention proposal history can carry the marker
`% style-allow: proposal-history`; the audit skips those lines. The marker is
limited to the proposal change log.
