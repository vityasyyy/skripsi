"""Baseline stabilization, drift injection, repair, and cleanup."""

from __future__ import annotations

import copy
import math
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, NoReturn, cast

if __package__:
    from . import contract as _contract
else:  # direct script execution
    import contract as _contract  # type: ignore[no-redef]

if __package__:
    from . import model as _model
else:  # direct script execution
    import model as _model  # type: ignore[no-redef]

if __package__:
    from . import sampling as _sampling
else:  # direct script execution
    import sampling as _sampling  # type: ignore[no-redef]

if __package__:
    from . import transport as _transport
else:  # direct script execution
    import transport as _transport  # type: ignore[no-redef]

APP_OF_APPS = _model.APP_OF_APPS
ARGO_NAMESPACE = _model.ARGO_NAMESPACE
ARMS = _model.ARMS
CONFIG_DRIFT = _model.CONFIG_DRIFT
CONFIG_KEY = _model.CONFIG_KEY
CONFIG_PREFIX = _model.CONFIG_PREFIX
DEFAULT_APP = _model.DEFAULT_APP
DRIFT_ANNOTATION = _model.DRIFT_ANNOTATION
FUTURE_SAMPLE_TOLERANCE_SECONDS = _model.FUTURE_SAMPLE_TOLERANCE_SECONDS
MAX_AGGREGATION_WINDOW_SECONDS = _model.MAX_AGGREGATION_WINDOW_SECONDS
MAX_SAMPLE_END_AGE_SECONDS = _model.MAX_SAMPLE_END_AGE_SECONDS
MEMORY_LIMIT_DRIFT = _model.MEMORY_LIMIT_DRIFT
MEMORY_LIMIT_DRIFT_FALLBACK = _model.MEMORY_LIMIT_DRIFT_FALLBACK
SCENARIOS = _model.SCENARIOS
SEALED_SECRET = _model.SEALED_SECRET
WEB_DEPLOYMENT = _model.WEB_DEPLOYMENT
WEB_SERVICE = _model.WEB_SERVICE
ArmEvidence = _model.ArmEvidence
ArmRestoreError = _model.ArmRestoreError
ArmStateError = _model.ArmStateError
BaselineError = _model.BaselineError
CleanupReport = _model.CleanupReport
Clock = _model.Clock
Contract = _model.Contract
HarnessError = _model.HarnessError
Injection = _model.Injection
InjectionError = _model.InjectionError
InstrumentationError = _model.InstrumentationError
Observation = _model.Observation
Point = _model.Point
SafetyError = _model.SafetyError
_point_dict = _model._point_dict
_short = _model._short

Snapshotter = _sampling.Snapshotter
_container = _sampling._container
_observation_key = _sampling._observation_key
recovery_manifest = _sampling.recovery_manifest
sanitize_application = _sampling.sanitize_application

_field_matches = _contract._field_matches
field_diffs = _contract.field_diffs
hpa_settled = _contract.hpa_settled
hpa_telemetry_valid = _contract.hpa_telemetry_valid

Kubectl = _transport.Kubectl
_point_bounds = _transport._point_bounds
_timestamp_instant = _transport._timestamp_instant
validate_namespace = _transport.validate_namespace


