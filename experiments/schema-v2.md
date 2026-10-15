# Experiment summary schema v2

This is the stable contract for new measurements. Write one JSON summary per
run. The legacy synthetic CSV and generated analysis outputs remain examples;
the legacy analyzer does not consume this schema.

## Fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer, exactly `2` | Contract version. |
| `run_id` | string | Unique identifier for this run. |
| `phase` | `fixture`, `pilot`, or `formal` | Data provenance. The schema can represent formal data; this runner does not support formal execution. A fixture is not empirical data. |
| `subject` | non-empty string | Workload subject. The current pilot runner accepts only `s1` or `s2`. |
| `env` | `manual` or `gitops` | Deployment arm. |
| `scenario` | `A`–`G` | Injection metadata for grouping. It must not be sent to the response procedure. |
| `rep` | positive integer | Repetition number. |
| `status` | `complete`, `timeout`, `baseline_failed`, `injection_failed`, `instrumentation_failed`, or `correction_failed` | Run outcome, using the precedence rules below. |
| `reason` | string or null | Sanitized reason code/message for a non-complete outcome. Never include command stderr, Secret data, hashes, or raw diffs. |
| `started_at_utc` | RFC 3339 UTC string | Audit time when run instrumentation starts. This is not used for elapsed-time calculations. |
| `t0_mono_s`, `ta_mono_s`, `td_mono_s`, `te_mono_s`, `tr_mono_s` | finite number or null | Event times from one host monotonic clock, in seconds. Never substitute zero for an unobserved event. |
| `timeout_s`, `poll_interval_s` | finite positive number | Observation cutoff and polling interval. |
| `detection_status`, `evidence_status`, `recovery_status` | `observed`, `right_censored`, or `not_evaluable` | Whether each event was observed, validly absent at the cutoff, or could not be evaluated. |
| `r1_baseline_pct`, `r1_post_pct`, `r1_recovered_pct` | number in `[0,100]` or null | Percentage of the common expected inventory matching the same predeclared field predicate in both arms. The denominator and numerator contain expected identities only; missing expected objects are mismatches. Unexpected objects are reported separately and never folded into R1. Null means not evaluable. |
| `healthy_baseline`, `healthy_final` | boolean or null | Workload health, independently measured from R1 desired-field equality. |
| `evidence` | array | Sanitized observations: resource identity, differing field paths, source, and monotonic observation time only. No field values, Secret data/hashes, full manifests, or root-cause claims. |

UTC audit time and monotonic event time have different purposes and must remain
separate. All non-null event times are finite seconds from the same host's
monotonic clock. `t0` is recorded immediately before injection dispatch;
`ta` is recorded only after the API accepts that request. Instrumentation starts
before `t0`. `td` is the first valid signal from the assigned deployment
mechanism: the imperative mechanism in the manual arm, or an actual relevant
ArgoCD drift signal in the GitOps arm. It may precede API acknowledgement
(`ta`) but cannot precede `t0`. Health/readiness and the common R1/restoration
oracle are not substitutes for the GitOps detection signal. `te` is the first time a
sanitized differing-field observation is captured as evidence, not a diagnosis
or root cause. `tr` is the time of the first of two consecutive reads matching
the complete expected inventory and field predicate. A failed second read
invalidates the candidate restoration; a later pair may establish `tr`.

## Validity and censoring

- Establish a baseline only when the expected inventory is readable and equal,
  workload health is observable, node metrics are non-empty, and the pod
  inventory is non-empty with every listed pod ready (or completed where the
  workload declares a completed job acceptable). Missing or empty observations
  fail closed; they do not establish a healthy baseline.
- Both arms use identical expected identities, declared fields, dynamic-field
  exclusions, and R1 scoring. R1 is matching expected resources divided by the
  expected inventory size; extras do not change that denominator and are
  reported separately as evidence. Health is reported separately. API/list/read
  errors are instrumentation failures, not mismatches or missed detections.
- The GitOps detection endpoint must observe ArgoCD's actual drift state for a
  relevant managed resource; generic application health and the independent
  common equality oracle cannot establish `td`. The manual endpoint uses its
  imperative mechanism signal. The common oracle provides R1 and restoration
  verification for both arms.
