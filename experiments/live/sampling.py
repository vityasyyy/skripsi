"""Observation capture, serialization, and background sampling."""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from typing import Any, cast

try:
    from . import declaration as _declaration
except ImportError:  # direct script execution
    import declaration as _declaration  # type: ignore[no-redef]

try:
    from . import model as _model
except ImportError:  # direct script execution
    import model as _model  # type: ignore[no-redef]

try:
    from . import transport as _transport
except ImportError:  # direct script execution
    import transport as _transport  # type: ignore[no-redef]

declaration = _declaration

APP_OF_APPS = _model.APP_OF_APPS
ARGO_NAMESPACE = _model.ARGO_NAMESPACE
CONFIG_PREFIX = _model.CONFIG_PREFIX
DEFAULT_APP = _model.DEFAULT_APP
SEALED_SECRET = _model.SEALED_SECRET
WEB_DEPLOYMENT = _model.WEB_DEPLOYMENT
WEB_HPA = _model.WEB_HPA
WEB_SERVICE = _model.WEB_SERVICE
CaptureStopped = _model.CaptureStopped
Clock = _model.Clock
InstrumentationError = _model.InstrumentationError
Observation = _model.Observation
Point = _model.Point
ReadStopped = _model.ReadStopped
_canonical = _model._canonical
_point_dict = _model._point_dict

Kubectl = _transport.Kubectl


def sanitize_metadata(metadata: dict) -> dict:
    """Drop volatile server-managed metadata before comparison or output."""
    result = {}
    for key in ("name", "namespace"):
        if metadata.get(key) is not None:
            result[key] = metadata[key]
    if metadata.get("labels"):
        result["labels"] = copy.deepcopy(metadata["labels"])
    annotations = copy.deepcopy(metadata.get("annotations") or {})
    for key in (
        "kubectl.kubernetes.io/last-applied-configuration",
        "argocd.argoproj.io/refresh-timestamp",
        "argocd.argoproj.io/tracking-id",
        "deployment.kubernetes.io/revision",
        "deprecated.daemonset.template.generation",
    ):
        annotations.pop(key, None)
    if annotations:
        result["annotations"] = annotations
    return result


def sanitize_object(obj: dict) -> dict:
    """Remove status and secret material from one observed object."""
    kind = obj.get("kind")
    if kind == "Application":
        return sanitize_application(obj)
    result = copy.deepcopy(obj)
    result.pop("status", None)
    result["metadata"] = sanitize_metadata(obj.get("metadata") or {})
    if kind == "SealedSecret":
        result.pop("spec", None)
    elif kind == "Secret":
        result.pop("data", None)
        result.pop("stringData", None)
    elif kind == "ConfigMap":
        result.pop("binaryData", None)
    elif kind == "Service":
        spec = result.get("spec", {})
        for key in (
            "clusterIP",
            "clusterIPs",
            "ipFamilies",
            "ipFamilyPolicy",
            "internalTrafficPolicy",
            "healthCheckNodePort",
        ):
            spec.pop(key, None)
    elif kind == "Deployment":
        template = result.get("spec", {}).get("template", {})
        if isinstance(template.get("metadata"), dict):
            template["metadata"].pop("creationTimestamp", None)
    return result


def sanitize_application(app: dict) -> dict:
    """Reduce an Argo Application to its name, namespace, and spec."""
    spec = copy.deepcopy(app.get("spec") or {})
    return {
        "name": (app.get("metadata") or {}).get("name"),
        "namespace": (app.get("metadata") or {}).get("namespace"),
        "spec": spec,
    }


def recovery_manifest(manifest: dict, hpa_owned: bool = False) -> dict:
    """Build a sanitized apply manifest from a declared resource."""
    result = copy.deepcopy(manifest)
    result.pop("status", None)
    result["metadata"] = sanitize_metadata(result.get("metadata") or {})
    if hpa_owned:
        result.get("spec", {}).pop("replicas", None)
    return result


def _container(doc: dict, name: str = "web") -> dict | None:
    containers = doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    return next((item for item in containers if item.get("name") == name), None)


def _resource_fields(doc: dict) -> dict:
    return declaration.selected_fields(doc)


def resource_id(doc: dict) -> str:
    """Return the Kind/name identity used by contract and evidence keys."""
    return f"{doc.get('kind')}/{(doc.get('metadata') or {}).get('name')}"