def _baseline_issues(observation: Observation, arm: str, app: str = DEFAULT_APP) -> list:
    issues = []

    def add(code: str, detail: str, retryable: bool = False) -> None:
        issues.append({"code": code, "detail": detail, "retryable": retryable})

    if not any(key.startswith("ConfigMap/" + CONFIG_PREFIX) for key in observation.resources):
        add("missing_configmap", "generated invenio-app-config ConfigMap is missing")
    if "Deployment/" + WEB_DEPLOYMENT not in observation.resources:
        add("missing_deployment", "invenio-web Deployment is missing")
    if "SealedSecret/" + SEALED_SECRET not in observation.resources:
        add("missing_sealed_secret", "invenio-app-secrets SealedSecret is missing")
    else:
        sealed = observation.resources["SealedSecret/" + SEALED_SECRET]
        if sealed["fields"].get("/metadata/annotations/" + DRIFT_ANNOTATION) is not None:
            add("contamination", "drift annotation is already present on SealedSecret")
    if "Service/" + WEB_SERVICE not in observation.resources:
        add("missing_service", "invenio-web Service is missing")
    if not isinstance(observation.hpa, dict):
        add("missing_hpa", "invenio-web-hpa is missing")
    else:
        if observation.hpa.get("target") != "Deployment/" + WEB_DEPLOYMENT:
            add("hpa_target", "HPA does not target invenio-web")
        elif not hpa_telemetry_valid(observation.hpa):
            raise InstrumentationError("HPA telemetry is malformed")
        elif not hpa_settled(observation.hpa):
            add("hpa_settling", "HPA is not settled at baseline", retryable=True)
    if observation.extra_resources:
        add("quarantine_preexisting", "quarantine resources exist before the run")
    if not observation.pods:
        add("pod_readiness", "no pods observed", retryable=True)
    for pod in observation.pods:
        if not isinstance(pod, dict):
            raise InstrumentationError("pod telemetry is malformed")
        if pod.get("phase") != "Running" or pod.get("ready") is not True:
            add("pod_readiness", f"pod {pod.get('name')} is not Running and Ready", retryable=True)
    if not observation.nodes:
        add("missing_node_metrics", "no node metrics observed")
    evaluation = None
    if observation.nodes:
        evaluation = _timestamp_instant(observation.at.utc, "observation timestamp")
    for node in observation.nodes:
        if not isinstance(node, dict):
            raise InstrumentationError("node telemetry is malformed")
        name = node.get("name")
        for metric in ("cpu_percent", "memory_percent"):
            value = cast(float, node.get(metric))
            finite = type(value) is int or (type(value) is float and math.isfinite(value))
            if not finite or value < 0:
                raise InstrumentationError(f"node {name} {metric} is not a finite percentage")
            if value >= 70:
                add("capacity", f"node {name} {metric} >= 70%", retryable=True)
        timestamp = _timestamp_instant(
            node.get("metrics_timestamp"), f"node {name} metrics timestamp"
        )
        age = (cast(datetime, evaluation) - timestamp).total_seconds()
        if age > MAX_SAMPLE_END_AGE_SECONDS:
            add(
                "stale_metrics",
                f"node {name} metrics sample is {age:.3f}s old "
                f"(limit {MAX_SAMPLE_END_AGE_SECONDS:.1f}s)",
                retryable=True,
            )
        elif age < -FUTURE_SAMPLE_TOLERANCE_SECONDS:
            add(
                "clock_anomaly",
                f"node {name} metrics sample is {-age:.3f}s in the future "
                f"(tolerance {FUTURE_SAMPLE_TOLERANCE_SECONDS:.1f}s)",
            )
        window = cast(float, node.get("metrics_window_seconds"))
        if type(window) not in (int, float) or not math.isfinite(window) or window <= 0:
            raise InstrumentationError(
                f"node {name} metrics window is not a positive finite duration"
            )
        if window > MAX_AGGREGATION_WINDOW_SECONDS:
            add(
                "long_window",
                f"node {name} metrics window is {window:.3f}s "
                f"(limit {MAX_AGGREGATION_WINDOW_SECONDS:.1f}s)",
                retryable=True,
            )
    if arm == "gitops":
        for name in (APP_OF_APPS, app):
            state = observation.argo.get(name) or {}
            if state.get("sync") != "Synced" or state.get("health") != "Healthy":
                add("argo_state", f"Argo Application {name} is not Synced/Healthy")
    return issues


def baseline_gate(observation: Observation, arm: str, app: str = DEFAULT_APP) -> None:
    """Raise when an observation is not a clean settled baseline."""
    issues = _baseline_issues(observation, arm, app)
    if issues:
        fatal = [issue for issue in issues if not issue["retryable"]]
        raise BaselineError((fatal or issues)[0]["detail"])


def _readiness_record(observation: Observation, issues: list, kind: str) -> dict:
    return {
        "kind": kind,
        "at": _point_dict(observation.at),
        "acquisition": copy.deepcopy(observation.acquisition),
        "reason": issues[0]["code"],
        "detail": issues[0]["detail"],
        "reasons": copy.deepcopy(issues),
        "pods": copy.deepcopy(observation.pods),
        "nodes": copy.deepcopy(observation.nodes),
        "hpa": copy.deepcopy(observation.hpa),
        "argo": copy.deepcopy(observation.argo),
        "extra_resources": copy.deepcopy(observation.extra_resources),
    }


def _raise_readiness(error: HarnessError, failures: list) -> NoReturn:
    error.readiness_failures = failures
    raise error


