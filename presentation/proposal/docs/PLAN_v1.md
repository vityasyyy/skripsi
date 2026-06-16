# PLAN.md

## Goal

Primary Goal:

* Pass proposal seminar comfortably.

Secondary Goals:

* Demonstrate methodological rigor.
* Demonstrate that the research question is meaningful beyond GitOps.
* Show that the experiment can produce useful evidence regardless of outcome.

## Core Narrative

The presentation must tell a single story:

What is deployment? What is GitOps? What is configuration drift?

↓

Configuration drift is a real operational problem.

↓

GitOps claims to solve this problem.

↓

Existing evidence is insufficient because studies are mostly qualitative, observational, or lack controlled comparison.

↓

Therefore a controlled empirical experiment is required.

↓

This research provides that experiment.

Everything in the presentation should support this narrative.

If a slide does not support this narrative, remove it.

## Critical Reframing

The biggest risk is NOT that examiners think the research is weak.

The biggest risk is that examiners think the conclusion is obvious:
"Of course GitOps recovers drift faster — ArgoCD is built to reconcile state."

The single most important sentence in the entire presentation:

> "Penelitian ini tidak berupaya membuktikan bahwa GitOps lebih unggul, melainkan mengisolasi dan mengkuantifikasi dampak operasional dari pilihan paradigma deployment dalam kondisi configuration drift terkontrol."

This reframes the work from "student benchmarking ArgoCD" to "student conducting a controlled systems experiment."

---

# Presentation Structure (17 Slides)

## Slide 1 — Title (30 sec)

Contents:

* Research title
* Name: Muhammad Argya Vityasy
* NIM: 23/522547/PA/22475
* Dosen Pembimbing: Dr. techn. Guntur Budi Herwanto, S.Kom., M.Cs.
* Dosen Penguji 1: Dr. techn. Kabul Kurniawan, S.Kom., M.Cs.
* Dosen Penguji 2: Aina Musdholifah, S.Kom., M.Kom., Ph.D.

---

## Slide 2 — Kunci Konsep (45 sec)

[NEW — addresses friends' feedback and lecturer's "elaborate background"]

Left column: 4 definitions with citations
* Deployment: managing application lifecycle on infrastructure
* Kubernetes: container orchestration platform (Burns et al., 2016)
* GitOps: declarative deployment paradigm, Git as single source of truth, automatic reconciliation (CNCF GitOps WG, 2021)
* Configuration Drift: actual state deviates from desired state (Pohjola, 2025)

Right column: gitops-flow diagram (moved from backup B1 to main)

Key: Establish shared vocabulary BEFORE problem statement.

---

## Slide 3 — Latar Belakang: Kompleksitas Operasional dan Configuration Drift (1 min)

[ELABORATED from old Slide 2 — addresses lecturer: "background should lead to problem"]

Left column: narrative bullets
* InvenioRDM: 16+ interdependent components (InvenioRDM, 2024)
* Manual management (kubectl apply, patching) is prone to drift
* Drift causes: (1) direct changes without source of truth; (2) inconsistent procedures; (3) no automatic detection (Pohjola, 2025)
* 71% of 2,260 K8s scripts contain significant misconfiguration (Zhang et al., 2026)
* Consequences: inconsistency, difficult recovery, audit degradation, security risks (Rahman et al., 2023)

Right column: motivation-drift diagram

Key: Story arc from operational complexity → drift → consequences.

---

## Slide 4 — Rumusan Masalah (1 min)

[NEW — addresses lecturer: "research problem statement should be explicitly included"]

Main question (highlighted beamercolorbox):

> Sejauh mana paradigma manajemen deployment yang berbeda — pendekatan manual menggunakan kubectl dan pendekatan GitOps menggunakan ArgoCD — menghasilkan perbedaan pada karakteristik operasional ketika menghadapi configuration drift yang terkontrol?

Three sub-questions: R1 (Konsistensi), R2 (Waktu), R3 (Traceability)

Reframing sentence in highlighted box (moved from old Slide 5).

---

## Slide 5 — Batasan Masalah (45 sec)

[NEW — addresses lecturer: "include scope/limitations"]

6 items from proposal §1.3:
1. Single K8s cluster (3 nodes, 24 core, ~23 Gi)
2. InvenioRDM as test subject, not research object
3. 7 drift scenarios (A-G)
4. Two paradigms: manual (kubectl) and GitOps (ArgoCD)
5. Statistical analysis: Mann-Whitney U, α = 0.05, Cohen's d
6. Intermediate paradigms not in scope

---

## Slide 6 — Tujuan Penelitian (30 sec)

[NEW — addresses lecturer: "include objectives"]

3 objectives from proposal §1.4:
1. Measure and compare deployment consistency (R1)
2. Measure and compare detection time, recovery time, root cause identification time (R2)
3. Document and compare operational traceability (R3)

---

## Slide 7 — Manfaat Penelitian (30 sec)

[NEW — addresses lecturer: "include benefits/contributions"]

3 columns:
* Teoritis: measurable empirical evidence
* Metodologis: replicable experimental protocol
* Praktis: operational insights for K8s administrators

---

## Slide 8 — Klaim Industri vs. Bukti Ilmiah (1 min)

[Same as old Slide 3]

Industry-claim diagram.

Key message: "Klaim diterima luas. Bukti terkontrol lemah."

---

## Slide 9 — Penelitian Terkait (1 min)

[NEW — addresses lecturer: "gradually discuss lit review" and "what distinguishes your work"]

