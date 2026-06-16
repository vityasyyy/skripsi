# PLAN.md — Presentation Structure (v3)

> See `docs/PRESENTATION_PLAN.md` for the full detailed plan with examiner defenses.
> See `docs/PLAN_v1.md` for the original plan.

## Slide Order (19 Main + 6 Backup)

### Act 1: Context & Problem (Slides 1–8)
1. Title
2. **Apa Itu Deployment Aplikasi?** — deployment-context diagram, two paradigms
3. Konteks: Kubernetes dan Masalah Drift — scenario + drift definition
4. **Bukti: Drift Bukan Masalah Teoritis** — stats + concrete university IT scenario
5. GitOps Menjanjikan Jawaban — OpenGitOps principles + gitops-flow diagram
6. Klaim Industri vs. Bukti Ilmiah — industry-claim diagram
7. **Kesenjangan Penelitian** ★ CLIMAX — research-gap diagram + "so what" framing
8. Rumusan Masalah — main question + R1/R2/R3/R4 (no H0/H1)

### Act 2: Research Design (Slides 9–16)
9. Batasan Masalah — 6 scope items
10. Tujuan dan Manfaat Penelitian — objectives + benefits
11. Penelitian Terkait dan Pembeda — lit review table (5 studies) + differentiation
12. Arsitektur Eksperimen ★ CRITICAL — architecture + InvenioRDM justification
13. Skenario Configuration Drift Terkontrol — drift scenarios
14. Metrik Pengukuran dan Operasionalisasi — R1/R2/R3/R4 + RCID definition note
15. Prosedur Eksperimen — experiment flow diagram
16. Analisis Statistik dan Ukuran Sampel — methods + power justifications

### Act 3: Implications (Slides 17–19)
17. Ancaman terhadap Validitas dan Mitigasi — threat-mitigation table
18. Jadwal Penelitian — Gantt chart
19. **Kontribusi yang Diharapkan** — "so what" + university IT stakeholder + closing

### Backup (B1–B6)
B1: ArgoCD Detail | B2: Defense RCID | B3: Defense R3/R4 Analysis
B4: Defense InvenioRDM | B5: Defense Single Operator | B6: Defense No Significant Difference

## Key Changes from v2
- Added Slide 2: deployment context (diagram already existed but was unused)
- Split old Slide 2 into Slides 3 (drift definition) + 4 (evidence + university IT scenario)
- Split old Slide 3 into Slides 5 (GitOps principles) + 6 (industry claims)
- Removed H0/H1 from all slides (not in proposal document)
- Fixed R1-R4 to match proposal: R1=konsistensi, R2=detection+recovery, R3=intervensi manual, R4=traceability
- Added "so what" framing to research gap (Slide 7) and closing (Slide 19)
- Closing slide now names concrete stakeholder (university IT team) and decision
- Lit review table now includes all 5 studies from proposal (added Damore 2021)
- Removed em dashes throughout; replaced with commas, semicolons, or rephrased
- Fixed all overfull vbox issues