def _instrumentation_record(
    error: HarnessError,
    started: Point,
    finished: Point,
    observation: Observation | None = None,
) -> dict:
    record = {
        "kind": "instrumentation_failure",
        "at": _point_dict(started),
        "acquisition": {"snapshot": _point_bounds(started, finished)},
        "reason": "instrumentation_failure",
        "detail": str(error),
        "reasons": [{"code": "instrumentation_failure", "detail": str(error), "retryable": False}],
        "pods": [],
        "nodes": [],
        "hpa": None,
        "argo": {},
        "extra_resources": [],
    }
    if observation is not None:
        record.update(
            {
                "at": _point_dict(observation.at),
                "pods": copy.deepcopy(observation.pods),
                "nodes": copy.deepcopy(observation.nodes),
                "hpa": copy.deepcopy(observation.hpa),
                "argo": copy.deepcopy(observation.argo),
                "extra_resources": copy.deepcopy(observation.extra_resources),
            }
        )
        acquisition: dict | None = copy.deepcopy(observation.acquisition)
        if acquisition:
            record["acquisition"] = acquisition
    else:
        acquisition = getattr(error, "acquisition", None)
        if isinstance(acquisition, dict) and acquisition:
            record["acquisition"] = copy.deepcopy(acquisition)
    return record


def stabilize_baseline(
    snapshotter: Snapshotter,
    kubectl: Kubectl,
    arm: str,
    timeout: float,
    interval: float,
    clock: Clock,
    sleep: Callable[[float], None] = time.sleep,
    app: str = DEFAULT_APP,
) -> Observation:
    """Sample until two identical clean observations settle."""
    deadline = clock.now().mono + timeout
    previous_key = None
    failures: list[dict] = []
    attempted = False
    while True:
        if attempted and clock.now().mono >= deadline:
            _raise_readiness(
                BaselineError(f"baseline did not stabilize within {timeout}s"), failures
            )
        attempted = True
        started = clock.now()
        observation = None
        pods_started = None
        nodes_started = None
        try:
            observation = snapshotter.capture()
            captured = clock.now()
            acquisition = copy.deepcopy(observation.acquisition) or {}
            acquisition["snapshot"] = _point_bounds(started, captured)
            acquisition.setdefault("started", _point_dict(started))
            acquisition.setdefault("finished", _point_dict(captured))
            acquisition.setdefault("reads", {})
            observation.acquisition = acquisition
            pods_started = clock.now()
            observation.pods = kubectl.pods(snapshotter.namespace)
            pods_finished = clock.now()
            observation.acquisition["pods"] = _point_bounds(pods_started, pods_finished)
            nodes_started = clock.now()
            observation.nodes = kubectl.top_nodes()
            nodes_finished = clock.now()
            observation.acquisition["nodes"] = _point_bounds(nodes_started, nodes_finished)
            issues = _baseline_issues(observation, arm, app)
        except InstrumentationError as error:
            finished = clock.now()
            if observation is not None:
                if pods_started is not None and "pods" not in observation.acquisition:
                    observation.acquisition["pods"] = _point_bounds(pods_started, finished)
                elif nodes_started is not None and "nodes" not in observation.acquisition:
                    observation.acquisition["nodes"] = _point_bounds(nodes_started, finished)
            failures.append(_instrumentation_record(error, started, finished, observation))
            _raise_readiness(error, failures)
        now = clock.now().mono
        if issues:
            previous_key = None
            failures.append(_readiness_record(observation, issues, "gate"))
            fatal = [issue for issue in issues if not issue["retryable"]]
            if fatal:
                _raise_readiness(BaselineError(fatal[0]["detail"]), failures)
            if now >= deadline:
                _raise_readiness(
                    BaselineError(
                        f"baseline not ready within {timeout}s: "
                        + "; ".join(issue["detail"] for issue in issues)
                    ),
                    failures,
                )
            sleep(min(interval, deadline - now))
            continue
        key = _observation_key(observation)
        if now >= deadline:
            failures.append(
                _readiness_record(
                    observation,
                    [
                        {
                            "code": "deadline",
                            "detail": "baseline read crossed the settling deadline",
                            "retryable": True,
                        }
                    ],
                    "deadline",
                )
            )
            _raise_readiness(
                BaselineError(f"baseline did not stabilize within {timeout}s"), failures
            )
        if previous_key == key:
            observation.readiness_failures = failures
            return observation
        if previous_key is not None:
            failures.append(
                _readiness_record(
                    observation,
                    [
                        {
                            "code": "unmatched_read",
                            "detail": "baseline read did not match the previous read",
                            "retryable": True,
                        }
                    ],
                    "unmatched",
                )
            )
        previous_key = key
        sleep(min(interval, deadline - now))


