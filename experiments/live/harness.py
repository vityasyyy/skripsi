#!/usr/bin/env python3
"""Automated sequential-arm InvenioRDM drift harness. Dry-run by default.

The harness never mutates a cluster unless `--live` is explicit. It targets the
single real InvenioRDM stack (`invenio-web`, `invenio-web-hpa`,
`invenio-app-config-<hash>`, `invenio-app-secrets`) and never the legacy NGINX
surrogate subjects.
"""

from __future__ import annotations

# Stable facade: constants, records, transport, sampling, scenario control, and
# timeline analysis are re-exported here so existing imports and tests keep
# working.
import argparse
import copy
import json
import os
import re
import secrets
import subprocess as subprocess  # patched through the harness namespace
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror  # noqa: F401 - patched through the harness namespace

if __package__:
    from . import contract as contract
else:  # direct script execution
    import contract as contract  # type: ignore[no-redef]

if __package__:
    from . import model as model
else:  # direct script execution
    import model as model  # type: ignore[no-redef]

if __package__:
    from . import sampling as sampling
else:  # direct script execution
    import sampling as sampling  # type: ignore[no-redef]

if __package__:
    from . import scenarios as scenarios
else:  # direct script execution
    import scenarios as scenarios  # type: ignore[no-redef]

if __package__:
    from . import timeline as timeline
else:  # direct script execution
    import timeline as timeline  # type: ignore[no-redef]

if __package__:
    from . import transport as transport
else:  # direct script execution
    import transport as transport  # type: ignore[no-redef]

if __package__:
    from . import convert as _convert
else:  # direct script execution
    import convert as _convert  # type: ignore[no-redef]

write_csv = _convert.write_csv

# Stable re-exports: the facade keeps the original harness namespace available.
ARMS = model.ARMS
SCENARIOS = model.SCENARIOS
DEFAULT_NAMESPACE = model.DEFAULT_NAMESPACE
DEFAULT_APP = model.DEFAULT_APP
APP_OF_APPS = model.APP_OF_APPS
ARGO_NAMESPACE = model.ARGO_NAMESPACE
WEB_DEPLOYMENT = model.WEB_DEPLOYMENT
WEB_HPA = model.WEB_HPA
WEB_SERVICE = model.WEB_SERVICE
SEALED_SECRET = model.SEALED_SECRET
CONFIG_PREFIX = model.CONFIG_PREFIX
DRIFT_ANNOTATION = model.DRIFT_ANNOTATION
CONFIG_KEY = model.CONFIG_KEY
RENDER_FORMAT = model.RENDER_FORMAT
Declaration = model.Declaration
DeclarationError = model.DeclarationError
CONFIG_DRIFT = model.CONFIG_DRIFT
MEMORY_LIMIT_DRIFT = model.MEMORY_LIMIT_DRIFT
MEMORY_LIMIT_DRIFT_FALLBACK = model.MEMORY_LIMIT_DRIFT_FALLBACK
_RESOURCE_QUANTITY_PATHS = model._RESOURCE_QUANTITY_PATHS
SEED_RECORD = model.SEED_RECORD
SEED_FILE = model.SEED_FILE
SEED_SIZE = model.SEED_SIZE
SEED_MD5 = model.SEED_MD5
SEED_SHA256 = model.SEED_SHA256
DEFAULT_INVENIO_URL = model.DEFAULT_INVENIO_URL
USER_AGENT = model.USER_AGENT
HTTP_RETRY_ATTEMPTS = model.HTTP_RETRY_ATTEMPTS
HTTP_RETRY_BACKOFF_SECONDS = model.HTTP_RETRY_BACKOFF_SECONDS
TRANSIENT_HTTP_STATUSES = model.TRANSIENT_HTTP_STATUSES
MISSING = model.MISSING
TIMING_CONVENTION = model.TIMING_CONVENTION
MAX_SAMPLE_END_AGE_SECONDS = model.MAX_SAMPLE_END_AGE_SECONDS
MAX_AGGREGATION_WINDOW_SECONDS = model.MAX_AGGREGATION_WINDOW_SECONDS
FUTURE_SAMPLE_TOLERANCE_SECONDS = model.FUTURE_SAMPLE_TOLERANCE_SECONDS
HarnessError = model.HarnessError
SafetyError = model.SafetyError
ArmStateError = model.ArmStateError
ArmRestoreError = model.ArmRestoreError
InjectionError = model.InjectionError
InstrumentationError = model.InstrumentationError
SeedVerificationError = model.SeedVerificationError
BaselineError = model.BaselineError
CaptureStopped = model.CaptureStopped
ReadStopped = model.ReadStopped
Point = model.Point
Clock = model.Clock
FakeClock = model.FakeClock
CommandResult = model.CommandResult
Observation = model.Observation
Contract = model.Contract
Injection = model.Injection
ImperativeRun = model.ImperativeRun
ArmEvidence = model.ArmEvidence
CleanupReport = model.CleanupReport
_canonical = model._canonical
_point_dict = model._point_dict
_short = model._short

validate_namespace = transport.validate_namespace
quarantine_namespace = transport.quarantine_namespace
load_token = transport.load_token
_CrossHostRedirectHandler = transport._CrossHostRedirectHandler
Http = transport.Http
verify_seed = transport.verify_seed
_quantity = transport._quantity
_quantity_nanocores = transport._quantity_nanocores
_quantity_bytes = transport._quantity_bytes
_duration_seconds = transport._duration_seconds
_timestamp_instant = transport._timestamp_instant
_timestamp = transport._timestamp
_command_bounds = transport._command_bounds
_point_bounds = transport._point_bounds
_attempt_bounds = transport._attempt_bounds
_read_bounds = transport._read_bounds
_node_name = transport._node_name
parse_node_metrics = transport.parse_node_metrics
Kubectl = transport.Kubectl
verify_one_stack = transport.verify_one_stack
urlrequest = transport.urlrequest