def observation_from_objects(
    objects: list,
    at: Point,
    argo: dict | None = None,
    hpa: dict | None = None,
    extras: list | None = None,
    acquisition: dict | None = None,
) -> Observation:
    """Build an Observation from raw Kubernetes objects."""
    resources = {}
    for doc in objects:
        if not isinstance(doc, dict) or not doc.get("kind"):
            continue
        identity = resource_id(doc)
        if identity in resources:
            raise InstrumentationError(f"duplicate observed resource {identity}")
        resources[identity] = {
            "id": identity,
            "kind": doc.get("kind"),
            "name": (doc.get("metadata") or {}).get("name"),
            "namespace": (doc.get("metadata") or {}).get("namespace"),
            "fields": _resource_fields(doc),
            "manifest": sanitize_object(doc),
        }
    return Observation(
        at=at,
        resources=resources,
        extra_resources=list(extras or []),
        argo=copy.deepcopy(argo or {}),
        hpa=copy.deepcopy(hpa),
        acquisition=copy.deepcopy(acquisition or {}),
    )


def application_state(app: dict) -> dict:
    """Extract the compared Argo sync and health fields."""
    status = app.get("status") or {}
    sync = status.get("sync") or {}
    health = status.get("health") or {}
    operation = status.get("operationState") or {}
    conditions = [
        {"type": condition.get("type"), "status": condition.get("status")}
        for condition in status.get("conditions") or []
    ]
    return {
        "name": (app.get("metadata") or {}).get("name"),
        "sync": sync.get("status"),
        "health": health.get("status"),
        "revision": sync.get("revision"),
        "operation_phase": operation.get("phase"),
        "conditions": conditions,
    }


def hpa_state(hpa: dict, deployment: dict) -> dict:
    """Extract the compared HPA fields and the Deployment replica spec."""
    spec = hpa.get("spec") or {}
    status = hpa.get("status") or {}
    conditions = status.get("conditions") or []
    able = any(
        item.get("type") == "AbleToScale" and item.get("status") == "True" for item in conditions
    )
    target = spec.get("scaleTargetRef") or {}
    deployment_spec = deployment.get("spec") or {} if deployment else {}
    return {
        "name": (hpa.get("metadata") or {}).get("name"),
        "target": f"{target.get('kind')}/{target.get('name')}",
        "min": spec.get("minReplicas"),
        "max": spec.get("maxReplicas"),
        "desired": status.get("desiredReplicas"),
        "current": status.get("currentReplicas"),
        "generation": (hpa.get("metadata") or {}).get("generation"),
        "observed_generation": status.get("observedGeneration"),
        "last_scale_time": status.get("lastScaleTime"),
        "able_to_scale": able,
        "deployment_spec_replicas": deployment_spec.get("replicas"),
    }