class ArmController:
    """Pause and restore Argo automation for the imperative arm."""

    def __init__(
        self,
        kubectl: Kubectl,
        app: str = DEFAULT_APP,
        apps_app: str = APP_OF_APPS,
        argo_namespace: str = ARGO_NAMESPACE,
    ) -> None:
        self.kubectl = kubectl
        self.app = app
        self.apps_app = apps_app
        self.argo_namespace = argo_namespace
        self.original: dict | None = None

    def get_app(self, name: str) -> dict:
        app = self.kubectl.get("Application", name, self.argo_namespace)
        if app is None:
            raise ArmStateError(f"Argo Application {name} is missing")
        return app

    @staticmethod
    def automated(app: dict) -> object:
        return ((app.get("spec") or {}).get("syncPolicy") or {}).get("automated")

    def enabled(self, app: dict) -> bool:
        automated = self.automated(app)
        return isinstance(automated, dict) and automated.get("selfHeal") is True

    def activate(self, arm: str) -> ArmEvidence:
        if arm not in ARMS:
            raise SafetyError(f"unknown arm {arm!r}")
        apps = {name: self.get_app(name) for name in (self.apps_app, self.app)}
        if arm == "gitops":
            for name, app in apps.items():
                if not self.enabled(app):
                    raise ArmStateError(f"{name} does not have automated sync/selfHeal enabled")
            return ArmEvidence(
                arm=arm,
                original={},
                applications={name: sanitize_application(app) for name, app in apps.items()},
                paused=False,
            )
        for name, app in apps.items():
            if not self.enabled(app):
                raise ArmStateError(f"{name} is not enabled; refusing to stack arm state")
        self.original = {
            name: {
                "spec": sanitize_application(app)["spec"],
                "automated": copy.deepcopy(self.automated(app)),
            }
            for name, app in apps.items()
        }
        try:
            for name in (self.apps_app, self.app):
                result = self.kubectl.patch(
                    "Application",
                    name,
                    self.argo_namespace,
                    {"spec": {"syncPolicy": {"automated": None}}},
                    "merge",
                )
                if not result.ok:
                    raise ArmStateError(f"failed to pause {name}: {result.stderr.strip()[:200]}")
                current = self.get_app(name)
                if self.automated(current) is not None:
                    raise ArmStateError(f"{name} is still auto-syncing")
        except Exception:
            try:
                self.restore()
            except ArmRestoreError as error:
                raise ArmRestoreError(f"pause failed and restore failed: {error}") from None
            raise
        current = {name: self.get_app(name) for name in (self.apps_app, self.app)}
        return ArmEvidence(
            arm=arm,
            original={name: copy.deepcopy(item["spec"]) for name, item in self.original.items()},
            applications={name: sanitize_application(app) for name, app in current.items()},
            paused=True,
        )

    def restore(self) -> bool | None:
        if not self.original:
            return None
        errors = []
        for name in (self.app, self.apps_app):
            patch = {
                "spec": {
                    "syncPolicy": {"automated": copy.deepcopy(self.original[name]["automated"])}
                }
            }
            result = self.kubectl.patch("Application", name, self.argo_namespace, patch, "merge")
            if not result.ok:
                errors.append(f"{name}: {result.stderr.strip()[:200]}")
                continue
            current = self.get_app(name)
            if self.automated(current) != self.original[name]["automated"]:
                errors.append(f"{name}: observed state does not match original")
        if errors:
            raise ArmRestoreError("; ".join(errors))
        self.original = None
        return True


def _field(contract: Contract, resource_id_value: str, path: str) -> Any:
    resource = next((item for item in contract.resources if item["id"] == resource_id_value), None)
    if resource is None:
        raise InjectionError(f"baseline resource {resource_id_value} is missing")
    if path not in resource["fields"]:
        raise InjectionError(f"baseline field {path} is missing")
    return resource["fields"][path]


def _configmap_name(contract: Contract) -> str:
    if not contract.configmap_name:
        raise InjectionError("generated invenio-app-config ConfigMap is missing")
    return contract.configmap_name