- `observed` requires a valid event and a corresponding non-null timestamp.
  `right_censored` requires valid instrumentation for that endpoint through its
  configured cutoff with no event. If collection stops early (for example,
  because restoration was observed), an unobserved endpoint is
  `not_evaluable`, not right-censored, unless its own cutoff was reached.
  `not_evaluable` also means instrumentation failure or an event outside the
  evaluator's visibility boundary. A missing event is never encoded as time
  zero.
- `evidence` contains observed resource identifiers and field paths, not values.
  Secret field comparison may happen in memory, but Secret values and hashes
  must never enter evidence, logs, or run records.
- Scenario F is reported as an unmanaged visibility-boundary case. It is not
  corrected by deleting a namespace or arbitrary unmanaged resource, and its
  out-of-scope recovery is `not_evaluable`, not `correction_failed`.

## Event ordering and failure precedence

Instrumentation starts before injection. After baseline, injection dispatch
(`t0`) and API acknowledgement (`ta`) are recorded; the concurrent mechanism
observer may record `td` before or after `ta`, but never before `t0`. Evidence
capture (`te`), response where applicable, and recovery verification (`tr`)
follow their own measured times. Events that did not occur remain null. A baseline failure stops before
injection; an injection failure may retain `ta` when the API replied but the
requested mutation could not be verified. Downstream endpoint times then remain
null and not evaluable. Instrumentation failure makes the
affected observation `not_evaluable`; a failed correction cannot produce an
observed recovery. If monitoring remains valid but a required event is absent at
the cutoff, the result is right-censored and the run status is `timeout`.

Use the first applicable terminal failure: `baseline_failed`, then
`injection_failed`, then `instrumentation_failed`, then `correction_failed`,
then `timeout`; otherwise use `complete`. A complete F boundary observation
does not imply controller correction. Store only a safe reason code or concise
sanitized explanation.

## Fixture example

```json
{
  "schema_version": 2,
  "run_id": "fixture-s1-manual-A-1",
  "phase": "fixture",
  "subject": "s1",
  "env": "manual",
  "scenario": "A",
  "rep": 1,
  "status": "complete",
  "reason": null,
  "started_at_utc": "2026-10-15T12:00:00Z",
  "t0_mono_s": 100.0,
  "ta_mono_s": 100.1,
  "td_mono_s": 100.2,
  "te_mono_s": 100.2,
  "tr_mono_s": 100.5,
  "timeout_s": 30.0,
  "poll_interval_s": 0.1,
  "detection_status": "observed",
  "evidence_status": "observed",
  "recovery_status": "observed",
  "r1_baseline_pct": 100.0,
  "r1_post_pct": 80.0,
  "r1_recovered_pct": 100.0,
  "healthy_baseline": true,
  "healthy_final": true,
  "evidence": [
    {
      "resource": "Deployment/exp-web",
      "field_paths": ["spec.replicas"],
      "source": "inventory-comparison",
      "observed_at_mono_s": 100.2
    }
  ]
}
```

This fixture illustrates shape and event semantics only; it is not a measured
result and must not be included in formal analysis.

## Endpoint independence and current capability

Do not impose `td <= te <= tr`: a signal or evidence capture may be missed or
delayed while the independent oracle verifies restoration. Previously observed
endpoints remain observed after an unrelated later instrumentation failure.
An unavailable evidence adapter yields `not_evaluable`, not a zero time or
invented field-level evidence. Other endpoints validly observed to the cutoff
may be right-censored even when one endpoint is not evaluable.

For F, `complete` means the boundary observation period completed, not that
controller detection, evidence or correction occurred. Its recovery is always
not evaluable. `$identity` is the safe field-path marker for missing/extra
resource identity evidence; unexpected objects do not change the R1 denominator.

The current live GitOps CLI is blocked because its field-level evidence
transport is not validated. The schema can represent later formal subjects,
but the runner cannot execute formal runs. No fixture or supported input shape
establishes permission, protocol approval, or empirical validity.
