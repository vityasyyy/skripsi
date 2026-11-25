# Thesis style rules

Scope: `content/skripsi/main.tex`, `content/skripsi/chapters/`,
`content/skripsi/lampiran/`, and `presentation/skripsi/contents/slides.tex`.
The proposal is historical and is not edited.

## Terminology

| Use | Avoid | Note |
|---|---|---|
| prosedur imperatif otomatis (first use), then mode imperatif / prosedur imperatif | manual, baseline manual, mode manual | No human timing is measured. "manual" survives only in the proposal change log and the proposal-history Q&A. |
| satu RQ with three timing components | RQ1 / RQ2 | The thesis has one timing research question. |
| R1 = recovery predicate and manipulation-validity check | R1 as a comparative outcome or a tested hypothesis | R1 = 100 means all four selected resources match the declaration. |
| blok waktu | R2 as a metric or a result | R2 names the repetitions 1–10 block only; prefer "blok waktu" in prose. |
| detik (Indonesian prose and tables), s (English abstract) | mixed units | Do not write "det" or "sec". |

## Claims

- Do not write "menolak hipotesis nol" in the abstract or the conclusion. Use
  "p terkoreksi < 0,05 di bawah model uji eksploratif; bukan estimasi populasi."
- Do not write "GitOps lebih cepat" without "pada sinyal yang teramati di bawah
  cadence masing-masing."
- Do not write "kedua mode mencapai kondisi akhir yang setara pada skenario
  yang diuji." Write "B–F; G adalah pengecualian."
- Recovery B is δ = 0.48 with a 95% CI that includes zero; do not present it as
  a clear advantage.
- State the block order: all GitOps runs preceded all imperative runs. State
  that repetitions are pseudoreplicates and p-values are descriptive summaries.
- State the evidence asymmetry: imperative `t_e = t_d` by construction; GitOps
  `t_e` comes from the independent collector.
- State the cadence: 5 s checker versus 1 s sampler; the 4.0–4.3 s gap is
  consistent with the cadence, not a pure controller-response estimate.
- G is descriptive and unattributed. Do not generalize it to ArgoCD failure.

## Typography

- Indonesian decimal comma (`0,48`), English decimal point (`0.48`).
- One space after punctuation; no space before punctuation; no double spaces in
  prose.
- Use `mis.`, `yaitu`, `dsb.` in Indonesian prose, not `e.g.`, `i.e.`, `etc.`
- Keep quotes consistent; do not mix curly and straight quotes in one paragraph.
- Cut "tersebut" in favour of a concrete noun. The audit reports the count.

## Report-only audit

```bash
make thesis-style
```

`scripts/check_thesis_style.py` is stdlib-only and always exits 0. It reports
counts and `file:line` for banned phrases, term drift, RQ/R1 collisions, Latin
abbreviations, and prose double spaces. It also reports the number of
"tersebut" occurrences.

Lines that must mention proposal history can carry the marker
`% style-allow: proposal-history`; the audit skips those lines. The marker is
limited to the proposal change log and the historical explanation in
[`defense/qa.md`](defense/qa.md).