def inject(
    kubectl: Kubectl, contract: Contract, scenario: str, run_id: str, clock: Clock
) -> Injection:
    """Apply exactly one scenario drift and verify that it changed."""
    if scenario not in SCENARIOS:
        raise SafetyError(f"unknown scenario {scenario!r}")
    started = clock.now()
    short = _short(run_id)
    commands = []
    changed = []
    expected_path: str | None = None
    expected_value: Any = None
    expected_baseline: Any = None
    target: Any = None
    effect = "value_changed"
    try:
        if scenario == "A":
            baseline_replicas = (contract.baseline_hpa or {}).get("deployment_spec_replicas")
            if type(baseline_replicas) is not int:
                raise InjectionError("baseline HPA did not retain the observed replicas")
            minimum = (contract.baseline_hpa or {}).get("min") or 2
            target = max(1, int(minimum) - 1) if int(minimum) > 1 else int(minimum) + 1
            if target == baseline_replicas:
                candidates = (max(1, int(minimum) - 1), int(minimum) + 1)
                target = next(value for value in candidates if value != baseline_replicas)
            commands.append(
                kubectl.patch(
                    "Deployment",
                    WEB_DEPLOYMENT,
                    contract.namespace,
                    {"spec": {"replicas": target}},
                    "merge",
                )
            )
            expected_path = "/spec/replicas"
            expected_value = target
            expected_baseline = baseline_replicas
        elif scenario == "B":
            image = _field(
                contract, "Deployment/" + WEB_DEPLOYMENT, "/spec/template/spec/containers/web/image"
            )
            repository = image.split("@")[0]
            if ":" in repository.rsplit("/", 1)[-1]:
                repository = repository.rsplit(":", 1)[0]
            target = repository + ":drift-" + short
            if target == image:
                raise InjectionError("drift image is identical to the declared image")
            commands.append(
                kubectl.patch(
                    "Deployment",
                    WEB_DEPLOYMENT,
                    contract.namespace,
                    {
                        "spec": {
                            "template": {"spec": {"containers": [{"name": "web", "image": target}]}}
                        }
                    },
                    "strategic",
                )
            )
            expected_path = "/spec/template/spec/containers/web/image"
            expected_value = target
            expected_baseline = image
        elif scenario == "C":
            name = _configmap_name(contract)
            key = CONFIG_KEY
            expected_baseline = _field(contract, "ConfigMap/" + name, "/data/" + key)
            target = CONFIG_DRIFT + "-" + short
            if target == expected_baseline:
                raise InjectionError("drift ConfigMap value is identical to the declared value")
            commands.append(
                kubectl.patch(
                    "ConfigMap", name, contract.namespace, {"data": {key: target}}, "merge"
                )
            )
            expected_path = "/data/" + key
            expected_value = target
        elif scenario == "D":
            commands.append(
                kubectl.delete("Deployment", WEB_DEPLOYMENT, contract.namespace, wait=True)
            )
            expected_path = "/metadata/name"
            expected_baseline = "present"
            effect = "deleted"
        elif scenario == "E":
            path = "/spec/template/spec/containers/web/resources/limits/memory"
            baseline = _field(contract, "Deployment/" + WEB_DEPLOYMENT, path)
            target = next(
                (
                    candidate
                    for candidate in (MEMORY_LIMIT_DRIFT, MEMORY_LIMIT_DRIFT_FALLBACK)
                    if not _field_matches(path, baseline, candidate)
                ),
                None,
            )
            if target is None:  # pragma: no cover - the two drift limits are distinct
                raise InjectionError(
                    "no distinct memory limit drift quantity is available"
                )  # pragma: no cover
            commands.append(
                kubectl.patch(
                    "Deployment",
                    WEB_DEPLOYMENT,
                    contract.namespace,
                    {
                        "spec": {
                            "template": {
                                "spec": {
                                    "containers": [
                                        {"name": "web", "resources": {"limits": {"memory": target}}}
                                    ]
                                }
                            }
                        }
                    },
                    "strategic",
                )
            )
            expected_path = path
            expected_value = target
            expected_baseline = baseline
        elif scenario == "F":
            path = "/spec/ports/0/targetPort"
            port = _field(contract, "Service/" + WEB_SERVICE, "/spec/ports/0/port")
            expected_baseline = _field(contract, "Service/" + WEB_SERVICE, path)
            expected_value = (
                expected_baseline % 65535 + 1 if type(expected_baseline) is int else 65535
            )
            if _field_matches(
                path, expected_baseline, expected_value
            ):  # pragma: no cover - derived value differs
                raise InjectionError(
                    "no distinct Service targetPort drift value is available"
                )  # pragma: no cover
            commands.append(
                kubectl.patch(
                    "Service",
                    WEB_SERVICE,
                    contract.namespace,
                    {"spec": {"ports": [{"port": port, "targetPort": expected_value}]}},
                    "strategic",
                )
            )
            expected_path = path
        elif scenario == "G":  # pragma: no branch - final scenario alternative
            target = "scenario-g-" + short
            commands.append(
                kubectl.annotate(
                    "SealedSecret", SEALED_SECRET, contract.namespace, DRIFT_ANNOTATION, target
                )
            )
            expected_path = "/metadata/annotations/" + DRIFT_ANNOTATION
            expected_value = target
            expected_baseline = None
    except HarnessError:
        raise
    except Exception as error:
        raise InjectionError(f"injection command failed: {type(error).__name__}") from None

    acknowledged = clock.now()
    failed = next((command for command in commands if not command.ok), None)
    if failed is not None:
        mutation_error = InjectionError(f"kubectl mutation failed with exit {failed.returncode}")
        mutation_error.injection = Injection(
            started=started,
            acknowledged=acknowledged,
            verified=None,
            accepted=False,
            changed=[],
            commands=commands,
            error=str(mutation_error),
        )
        raise mutation_error

    try:
        if scenario == "A":
            observed = kubectl.get("Deployment", WEB_DEPLOYMENT, contract.namespace)
            actual = (observed or {}).get("spec", {}).get("replicas")
            if actual != expected_value:
                raise InjectionError("/spec/replicas did not change")
            changed.append(
                {
                    "resource": "Deployment/" + WEB_DEPLOYMENT,
                    "path": expected_path,
                    "effect": effect,
                    "matches_desired": False,
                    "expected": expected_baseline,
                    "actual": actual,
                }
            )
        elif scenario == "B":
            observed = kubectl.get("Deployment", WEB_DEPLOYMENT, contract.namespace)
            container = _container(observed or {})
            actual = container.get("image") if container else None
            if actual != expected_value:
                raise InjectionError("/spec/template/spec/containers/web/image did not change")
            changed.append(
                {
                    "resource": "Deployment/" + WEB_DEPLOYMENT,
                    "path": expected_path,
                    "effect": effect,
                    "matches_desired": False,
                    "expected": expected_baseline,
                    "actual": actual,
                }
            )
        elif scenario == "C":
            name = _configmap_name(contract)
            observed = kubectl.get("ConfigMap", name, contract.namespace)
            actual = (observed or {}).get("data", {}).get(CONFIG_KEY)
            if actual != expected_value:
                raise InjectionError("/data/" + CONFIG_KEY + " did not change")
            changed.append(
                {
                    "resource": "ConfigMap/" + name,
                    "path": expected_path,
                    "effect": effect,
                    "matches_desired": False,
                    "expected": expected_baseline,
                    "actual": actual,
                }
            )
        elif scenario == "D":
            if kubectl.get("Deployment", WEB_DEPLOYMENT, contract.namespace) is not None:
                raise InjectionError("Deployment/invenio-web was not deleted")
            changed.append(
                {
                    "resource": "Deployment/" + WEB_DEPLOYMENT,
                    "path": expected_path,
                    "effect": effect,
                    "matches_desired": False,
                    "expected": expected_baseline,
                    "actual": "deleted",
                }
            )
        elif scenario == "E":
            observed = kubectl.get("Deployment", WEB_DEPLOYMENT, contract.namespace)
            container = _container(observed or {})
            actual = (container or {}).get("resources", {}).get("limits", {}).get("memory")
            if actual is None or not _field_matches(
                cast(str, expected_path), expected_value, actual
            ):
                raise InjectionError(
                    "/spec/template/spec/containers/web/resources/limits/memory did not change"
                )
            changed.append(
                {
                    "resource": "Deployment/" + WEB_DEPLOYMENT,
                    "path": expected_path,
                    "effect": effect,
                    "matches_desired": False,
                    "expected": expected_baseline,
                    "actual": actual,
                }
            )
        elif scenario == "F":
            observed = kubectl.get("Service", WEB_SERVICE, contract.namespace)
            ports = ((observed or {}).get("spec") or {}).get("ports") or []
            actual = ports[0].get("targetPort") if ports else None
            if actual != expected_value:
                raise InjectionError("/spec/ports/0/targetPort did not change")
            changed.append(
                {
                    "resource": "Service/" + WEB_SERVICE,
                    "path": expected_path,
                    "effect": effect,
                    "matches_desired": False,
                    "expected": expected_baseline,
                    "actual": actual,
                }
            )
        elif scenario == "G":  # pragma: no branch - final scenario alternative
            observed = kubectl.get("SealedSecret", SEALED_SECRET, contract.namespace)
            actual = ((observed or {}).get("metadata", {}).get("annotations") or {}).get(
                DRIFT_ANNOTATION
            )
            if actual != expected_value:
                raise InjectionError("metadata annotation did not change")
            changed.append(
                {
                    "resource": "SealedSecret/" + SEALED_SECRET,
                    "path": expected_path,
                    "effect": effect,
                    "matches_desired": False,
                    "expected": expected_baseline,
                    "actual": actual,
                }
            )
    except InjectionError as error:
        error.injection = Injection(
            started=started,
            acknowledged=acknowledged,
            verified=None,
            accepted=False,
            changed=changed,
            commands=commands,
            error=str(error),
            verification_started=acknowledged,
        )
        raise
    except HarnessError as error:
        error.injection = Injection(
            started=started,
            acknowledged=acknowledged,
            verified=None,
            accepted=False,
            changed=changed,
            commands=commands,
            error=str(error),
            verification_started=acknowledged,
        )
        raise
    except Exception as error:
        raise InjectionError(f"injection verification failed: {type(error).__name__}") from None

    return Injection(
        started=started,
        acknowledged=acknowledged,
        verified=clock.now(),
        accepted=True,
        changed=changed,
        commands=commands,
        error=None,
        verification_started=acknowledged,
    )


