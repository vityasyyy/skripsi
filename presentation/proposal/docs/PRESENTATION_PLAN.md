# PLAN — Presentation Restructuring

## Goal

Restructure the proposal presentation to:

1. **Move the research gap to the climax of Act 1** (slide 6 instead of slide 10)
2. **Move InvenioRDM after methodology** (it's a workload, not the research problem)
3. **Elaborate the background** so it clearly leads to the research problem (supervisor)
4. **Include explicit problem statement, scope/limitations, objectives, benefits** (supervisor)
5. **Gradual lit review with differentiation** (supervisor)
6. **Prepare backup slides for all examiner defense questions** (review)

---

# Presentation Structure (17 Slides + 14 Backup)

## Act 1: Problem & Gap (Slides 1–7)

Narrative arc: Problem → Pain → Existing response → Gap → Question

---

### Slide 1 — Title (30 sec)

Standard title slide with metadata.

---

### Slide 2 — Mengapa Masalah Ini Penting? (1 min)

**[ELABORATED — addresses supervisor: "background should lead to problem"]**

Left column: Narrative scenario
- Aplikasi berjalan di Kubernetes dengan banyak komponen.
- Operator melakukan perubahan cepat langsung di klaster.
- Dokumentasi konfigurasi tidak ikut berubah.
- Saat insiden terjadi, tim tidak tahu kondisi mana yang benar.
- Konsekuensi: inkonsistensi, pemulihan lambat, akar masalah tidak jelas, audit sulit.

Right column: motivation-drift diagram

Callout: **Inti masalah: bukan sekadar aplikasi rusak, tetapi hilangnya kepastian tentang state sistem.**

**Speaker notes:**
> Imagine an operator makes a quick change directly in production. The application keeps running, so nobody notices. Days later another engineer investigates an issue and discovers that the running system no longer matches documented configuration. [Pause.] That situation is configuration drift. The fundamental problem is not an outage — it is loss of confidence in system state.

---

### Slide 3 — Configuration Drift: Definisi dan Bukti (1 min)

**[NEW — formal definition + evidence, builds from slide 2]**

Left column:
- Formal definition: state aktual klaster menyimpang dari state yang dideklarasikan (Pohjola, 2025).
- Tiga penyebab utama: (1) perubahan langsung tanpa source of truth, (2) prosedur tidak konsisten, (3) tidak ada mekanisme deteksi otomatis.
- 71% dari 2.260 K8s scripts mengandung misconfiguration bermakna (Zhang et al., 2026).
- 11 kategori security misconfiguration berulang (Rahman et al., 2023).

Right column: motivation-drift diagram (reused)

**Speaker notes:**
> Configuration drift is when the actual state deviates from the declared state. Zhang et al. found 71% of K8s scripts contain significant misconfiguration. This is an operational reality, not a theoretical problem.

---

### Slide 4 — GitOps sebagai Respons (45 sec)

**[SIMPLIFIED — one-sentence principle, no ArgoCD internals]**

Left column (brief):
- Git sebagai single source of truth.
- Agen software melakukan reconciliation secara kontinu.
- Jika drift terjadi, sistem mendeteksi dan mengoreksi otomatis.

Right column: gitops-flow diagram

Small note: Pertanyaan ilmiahnya bukan "apakah GitOps populer?", melainkan seberapa berbeda respons operasionalnya saat drift terjadi.

**Speaker notes:**
> GitOps addresses this through continuous reconciliation. The scientific question is not whether GitOps is popular, but how much operational difference the paradigm actually makes.

---

### Slide 5 — Klaim Industri vs. Bukti Ilmiah (1 min)

**[MOVED to before gap — sets up the gap]**

Industry-claim diagram (5 sources → weak evidence type)

Gap callout (big red box):
> Klaim diterima luas. Bukti terkontrol masih lemah. Dampak kausal paradigma deployment belum jelas.

**Speaker notes:**
> At first glance the problem seems solved. Many studies report benefits. [Pause.] However, when reviewing the literature, I found recurring limitations: qualitative metrics, no control groups, limited statistical comparison. Therefore, we still lack controlled empirical evidence quantifying the operational impact. This is the sentence I want you to remember.

---

### Slide 6 — Kesenjangan Penelitian (1 min) ★ CLIMAX OF ACT 1

**[MOVED from slide 10 → slide 6. THE turning point.]**

research-gap diagram (4 gap boxes + "this research" callout)

Explicit differentiation callout (beamercolorbox):
> Penelitian ini mengisi keempat kesenjangan: (1) metrik teroperasionalisasi, (2) variabel terkontrol, (3) uji statistik formal, (4) konteks klaster akademis.

**Speaker notes:**
> [Pause after showing gap.] Therefore, controlled empirical evidence is needed. This research provides that experiment. [Pause.] Let me now state the research question.

---

### Slide 7 — Rumusan Masalah (1 min)

**[NEW — addresses supervisor: "research problem statement explicitly included"]**

Main question in highlighted beamercolorbox.

Three sub-questions: R1 (Konsistensi), R2 (Waktu), R3 (Traceability).

---

## Act 2: Research Design (Slides 8–14)

---

### Slide 8 — Batasan Masalah (45 sec)

**[NEW — addresses supervisor: "include scope/limitations"]**

6 items from proposal §1.3.

---

### Slide 9 — Tujuan dan Manfaat Penelitian (45 sec)

**[NEW — addresses supervisor: "include objectives and benefits"]**

Left: 3 objectives. Right: 3 benefit columns.

Callout: Kontribusi utama: bukan membuktikan GitOps selalu unggul, tetapi mengukur dampak operasional pilihan paradigma deployment.

---

### Slide 10 — Penelitian Terkait (1 min)

**[NEW — addresses supervisor: "gradually discuss lit review" + "what distinguishes your work"]**

Table: 4 studies × (Temuan | Kelemahan)

Differentiation callout: This research differs: (1) controlled experimental design, (2) controlled confounding variables, (3) formal statistical analysis, (4) quantitatively operationalized metrics.

---

### Slide 11 — Desain Eksperimen (2 min) ★ CRITICAL SLIDE

**[ENHANCED — InvenioRDM justification moved here]**

experiment-comparison + architecture-overview diagrams.

Two callout boxes:
- Control variables: satu variabel independen. Kontrol: workload sama, drift sama, klaster sama, prosedur pengukuran sama.
- Workload justification: InvenioRDM dipilih karena kompleksitas dependensi, komponen infrastruktur luas, open-source. InvenioRDM bukan objek penelitian.

**Speaker notes:**
> Everything is intentionally held constant. Same workload. Same drift. Same cluster. Same measurement. The only intended difference is deployment paradigm. That is the sentence that protects your internal validity.

---

### Slide 12 — Skenario Configuration Drift Terkontrol (1 min)

drift-scenarios diagram.

---

### Slide 13 — Metrik Pengukuran dan Operasionalisasi (2 min)

operationalization-validity diagram.

**NEW note added:**
> Root Cause Identification Time ($t_{rci} - t_d$) dianggap teridentifikasi ketika operator dapat menyebutkan kategori drift dan sumber daya yang terpengaruh, diverifikasi terhadap skenario injeksi yang diketahui.

---

### Slide 14 — Ancaman terhadap Validitas dan Mitigasi (1.5 min)

Threat-mitigation table.

Callout: Klaim penelitian dibatasi: hasil berlaku sebagai evaluasi empiris terkontrol pada konteks yang didefinisikan.

---

## Act 3: Implications (Slides 15–17)

---

### Slide 15 — Analisis Statistik (1 min)

Left column: Statistical analysis details.
Right column: **[NEW — justifications]**
- Mengapa Mann–Whitney? Waktu deteksi/pemulihan mungkin tidak berdistribusi normal dan n relatif kecil.
- Mengapa n = 10? Studi sistem berulang. 7×10 = 70 observasi per lingkungan.

---

### Slide 16 — Hasil yang Mungkin dan Maknanya (1 min)

Three outcome columns.

Callout: Apa pun hasilnya, kontribusi penelitian adalah bukti yang dapat diperiksa, bukan opini adopsi teknologi.

---

### Slide 17 — Kesimpulan (30 sec)

Quote slide.

---

# Backup Slides (14 slides)

### B1 — Kunci Konsep
Definitions of deployment, Kubernetes, GitOps, configuration drift with citations.

### B2 — Detail ArgoCD dan Reconciliation
ArgoCD components, reconciliation loop.

### B3 — Detail Skenario Drift
Table of 7 scenarios with IDs, names, example commands.

### B4 — Bagan Alir Eksperimen
experiment-flow-presentation diagram.

### B5 — Analisis Statistik Detail
Mann-Whitney justification, effect sizes, power analysis, R3 deskriptif.

### B6 — Ancaman Validitas Detail
Full validity threat table (internal, construct, external, reliability).

### B7 — Defense: Root Cause Identification Time
Operational definition: RCID complete when operator identifies drift category + affected resource, verified against known injected scenario. Known-answer verification analogy.

### B8 — Defense: Traceability (R3)
Purpose is not hypothesis testing — it's documenting operational characteristics that accompany R1/R2 quantitative results.

### B9 — Defense: Why InvenioRDM?
Three criteria: dependency complexity, infrastructure breadth, academic reproducibility. Not about InvenioRDM specifically.

### B10 — Defense: Single Operator
Runbook + automated timestamps + metrics independent of operator. Single operator reduces inter-run variance for internal validity.

### B11 — Defense: What If No Significant Difference?
Non-significant result with small effect = comparable paradigms (still a finding). With medium/large effect = need more data. R3 provides structural value regardless.

### B12 — Defense: Isn't GitOps Obviously Better?
Claims require controlled evidence. This research isolates the paradigm variable for the first controlled measurement of effect size.

### B13 — Defense: Are You Measuring Human Attention?
Detection capability is part of the paradigm, intentionally included. In manual, operator IS the detector. In GitOps, ArgoCD IS the detector.

### B14 — Defense: Why Seven Scenarios and Equal Weighting?
Derived from Zhang et al. taxonomy + Pohjola operational patterns. Equal weighting is an initial assumption. Per-scenario analysis captures difficulty differences.

---

# Implementation Tasks

1. Rewrite `contents/slides.tex` with new 17-slide structure
2. Update/create necessary TikZ diagrams
3. Add 14 backup slides with defense content
4. Compile and verify PDF builds correctly
5. Update PLAN.md in proposal directory

---

# Key Examiner Defenses (Quick Reference)

| # | Question | Key Answer |
|---|----------|-----------|
| 1 | Why InvenioRDM? | 3 criteria: dependency complexity, infrastructure breadth, academic reproducibility |
| 2 | Isn't GitOps obviously better? | Claims require controlled evidence. How much better, under what conditions? |
| 3 | How do you know difference comes from GitOps, not operator? | Same operator, cluster, drift, measurement. Only difference is paradigm. |
| 4 | Operator is also the researcher? | Single operator reduces inter-run variance. Runbook + automated timestamps. |
| 5 | 16 components representative? | Represents class of multi-service workloads where drift is most impactful. |
| 6 | Why 7 scenarios sufficient? | Derived from Zhang et al. taxonomy + Pohjola patterns. |
| 7 | Why equal weighting? | Initial assumption. Per-scenario analysis captures difficulty differences. |
| 8 | Why trust Root Cause ID metric? | Known-answer verification: identify category + affected resource. |
| 9 | Why Mann-Whitney not t-test? | Data may not be normal; n is small; non-parametric is more appropriate. |
| 10 | What if no significant difference? | Still a finding. Effect size provides practical info. R3 provides structural value. |