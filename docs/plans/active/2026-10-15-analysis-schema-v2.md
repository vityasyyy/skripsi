# Measurement Schema V2 Analysis Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `executing-plans`. Delegation uses herd/Herdr; no subagent chains.

**Goal:** Analyze versioned structured run records without confusing event timestamps with durations, silently dropping failures, or mixing pilots/fixtures with formal evidence.

**Architecture:** Add the smallest explicit schema-v2 input path to the existing analysis tools. Keep legacy synthetic CSV behavior explicitly labeled and isolated. Validate JSON run records before producing output; derive elapsed times from same-clock monotonic events, preserve outcome counts, and gate exploratory comparisons rather than inventing uncensored data.

**Tech Stack:** Python 3, stdlib unittest, already installed numpy/pandas/scipy/matplotlib. No new dependencies or downloads.

## Scope and ownership

- Worker owns `experiments/analysis/` except existing `outputs/`, `mockgen.py` and `requirements.txt` (preserve these). Tests belong in `experiments/analysis/tests/`. This plan may be updated.
- Do not edit `experiments/scripts/`, `experiments/tests/`, `experiments/schema-v2.md`, thesis/proposal/presentation, CI, infrastructure or another checkout.
- No cluster clients, live measurements, credentials, database copies, downloads or subagents. No commits/pushes; lead handles integration after review.
- Generated test outputs belong in temporary directories and are explicitly synthetic. Never put fixture results into thesis tables or existing result directories.
- No universal GitOps superiority, statistical-power claims or firstness claims. No silent data reinterpretation.

## Fixed inter-worker contract

The apparatus worker publishes `experiments/schema-v2.md`. Its fixed contract is already specified in `docs/plans/active/2026-10-15-offline-apparatus-repair.md` in the sibling apparatus checkout. Read that plan as the initial authoritative field list; later read the published schema without editing it. Do not wait-poll the file. If publication is not available, implement against the literal field list below and report any discrepancy to the lead.

One JSON document per run, `schema_version: 2`, with:

- `run_id`, `phase` (`fixture`, `pilot`, `formal`), `subject`, `env` (`manual`, `gitops`), `scenario` (A–G), positive integer `rep`.
- `status` (`complete`, `timeout`, `baseline_failed`, `injection_failed`, `instrumentation_failed`, `correction_failed`), sanitized `reason` where applicable.
- `started_at_utc`; `t0_mono_s`, `ta_mono_s`, `td_mono_s`, `te_mono_s`, `tr_mono_s` (finite same-host monotonic seconds or null). A signal may arrive before API acknowledgement; do not require `td >= ta`, but all measured durations must be nonnegative relative to dispatch `t0`.
- Positive `timeout_s` and `poll_interval_s`; `detection_status`, `evidence_status`, `recovery_status` (`observed`, `right_censored`, `not_evaluable`). Outcome/timestamp combinations must be consistent. Missing events are not zero.
- `r1_baseline_pct`, `r1_post_pct`, `r1_recovered_pct` (null or [0,100]); `healthy_baseline`, `healthy_final` (boolean or null), separate from R1.
- `evidence`: sanitized resource identifiers, differing field paths, evidence source and observation time, never Secret values/hashes. Accept this array as structured provenance; do not copy arbitrary raw payloads into public reports.

Derived durations: detection = `td_mono_s - t0_mono_s`, evidence availability = `te_mono_s - t0_mono_s`, restoration = `tr_mono_s - t0_mono_s`. Injection request latency `ta-t0` is optional diagnostic output, not a fourth response-time metric or a root-cause metric.

Pilot subjects S1/S2 must never become formal workload evidence even if mislabeled phase=formal; fail closed on contradictory subject/phase metadata. Fixture input requires an explicit fixture mode and labels all outputs synthetic. Pilot analysis is explicitly pilot-only. Formal mode rejects mixed-phase input, legacy CSV and known surrogate subjects, not merely filters them away. Do not silently pool subjects, scenarios or repeat identifiers.

## Tasks

- [x] **Red tests first:** reproduced absent schema-v2 support with CLI behavior tests before implementation. Hand-checked fixture duration (t0=100, td=102.5 → 2.5 seconds), Cliff's delta, and Holm adjustment independently of production helpers.
- [x] **Validated input:** explicit version/phase selection; one JSON file or direct JSON summaries only; strict types/ranges, null/event/status consistency, duplicate IDs/replicates, phase/subject guards and pre-output rejection.
- [x] **Descriptive outputs:** per subject/scenario/environment status and event counts, observed-only durations, separate R1/health summaries, and isolated scenario-F visibility-boundary section.
- [x] **Exploratory comparison gates:** implemented two-sided Mann–Whitney and manual-minus-GitOps Cliff's delta behind formal phase, explicit opt-in, approved/prespecified policy, exact collection IDs, and complete observed R2 cells. End-to-end CLI mechanics were tested with synthetic formal-labeled temporary records only; no real formal input was used.
- [x] **Documentation and output separation:** documented CLI, units/scales, phase/status guards, exclusions, policy format and legacy synthetic-only mode. V2 report is exclusive-create and fixture outputs are labeled synthetic. Preserved legacy artifacts and dependencies.
- [x] **Verification:** stdlib unittest, `py_compile`, CLI subprocess checks in temporary directories, hand-derived duration/Cliff/Holm checks, and `git diff --check`. No configured lint/type-check tool was present.
- [x] **Handoff:** untracked `WORKER-REPORT.md` records evidence, changed files, caveats, and approval gates. No commit/push.
- [ ] **Lead integration:** review diff, rerun tests, then feed a real fixture record emitted by the apparatus implementation into the analyzer; verify types, timestamps, null/failure handling and phase isolation across the boundary. No cluster access.

## Known baseline and limits

Base `9362e4c`. Existing `analyze.py` expects legacy CSV and compares raw timing columns; legacy README incorrectly suggests unchanged compatibility with real epochs and pools surrogate subjects. No analysis tests were found. Installed Python dependencies are available. New inference must remain gated on the revised thesis's protocol/supervisor review; this task establishes correct mechanics, not an approved final statistical design.

## Lead review follow-up

The initial worker suite passed 18 tests independently. Lead review then identified unsupported ordering/prerequisite coupling between detection, evidence and restoration; the worker added red regressions and corrected it. An end-to-end temporary synthetic comparison test now exercises approved-policy, complete-sample, Cliff direction and Holm adjustment behavior; it does not constitute real formal analysis.

The lead added producer-boundary cases: API acknowledgement may exist on an unverified injection; an unavailable evidence endpoint does not invalidate independently observed restoration or valid cutoff censoring of a different endpoint; correction failure need not imply an earlier evidence event; and completed F boundary observation does not imply detection/correction. The 25-test suite passes locally. Cross-component emitted-fixture integration remains a separate lead gate, not inferred from these unit tests.

## Analysis worker findings

- The schema text read for this task lists `subject` as `s1` or `s2`; the lead clarified that the general schema is a nonempty string while the current pilot runner only emits `s1`/`s2`. The analyzer follows the clarification: formal-labeled `s1`/`s2` fail closed; other subject labels are accepted as future input, not as collection authorization. Reconcile the schema prose during lead integration.
- No real formal collection was available. The end-to-end comparison test uses only synthetic formal-labeled records/policy in temporary directories; the lead's emitted-apparatus-fixture integration remains open.