def repair(
    kubectl: Kubectl,
    contract: Contract,
    observation: Observation,
    clock: Clock,  # noqa: ARG001 - kept for call-site symmetry
) -> list:
    """Reverse observed drift using the declared baselines."""
    commands = []
    for expected in contract.resources:
        actual = observation.resources.get(expected["id"])
        if actual is None:
            if expected["kind"] == "SealedSecret":
                continue
            manifest = recovery_manifest(
                expected["manifest"], hpa_owned=expected["id"] in contract.hpa_targets
            )
            commands.append(kubectl.apply(manifest))
            continue
        values = actual.get("fields") or {}
        diffs = [
            diff
            for diff in field_diffs(contract, observation)
            if diff["resource"] == expected["id"] and not diff.get("missing")
        ]
        if not diffs:
            continue
        if expected["kind"] == "Deployment":
            fields = {diff["path"]: diff["expected"] for diff in diffs}
            container_patch: dict[str, Any] = {"name": "web"}
            image = fields.get("/spec/template/spec/containers/web/image")
            if image is not None:
                container_patch["image"] = image
            resources: dict[str, dict[str, Any]] = {}
            for path, value in fields.items():
                prefix = "/spec/template/spec/containers/web/resources/"
                if path.startswith(prefix):
                    parts = path[len(prefix) :].split("/")
                    if len(parts) == 2:  # pragma: no branch - resource paths always have two parts
                        resources.setdefault(parts[0], {})[parts[1]] = value
            if resources:
                container_patch["resources"] = resources
            if len(container_patch) > 1:
                commands.append(
                    kubectl.patch(
                        "Deployment",
                        expected["name"],
                        contract.namespace,
                        {"spec": {"template": {"spec": {"containers": [container_patch]}}}},
                        "strategic",
                    )
                )
            else:  # pragma: no cover - Deployment drift always selects image or resources
                commands.append(
                    kubectl.apply(
                        recovery_manifest(
                            expected["manifest"], hpa_owned=expected["id"] in contract.hpa_targets
                        )
                    )
                )
        elif expected["kind"] == "ConfigMap":
            patch = {}
            for diff in diffs:
                if diff["path"].startswith(
                    "/data/"
                ):  # pragma: no branch - ConfigMap fields are data keys
                    patch[diff["path"][len("/data/") :]] = diff["expected"]
            if patch:  # pragma: no cover - every ConfigMap diff is a data key
                commands.append(
                    kubectl.patch(
                        "ConfigMap", expected["name"], contract.namespace, {"data": patch}, "merge"
                    )
                )
        elif expected["kind"] == "SealedSecret":
            for diff in diffs:
                if diff["path"].startswith(
                    "/metadata/annotations/"
                ):  # pragma: no branch - only annotation field
                    key = diff["path"][len("/metadata/annotations/") :]
                    if values.get(diff["path"]) is not None:
                        commands.append(
                            kubectl.annotate(
                                "SealedSecret", expected["name"], contract.namespace, key, None
                            )
                        )
        else:
            commands.append(
                kubectl.apply(
                    recovery_manifest(
                        expected["manifest"], hpa_owned=expected["id"] in contract.hpa_targets
                    )
                )
            )
    return commands