Table: 4 studies × (Temuan | Kelemahan)
* Shrestha (2024) | GitOps drift detection better | Qualitative; no formal statistics
* Kaggantinataraja (2025) | Declarative faster & safer | Variables uncontrolled; observational
* Matubber (2025) | Reconciliation time measured | No control group
* Paavola (2021) | ArgoCD suitable for multi-app | Descriptive comparative; no quantitative metrics

Differentiation callout (beamercolorbox): "This research differs: (1) controlled experimental design; (2) controlled confounding variables; (3) formal statistical analysis; (4) quantitatively operationalized metrics"

---

## Slide 10 — Kesenjangan Penelitian (1 min)

[Enhanced from old Slide 4 — adds differentiation callout]

Research-gap diagram + explicit callout:
"Penelitian ini mengisi keempat kesenjangan: (1) metrik teroperasionalisasi, (2) variabel terkontrol, (3) uji statistik formal, (4) konteks klaster akademis"

---

## Slide 11 — Desain Eksperimen (2 min)

[Enhanced from old Slide 6 + merged InvenioRDM justification + added architecture-overview]

Left column: experiment-comparison diagram
Right column: architecture-overview diagram (Figure 3.1 — was missing from presentation)

Two callout boxes:
* Control variables (one independent variable, same cluster/workload/drift/hardware)
* Workload justification: InvenioRDM (16+ interdependent components), chosen for: (a) dependency complexity; (b) broad infrastructure components; (c) open-source reproducible

---

## Slide 12 — Skenario Drift Terkontrol (1 min)

[Same as old Slide 8, with fixed diagram]

drift-scenarios diagram (fixed overlapping elements)

---

## Slide 13 — Metrik Pengukuran dan Operasionalisasi (2 min)

[Same as old Slide 9]

operationalization-validity diagram

---

## Slide 14 — Ancaman terhadap Validitas dan Mitigasi (1.5 min)

[Same as old Slide 10]

Threat → Mitigation table

---

## Slide 15 — Analisis Statistik (1 min)

[Same as old Slide 11]

Mann-Whitney U, effect sizes, power analysis

---

## Slide 16 — Hasil yang Mungkin dan Maknanya (1 min)

[Same as old Slide 12]

Three possible outcomes table

---

## Slide 17 — Kesimpulan (30 sec)

Closing quote (same as old Slide 13)

---

# Backup Slides

Keep all existing backup slides (B1-B6). Add:

* B1: GitOps Fundamentals (kept, now also in main Slide 2)
* B2: Why Configuration Drift Matters (kept)
* B3: Detailed Metrics (kept)
* B4: Power Analysis Detail (kept)
* B5: Full Threats to Validity (kept)
* B6: Drift Scenario Details (kept)
* B7: Architecture Overview Detail (NEW)

---

# Changes from Previous Version

1. **Slide 2 (Kunci Konsep)**: NEW — foundational concepts before problem statement
2. **Slide 3 (Latar Belakang)**: ELABORATED — story arc from complexity → drift → consequences
3. **Slide 4 (Rumusan Masalah)**: NEW — explicit research problem statement with R1-R3
4. **Slide 5 (Batasan Masalah)**: NEW — scope/limitations
5. **Slide 6 (Tujuan Penelitian)**: NEW — objectives
6. **Slide 7 (Manfaat Penelitian)**: NEW — benefits/contributions
7. **Slide 9 (Penelitian Terkait)**: NEW — progressive lit review with differentiation
8. **Slide 10**: ENHANCED — added "how this research fills the gaps" callout
9. **Slide 11**: ENHANCED — added architecture-overview diagram + InvenioRDM justification callout
10. **Removed**: Old Slide 5 (Pertanyaan Penelitian) — merged into Slide 4
11. **Removed**: Old Slide 7 (Mengapa InvenioRDM?) — merged into Slide 11
12. **Fixed**: Overlapping figures in drift-scenarios.tex, experiment-comparison.tex, inveniordm-justification.tex
13. **Added**: architecture-overview.tex diagram (Figure 3.1 from proposal)
14. **More citations**: Added inline citations throughout (Burns et al., Pohjola, Rahman, etc.)

# Preparation Priority

Priority 1: Research Gap + Differentiation (Slides 9-10)
Priority 2: Experimental Design + Operationalization (Slides 11, 13)
Priority 3: Rumusan Masalah + Batasan + Tujuan + Manfaat (Slides 4-7)
Priority 4: Background and Concepts (Slides 2-3)
Priority 5: Statistical Analysis (Slide 15)

# Key Examiner Defenses

## "Are you proving something we already know?"

Answer: GitOps reducing drift is a widely-accepted claim with weak controlled evidence. This research provides the controlled experiment that the claim lacks.

## "You're measuring human attention, not deployment strategy."

Answer: Detection capability is part of the deployment paradigm and intentionally included. In manual deployment, the operator IS the detection mechanism. In GitOps, ArgoCD IS the detection mechanism. Both are inherent properties of their respective paradigms. Furthermore, the operator follows a standardized recovery runbook with automated timestamps — not subjective judgment.

## "Why InvenioRDM and not a simpler workload?"

Answer: Configuration drift becomes meaningful when there are multiple interdependent services. A single-service workload under-represents operational complexity. InvenioRDM's 16+ interdependent components represent the class of workloads where drift has the most impact.

## "Why n = 10?"

Answer: Power analysis. Power = 0.80, α = 0.05, target effect size d = 1.0 (large, based on Kaggantinataraja 2025 findings). This yields minimum n = 17 total per group. With 7 scenarios × 10 repetitions = 70 observations per environment, far exceeding the minimum.