sanitize_metadata = sampling.sanitize_metadata
sanitize_object = sampling.sanitize_object
sanitize_application = sampling.sanitize_application
recovery_manifest = sampling.recovery_manifest
_container = sampling._container
_resource_fields = sampling._resource_fields
resource_id = sampling.resource_id
observation_from_objects = sampling.observation_from_objects
application_state = sampling.application_state
hpa_state = sampling.hpa_state
Snapshotter = sampling.Snapshotter
_observation_key = sampling._observation_key
Sampler = sampling.Sampler

build_contract = contract.build_contract
_same = contract._same
_normalized_value = contract._normalized_value
_field_matches = contract._field_matches
_resource_diffs = contract._resource_diffs
resource_results = contract.resource_results
score = contract.score
field_diffs = contract.field_diffs
hpa_settled = contract.hpa_settled
hpa_telemetry_valid = contract.hpa_telemetry_valid
hpa_changed = contract.hpa_changed
argo_signal = contract.argo_signal
load_declaration = contract.load_declaration
load_declaration_bytes = contract.load_declaration_bytes
_prepare_declaration = contract._prepare_declaration
_validate_declared_quantities = contract._validate_declared_quantities

_field = scenarios._field
_configmap_name = scenarios._configmap_name
_baseline_issues = scenarios._baseline_issues
baseline_gate = scenarios.baseline_gate
_readiness_record = scenarios._readiness_record
_raise_readiness = scenarios._raise_readiness
_instrumentation_record = scenarios._instrumentation_record
stabilize_baseline = scenarios.stabilize_baseline
ArmController = scenarios.ArmController
inject = scenarios.inject
repair = scenarios.repair
cleanup_g_annotation = scenarios.cleanup_g_annotation
cleanup_quarantine = scenarios.cleanup_quarantine
read_diff_evidence = scenarios.read_diff_evidence
planned_mutations = scenarios.planned_mutations

_metric_status = timeline._metric_status
_finite_mono = timeline._finite_mono
_validate_acquisition = timeline._validate_acquisition
_read = timeline._read
_read_eligible = timeline._read_eligible
_reads_eligible = timeline._reads_eligible
_read_completion = timeline._read_completion
_complete_match_completion = timeline._complete_match_completion
_diff_keys = timeline._diff_keys
_r1_keys = timeline._r1_keys
_hpa_keys = timeline._hpa_keys
_recovery_keys = timeline._recovery_keys
_post_injection = timeline._post_injection
_imperative_event_keys = timeline._imperative_event_keys
_evaluation_keys = timeline._evaluation_keys
_evaluation_evidence = timeline._evaluation_evidence
_recovered = timeline._recovered
analyze_timeline = timeline.analyze_timeline