def cleanup_g_annotation(kubectl: Kubectl, namespace: str) -> CleanupReport:
    """Remove the test annotation from the Git-managed SealedSecret."""
    try:
        sealed = kubectl.get("SealedSecret", SEALED_SECRET, namespace)
        annotations = ((sealed or {}).get("metadata") or {}).get("annotations") or {}
        if DRIFT_ANNOTATION not in annotations:
            return CleanupReport(ok=True, results=[], errors=[])
        result = kubectl.annotate("SealedSecret", SEALED_SECRET, namespace, DRIFT_ANNOTATION, None)
        if not result.ok:
            return CleanupReport(
                ok=False,
                results=[result],
                errors=[f"remove {DRIFT_ANNOTATION} failed: {result.stderr.strip()[:200]}"],
            )
        return CleanupReport(ok=True, results=[result], errors=[])
    except HarnessError as error:
        return CleanupReport(ok=False, results=[], errors=[f"annotation cleanup failed: {error}"])


def cleanup_quarantine(
    kubectl: Kubectl,
    quarantine: str,
    owner: str | None = None,
    wait_seconds: float = 30.0,
) -> CleanupReport:
    """Delete the quarantine namespace after verifying ownership."""
    if not quarantine.startswith("exp-"):
        raise SafetyError("quarantine cleanup only accepts exp-* namespaces")
    validate_namespace(quarantine)
    results = []
    errors = []
    namespace = kubectl.get("Namespace", quarantine)
    if namespace is None:
        return CleanupReport(ok=True, results=[], errors=[])
    if owner is not None:
        label = ((namespace.get("metadata") or {}).get("labels") or {}).get(
            "experiment.invenio.ugm/run-id"
        )
        if label != owner:
            return CleanupReport(
                ok=False,
                results=[],
                errors=[f"refusing to delete {quarantine}: owner label mismatch"],
            )
    for kind, name in (("Deployment", WEB_DEPLOYMENT), ("Namespace", quarantine)):
        try:
            result = kubectl.delete(kind, name, quarantine if kind == "Deployment" else None)
            results.append(result)
            if not result.ok and "not found" not in result.stderr.lower():
                errors.append(f"delete {kind}/{name} failed: {result.stderr.strip()[:200]}")
        except HarnessError as error:  # noqa: PERF203 - one delete must not abort cleanup
            errors.append(f"delete {kind}/{name} failed: {error}")
    deadline = time.monotonic() + wait_seconds
    try:
        while kubectl.get("Namespace", quarantine) is not None:
            if time.monotonic() >= deadline:
                errors.append(f"quarantine namespace {quarantine} still exists")
                break
            time.sleep(0.5)
    except HarnessError as error:
        errors.append(f"quarantine verification failed: {error}")
    return CleanupReport(ok=not errors, results=results, errors=errors)