class Snapshotter:
    """Capture the scoped objects and Argo/HPA telemetry."""

    def __init__(
        self,
        kubectl: Kubectl,
        namespace: str,
        quarantine: str,
        clock: Clock,
        configmap_name: str | None = None,
        argo_namespace: str = ARGO_NAMESPACE,
        app: str = DEFAULT_APP,
    ) -> None:
        self.kubectl = kubectl
        self.namespace = namespace
        self.quarantine = quarantine
        self.clock = clock
        self.configmap_name = configmap_name
        self.argo_namespace = argo_namespace
        self.app = app

    def discover_configmap(
        self,
        deployment: dict | None,
        reads: dict | None = None,
        guard: Callable[[], str | None] | None = None,
    ) -> str | None:
        if deployment:
            for source in (
                deployment.get("spec", {})
                .get("template", {})
                .get("spec", {})
                .get("containers", [{}])[0]
                .get("envFrom")
                or []
            ):
                name = (source.get("configMapRef") or {}).get("name")
                if name and name.startswith(CONFIG_PREFIX):
                    return name
        self._guard_stop(reads or {}, guard)
        configmaps = self.kubectl.get("ConfigMap", namespace=self.namespace) or []
        names = [
            item.get("metadata", {}).get("name")
            for item in configmaps
            if str(item.get("metadata", {}).get("name", "")).startswith(CONFIG_PREFIX)
        ]
        return names[0] if len(names) == 1 else None

    def _read(
        self,
        reads: dict,
        key: str,
        kind: str,
        name: str | None = None,
        namespace: str | None = None,
        guard: Callable[[], str | None] | None = None,
    ) -> Any:
        self._guard_stop(reads, guard)
        try:
            payload, bounds = self.kubectl.read(kind, name, namespace, guard=guard)
        except ReadStopped as stopped:
            if stopped.read_bounds:
                reads[key] = copy.deepcopy(stopped.read_bounds)
            started = self._capture_started if getattr(self, "_capture_started", None) else None
            started = started or self.clock.now()
            finished = self.clock.now()
            acquisition = {
                "started": _point_dict(started),
                "finished": _point_dict(finished),
                "started_utc": started.utc,
                "started_mono": started.mono,
                "finished_utc": finished.utc,
                "finished_mono": finished.mono,
                "reads": copy.deepcopy(reads),
            }
            raise CaptureStopped(acquisition, stopped.reason) from None
        except InstrumentationError as error:
            error_bounds = getattr(error, "read_bounds", None)
            if error_bounds:
                reads[key] = copy.deepcopy(cast(dict, error_bounds))
            started = self._capture_started if getattr(self, "_capture_started", None) else None
            started = started or self.clock.now()
            finished = self.clock.now()
            error.acquisition = {
                "started": _point_dict(started),
                "finished": _point_dict(finished),
                "started_utc": started.utc,
                "started_mono": started.mono,
                "finished_utc": finished.utc,
                "finished_mono": finished.mono,
                "reads": copy.deepcopy(reads),
            }
            raise
        reads[key] = copy.deepcopy(bounds)
        return payload

    def _guard_stop(self, reads: dict, guard: Callable[[], str | None] | None) -> None:
        if guard is None:
            return
        reason = guard()
        if not reason:
            return
        started = self._capture_started if getattr(self, "_capture_started", None) else None
        started = started or self.clock.now()
        finished = self.clock.now()
        acquisition = {
            "started": _point_dict(started),
            "finished": _point_dict(finished),
            "started_utc": started.utc,
            "started_mono": started.mono,
            "finished_utc": finished.utc,
            "finished_mono": finished.mono,
            "reads": copy.deepcopy(reads),
        }
        raise CaptureStopped(acquisition, reason)

    def capture(
        self, at: Point | None = None, guard: Callable[[], str | None] | None = None
    ) -> Observation:
        at = at or self.clock.now()
        self._capture_started = at
        reads: dict[str, dict] = {}
        deployment = self._read(
            reads,
            "Deployment/" + WEB_DEPLOYMENT,
            "Deployment",
            WEB_DEPLOYMENT,
            self.namespace,
            guard=guard,
        )
        if deployment and self.configmap_name is None:
            self.configmap_name = self.discover_configmap(deployment, reads, guard)
        configmap = (
            self._read(
                reads,
                "ConfigMap/" + self.configmap_name,
                "ConfigMap",
                self.configmap_name,
                self.namespace,
                guard=guard,
            )
            if self.configmap_name
            else None
        )
        secret = self._read(
            reads,
            "SealedSecret/" + SEALED_SECRET,
            "SealedSecret",
            SEALED_SECRET,
            self.namespace,
            guard=guard,
        )
        service = self._read(
            reads, "Service/" + WEB_SERVICE, "Service", WEB_SERVICE, self.namespace, guard=guard
        )
        hpa_doc = self._read(
            reads,
            "HorizontalPodAutoscaler/" + WEB_HPA,
            "HorizontalPodAutoscaler",
            WEB_HPA,
            self.namespace,
            guard=guard,
        )
        objects = [item for item in (deployment, configmap, secret, service) if item]
        apps = {}
        for name in (APP_OF_APPS, self.app):
            app = self._read(
                reads, "Application/" + name, "Application", name, self.argo_namespace, guard=guard
            )
            if app is None:
                raise InstrumentationError(f"Argo Application {name} is missing")
            apps[name] = application_state(app)
        extras = []
        quarantine_key = "Namespace/" + self.quarantine
        if self._read(reads, quarantine_key, "Namespace", self.quarantine, guard=guard) is not None:
            quarantine_deployment = self._read(
                reads,
                f"{self.quarantine}/Deployment/" + WEB_DEPLOYMENT,
                "Deployment",
                WEB_DEPLOYMENT,
                self.quarantine,
                guard=guard,
            )
            if quarantine_deployment:
                extras.append(f"{self.quarantine}/Deployment/{WEB_DEPLOYMENT}")
        hpa = hpa_state(hpa_doc, deployment) if hpa_doc else None
        finished = self.clock.now()
        acquisition = {
            "started": _point_dict(at),
            "finished": _point_dict(finished),
            "started_utc": at.utc,
            "started_mono": at.mono,
            "finished_utc": finished.utc,
            "finished_mono": finished.mono,
            "reads": reads,
        }
        return observation_from_objects(
            objects, at=at, argo=apps, hpa=hpa, extras=extras, acquisition=acquisition
        )


