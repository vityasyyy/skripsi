# Offline Experiment Apparatus Repair Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `executing-plans`. Delegation uses herd/Herdr; no subagent chains.

**Goal:** Make the apparatus testable offline and align its observable measurement behavior with the revised thesis, without executing cluster commands or claiming live validation.

**Architecture:** Keep the existing safe dry-run command surface where practical. Use the smallest shared Python-standard-library measurement/comparison helper necessary for structured JSON, a common monotonic clock, safe subprocess argument lists and offline tests. Separate the injection coordinator, scenario-blind response procedure and independent evaluator. Do not introduce a general-purpose experiment framework.

**Tech Stack:** Existing Bash entry points, Python 3 standard library/unittest, installed ShellCheck. No installs or downloads.

## Approved scope and boundaries

- Worker owns `experiments/scripts/`, `experiments/tests/`, `experiments/README.md`, and `experiments/schema-v2.md`. This plan may be updated with findings and checkboxes.
- Do not edit thesis/proposal/presentation, analysis code/outputs, dependency files, CI, infrastructure or another checkout. Do not commit or push; lead reviews and handles delivery.
- No actual kubectl/argocd commands, even read-only. Tests must use in-process fake adapters or explicit fake executables; subprocess tests must never fall through to installed cluster clients.
- Default dry-run performs no external commands and writes no empirical records. Actual execution always requires an explicit live flag, explicit context, tightly allowlisted pilot namespace and a passing fail-closed baseline. Do not expand allowlists to InvenioRDM/production or enable formal experiments.
- The efficient imperative responder receives baseline declarations and observed differences, never scenario labels or injection metadata. No artificial human delay, fastest-human guarantee, or guaranteed GitOps advantage.
- F is an unmanaged visibility-boundary case with separate reporting; never automatically delete namespaces or arbitrary unmanaged resources.
- No raw Secret values, hashes, full sensitive manifests, credential-bearing stderr, or unsanitized diff output in records/evidence/logging.
- Preserve existing mock outputs and CSV as legacy synthetic examples; do not overwrite them with new-format records or claim compatibility with the old analyzer.

## Data contract to publish before implementation

Write `experiments/schema-v2.md` first and keep it stable. New measurements use one JSON summary per run, not the ambiguous legacy CSV. Include:

- `schema_version: 2`; `run_id`; `phase` (`fixture`, `pilot`, `formal`); `subject`; `env` (`manual`, `gitops`); `scenario`; positive `rep`.
- `status`: `complete`, `timeout`, `baseline_failed`, `injection_failed`, `instrumentation_failed`, or `correction_failed`; a sanitized `reason` when applicable. F does not become a correction failure merely because it is outside controller scope.
- `started_at_utc`; `t0_mono_s`, `ta_mono_s`, `td_mono_s`, `te_mono_s`, `tr_mono_s`: finite seconds from the same host monotonic clock, or JSON null for an unobserved event. `t0` is injection dispatch; `ta` is API response acceptance time. Instrumentation must start before dispatch. Store UTC audit times separately from elapsed-time calculations.
- `timeout_s`, `poll_interval_s`; `detection_status`, `evidence_status`, `recovery_status`: `observed`, `right_censored`, or `not_evaluable`. Only valid observation to the predefined cutoff justifies right censoring. Failed instrumentation is not a missed detection and missing events never become zeros.
- `r1_baseline_pct`, `r1_post_pct`, `r1_recovered_pct`: null or percent in [0,100] using the same expected-resource inventory and field predicate for both arms; `healthy_baseline` and `healthy_final`: booleans or null, separate from R1.
- `evidence`: sanitized resource identifiers and differing field paths, evidence source, and observation time; no Secret values/hashes. `te` requires actual stored deviation evidence, not any status/health text and not the full four-part R3 audit rubric.
- Metadata may retain the scenario for grouping, but responder interfaces and command arguments must not receive it. Keep subject/phase explicit so fixture and pilot data cannot silently enter formal analysis.

Document event ordering, validity, failure precedence and a fixture example. Be explicit that the legacy analyzer does not yet consume this schema. If a change to this interface is unavoidable, report it rather than silently changing it mid-task.

## Tasks and acceptance

