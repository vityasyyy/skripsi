# Experiment Readiness Handoff

Date: 2026-10-15. Status: preparation only; no cluster inspection or live experiment is authorized by this document. Infrastructure repair remains owned by its existing session. Offline apparatus and analysis repairs run in separate worktrees; the lead's integration checkout is separate from both.

## Independent work and integration boundary

| Owner | Scope | Acceptance evidence |
|---|---|---|
| Apparatus worker | Scripts, common comparison, coordinator and offline regression tests | Red-to-green tests for fail-closed baseline, actual drift detection, safe evidence, verified correction and explicit missing/failure outcomes |
| Analysis worker | Schema-v2 parser, derived durations, descriptive reporting and gated comparisons | Hand-checked duration/effect fixtures; phase, schema, duplicate, invalid/censored outcome guards; no silent legacy reinterpretation |
| Lead | Integration and readiness preparation | An actual apparatus-generated fixture passes the analyzer; no mixed phase, timestamp, scale, or censoring assumptions; protected paths unchanged |
| Infrastructure repair session | Cluster repair | Its own reviewed deployment/change verification; no concurrent repair activity initiated by this wave |

Synthetic fixture outputs are test artifacts, never pilot observations or formal evidence. Offline test success does not establish a healthy cluster or a validated live measurement protocol.

## Readiness gates before a live pilot

All entries below are unverified until the handoff supplies dated evidence. A repair completion message is not a substitute.

| Gate | Required evidence | Owner/action |
|---|---|---|
| Intended target | Explicit cluster identity/context and relation to the repair session; no inference from an old reachable-context report | Lead verifies read-only after repair handoff |
| Isolation and safety | Dedicated pilot namespaces/apps, bounded service-account permissions, no production injection or broad namespace cleanup, explicit context and resource allowlists | Review plan before any provisioning; separate execution approval |
| Capacity and storage | Actual node allocatable capacity, workload requests/limits, storage topology and health; room for pilot without interference | Read-only readiness assessment; escalate insufficient capacity |
| Healthy baseline | Nonempty expected inventory, desired-field equality, required Pod readiness and service health, no unexplained restart/rollout/storage/API failures | Fail closed on missing metrics or missing resources |
| Stable observation window | Prespecified observation duration, resource/latency limits, monitored error/restart/pressure history and no concurrent repair/change | Freeze thresholds before observations are accepted |
| Controller configuration | ArgoCD version, app scope, desired revision, auto-sync/self-heal/prune and effective reconciliation behavior; no assumption from old configuration | Record actual settings without mutating global controllers |
| Instrumentation | Monotonic clock domain, UTC audit trail, command/poll latency, evidence availability, complete timeout observation and redaction | Offline tests first; validate live behavior in pilot |
| Evidence access | Required audit/control-plane/log visibility and safe capture; absence recorded rather than interpreted as complete traceability | Verify permissions and retention; never publish Secrets or credentials |
| Abort/reset | Observable stop conditions, immutable failed-run record, safe per-run reset and independently verified restored baseline | Review before first pilot; no destructive production cleanup |

## Gates between pilot and formal data

- The revised comparator and operational definitions require supervisor acceptance. Keep the title/method changes explicit; no claim that automated kubectl is a proved fastest-human bound.
- Freeze a versioned protocol manifest: actual inventory and compared fields, health predicates, mechanism/evaluator intervals, observation cutoff, sample allocation, randomization, invalid-run/retry policy and statistical family.
- Validate S1/S2 injection acceptance, scenario-blind response, fast/missed observations, evidence before/after correction, API failures and timeout behavior. F is a separate unmanaged visibility case.
- Pilot findings may change apparatus/protocol before formal collection; they do not enter the formal dataset. Record any calibration changes and rerun affected validation.
- Verify the formal multi-service InvenioRDM inventory (planned at least 16 application/support components), isolation and capacity separately. Pilot readiness does not establish full-workload readiness.
- Approve a small first formal batch, review raw evidence and protocol adherence, then authorize the remainder. Preserve all attempts, exclusions and failures; never rerun selectively until a preferred outcome appears.

## Formal-run record and thesis provenance

The collection manifest should link run identifiers to phase, workload/version, environment, scenario, measurement allocation and randomization order. Responder inputs exclude hidden injection labels. Preserve immutable raw evidence, sanitized event summaries, apparatus/protocol revisions and analysis invocation. Any shared artifact must exclude raw Secret values, credential-bearing command output and unsafe secret hashes.

Bab IV consumes only validated formal observations and explicitly reports missing/censored/invalid outcomes. Bab V answers the revised research questions without assuming either mechanism wins. Final manuscript verification includes citations, field/metric consistency, appendices, full compilation and personal front matter; no current draft claims empirical completion.

## Decisions still requiring a future gate

Actual experimental target; repair handoff and observed health; pilot provisioning/execution approval; supervisor acceptance; exact inventory, resource thresholds, observation window/cutoff and sampling allocation; statistical policy and formal-run authorization. None is silently granted by approving offline code work.

## Offline review findings to resolve before integration

- The lead independently ran the analysis worker's initial 18-test suite successfully, then found an unsupported assumption that detection, deviation evidence and restoration must always occur in that order. Their observable events are separate; a missed controller signal must not erase independently verified restoration. Regression fixes were requested from both workers.
- Successful injection command exit alone does not establish that the intended mutation was accepted. The producer must distinguish verified acceptance from a successful no-op, including fast reconciliation that precedes a later read-back.
- Deviation evidence must come from the response mechanism's observable information, not silently borrow the evaluator's privileged injection knowledge. The evaluator remains the common R1/restoration oracle.
- Unexpected-resource evidence requires a safe identity marker consistent with the schema, without changing the expected-inventory percentage denominator. F remains a separate boundary case.
- A completed run should terminate once all required endpoints are observed and restoration confirmed. An unobserved endpoint is right-censored only after valid observation to its cutoff; early collection termination is not full-cutoff censoring.
- Existing repository CI filters cover LaTeX-related paths, not the apparatus/analysis paths. Local offline tests and cross-component checks must be reported accurately; absence of applicable CI must not be described as green apparatus CI. Adding an offline CI workflow is separate from the workers' explicitly bounded file ownership.

## Integration verification and remaining work

The worker file sets are disjoint. Their commits were integrated on a separate feature branch, never merged into main directly. The lead added eight cross-component tests using actual producer records, the real parser/report writer and a CLI invocation; they pass for successful recovery, failed baseline, unverified injection with retained acknowledgement, failed correction, missed controller signal with valid restoration, censoring, F separation and fixture/formal rejection.

The reviewed component suites contain 42 apparatus tests and 25 analysis tests. ShellCheck and Python syntax checks pass; original generated mock artifacts, dependencies, thesis, proposal, presentation and infrastructure are unchanged. Python caches and worker reports are excluded from the delivery. These results establish offline behavior only.

This is an incremental hardening delivery, not completion of the live apparatus. The current ArgoCD field-level evidence transport is intentionally unavailable; live GitOps execution fails before any client call. The unsafe fallback of treating evaluator data as controller evidence was removed. Implement and validate that transport, verify app/server-to-context mapping, and review explicit reset and collection orchestration before any live-pilot approval. Formal execution and live F remain blocked. The draft PR must retain these limitations and must not be merged or used for live collection implicitly.