# --------------------------------------------------------------------------
# Baseline readiness
# --------------------------------------------------------------------------


def _observation_key(observation: Observation) -> str:
    # Node metrics fluctuate between reads; the quiet-window threshold is
    # checked separately, so configuration stability excludes them.
    return _canonical(
        {
            "resources": {
                key: value.get("fields") for key, value in sorted(observation.resources.items())
            },
            "extras": sorted(observation.extra_resources),
            "argo": observation.argo,
            "hpa": observation.hpa,
            "pods": observation.pods,
        }
    )


class Sampler(threading.Thread):
    """Background guarded snapshot collector with a join report."""

    def __init__(
        self,
        capture: Callable[..., Observation],
        clock: Clock,
        interval: float,
        join_timeout: float = 10.0,
        guarded: bool = False,
    ) -> None:
        super().__init__(daemon=True)
        self.capture = capture
        self.clock = clock
        self.interval = interval
        self.join_timeout = join_timeout
        self.guarded = guarded
        self.samples: list[Observation] = []
        self.error: Exception | None = None
        self.late_error: Exception | None = None
        self.deadline: float | None = None
        self.stopped_at_deadline = False
        self.stopped_capture: dict | None = None
        self.capture_stop_reason: str | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._closed = False
        self._late_result: Observation | None = None
        self._late_result_at: dict | None = None
        self._late_result_acquisition: dict | None = None

    def _guard(self) -> str | None:
        if self._stop_event.is_set():
            return "stop"
        if self.deadline is not None and self.clock.now().mono >= self.deadline:
            self.stopped_at_deadline = True
            return "deadline"
        return None

    def run(self) -> None:
        while True:
            if self._stop_event.is_set():
                return
            if self.deadline is not None and self.clock.now().mono >= self.deadline:
                self.stopped_at_deadline = True
                self._ready_event.set()
                return
            if self._stop_event.is_set():
                return
            started = self.clock.now()
            try:
                sample = self.capture(guard=self._guard) if self.guarded else self.capture()
            except CaptureStopped as stopped:
                with self._lock:
                    self.stopped_capture = copy.deepcopy(stopped.acquisition)
                    self.capture_stop_reason = stopped.reason
                self._ready_event.set()
                return
            except Exception as error:
                with self._lock:
                    self.error = error
                    if self._closed:
                        self.late_error = error
                self._ready_event.set()
                return
            with self._lock:
                if self._closed:
                    self._late_result = sample
                    if isinstance(sample, Observation):
                        self._late_result_at = _point_dict(sample.at)
                        self._late_result_acquisition = copy.deepcopy(sample.acquisition)
                else:
                    self.samples.append(sample)
                self._ready_event.set()
            elapsed = self.clock.now().mono - started.mono
            self._stop_event.wait(max(0.0, self.interval - elapsed))

    def wait_ready(self, timeout: float = 10.0) -> bool:
        return self._ready_event.wait(timeout)

    def snapshot(self) -> list:
        with self._lock:
            return list(self.samples)

    def stop(self, timeout: float | None = None) -> dict:
        self._stop_event.set()
        self.join(timeout=self.join_timeout if timeout is None else timeout)
        with self._lock:
            self._closed = True
            alive = self.is_alive()
            return {
                "joined": not alive,
                "in_flight": alive,
                "error": str(self.error) if self.error else None,
                "late_result": self._late_result is not None,
                "late_result_at": copy.deepcopy(self._late_result_at),
                "late_result_acquisition": copy.deepcopy(self._late_result_acquisition),
                "late_error": (str(self.late_error) if self.late_error else None),
                "stopped_at_deadline": self.stopped_at_deadline,
                "partial_acquisition": copy.deepcopy(self.stopped_capture),
                "capture_stop_reason": self.capture_stop_reason,
            }


__all__ = [
    "Sampler",
    "Snapshotter",
    "_container",
    "_observation_key",
    "_resource_fields",
    "application_state",
    "hpa_state",
    "observation_from_objects",
    "recovery_manifest",
    "resource_id",
    "sanitize_application",
    "sanitize_metadata",
    "sanitize_object",
]