- [ ] **Reproduce defects with failing tests:** show missing/empty node metrics and empty/nonready pod inventories cannot establish baseline; rollout health does not detect ConfigMap/Secret/image/replica drift; timeout does not fabricate timestamps; failed correction cannot declare recovery. Record root causes and actual red-test evidence before fixes.
- [ ] **Common comparison and evidence:** compare expected identities and predeclared fields with identical semantics for both arms; missing resources count as mismatch, API/read errors as instrumentation failures; health remains independent. Test health-with-drift, missing objects, dynamic-field exclusions, extra objects/F and Secret redaction.
- [ ] **Observation and response:** implement/test the minimum coordinated flow: baseline, active collector, one injection, observed detection, nonblocking evidence and automated scenario-blind correction for the imperative arm, repeated inventory/field verification, explicit timeout/error outcomes, reset verification. Keep final restoration confirmed by two consecutive reads and report its first observation. Never claim diagnosis or root cause from a diff.
- [ ] **Safety and entry points:** retain dry-run behavior and namespace gates; reject accidental multi-scenario live injection without reset orchestration; reject mismatched namespace/environment/subject and arbitrary app/context targets where applicable. Remove eval-based command execution on touched paths in favor of argument lists. Every subprocess has a bounded timeout; no cleanup of production or whole namespaces.
- [ ] **Contract and operator documentation:** document the new JSON schema and offline invocation, exact tests, legacy CSV incompatibility, pilot-only restrictions, and what still needs live validation. Do not present a supported live runner unless all gates/paths are implemented and tested offline.
- [ ] **Verification:** run stdlib unittest tests and subprocess integration tests using fakes, Bash syntax and installed ShellCheck on touched scripts, Python compile checks without committing caches, default dry-run no-command tests, and diff/secret checks. No statistical/mock generation into thesis results.
- [ ] **Worker handoff:** write untracked `WORKER-REPORT.md` with exact test commands/results, red-to-green evidence, changed files, contract deviations, live-validation gaps, and remaining concerns. Do not commit/push. Stop expanding scope once these deliverables are met.
- [ ] **Lead gate:** inspect full diff and scope, independently rerun verification, review contract and security; only then prepare scoped PR. No deployment or experiment execution is authorized.

## Baseline evidence

Base `origin/main`: `9362e4c` (merged revised thesis). Existing shell scripts pass `bash -n`; ShellCheck reports existing return-code masking, unused variables and eval-array warnings. No existing apparatus tests were found. All four scripts were read; confirmed static defects include rollout-health drift proxy, fabricated timeout events, scenario-aware response, swallowed correction errors, inconsistent R1 predicates, and fail-open missing CPU observations. Tests must reproduce these before fixing.

## Deferred work

Analyzer/schema-v2 consumption can be implemented independently only against this frozen contract and in a separate worktree after owner approval. Statistical policy still follows the thesis's supervisor-review gate. Cluster readiness, target selection, manifests/apps, live pilots and formal runs are separate approvals. No downloaded tools or dependencies are authorized.

## Lead review and partial delivery boundary

The worker exceeded its time box with core regressions still failing; the lead stopped worker implementation and took over. The lead reproduced six failures before fixing verified API acceptance, mechanism-versus-oracle evidence, independently observed restoration and early completion. Further red tests caught unrelated delete responses and loss of a previously observed recovery after a later read error. Regression fixes preserve API acknowledgement even when the requested mutation is unverified; only downstream endpoint observations become not evaluable for an invalid injection.

The offline core and legacy-path safety changes are delivered incrementally, not as a live-ready pipeline. The common expected inventory/field oracle and scenario-blind responder are tested offline. Live GitOps execution is blocked before client calls because the ArgoCD field-level evidence transport is not yet implemented/validated; no common-oracle data is passed off as controller evidence. Unsupported evidence is not evaluable while independently measurable detection/restoration endpoints remain visible. F remains fixture-only. Cross-run reset, batch randomization and formal-workload support are not automated by this single-run tool.

The obsolete unsafe shell live paths are disabled, not silently kept compatible. Shell executable modes are retained. Original synthetic CSV examples and generated outputs remain unchanged. These compatibility and capability limits must be included in the PR and final handoff. Remaining implementation work is the explicit ArgoCD evidence adapter, context/server validation and reset/collection orchestration before any separately approved live validation.
