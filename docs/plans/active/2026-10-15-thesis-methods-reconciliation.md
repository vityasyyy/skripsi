# Thesis Methodology and Chapter Drafting Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Delegation uses herd/Herdr; no subagent chains.

**Goal:** Produce a coherent Indonesian thesis draft through Bab V for the approved automated imperative versus GitOps comparison, without claiming uncollected empirical results.

**Architecture:** Preserve the accepted proposal as the historical baseline. Reconcile thesis methods first, align framing and literature, then draft the results structure and evidence-bounded conclusions/limitations. Separate intended protocol, pilot validation, and formal measured findings.

**Tech Stack:** Existing ugmskripsi LaTeX class, BibTeX, Makefile, installed TeX Live.

## Approved constraints

- Work only in `content/skripsi/` and this plan; no proposal, presentation, experiment-code, infrastructure or CI edits.
- One writing worker in an isolated worktree. Lead reviews, verifies and pushes a feature branch/PR; no merge authorized.
- Efficient, fixed automated imperative kubectl baseline: no human reaction/typing delays or artificial waits; no universal fastest-human claim and no hidden injection identity supplied to the responder.
- Formal workload retains the accepted multi-service scope. S1/S2 surrogates are pilot-only and cannot support formal InvenioRDM conclusions.
- R1 uses the same desired-field equality/inventory rule in both arms; health is separate. Use safe equality checks for Secrets without publishing their values.
- Replace root-cause-identification timing with time to obtain verifiable evidence of the configuration deviation; do not infer causal origin from a diff.
- Scenario F is a separately interpreted unmanaged-resource visibility-boundary case, not an assumed ArgoCD self-heal success.
- No fabricated values, analysis results, versions, stability observations, supervisor approval, or completed-experiment claims.
- Protocol changes remain a draft for supervisor review; existing apparatus is not certified to implement them.
- Literature gap claims are bounded. Prior work includes controlled comparisons and timing-based evaluations; do not assert firstness or guaranteed GitOps superiority.
- Indonesian academic prose, existing five-chapter structure, citations and figures with captions/labels. No plan-step references in LaTeX comments or prose.

## Tasks

- [x] **Methods:** revise `content/skripsi/chapters/bab3-metodologi.tex` with comparator/estimand, operator role, pilot/formal separation, common R1 predicate, observable R2 event definitions, R3 evidence rubric, F classification, readiness gates, one-injection/reset protocol, failure/censoring policy and scenario-specific analysis/sample-size limitations. Keep the existing n=10 R2 / n=5 R1 as planned descriptive sampling, not an unsupported per-scenario power guarantee. Do not pool pilot subjects into formal inference. State timestamp units, injection acceptance, polling resolution and separate detection/evidence/recovery durations. Do not replace missing detection with zero, or condition on successful recovery silently.
- [x] **Framing:** align `bab1-pendahuluan.tex`, `bab2-tinjauan-pustaka.tex`, `main.tex` and `references.bib` only as necessary. Update title if needed to accurately distinguish automated imperative management from human manual work; preserve metadata. Remove obsolete operator/TLX claims and symbol entries, distinguish drift from static defects, remove overstrong causal/generality claims, correct closest-work summaries using verified abstracts. Do not add unverified full-text assertions.
- [x] **Figures:** inspect diagrams included by the thesis. If an inherited PDF encodes the superseded human protocol, replace its thesis-side inclusion with a concise accurate figure using existing LaTeX/TikZ support; never alter proposal assets. Keep a methodology flowchart and architecture figure. Explain figures in surrounding prose; avoid conflicting duplicate visual definitions.
- [x] **Results draft:** replace TODO-only `bab4-hasil-analisis.tex` with substantive setup/provenance and reporting structure. State no validated formal dataset is available in this draft; provide empty result-table schemas or prose, not synthetic numbers. Keep target specifications explicitly planned until verified. Separate F's possible missed detection from invalid instrumentation. No actual effect interpretation or statistical values.
- [x] **Bab V:** write established design limitations and future-work recommendations in `bab5-kesimpulan-saran.tex`; map eventual empirical conclusions to the revised questions but state findings are unavailable. Do not conclude effectiveness or recommend adoption based on unmeasured results. Avoid operator-replication advice framed as mitigation of a human experiment that is no longer performed.
- [x] **Appendix consistency:** update `lampiran/lampiran-a.tex` only if required to align evidence schema/labels; do not present current scripts as validated or include real Secrets.
- [x] **Worker verification:** compile with `PATH=/Library/TeX/texbin:$PATH make skripsi`; inspect final log for undefined citations/references and new serious layout issues; `git diff --check`; inspect PDF text for contradictory old terminology and TODO-only results. Report pre-existing warnings separately. Do not download anything.
- [x] **Lead review:** inspect full diff, revised questions/metrics/claims, forbidden-scope diff and secret exposure; independently compile and validate citations/cross-references and changed-page readability. Fix forward any findings before push.
- [ ] **Delivery:** commit scoped changes with `docs(thesis): reconcile automated deployment experiment methodology`, push branch, open a PR with methodological caveats and exact verification, wait for PR CI. Do not merge.

## Verified baseline

- Base: `origin/main` at `9054d89`.
- Baseline `make skripsi`: success, 61-page PDF using installed TeX Live (2026-10-15).
- Worker checkout: `.worktrees/thesis-methods-reconciliation`, branch `docs/thesis-methods-reconciliation`.
- Official/example PDFs referenced by AGENTS.md are not present in the checked-out repository; preserve existing class/structure and disclose that document-level compliance cannot be re-audited against absent PDFs.

## Decisions and evidence limits

The owner approved this drafting scope and GitHub push. Supervisor review of the revised comparator and operational definitions remains pending. Cluster context, live readiness, actual versions, final resource inventory and empirical results require separate verification and are not established by this writing task.

Closest-work abstract corrections: Nataraja (2025) describes a controlled single-node Minikube comparison with differing security configurations; Matubber (2025) includes a legacy semi-automated comparison baseline; Shrestha and Ali (2024) compare drift induction/discovery/remedy times against Ansible. Neither presence nor absence of formal statistical tests is asserted without full-text verification.

## Review findings and supervisor checklist

- The title and comparator now describe automated imperative management, not a human-performance experiment. Supervisor acceptance remains pending.
- R2 uses detection, deviation-evidence availability and configuration restoration, not root-cause identification. The collector starts before injection; injection dispatch and API acknowledgement are recorded separately. Evidence capture must not delay correction.
- The formal target remains at least 16 application/support components, subject to a verified inventory and isolation boundary. S1/S2 remain pilots only.
- One-second evaluator polling is a planned pilot-validation target, not a verified capability. The imperative checking schedule, ArgoCD reconciliation settings, health/resource limits and observation timeout must be frozen before formal collection.
- Cliff's delta is the planned primary time-effect measure; exploratory Mann–Whitney comparisons require complete observations and independence. The final Holm comparison family and any censored-data analysis need supervisor review before data collection.
- The lead corrected a residual complete-Git-audit claim, limited Secret comparison to in-memory equality, separated the deviation-evidence event from the complete R3 rubric, and corrected figure routing after rendered-page inspection.
- No validated formal results exist in this draft. Bab IV provides reporting schemas; Bab V states pending empirical conclusions and established design limitations.
- Existing personal front-matter placeholder `Isi Prakata di sini...` is outside this research-writing scope and remains for the author.
- The final local build produces a 49-page PDF. No undefined citations/references or overfull boxes remain; two underfull boxes remain in the approval-page template and R1 reporting table. The accepted proposal, presentation, apparatus and CI files are unchanged.
