# Experiment apparatus

The scripts support controlled, single-injection measurements for the S1/S2
surrogate. This is experimental apparatus, not a production deployment tool.
The published data contract is [`schema-v2.md`](schema-v2.md). Schema-v2 analysis
must use the explicit JSON mode documented in `analysis/README.md`; the legacy
CSV path cannot interpret these records.

```mermaid
flowchart TD
  baseline[Fail-closed baseline] --> observe[Start common observer]
  observe --> dispatch[t0 injection dispatch]
  dispatch --> ack[ta API acknowledgement]
  dispatch --> signals{Arm-specific signal}
  signals -->|Manual: kubectl inventory| response[Scenario-blind responder]
  signals -->|GitOps: relevant ArgoCD drift| controller[ArgoCD reconciliation]
  response --> oracle[Common inventory and field oracle]
  controller --> oracle
  oracle --> restore[Two consecutive equality reads]
  restore --> summary[One schema-v2 JSON summary]
```

Instrumentation starts before injection, so `td` may precede `ta`. Manual
detection uses the imperative inventory signal; GitOps detection uses an actual
ArgoCD `OutOfSync`/`Missing` status for an expected resource. The common oracle
provides identical R1 and restoration checks to both arms, but does not replace
the GitOps detection signal. The responder receives only expected declarations
and observed differences; it never receives the scenario label or injection
metadata. Health is measured separately from desired-field equality.

## Offline use

The default command is a no-command, no-write preview:

```bash
python3 experiments/scripts/apparatus.py --subject s1 --env manual --scenario A
```

It writes no measurement, even when `--output` is supplied. Legacy shell entry
points are preview-only. `metrics-collect.sh --live-dryrun` remains available
only to append the old synthetic CSV example; that CSV and the checked-in
analysis outputs remain unchanged and are not schema-v2 measurements.

Run the three offline suites and static checks with:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s experiments/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s experiments/analysis/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s experiments/integration_tests -v
for script in experiments/scripts/*.sh; do bash -n "$script" || exit; done
shellcheck -S warning experiments/scripts/*.sh
PYTHONDONTWRITEBYTECODE=1 python3 -c 'from pathlib import Path; [compile(path.read_text(), str(path), "exec") for path in Path("experiments").rglob("*.py")]'
git diff --check
```

The `Offline Experiment Tests` GitHub Actions workflow runs the same suites and
checks. It has read-only repository permissions, denies real cluster clients
through `PATH`, and does not upload fixtures or request credentials. Tests use
mocked transports or explicit fake `kubectl`/`argocd` executables; no test
invokes an installed cluster client.

## Pilot gates and limitations

The runner accepts only `s1`/`s2`, one scenario `A`–`G`, a positive repetition
number, and the exact namespace mapped to the subject/environment. Live runs
must explicitly use `--live --phase pilot`, an allowlisted context in
`APPARATUS_PILOT_CONTEXTS`, and a passing baseline. GitOps runs additionally
require an exact five-part `context|namespace|app|argocd-context|destination-server`
entry in `APPARATUS_PILOT_TARGETS`, with matching `--argocd-context` and
`--destination-server` flags. The ArgoCD application must report the selected
namespace and all expected resources. The following is syntax only, not an
approved target or instruction to configure a pilot:

```text
<kube-context>|<namespace>|<application>|<argocd-context>|<destination-server>
```

These allowlists are empty by default. Formal execution is unsupported.

As of 2026-10-19, the offline-tested GitOps adapter obtains structured
Application status and relevant resource JSON through ArgoCD. It preflights
`get-resource` CLI support and resource read access before baseline or injection;
unsupported clients and denied access fail closed. Application context,
destination server, and Kubernetes context are joined only by an explicit
operator allowlist mapping. That configured mapping is not runtime proof that
the endpoints share a cluster identity. This implementation has not been
validated against a live ArgoCD server or cluster.

ArgoCD server-redacted Secret values are never compared as raw evidence. A
value-only Secret difference that cannot be established safely remains
`not_evaluable`, including after healing; independently observed detection and
restoration remain visible. This is an offline-tested core, not a live-pilot-
ready experiment pipeline.

Scenario F is fixture/reporting-only in this repair. It is an unmanaged
visibility-boundary case, not something the runner may create or clean up in a
derived namespace. Live F remains blocked pending separate boundary approval;
no namespace or arbitrary unmanaged resource is automatically deleted.

No live pilot or cluster readiness was validated. Fixture tests prove only
offline behavior. Live compatibility and permissions, runtime cluster identity,
workload readiness, and protocol/supervisor/execution approval remain pending.
Before any separately approved pilot, validate the exact Kubernetes/ArgoCD
client versions, operator mapping, expected resource fields, API status behavior,
metrics and pod readiness, and correction semantics against the approved pilot
context. The coordinator bounds every client subprocess and records only
sanitized identities/field paths; it never stores Secret values, hashes, full
manifests, raw diffs, or command stderr.

Before the next run, a separate approved reset must restore inventory and health.
This single-run tool does not automate batch allocation, randomization or cleanup.
A failed run remains recorded and the next baseline fails closed; no namespace
is deleted to make a subsequent run pass. Live F, live ArgoCD compatibility and
permissions, runtime context/app identity verification, and formal-workload
adapters remain future gates.