def read_diff_evidence(contract: Contract, observation: Observation) -> list:
    """Return sanitized field diffs for an evidence artifact."""
    diffs = field_diffs(contract, observation)
    sanitized = []
    for diff in diffs:
        item = {
            "resource": diff["resource"],
            "path": diff.get("path"),
            "missing": bool(diff.get("missing")),
        }
        if "expected" in diff:  # pragma: no branch - _resource_diffs always sets it
            item["expected"] = diff["expected"]
            item["actual"] = diff["actual"]
        sanitized.append(item)
    return sanitized


def planned_mutations(scenario: str) -> list:
    """Describe the single mutation each scenario would perform."""
    table = {
        "A": ["patch Deployment/invenio-web /spec/replicas (HPA-owned)"],
        "B": ["patch Deployment/invenio-web container web image"],
        "C": ["patch ConfigMap/invenio-app-config-<hash> data key"],
        "D": ["delete Deployment/invenio-web"],
        "E": ["patch Deployment/invenio-web container web memory limit"],
        "F": ["patch Service/invenio-web spec.ports[0].targetPort"],
        "G": ["annotate SealedSecret/invenio-app-secrets metadata only"],
    }
    return table.get(scenario, [])


__all__ = [
    "ArmController",
    "_baseline_issues",
    "_configmap_name",
    "_field",
    "_instrumentation_record",
    "_raise_readiness",
    "_readiness_record",
    "baseline_gate",
    "cleanup_g_annotation",
    "cleanup_quarantine",
    "inject",
    "planned_mutations",
    "read_diff_evidence",
    "repair",
    "stabilize_baseline",
]
