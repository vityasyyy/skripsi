# ArgoCD Evidence Adapter and Offline CI Plan

> **Current status (2026-10-19):** Offline adapter, fake-transport coverage, and
> read-only offline CI workflow are implemented and locally verified. Live
> compatibility, permissions, runtime cluster identity, readiness, and protocol
> approval remain pending. Delivery to PR #4 is lead-owned; this worker must not
> push or change the PR.

> **For agentic workers:** use `executing-plans`; one bounded completion worker is authorized in the existing PR #4 isolated checkout. No additional workers or cluster access are authorized by this follow-up.

**Goal:** Complete the missing structured ArgoCD deviation-evidence adapter and automate the offline regression suites in GitHub Actions.

**Architecture:** Obtain controller signals from Application JSON and relevant live resource details through the documented `argocd app get-resource ... -o json` command. Compare only predeclared fields in memory and emit identifiers/field paths, never values. Preserve the independent common oracle and schema-v2 analysis boundary.

## Verified source constraints

- ArgoCD's documented `app diff` ignores Secrets and emits rendered text; it is not a structured evidence transport.
- The current documented `get-resource` command exposes live resource JSON through the ArgoCD server. The upstream implementation calls `GetResource` then prints manifests; responses can contain one object or a list.
- The upstream server replaces Secret values. Never interpret redacted data values as configuration mismatches. A value-only Secret change may remain not evaluable at the evidence endpoint, while detection/restoration remain independently reportable.
- ArgoCD v2.12.0 command sources do not provide `get-resource`. Probe required CLI help/capability before baseline/injection; unsupported clients fail closed without an automatic install or upgrade.
- The application destination address may be an internal API alias rather than the kube-context's external URL. Require an operator-approved explicit mapping, not a claim that string equality proves cluster identity.

Sources: official `argocd_app_get-resource` and `argocd_app_diff` command references; upstream `cmd/argocd/commands/app_resources.go` and `server/application/application.go`, inspected read-only on 2026-10-19.

## Approved scope

Scripts, offline tests, experiment documentation, and one read-only GitHub Actions workflow. Preserve thesis/proposal/presentation, empirical data, dependency specifications and infrastructure. No local installs/downloads, actual cluster clients, live experiment or merge. CI may install the already-declared Python analysis requirements on its isolated GitHub runner; fixtures remain temporary and are not uploaded as research evidence.

## Tasks

- [x] Add tests for structured controller evidence, identity/group/namespace validation, unavailable/redacted Secret data, sanitized failures, explicit controller context/destination mapping, unsupported CLI rejection before injection, and retaining oracle restoration after a later controller-signal failure.
- [x] Implement the smallest shared Application-status reader and a scoped JSON resource reader. Only retrieve relevant OutOfSync/Missing resources; preserve empty/no-diff versus unavailable/error distinctions. Store only safe evidence paths and source labels.
- [x] Pin ArgoCD commands to `--argocd-context`. Extend the pilot target allowlist for GitOps with that context and expected destination server. Validate capability and Application destination before injection; keep formal/F restrictions and empty-default allowlists.
- [x] Exercise a real subprocess adapter backed by explicit fake executables through producer summary and analyzer, including successful GitOps restoration and Secret evidence unavailability. Do not use source-text tests or real clients.
- [x] Add `Offline Experiment Tests` for experiment-path PRs/pushes: Python 3.12, existing analysis requirements, denied real cluster clients, all three offline suites, Bash syntax, ShellCheck and Python compilation. Read-only token permissions, bounded job, no secrets or fixture upload.
- [x] Update current README/schema/plan status to distinguish completed offline functionality from pending live compatibility, permission, cluster identity/readiness and reset/batch/formal gates. Preserve historical audit findings as history, not current capability claims.
- [x] Independently run all offline suites and static checks and inspect the local diff. The push/PR update and remote CI observation are lead-owned and remain pending; no merge.