def dry_run_row(
    run_id: str,
    arm: str,
    scenario: str,
    rep: int,
    namespace: str,
    app: str,
    args: argparse.Namespace,
) -> dict:
    """Build the offline dry-run row with no observations."""
    return {
        "schema_version": 2,
        "run_id": run_id,
        "synthetic": False,
        "timing_convention": TIMING_CONVENTION,
        "formal_execution_approved": False,
        "dry_run": True,
        "mutations_executed": 0,
        "env": arm,
        "arm": arm,
        "scenario": scenario,
        "rep": rep,
        "namespace": namespace,
        "app": app,
        "quarantine_namespace": quarantine_namespace(namespace),
        "analysis_group": (
            "hpa_control"
            if scenario == "A"
            else "visibility_boundary"
            if scenario == "F"
            else "managed_drift"
        ),
        "efficacy_eligible": scenario not in ("A", "F"),
        "status": "dry_run",
        "stop_reason": None,
        "injection_seconds": None,
        "detection_seconds": None,
        "evidence_seconds": None,
        "evidence_store_seconds": None,
        "recovery_seconds": None,
        "detection_status": "not_observed",
        "evidence_status": "not_observed",
        "recovery_status": "not_observed",
        "t_r_first_seconds": None,
        "t_r_confirmed_seconds": None,
        "recovery_confirmation": None,
        "detection_reads": [],
        "evidence_reads": [],
        "recovery_reads": [],
        "censor_seconds": None,
        "detection_controller": None,
        "recovery_controller": None,
        "detection_ref": None,
        "evidence_ref": None,
        "r1_baseline": None,
        "r1_first": None,
        "r1_last": None,
        "r1_baseline_details": None,
        "r1_first_details": None,
        "r1_last_details": None,
        "r1_baseline_reason": "dry_run",
        "r1_first_reason": "dry_run",
        "r1_last_reason": "dry_run",
        "t_d_utc": None,
        "t_d_mono": None,
        "t_e_utc": None,
        "t_e_mono": None,
        "t_e_store_utc": None,
        "t_e_store_mono": None,
        "t_r_utc": None,
        "t_r_mono": None,
        "t_r_first_utc": None,
        "t_r_first_mono": None,
        "t_r_confirmed_utc": None,
        "t_r_confirmed_mono": None,
        "window_completed": False,
        "window_end_utc": None,
        "window_end_mono": None,
        "kubectl_cmds": 0,
        "source_revision": getattr(args, "source_revision", None),
        "render_sha256": getattr(args, "render_sha256", None),
        "planned_mutations": planned_mutations(scenario),
        "safety": {
            "live": False,
            "namespace_allowed": True,
            "one_stack_required": True,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse harness CLI arguments and validate their bounds."""
    parser = argparse.ArgumentParser(description=__doc__)
    tokens = list(sys.argv[1:] if argv is None else argv)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--rep", type=int, required=True)
    parser.add_argument("--namespace")
    parser.add_argument("--app")
    parser.add_argument("--argocd-namespace", default=ARGO_NAMESPACE)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent / "runs"))
    parser.add_argument("--run-id")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-single-stack", action="store_true")
    parser.add_argument("--source-revision")
    parser.add_argument("--render-sha256")
    parser.add_argument("--render-file")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--imperative-interval", type=float, default=5.0)
    parser.add_argument("--baseline-timeout", type=float, default=120.0)
    parser.add_argument("--reset-timeout", type=float, default=180.0)
    parser.add_argument("--invenio-url", default=DEFAULT_INVENIO_URL)
    parser.add_argument("--seed-record", default=SEED_RECORD)
    parser.add_argument("--seed-file", default=SEED_FILE)
    parser.add_argument("--seed-size", type=int, default=SEED_SIZE)
    parser.add_argument("--seed-md5", default=SEED_MD5)
    parser.add_argument("--seed-sha256", default=SEED_SHA256)
    args = parser.parse_args(argv)
    args.namespace_explicit = any(
        token == "--namespace" or token.startswith("--namespace=") for token in tokens
    )
    args.app_explicit = any(token == "--app" or token.startswith("--app=") for token in tokens)
    args.namespace = args.namespace or DEFAULT_NAMESPACE
    args.app = args.app or DEFAULT_APP
    if args.rep < 1:
        parser.error("--rep must be >= 1")
    for name in (
        "timeout",
        "sample_interval",
        "imperative_interval",
        "baseline_timeout",
        "reset_timeout",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.source_revision and not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        parser.error("--source-revision must be 40 lowercase hex")
    if args.render_sha256 and not re.fullmatch(r"[0-9a-f]{64}", args.render_sha256):
        parser.error("--render-sha256 must be 64 lowercase hex")
    if args.run_id and not re.fullmatch(r"[A-Za-z0-9._-]+", args.run_id):
        parser.error("--run-id may only contain letters, digits, dot, dash, underscore")
    if args.run_id and len(args.run_id) > 63:
        parser.error("--run-id must be at most 63 characters for label values")
    return args


def validate_live_args(
    args: argparse.Namespace, environ: Mapping[str, str] | None = None
) -> dict | None:
    """Perform live preflight and return the verified context."""
    if not args.live:
        return None
    if not getattr(args, "namespace_explicit", False):
        raise SafetyError("--namespace must be explicit in live mode")
    if not getattr(args, "app_explicit", False):
        raise SafetyError("--app must be explicit in live mode")
    if not args.confirm_single_stack:
        raise SafetyError("--live requires --confirm-single-stack")
    validate_namespace(args.namespace)
    token = load_token(environ)
    if not args.render_sha256:
        raise SafetyError("--render-sha256 is required in live mode; freeze the render first")
    if not args.source_revision:
        raise SafetyError("--source-revision is required in live mode; freeze the revision first")
    if not args.render_file:
        raise SafetyError("--render-file is required in live mode; freeze the render bundle first")
    if "://" in args.render_file:
        raise SafetyError("--render-file must be a local file, not a URL")
    try:
        frozen = load_declaration(
            args.render_file, args.render_sha256, args.source_revision, args.namespace
        )
    except DeclarationError as error:
        raise SafetyError(f"invalid frozen render: {error}") from None
    http = Http(token, base_url=args.invenio_url)
    seed = verify_seed(
        http, args.seed_record, args.seed_file, args.seed_size, args.seed_md5, args.seed_sha256
    )
    return {"http": http, "seed": seed, "declaration": frozen}


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def ensure_new_run(args: argparse.Namespace, run_id: str) -> None:
    """Refuse to reuse an existing run id or evidence directory."""
    out = Path(args.out)
    jsonl = out / (run_id + ".jsonl")
    evidence_dir = out / run_id
    if jsonl.exists() or (evidence_dir.exists() and any(evidence_dir.iterdir())):
        raise SafetyError(f"refusing to overwrite existing run output {run_id}")


def write_outputs(row: dict, args: argparse.Namespace, evidence_dir: Path, evidence: dict) -> None:
    """Write the row JSONL/CSV and per-run evidence files."""
    run_id = row["run_id"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    jsonl = out / (run_id + ".jsonl")
    if jsonl.exists():
        raise SafetyError(f"refusing to overwrite existing run output {jsonl}")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    jsonl.write_text(json.dumps(row, sort_keys=True, default=str) + "\n")
    write_csv([row], out / (run_id + ".csv"))
    for name, payload in evidence.items():
        if name in ("samples", "commands"):
            with (evidence_dir / (name + ".jsonl")).open("w") as handle:
                for item in payload:
                    handle.write(json.dumps(item, sort_keys=True, default=str) + "\n")
        else:
            _write_json(evidence_dir / (name + ".json"), payload)


@dataclass
class _ObservationWindow:
    """Mutable state handed to and returned from the sampler observation loop."""

    injection: Injection | None = None
    samples: list = field(default_factory=list)
    imperative: ImperativeRun | None = None
    sampler_stop: dict | None = None
    evidence_at: Point | None = None
    evidence_store_at: Point | None = None
    evidence_ref: str | None = None


@dataclass
class _RunContext:
    """Mutable state shared by the run phases and the final row."""

    run_id: str
    evidence_dir: Path
    arm_controller: ArmController
    arm_evidence: ArmEvidence | None = None
    cleanup: CleanupReport | None = None
    injection: Injection | None = None
    timeline: dict | None = None
    contract: Contract | None = None
    baseline: Observation | None = None
    readiness_failures: list = field(default_factory=list)
    samples: list = field(default_factory=list)
    imperative: ImperativeRun | None = None
    collector_evidence_at: Point | None = None
    collector_evidence_store_at: Point | None = None
    collector_evidence_ref: str | None = None
    sampler: Sampler | None = None
    sampler_stop: dict | None = None
    restore_error: str | None = None
    postcondition: dict | None = None
    failure: Exception | None = None
    window_end: Point | None = None
    allow_cleanup: bool = False


class LiveRunner:
    """Own one live or dry run from preflight to evidence."""

    def __init__(
        self,
        args: argparse.Namespace,
        preflight: dict | None,
        kubectl: Kubectl,
        clock: Clock,
    ) -> None:
        self.args = args
        self.preflight = preflight
        self.kubectl = kubectl
        self.clock = clock
        self.quarantine = quarantine_namespace(args.namespace)
        self.collector_started: Point | None = None

    def _declaration(self) -> Declaration:
        frozen = (self.preflight or {}).get("declaration")
        if not isinstance(frozen, Declaration):
            raise SafetyError("live runner requires a validated frozen render declaration")
        if (
            frozen.source_revision != self.args.source_revision
            or frozen.render_sha256 != self.args.render_sha256
        ):
            raise SafetyError("frozen render identity does not match the live run arguments")
        if any(resource["namespace"] != self.args.namespace for resource in frozen.resources):
            raise SafetyError("frozen render namespace does not match --namespace")
        return frozen

    @staticmethod
    def _require_baseline_agreement(contract: Contract, baseline: Observation) -> None:
        diffs = field_diffs(contract, baseline)
        if not diffs:
            return
        first = diffs[0]
        if first.get("missing"):
            detail = (
                f"live baseline is missing {first['resource']}; the frozen declaration requires it"
            )
        else:
            detail = (
                "live baseline differs from the frozen declaration at "
                f"{first['resource']} {first['path']} "
                f"({len(diffs)} field(s))"
            )
        baseline.readiness_failures.append(
            _readiness_record(
                baseline,
                [{"code": "declaration_mismatch", "detail": detail, "retryable": False}],
                "declaration",
            )
        )
        error = BaselineError(detail)
        error.readiness_failures = baseline.readiness_failures
        raise error

    def run(self) -> int:
        args = self.args
        run_id = args.run_id or (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + f"-{args.arm}-{args.scenario}-r{args.rep}-"
            + secrets.token_hex(3)
        )
        evidence_dir = Path(args.out) / run_id
        ensure_new_run(args, run_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        context = _RunContext(
            run_id=run_id,
            evidence_dir=evidence_dir,
            arm_controller=ArmController(
                self.kubectl, app=args.app, argo_namespace=args.argocd_namespace
            ),
        )
        try:
            snapshotter = self._prepare(context)
            self._execute(context, snapshotter)
        except HarnessError as error:
            context.failure = error
            context.readiness_failures = list(
                getattr(error, "readiness_failures", context.readiness_failures)
            )
            context.injection = getattr(error, "injection", context.injection)
            if context.arm_evidence is None and context.arm_controller.original:
                context.arm_evidence = ArmEvidence(
                    arm=args.arm,
                    original={
                        name: copy.deepcopy(item["spec"])
                        for name, item in context.arm_controller.original.items()
                    },
                    applications={},
                    paused=True,
                )
        except Exception as error:
            context.failure = error
        finally:
            self._finalize(context)
        return self._report(context)

    def _prepare(self, context: _RunContext) -> Snapshotter:
        """Validate the frozen declaration and settle the live baseline."""
        args = self.args
        frozen = self._declaration()
        verify_one_stack(self.kubectl, args.namespace, args.app, args.argocd_namespace)
        context.allow_cleanup = True
        snapshotter = Snapshotter(
            self.kubectl,
            args.namespace,
            self.quarantine,
            self.clock,
            configmap_name=frozen.configmap_name,
            argo_namespace=args.argocd_namespace,
            app=args.app,
        )
        context.arm_evidence = context.arm_controller.activate(args.arm)
        context.baseline = stabilize_baseline(
            snapshotter,
            self.kubectl,
            args.arm,
            args.baseline_timeout,
            args.sample_interval,
            self.clock,
            app=args.app,
        )
        context.readiness_failures = list(context.baseline.readiness_failures)
        context.contract = build_contract(
            frozen, context.baseline, args.namespace, self.quarantine, app=args.app
        )
        self._require_baseline_agreement(context.contract, context.baseline)
        return snapshotter

    def _execute(self, context: _RunContext, snapshotter: Snapshotter) -> None:
        """Start the collector, inject, and sample until recovery or deadline."""
        args = self.args
        assert context.contract is not None
        assert context.baseline is not None
        sampler = Sampler(snapshotter.capture, self.clock, args.sample_interval, guarded=True)
        context.sampler = sampler
        self.collector_started = self.clock.now()
        sampler.start()
        if not sampler.wait_ready(timeout=10):
            raise InstrumentationError("collector did not produce an initial sample")
        if sampler.error:
            raise InstrumentationError(str(sampler.error))
        if not sampler.snapshot():
            raise InstrumentationError("collector produced no sample")
        window = _ObservationWindow()
        try:
            self._observe_until_recovery(
                context.contract,
                context.run_id,
                context.evidence_dir,
                sampler,
                context.baseline,
                window,
            )
        finally:
            context.injection = window.injection
            context.imperative = window.imperative
            context.samples = window.samples
            context.sampler_stop = window.sampler_stop
            context.collector_evidence_at = window.evidence_at
            context.collector_evidence_store_at = window.evidence_store_at
            context.collector_evidence_ref = window.evidence_ref
        if context.injection is not None:
            window_end = self.clock.now()
            context.window_end = window_end
            timeline = analyze_timeline(
                context.contract,
                context.samples,
                context.injection,
                args.arm,
                args.scenario,
                args.timeout,
                context.imperative,
                evidence_at=context.collector_evidence_at,
                provided_evidence_ref=context.collector_evidence_ref,
                app=args.app,
                baseline=context.baseline,
                window_end=window_end,
            )
            context.timeline = timeline
            if timeline is not None:
                timeline["window_completed"] = (
                    timeline["recovery_seconds"] is not None
                    or window_end.mono >= context.injection.started.mono + args.timeout
                )
                if (
                    timeline["recovery_seconds"] is None
                    and not timeline["window_completed"]
                    and context.failure is None
                ):
                    context.failure = InstrumentationError(
                        "observation window did not reach its deadline"
                    )
                if (
                    context.collector_evidence_store_at
                    and timeline.get("t_e") is not None
                    and not (args.arm == "imperative" and args.scenario in "BCDEFG")
                ):
                    timeline["t_e_store"] = context.collector_evidence_store_at
        if sampler.error is not None:
            raise InstrumentationError(str(sampler.error))
        if context.sampler_stop is not None and context.sampler_stop.get("in_flight"):
            raise InstrumentationError("collector did not join before evidence finalization")

    def _finalize(self, context: _RunContext) -> None:
        """Stop the collector, clean up, restore the arm, and check the reset."""
        args = self.args
        if context.sampler is not None and context.sampler_stop is None:
            context.sampler_stop = context.sampler.stop()
            context.samples = context.sampler.snapshot()
        g_annotation_owned = bool(
            args.scenario == "G"
            and context.injection is not None
            and any(
                command.argv[:2] == ["annotate", "SealedSecret"]
                for command in context.injection.commands
            )
        )
        try:
            context.cleanup = (
                cleanup_quarantine(self.kubectl, self.quarantine, owner=context.run_id)
                if context.allow_cleanup
                else CleanupReport(True, [], [])
            )
            if args.scenario == "G" and context.allow_cleanup and g_annotation_owned:
                annotation_cleanup = cleanup_g_annotation(self.kubectl, args.namespace)
                context.cleanup = CleanupReport(
                    ok=context.cleanup.ok and annotation_cleanup.ok,
                    results=context.cleanup.results + annotation_cleanup.results,
                    errors=context.cleanup.errors + annotation_cleanup.errors,
                )
        except Exception as error:
            context.cleanup = CleanupReport(
                ok=False, results=[], errors=[f"cleanup failed: {type(error).__name__}"]
            )
        try:
            context.arm_controller.restore()
        except Exception as error:
            context.restore_error = str(error)
        if context.contract is not None:
            for attempt in range(3):
                try:
                    snapshotter = Snapshotter(
                        self.kubectl,
                        args.namespace,
                        self.quarantine,
                        self.clock,
                        configmap_name=context.contract.configmap_name,
                        argo_namespace=args.argocd_namespace,
                        app=args.app,
                    )
                    context.postcondition = self._postcondition(
                        snapshotter, context.contract, args.scenario, args.arm
                    )
                    break
                except Exception as error:
                    if attempt == 2:
                        context.postcondition = {
                            "verified": False,
                            "error": f"{type(error).__name__}: {error}",
                        }
                    else:
                        time.sleep(1)

    def _report(self, context: _RunContext) -> int:
        """Build the row, persist evidence, and return the process exit code."""
        args = self.args
        row = self._row(
            context.run_id,
            args,
            context.contract,
            context.injection,
            context.timeline,
            context.failure,
            context.cleanup,
            context.restore_error,
            context.postcondition,
        )
        if context.sampler is not None and context.sampler_stop is not None:
            context.sampler_stop["partial_acquisition"] = copy.deepcopy(
                getattr(context.sampler, "stopped_capture", None)
            )
            context.sampler_stop["capture_stop_reason"] = getattr(
                context.sampler, "capture_stop_reason", None
            )
        self._write_evidence(
            args,
            context.evidence_dir,
            row=row,
            baseline=context.baseline,
            contract=context.contract,
            injection=context.injection,
            imperative=context.imperative,
            arm_evidence=context.arm_evidence,
            cleanup=context.cleanup,
            postcondition=context.postcondition,
            sampler_stop=context.sampler_stop,
            readiness_failures=context.readiness_failures,
            samples=context.samples,
        )
        print(
            json.dumps(
                {
                    "run_id": context.run_id,
                    "status": row["status"],
                    "jsonl": str(Path(args.out) / (context.run_id + ".jsonl")),
                    "csv": str(Path(args.out) / (context.run_id + ".csv")),
                },
                sort_keys=True,
            )
        )
        return (
            0
            if row["status"] in ("observed", "right_censored")
            and not (context.cleanup and not context.cleanup.ok)
            and not context.restore_error
            else 1
        )

    def _observe_until_recovery(
        self,
        contract: Contract,
        run_id: str,
        evidence_dir: Path,
        sampler: Sampler,
        baseline: Observation,
        window: _ObservationWindow,
    ) -> None:
        """Inject, repair, and sample until recovery or the frozen deadline."""
        args = self.args
        try:
            injection = inject(self.kubectl, contract, args.scenario, run_id, self.clock)
            window.injection = injection
            deadline = injection.started.mono + args.timeout
            sampler.deadline = deadline
            t0 = injection.started.mono
            next_repair = self.clock.now().mono
            while self.clock.now().mono < deadline:
                if sampler.error:
                    raise InstrumentationError(str(sampler.error))
                samples = sampler.snapshot()
                window.samples = samples
                now = self.clock.now().mono
                if now >= deadline:
                    break
                if samples and window.evidence_at is None:
                    latest = samples[-1]
                    if args.scenario == "A":
                        changed = hpa_changed(contract.baseline_hpa, latest.hpa)
                        keys = _hpa_keys()
                    else:
                        diffs = field_diffs(contract, latest)
                        changed = bool(diffs)
                        keys = sorted({diff["resource"] for diff in diffs})
                    evaluated = self.clock.now()
                    latest.evaluated_at = evaluated
                    latest.evaluated_signal = bool(changed)
                    latest.evaluated_reads = list(keys)
                    if changed and _reads_eligible(latest, keys, t0, deadline):
                        window.evidence_at = evaluated
                        if args.scenario == "A":
                            window.evidence_ref = "samples.jsonl"
                        else:
                            evidence_ref = "diff-" + _short(run_id) + "-collector.json"
                            window.evidence_ref = evidence_ref
                            try:
                                _write_json(
                                    evidence_dir / evidence_ref,
                                    {
                                        "run_id": run_id,
                                        "at": _point_dict(latest.at),
                                        "diffs": read_diff_evidence(contract, latest),
                                    },
                                )
                            except OSError as error:
                                raise InstrumentationError(
                                    f"collector evidence write failed: {type(error).__name__}"
                                ) from None
                            window.evidence_store_at = self.clock.now()
                if (
                    args.arm == "imperative"
                    and args.scenario in "BCDEFG"
                    and now >= next_repair
                    and samples
                ):
                    latest = samples[-1]
                    diffs = field_diffs(contract, latest)
                    keys = sorted({diff["resource"] for diff in diffs})
                    evaluated = self.clock.now()
                    if keys and _reads_eligible(latest, keys, t0, deadline):
                        if window.imperative is None:
                            window.imperative = ImperativeRun()
                        imperative = window.imperative
                        if imperative.detection_at is None:
                            imperative.detection_at = evaluated
                            imperative.detection_reads = keys
                            imperative.evidence_at = evaluated
                            imperative.evidence_reads = keys
                            evidence_ref = "diff-" + _short(run_id) + ".json"
                            imperative.evidence_ref = evidence_ref
                            try:
                                _write_json(
                                    evidence_dir / evidence_ref,
                                    {
                                        "run_id": run_id,
                                        "at": _point_dict(latest.at),
                                        "diffs": read_diff_evidence(contract, latest),
                                    },
                                )
                            except OSError as error:
                                raise InstrumentationError(
                                    f"imperative evidence write failed: {type(error).__name__}"
                                ) from None
                            imperative.evidence_store_at = self.clock.now()
                        commands = repair(self.kubectl, contract, latest, self.clock)
                        imperative.commands.extend(commands)
                        if any(not command.ok for command in commands):
                            imperative.failed = True
                    next_repair = now + args.imperative_interval
                if len(samples) >= 2:
                    candidate = analyze_timeline(
                        contract,
                        samples,
                        injection,
                        args.arm,
                        args.scenario,
                        args.timeout,
                        window.imperative,
                        evidence_at=window.evidence_at,
                        provided_evidence_ref=window.evidence_ref,
                        app=args.app,
                        baseline=baseline,
                    )
                    if candidate["recovery_seconds"] is not None:
                        break
                time.sleep(args.sample_interval)
        finally:
            window.sampler_stop = sampler.stop()
            window.samples = sampler.snapshot()

    def _write_evidence(
        self,
        args: argparse.Namespace,
        evidence_dir: Path,
        *,
        row: dict,
        baseline: Observation | None,
        contract: Contract | None,
        injection: Injection | None,
        imperative: ImperativeRun | None,
        arm_evidence: ArmEvidence | None,
        cleanup: CleanupReport | None,
        postcondition: dict | None,
        sampler_stop: dict | None,
        readiness_failures: list,
        samples: list,
    ) -> None:
        """Assemble the per-run evidence payload and write all artifacts."""
        evidence: dict[str, Any] = {
            "baseline": baseline if baseline else None,
            "contract": contract.as_dict() if contract else None,
            "injection": injection.as_dict() if injection else None,
            "imperative": imperative.as_dict() if imperative else None,
            "arm": arm_evidence.as_dict() if arm_evidence else None,
            "cleanup": cleanup.as_dict() if cleanup else None,
            "postcondition": postcondition,
            "sampler": sampler_stop,
            "row": row,
        }
        evidence["commands"] = (
            ([command.as_dict() for command in injection.commands] if injection else [])
            + ([command.as_dict() for command in imperative.commands] if imperative else [])
            + ([command.as_dict() for command in cleanup.results] if cleanup else [])
        )
        if baseline:
            evidence["baseline"] = {
                "at": _point_dict(baseline.at),
                "acquisition": baseline.acquisition,
                "readiness_failures": baseline.readiness_failures,
                "resources": {
                    key: {"fields": value.get("fields"), "manifest": value.get("manifest")}
                    for key, value in baseline.resources.items()
                },
                "argo": baseline.argo,
                "hpa": baseline.hpa,
                "pods": baseline.pods,
                "nodes": baseline.nodes,
                "extra_resources": baseline.extra_resources,
            }
        if readiness_failures:
            evidence["readiness"] = readiness_failures
        evidence["samples"] = [
            {
                "at": _point_dict(sample.at),
                "acquisition": copy.deepcopy(sample.acquisition),
                "evaluated_at": _point_dict(sample.evaluated_at),
                "evaluated_signal": sample.evaluated_signal,
                "evaluated_reads": list(sample.evaluated_reads),
                "resources": {key: value.get("fields") for key, value in sample.resources.items()},
                "extra_resources": sample.extra_resources,
                "argo": sample.argo,
                "hpa": sample.hpa,
            }
            for sample in samples
        ]
        write_outputs(row, args, evidence_dir, evidence)

    def _postcondition(
        self, snapshotter: Snapshotter, contract: Contract, scenario: str, arm: str
    ) -> dict:
        deadline = self.clock.now().mono + self.args.reset_timeout
        previous_ok = False
        while True:
            started = self.clock.now()
            observation = snapshotter.capture()
            observation.pods = self.kubectl.pods(self.args.namespace)
            finished = self.clock.now()
            acquisition = copy.deepcopy(observation.acquisition) or {}
            acquisition["postcondition"] = _point_bounds(started, finished)
            acquisition.setdefault("started", _point_dict(started))
            acquisition["started_utc"] = started.utc
            acquisition["started_mono"] = started.mono
            acquisition["finished"] = _point_dict(finished)
            acquisition["finished_utc"] = finished.utc
            acquisition["finished_mono"] = finished.mono
            observation.acquisition = acquisition
            ok = (
                score(contract, observation) == 100
                and not observation.extra_resources
                and bool(observation.pods)
                and all(
                    pod.get("phase") == "Running" and pod.get("ready") is True
                    for pod in observation.pods
                )
            )
            if scenario == "A":
                ok = ok and hpa_settled(observation.hpa)
            if arm == "gitops":
                for name in (APP_OF_APPS, self.args.app):
                    state = observation.argo.get(name) or {}
                    ok = ok and state.get("sync") == "Synced" and state.get("health") == "Healthy"
            if finished.mono > deadline:
                return {
                    "verified": False,
                    "reason": "deadline",
                    "deadline_mono": deadline,
                    "error": "postcondition read completed after the reset deadline",
                    "acquisition": acquisition,
                }
            if ok and previous_ok:
                return {
                    "verified": True,
                    "at": _point_dict(observation.at),
                    "acquisition": acquisition,
                }
            previous_ok = ok
            if self.clock.now().mono >= deadline:
                return {
                    "verified": False,
                    "reason": "deadline",
                    "deadline_mono": deadline,
                    "error": "two consecutive postcondition reads did not match",
                    "acquisition": acquisition,
                }
            time.sleep(self.args.sample_interval)

    def _row_identity(
        self, run_id: str, args: argparse.Namespace, contract: Contract | None
    ) -> dict:
        """Identity and provenance fields shared by every row."""
        base = {
            "schema_version": 2,
            "run_id": run_id,
            "synthetic": False,
            "timing_convention": TIMING_CONVENTION,
            "formal_execution_approved": False,
            "env": args.arm,
            "arm": args.arm,
            "scenario": args.scenario,
            "rep": args.rep,
            "namespace": args.namespace,
            "app": args.app,
            "quarantine_namespace": self.quarantine,
            "source_revision": getattr(args, "source_revision", None),
            "render_sha256": getattr(args, "render_sha256", None),
            "analysis_group": (
                "hpa_control"
                if args.scenario == "A"
                else "visibility_boundary"
                if args.scenario == "F"
                else "managed_drift"
            ),
            "efficacy_eligible": args.scenario not in ("A", "F"),
        }
        if contract:
            base["configmap_name"] = contract.configmap_name
            base["baseline_sha256"] = contract.baseline_sha256
        return base

    @staticmethod
    def _row_defaults(args: argparse.Namespace) -> dict:
        """Unobserved metric and timing defaults before timeline or injection."""
        return {
            "detection_seconds": None,
            "evidence_seconds": None,
            "evidence_store_seconds": None,
            "recovery_seconds": None,
            "detection_status": "not_observed",
            "evidence_status": "not_observed",
            "recovery_status": "not_observed",
            "t_r_first_seconds": None,
            "t_r_confirmed_seconds": None,
            "recovery_confirmation": None,
            "detection_reads": [],
            "evidence_reads": [],
            "recovery_reads": [],
            "censor_seconds": args.timeout,
            "detection_controller": None,
            "recovery_controller": None,
            "r1_baseline": None,
            "r1_first": None,
            "r1_last": None,
            "r1_baseline_details": None,
            "r1_first_details": None,
            "r1_last_details": None,
            "r1_baseline_reason": None,
            "r1_first_reason": None,
            "r1_last_reason": None,
            "kubectl_cmds": 0,
            "t0_utc": None,
            "t0_mono": None,
            "t_a_utc": None,
            "t_a_mono": None,
            "t_d_utc": None,
            "t_d_mono": None,
            "t_e_utc": None,
            "t_e_mono": None,
            "t_e_store_utc": None,
            "t_e_store_mono": None,
            "t_r_utc": None,
            "t_r_mono": None,
            "t_r_first_utc": None,
            "t_r_first_mono": None,
            "t_r_confirmed_utc": None,
            "t_r_confirmed_mono": None,
            "window_completed": False,
            "window_end_utc": None,
            "window_end_mono": None,
            "max_sample_gap_seconds": None,
            "observation_end_utc": None,
            "observation_end_mono": None,
        }

    def _row_operation_status(
        self,
        restore_error: str | None,
        cleanup: CleanupReport | None,
        postcondition: dict | None,
    ) -> dict:
        """Restore, cleanup, postcondition, and collector provenance fields."""
        return {
            "arm_restore_status": "failed" if restore_error else "restored",
            "arm_restore_error": restore_error,
            "cleanup_status": "failed" if cleanup and not cleanup.ok else "ok",
            "cleanup_errors": cleanup.errors if cleanup else [],
            "postcondition": postcondition,
            "collector_started_utc": (
                self.collector_started.utc if self.collector_started else None
            ),
            "collector_started_mono": (
                self.collector_started.mono if self.collector_started else None
            ),
        }

    @staticmethod
    def _apply_timeline(base: dict, timeline: dict) -> None:
        """Copy the timeline fields and point aliases into the row."""
        for key in (
            "analysis_group",
            "efficacy_eligible",
            "stop_reason",
            "injection_seconds",
            "detection_seconds",
            "evidence_seconds",
            "recovery_seconds",
            "detection_status",
            "evidence_status",
            "recovery_status",
            "detection_controller",
            "recovery_controller",
            "detection_ref",
            "evidence_ref",
            "detection_reads",
            "evidence_reads",
            "recovery_reads",
            "t_r_first_seconds",
            "t_r_confirmed_seconds",
            "recovery_confirmation",
            "r1_baseline_reason",
            "r1_first_reason",
            "r1_last_reason",
            "window_completed",
            "r1_baseline",
            "r1_first",
            "r1_last",
            "kubectl_cmds",
            "r1_baseline_details",
            "r1_first_details",
            "r1_last_details",
            "max_sample_gap_seconds",
        ):
            base[key] = timeline[key]
        for key in (
            "t_d",
            "t_e",
            "t_e_store",
            "t_r",
            "t_r_first",
            "t_r_confirmed",
            "window_end",
        ):
            point = timeline[key]
            base[key + "_utc"] = point.utc if point else None
            base[key + "_mono"] = point.mono if point else None
        if timeline.get("t_e_store") is not None:
            base["t_e_store_utc"] = timeline["t_e_store"].utc
            base["t_e_store_mono"] = timeline["t_e_store"].mono
            base["evidence_store_seconds"] = timeline["t_e_store"].mono - timeline["t0"].mono
        observation_end = timeline.get("observation_end")
        base["observation_end_utc"] = observation_end.utc if observation_end else None
        base["observation_end_mono"] = observation_end.mono if observation_end else None

    @staticmethod
    def _apply_injection(base: dict, injection: Injection) -> None:
        """Copy injection start/acknowledgement and its serialized evidence."""
        base.update(
            {
                "t0_utc": injection.started.utc,
                "t0_mono": injection.started.mono,
                "t_a_utc": injection.acknowledged.utc,
                "t_a_mono": injection.acknowledged.mono,
                "injection": injection.as_dict(),
            }
        )

    @staticmethod
    def _apply_outcome(
        base: dict,
        failure: Exception | None,
        restore_error: str | None,
        cleanup: CleanupReport | None,
        postcondition: dict | None,
        timeline: dict | None,
    ) -> None:
        """Resolve the row status from the run outcome."""
        if failure:
            base["status"] = (
                "arm_state_mismatch"
                if isinstance(failure, ArmStateError)
                else "invalid_injection"
                if isinstance(failure, InjectionError)
                else "instrumentation_failure"
                if isinstance(failure, InstrumentationError)
                else "baseline_failure"
                if isinstance(failure, BaselineError)
                else "safety_refusal"
                if isinstance(failure, SafetyError)
                else "failure"
            )
            base["error"] = str(failure)
        elif timeline is None:
            base["status"] = "failure"
        else:
            base["status"] = timeline["status"]
        if restore_error:
            base["status"] = "arm_restore_failure"
        if cleanup and not cleanup.ok:
            base["cleanup_status"] = "failed"
        if (
            postcondition
            and not postcondition.get("verified")
            and base["status"] in ("observed", "right_censored")
        ):
            base["status"] = "reset_failure"

    def _row(
        self,
        run_id: str,
        args: argparse.Namespace,
        contract: Contract | None,
        injection: Injection | None,
        timeline: dict | None,
        failure: Exception | None,
        cleanup: CleanupReport | None,
        restore_error: str | None,
        postcondition: dict | None,
    ) -> dict:
        """Assemble one analysis row from identity, timeline, and outcome."""
        base = self._row_identity(run_id, args, contract)
        base.update(self._row_defaults(args))
        base.update(self._row_operation_status(restore_error, cleanup, postcondition))
        if timeline:
            self._apply_timeline(base, timeline)
        if injection:
            self._apply_injection(base, injection)
        self._apply_outcome(base, failure, restore_error, cleanup, postcondition, timeline)
        return base


def _run_dry(args: argparse.Namespace) -> int:
    run_id = args.run_id or (
        "dryrun-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + secrets.token_hex(3)
    )
    ensure_new_run(args, run_id)
    row = dry_run_row(run_id, args.arm, args.scenario, args.rep, args.namespace, args.app, args)
    evidence_dir = Path(args.out) / run_id
    write_outputs(row, args, evidence_dir, {"row": row})
    print(
        json.dumps(
            {
                "run_id": run_id,
                "status": "dry_run",
                "jsonl": str(Path(args.out) / (run_id + ".jsonl")),
                "csv": str(Path(args.out) / (run_id + ".csv")),
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint with the documented exit-code mapping."""
    try:
        args = parse_args(argv)
        validate_namespace(args.namespace)
        if not args.live:
            return _run_dry(args)
        preflight = validate_live_args(args, os.environ)
        clock = Clock()
        return LiveRunner(args, preflight, Kubectl(clock), clock).run()
    except SafetyError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    except SeedVerificationError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 3
    except HarnessError as error:
        print(f"failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - executable guard
    sys.exit(main())
