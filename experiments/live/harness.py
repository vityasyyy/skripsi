#!/usr/bin/env python3
"""Automated sequential-arm InvenioRDM drift harness. Dry-run by default.

The harness never mutates a cluster unless `--live` is explicit. It targets the
single real InvenioRDM stack (`invenio-web`, `invenio-web-hpa`,
`invenio-app-config-<hash>`, `invenio-app-secrets`) and never the legacy NGINX
surrogate subjects.
"""
from __future__ import annotations

import argparse
import copy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

try:
    from . import declaration as declaration
except ImportError:
    import declaration  # type: ignore[no-redef]

ARMS = ("gitops", "imperative")
SCENARIOS = tuple("ABCDEFG")
DEFAULT_NAMESPACE = "invenio"
DEFAULT_APP = "invenio-bootstrap"
APP_OF_APPS = "apps"
ARGO_NAMESPACE = "argocd"
WEB_DEPLOYMENT = declaration.WEB_DEPLOYMENT
WEB_HPA = "invenio-web-hpa"
WEB_SERVICE = declaration.WEB_SERVICE
SEALED_SECRET = declaration.SEALED_SECRET
CONFIG_PREFIX = declaration.CONFIG_PREFIX
DRIFT_ANNOTATION = declaration.DRIFT_ANNOTATION
CONFIG_KEY = declaration.CONFIG_KEY
RENDER_FORMAT = declaration.FORMAT
Declaration = declaration.Declaration
DeclarationError = declaration.DeclarationError
CONFIG_DRIFT = "drift-config-value"
MEMORY_LIMIT_DRIFT = "1536Mi"
MEMORY_LIMIT_DRIFT_FALLBACK = "1024Mi"
_RESOURCE_QUANTITY_PATHS = frozenset({
    "/spec/template/spec/containers/web/resources/requests/cpu",
    "/spec/template/spec/containers/web/resources/requests/memory",
    "/spec/template/spec/containers/web/resources/limits/cpu",
    "/spec/template/spec/containers/web/resources/limits/memory",
})
SEED_RECORD = "4ben9-bgh38"
SEED_FILE = "seed.bin"
SEED_SIZE = 65536
SEED_MD5 = "8f1445bafe2c2095044af7789462f475"
SEED_SHA256 = "7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2"
DEFAULT_INVENIO_URL = "https://invenio.vityasy.me"
USER_AGENT = "invenio-live-harness/1.0"
MISSING = "<missing>"
TIMING_CONVENTION = "completed-observation-v1"


class HarnessError(Exception):
    pass


class SafetyError(HarnessError):
    pass


class ArmStateError(HarnessError):
    pass


class ArmRestoreError(HarnessError):
    pass


class InjectionError(HarnessError):
    pass


class InstrumentationError(HarnessError):
    pass


class SeedVerificationError(HarnessError):
    pass


class BaselineError(HarnessError):
    pass


class CaptureStopped(HarnessError):
    """A cooperative between-read stop; carries safe partial acquisition."""

    def __init__(self, acquisition, reason):
        super().__init__(f"capture stopped before the next read: {reason}")
        self.acquisition = acquisition
        self.reason = reason


@dataclass(frozen=True)
class Point:
    mono: float
    utc: str


@dataclass
class Clock:
    def now(self) -> Point:
        return Point(time.monotonic(), datetime.now(timezone.utc).isoformat())


class FakeClock:
    """Deterministic clock for tests; repeats the last value when exhausted."""

    def __init__(self, values):
        self.values = list(values)
        self.index = 0

    def now(self) -> Point:
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        stamp = datetime(2026, 10, 27, tzinfo=timezone.utc)
        return Point(float(value), stamp.isoformat())


@dataclass
class CommandResult:
    argv: list
    returncode: int
    stdout: str
    stderr: str
    started: Point
    finished: Point

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def as_dict(self) -> dict:
        return {
            "argv": list(self.argv),
            "returncode": self.returncode,
            "stdout": self.stdout[:4000],
            "stderr": self.stderr[:4000],
            "started_utc": self.started.utc,
            "started_mono": self.started.mono,
            "finished_utc": self.finished.utc,
            "finished_mono": self.finished.mono,
        }


@dataclass
class Observation:
    at: Point
    resources: dict
    extra_resources: list
    argo: dict
    hpa: dict | None
    pods: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    acquisition: dict = field(default_factory=dict)
    readiness_failures: list = field(default_factory=list)
    evaluated_at: Point | None = None
    evaluated_signal: bool = False
    evaluated_reads: list = field(default_factory=list)


@dataclass
class Contract:
    namespace: str
    quarantine_namespace: str
    resources: list
    hpa_targets: list
    configmap_name: str
    source_revision: str | None
    render_sha256: str | None
    baseline_sha256: str
    baseline_hpa: dict | None

    def as_dict(self) -> dict:
        return {
            "namespace": self.namespace,
            "quarantine_namespace": self.quarantine_namespace,
            "resources": [{key: copy.deepcopy(value) for key, value in resource.items()}
                          for resource in self.resources],
            "hpa_targets": list(self.hpa_targets),
            "configmap_name": self.configmap_name,
            "source_revision": self.source_revision,
            "render_sha256": self.render_sha256,
            "baseline_sha256": self.baseline_sha256,
            "baseline_hpa": copy.deepcopy(self.baseline_hpa),
        }


@dataclass
class Injection:
    started: Point
    acknowledged: Point
    verified: Point | None
    accepted: bool
    changed: list
    commands: list
    error: str | None = None
    verification_started: Point | None = None

    def as_dict(self) -> dict:
        return {
            "started_utc": self.started.utc,
            "started_mono": self.started.mono,
            "acknowledged_utc": self.acknowledged.utc,
            "acknowledged_mono": self.acknowledged.mono,
            "verification_started_utc": (self.verification_started.utc
                                         if self.verification_started else None),
            "verification_started_mono": (self.verification_started.mono
                                          if self.verification_started else None),
            "verified_utc": self.verified.utc if self.verified else None,
            "verified_mono": self.verified.mono if self.verified else None,
            "accepted": self.accepted,
            "changed_fields": copy.deepcopy(self.changed),
            "commands": [command.as_dict() for command in self.commands],
            "error": self.error,
        }


@dataclass
class ImperativeRun:
    detection_at: Point | None = None
    evidence_at: Point | None = None
    evidence_store_at: Point | None = None
    evidence_ref: str | None = None
    detection_reads: list = field(default_factory=list)
    evidence_reads: list = field(default_factory=list)
    commands: list = field(default_factory=list)
    failed: bool = False

    def as_dict(self) -> dict:
        return {
            "detection_at_utc": self.detection_at.utc if self.detection_at else None,
            "detection_at_mono": self.detection_at.mono if self.detection_at else None,
            "evidence_at_utc": self.evidence_at.utc if self.evidence_at else None,
            "evidence_at_mono": self.evidence_at.mono if self.evidence_at else None,
            "evidence_store_at_utc": (self.evidence_store_at.utc
                                      if self.evidence_store_at else None),
            "evidence_store_at_mono": (self.evidence_store_at.mono
                                       if self.evidence_store_at else None),
            "evidence_ref": self.evidence_ref,
            "detection_reads": list(self.detection_reads),
            "evidence_reads": list(self.evidence_reads),
            "commands": [command.as_dict() for command in self.commands],
            "failed": self.failed,
        }


@dataclass
class ArmEvidence:
    arm: str
    original: dict
    applications: dict
    paused: bool

    def as_dict(self) -> dict:
        return {
            "arm": self.arm,
            "paused": self.paused,
            "original": copy.deepcopy(self.original),
            "applications": copy.deepcopy(self.applications),
        }


@dataclass
class CleanupReport:
    ok: bool
    results: list
    errors: list

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "results": [command.as_dict() for command in self.results],
            "errors": list(self.errors),
        }


def validate_namespace(namespace: str) -> str:
    if namespace == "invenio":
        return namespace
    if (len(namespace or "") <= 63
            and re.fullmatch(r"exp-[a-z0-9]([-a-z0-9]*[a-z0-9])?", namespace or "")):
        return namespace
    raise SafetyError(
        "namespace must be 'invenio' or an 'exp-*' experiment namespace; "
        f"refusing {namespace!r}"
    )


def quarantine_namespace(namespace: str) -> str:
    namespace = validate_namespace(namespace)
    name = "exp-" + namespace + "-drift"
    if len(name) > 63:
        raise SafetyError("derived quarantine namespace exceeds 63 characters")
    return name


def load_token(environ=None) -> str:
    environ = os.environ if environ is None else environ
    token = environ.get("INVENIO_TOKEN", "")
    if not token or not token.strip():
        raise SeedVerificationError(
            "INVENIO_TOKEN is required for live seed verification; failing closed"
        )
    return token


class _CrossHostRedirectHandler(urlrequest.HTTPRedirectHandler):
    """Do not forward API auth headers to a presigned object-store redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = urlparse.urlparse(req.full_url).hostname
        new_host = urlparse.urlparse(newurl).hostname
        if old_host != new_host:
            redirected.remove_header("Authorization")
            redirected.remove_header("Accept")
        return redirected


class Http:
    def __init__(self, token: str, base_url: str = DEFAULT_INVENIO_URL, timeout: float = 15):
        parsed = urlparse.urlparse(base_url)
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1"):
            raise SafetyError(
                "Invenio URL must use HTTPS unless it is a loopback address")
        self._token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = urlrequest.build_opener(_CrossHostRedirectHandler())

    def __repr__(self):
        return "Http(token=<redacted>)"

    def get(self, path: str, accept: str = "application/json"):
        url = self.base_url + path if path.startswith("/") else path
        request = urlrequest.Request(
            url,
            headers={"Authorization": "Bearer " + self._token,
                     "Accept": accept,
                     "User-Agent": USER_AGENT},
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return response.status, response.read()
        except urlerror.HTTPError as error:
            return error.code, error.read()
        except (urlerror.URLError, TimeoutError, OSError) as error:
            raise HarnessError(
                f"Invenio API request failed: {type(error).__name__}"
            ) from None


def verify_seed(http, record: str, file_name: str, expected_size: int,
                expected_md5: str, expected_sha256: str) -> dict:
    status, body = http.get(f"/api/records/{record}/draft")
    if status != 200:
        raise SeedVerificationError(
            f"seed draft endpoint returned HTTP {status}; failing closed"
        )
    try:
        draft = json.loads(body)
    except (TypeError, ValueError):
        raise SeedVerificationError("seed draft response is not JSON") from None
    files = draft.get("files") if isinstance(draft, dict) else None
    if isinstance(files, dict) and files.get("enabled") is False:
        raise SeedVerificationError("seed draft has files disabled; failing closed")

    status, body = http.get(f"/api/records/{record}/draft/files")
    if status != 200:
        raise SeedVerificationError(
            f"seed file listing returned HTTP {status}; failing closed"
        )
    try:
        listing = json.loads(body)
        entries = listing.get("entries", [])
    except (TypeError, ValueError):
        raise SeedVerificationError("seed file listing is not JSON") from None
    entry = next((item for item in entries if item.get("key") == file_name), None)
    if entry is None:
        raise SeedVerificationError(f"seed file {file_name!r} is missing")
    if entry.get("status") not in (None, "completed"):
        raise SeedVerificationError("seed file is not completed")
    if int(entry.get("size", -1)) != int(expected_size):
        raise SeedVerificationError(
            f"seed size mismatch: expected {expected_size}, got {entry.get('size')}"
        )
    checksum = str(entry.get("checksum", ""))
    if expected_md5 and checksum.lower() != "md5:" + expected_md5.lower():
        raise SeedVerificationError("seed MD5 checksum mismatch")

    status, content = http.get(
        f"/api/records/{record}/draft/files/{file_name}/content",
        accept="*/*",
    )
    if status != 200:
        raise SeedVerificationError(
            f"seed content endpoint returned HTTP {status}; failing closed"
        )
    if len(content) != expected_size:
        raise SeedVerificationError("seed content size mismatch")
    if expected_md5 and hashlib.md5(content).hexdigest() != expected_md5.lower():
        raise SeedVerificationError("seed content MD5 mismatch")
    if expected_sha256 and hashlib.sha256(content).hexdigest() != expected_sha256.lower():
        raise SeedVerificationError("seed content SHA-256 mismatch")
    return {
        "verified": True,
        "record": record,
        "file": file_name,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def sanitize_metadata(metadata: dict) -> dict:
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
        for key in ("clusterIP", "clusterIPs", "ipFamilies", "ipFamilyPolicy",
                    "internalTrafficPolicy", "healthCheckNodePort"):
            spec.pop(key, None)
    elif kind == "Deployment":
        template = result.get("spec", {}).get("template", {})
        if isinstance(template.get("metadata"), dict):
            template["metadata"].pop("creationTimestamp", None)
    return result


def sanitize_application(app: dict) -> dict:
    spec = copy.deepcopy(app.get("spec") or {})
    return {
        "name": (app.get("metadata") or {}).get("name"),
        "namespace": (app.get("metadata") or {}).get("namespace"),
        "spec": spec,
    }


def recovery_manifest(manifest: dict, hpa_owned: bool = False) -> dict:
    result = copy.deepcopy(manifest)
    result.pop("status", None)
    result["metadata"] = sanitize_metadata(result.get("metadata") or {})
    if hpa_owned:
        result.get("spec", {}).pop("replicas", None)
    return result


def _container(doc: dict, name: str = "web") -> dict | None:
    containers = (doc.get("spec", {}).get("template", {}).get("spec", {})
                  .get("containers", []))
    return next((item for item in containers if item.get("name") == name), None)


def _resource_fields(doc: dict) -> dict:
    return declaration.selected_fields(doc)


def resource_id(doc: dict) -> str:
    return f"{doc.get('kind')}/{(doc.get('metadata') or {}).get('name')}"


def observation_from_objects(objects, at: Point, argo=None, hpa=None,
                             extras=None, acquisition=None) -> Observation:
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
    return Observation(at=at, resources=resources, extra_resources=list(extras or []),
                       argo=copy.deepcopy(argo or {}), hpa=copy.deepcopy(hpa),
                       acquisition=copy.deepcopy(acquisition or {}))


def application_state(app: dict) -> dict:
    status = app.get("status") or {}
    sync = status.get("sync") or {}
    health = status.get("health") or {}
    operation = status.get("operationState") or {}
    conditions = []
    for condition in status.get("conditions") or []:
        conditions.append({"type": condition.get("type"),
                           "status": condition.get("status")})
    return {
        "name": (app.get("metadata") or {}).get("name"),
        "sync": sync.get("status"),
        "health": health.get("status"),
        "revision": sync.get("revision"),
        "operation_phase": operation.get("phase"),
        "conditions": conditions,
    }


def hpa_state(hpa: dict, deployment: dict) -> dict:
    spec = hpa.get("spec") or {}
    status = hpa.get("status") or {}
    conditions = status.get("conditions") or []
    able = any(item.get("type") == "AbleToScale" and item.get("status") == "True"
               for item in conditions)
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


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def build_contract(frozen: Declaration, observation: Observation,
                   namespace: str, quarantine_namespace: str,
                   app=DEFAULT_APP) -> Contract:
    if not isinstance(frozen, Declaration):
        raise InstrumentationError(
            "contract requires an independently loaded frozen declaration")
    if not re.fullmatch(r"[0-9a-f]{40}", frozen.source_revision):
        raise InstrumentationError("source revision must be 40 lowercase hex")
    if not re.fullmatch(r"[0-9a-f]{64}", frozen.render_sha256):
        raise InstrumentationError("render SHA-256 must be 64 lowercase hex")
    observed_revision = (observation.argo.get(app) or {}).get("revision")
    if observed_revision != frozen.source_revision:
        raise InstrumentationError(
            "frozen source revision does not match the observed Argo revision")
    hpa_targets = []
    if observation.hpa and observation.hpa.get("target"):
        hpa_targets.append(observation.hpa["target"])
    resources = []
    for declared in frozen.resources:
        if declared["namespace"] != namespace:
            raise InstrumentationError(
                f"declared {declared['id']} is not in namespace {namespace!r}")
        resource = {key: copy.deepcopy(declared[key])
                    for key in ("id", "kind", "name", "namespace", "fields")}
        manifest = sanitize_object(declared["manifest"])
        if resource["kind"] == "Deployment":
            manifest.get("spec", {}).pop("replicas", None)
        resource["manifest"] = manifest
        resources.append(resource)
    if len(resources) != 4:
        raise InstrumentationError(
            "frozen declaration must select exactly four scoped resources")
    digest_payload = {
        "resources": [{key: resource[key] for key in
                       ("id", "kind", "name", "namespace", "fields")}
                      for resource in resources],
        "hpa_targets": hpa_targets,
        "configmap_name": frozen.configmap_name,
        "source_revision": frozen.source_revision,
        "render_sha256": frozen.render_sha256,
    }
    return Contract(
        namespace=namespace,
        quarantine_namespace=quarantine_namespace,
        resources=resources,
        hpa_targets=hpa_targets,
        configmap_name=frozen.configmap_name,
        source_revision=frozen.source_revision,
        render_sha256=frozen.render_sha256,
        baseline_sha256=hashlib.sha256(
            _canonical(digest_payload).encode()).hexdigest(),
        baseline_hpa=copy.deepcopy(observation.hpa),
    )


def _same(expected, actual) -> bool:
    return type(expected) is type(actual) and expected == actual


def _normalized_value(path: str, value):
    if path == "/spec/type":
        return "ClusterIP" if value is None else value
    if path in _RESOURCE_QUANTITY_PATHS:
        if value is None:
            return None
        if path.endswith("/cpu"):
            return _quantity_nanocores(value, path)
        return _quantity_bytes(value, path)
    return value


def _field_matches(path: str, expected, actual) -> bool:
    return _same(_normalized_value(path, expected),
                 _normalized_value(path, actual))


def _resource_diffs(expected: dict, actual: dict | None) -> list:
    if actual is None:
        return [{"resource": expected["id"], "missing": True,
                 "path": None, "expected": "present", "actual": "missing"}]
    values = actual.get("fields") or {}
    diffs = []
    for path, expected_value in expected["fields"].items():
        actual_value = values.get(path, MISSING)
        if (actual_value is MISSING
                or not _field_matches(path, expected_value, actual_value)):
            diffs.append({
                "resource": expected["id"],
                "path": path,
                "expected": expected_value,
                "actual": None if actual_value is MISSING else actual_value,
            })
    return diffs


def resource_results(contract: Contract, observation: Observation) -> dict:
    if not contract.resources:
        return {"score": 0.0, "matched": 0, "total": 0, "resources": []}
    items = []
    matched = 0
    for expected in contract.resources:
        actual = observation.resources.get(expected["id"])
        diffs = _resource_diffs(expected, actual)
        resource_matched = not diffs
        matched += resource_matched
        item = {
            "resource": expected["id"],
            "kind": expected["kind"],
            "matched": resource_matched,
            "missing": actual is None,
        }
        if diffs and actual is not None:
            item["mismatches"] = [
                {"path": diff["path"], "expected": diff["expected"],
                 "actual": diff["actual"]}
                for diff in diffs
            ]
        items.append(item)
    return {
        "score": 100.0 * matched / len(contract.resources),
        "matched": matched,
        "total": len(contract.resources),
        "resources": items,
    }


def score(contract: Contract, observation: Observation) -> float:
    return resource_results(contract, observation)["score"]


def field_diffs(contract: Contract, observation: Observation) -> list:
    diffs = []
    for expected in contract.resources:
        diffs.extend(_resource_diffs(
            expected, observation.resources.get(expected["id"])))
    return diffs


def hpa_settled(state: dict | None) -> bool:
    if not state:
        return False
    values = (state.get("desired"), state.get("current"),
              state.get("deployment_spec_replicas"), state.get("min"),
              state.get("max"))
    if any(type(value) is not int for value in values):
        return False
    desired, current, replicas, minimum, maximum = values
    generation = state.get("generation")
    observed = state.get("observed_generation")
    if generation is None and observed is None:
        generation_ok = True
    elif type(generation) is int and type(observed) is int:
        generation_ok = generation == observed
    else:
        generation_ok = False
    return (state.get("able_to_scale") is True
            and minimum <= desired <= maximum
            and desired == current == replicas
            and generation_ok)


def hpa_telemetry_valid(state: dict) -> bool:
    values = (state.get("desired"), state.get("current"),
              state.get("deployment_spec_replicas"), state.get("min"),
              state.get("max"))
    if any(type(value) is not int or value < 0 for value in values):
        return False
    if values[3] <= 0 or values[4] < values[3]:
        return False
    if type(state.get("able_to_scale")) is not bool:
        return False
    generation = state.get("generation")
    observed = state.get("observed_generation")
    if generation is None and observed is None:
        return True
    return type(generation) is int and type(observed) is int


def hpa_changed(baseline: dict | None, current: dict | None) -> bool:
    if not baseline or not current:
        return False
    keys = ("desired", "current", "deployment_spec_replicas", "last_scale_time")
    return any(baseline.get(key) != current.get(key) for key in keys)


def argo_signal(state: dict | None) -> bool:
    if not state:
        return False
    if state.get("sync") == "OutOfSync":
        return True
    if state.get("operation_phase") in ("Running", "Error", "Failed"):
        return True
    return any(item.get("type") in ("ComparisonError", "SyncError")
               and item.get("status") == "True"
               for item in state.get("conditions") or [])


_QUANTITY_RE = re.compile(
    r"^(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+))"
    r"(?P<suffix>Ki|Mi|Gi|Ti|Pi|Ei|[numkKMGTPE]|[eE][+-]?\d+)?$")
_BINARY_FACTORS = {
    "Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3,
    "Ti": 1024 ** 4, "Pi": 1024 ** 5, "Ei": 1024 ** 6,
}
_DECIMAL_FACTORS = {
    None: 1, "n": Decimal("1e-9"), "u": Decimal("1e-6"),
    "m": Decimal("1e-3"), "k": 1000, "M": 1000 ** 2, "G": 1000 ** 3,
    "T": 1000 ** 4, "P": 1000 ** 5, "E": 1000 ** 6,
}
_DURATION_PART = re.compile(r"(\d+(?:\.\d*)?|\.\d+)(ns|us|µs|ms|s|m|h)")
_DURATION_FACTORS = {
    "ns": Decimal("1e-9"), "us": Decimal("1e-6"), "µs": Decimal("1e-6"),
    "ms": Decimal("1e-3"), "s": 1, "m": 60, "h": 3600,
}


def _quantity(value, field: str) -> Decimal:
    if not isinstance(value, str) or not value or value != value.strip():
        raise InstrumentationError(f"{field} is not a valid Kubernetes quantity")
    match = _QUANTITY_RE.fullmatch(value)
    if match is None:
        raise InstrumentationError(f"{field} is not a valid Kubernetes quantity")
    try:
        number = Decimal(match.group("number"))
    except InvalidOperation:
        raise InstrumentationError(
            f"{field} is not a valid Kubernetes quantity") from None
    suffix = match.group("suffix")
    try:
        if suffix in _BINARY_FACTORS:
            factor = Decimal(_BINARY_FACTORS[suffix])
        elif suffix in _DECIMAL_FACTORS:
            factor = Decimal(_DECIMAL_FACTORS[suffix])
        elif suffix and suffix[0] in "eE":
            factor = Decimal(10) ** int(suffix[1:])
        else:
            raise InstrumentationError(
                f"{field} is not a valid Kubernetes quantity")
        result = number * factor
    except ArithmeticError:
        raise InstrumentationError(
            f"{field} is not a valid Kubernetes quantity") from None
    if result == 0 and number != 0:
        raise InstrumentationError(f"{field} underflows")
    if not result.is_finite():
        raise InstrumentationError(f"{field} is not a finite Kubernetes quantity")
    return result


def _quantity_nanocores(value, field: str, positive: bool = False) -> int:
    try:
        amount = _quantity(value, field) * Decimal(10 ** 9)
    except ArithmeticError:
        raise InstrumentationError(f"{field} is not a valid CPU quantity") from None
    if amount != amount.to_integral_value():
        raise InstrumentationError(f"{field} is not representable in nanocores")
    result = int(amount)
    if result < 0 or (positive and result == 0):
        raise InstrumentationError(
            f"{field} must be {'positive' if positive else 'non-negative'}")
    return result


def _quantity_bytes(value, field: str, positive: bool = False) -> int:
    amount = _quantity(value, field)
    if amount != amount.to_integral_value():
        raise InstrumentationError(f"{field} is not representable in bytes")
    result = int(amount)
    if result < 0 or (positive and result == 0):
        raise InstrumentationError(
            f"{field} must be {'positive' if positive else 'non-negative'}")
    return result


def load_declaration(path, expected_sha256: str, expected_revision: str,
                     namespace: str) -> Declaration:
    return _prepare_declaration(declaration.load(
        path, expected_sha256, expected_revision, namespace))


def load_declaration_bytes(data: bytes, expected_sha256: str,
                           expected_revision: str,
                           namespace: str) -> Declaration:
    return _prepare_declaration(declaration.loads(
        data, expected_sha256, expected_revision, namespace))


def _prepare_declaration(frozen: Declaration) -> Declaration:
    resources = []
    for resource in frozen.resources:
        clean = dict(resource)
        clean["manifest"] = sanitize_object(resource["manifest"])
        resources.append(clean)
    prepared = Declaration(
        source_revision=frozen.source_revision,
        render_sha256=frozen.render_sha256,
        configmap_name=frozen.configmap_name,
        resources=tuple(resources),
        format=frozen.format,
    )
    _validate_declared_quantities(prepared)
    return prepared


def _validate_declared_quantities(frozen: Declaration) -> None:
    for resource in frozen.resources:
        if resource["kind"] != "Deployment":
            continue
        for path, value in resource["fields"].items():
            if path not in _RESOURCE_QUANTITY_PATHS:
                continue
            try:
                if path.endswith("/cpu"):
                    _quantity_nanocores(value, f"declared {path}")
                else:
                    _quantity_bytes(value, f"declared {path}")
            except InstrumentationError as error:
                raise DeclarationError(str(error)) from None


def _duration_seconds(value, field: str) -> float:
    if not isinstance(value, str) or not value:
        raise InstrumentationError(f"{field} is not a valid duration")
    position = 0
    total = Decimal(0)
    try:
        for match in _DURATION_PART.finditer(value):
            if match.start() != position:
                raise InstrumentationError(f"{field} is not a valid duration")
            total += Decimal(match.group(1)) * Decimal(
                _DURATION_FACTORS[match.group(2)])
            position = match.end()
        if position != len(value) or total <= 0:
            raise InstrumentationError(f"{field} is not a valid duration")
        seconds = float(total)
    except ArithmeticError:
        raise InstrumentationError(f"{field} is not a valid duration") from None
    if not math.isfinite(seconds):
        raise InstrumentationError(f"{field} is not a finite duration")
    return seconds


def _timestamp(value, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise InstrumentationError(f"{field} is not a valid timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InstrumentationError(f"{field} is not a valid timestamp") from None
    if parsed.tzinfo is None:
        raise InstrumentationError(f"{field} has no timezone")
    return value


def _command_bounds(command: CommandResult) -> dict:
    return {
        "started_utc": command.started.utc,
        "started_mono": command.started.mono,
        "finished_utc": command.finished.utc,
        "finished_mono": command.finished.mono,
    }


def _point_bounds(started: Point, finished: Point) -> dict:
    return {
        "started_utc": started.utc,
        "started_mono": started.mono,
        "finished_utc": finished.utc,
        "finished_mono": finished.mono,
    }


def _attempt_bounds(command: CommandResult) -> dict:
    return {
        "started_utc": command.started.utc,
        "started_mono": command.started.mono,
        "finished_utc": command.finished.utc,
        "finished_mono": command.finished.mono,
        "returncode": command.returncode,
        "ok": command.returncode == 0,
    }


def _read_bounds(kind, name, namespace, attempts, present, ok) -> dict:
    last = attempts[-1]
    return {
        "kind": kind,
        "name": name,
        "namespace": namespace,
        "started_utc": last["started_utc"],
        "started_mono": last["started_mono"],
        "finished_utc": last["finished_utc"],
        "finished_mono": last["finished_mono"],
        "ok": ok,
        "present": present,
        "attempts": copy.deepcopy(attempts),
    }


def _node_name(item, field: str, seen: set) -> str:
    if not isinstance(item, dict):
        raise InstrumentationError(f"{field} contains a non-object node")
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        raise InstrumentationError(f"{field} node has no metadata")
    name = metadata.get("name")
    if not isinstance(name, str) or not name.strip():
        raise InstrumentationError(f"{field} node has no name")
    if name in seen:
        raise InstrumentationError(f"duplicate node {name} in {field}")
    seen.add(name)
    return name


def parse_node_metrics(metrics_payload, nodes_payload, metrics_bounds,
                       allocatable_bounds) -> list:
    if not isinstance(metrics_payload, dict):
        raise InstrumentationError("node metrics payload is not an object")
    metrics_items = metrics_payload.get("items")
    if not isinstance(metrics_items, list) or not metrics_items:
        raise InstrumentationError("no node metrics returned")
    if isinstance(nodes_payload, dict):
        nodes_payload = nodes_payload.get("items")
    if not isinstance(nodes_payload, list) or not nodes_payload:
        raise InstrumentationError("no node inventory returned")
    allocatable = {}
    seen = set()
    for item in nodes_payload:
        name = _node_name(item, "node inventory", seen)
        status = item.get("status")
        if not isinstance(status, dict):
            raise InstrumentationError(f"node {name} has no status")
        resources = status.get("allocatable")
        if not isinstance(resources, dict):
            raise InstrumentationError(
                f"node {name} has no allocatable resources")
        allocatable[name] = {
            "cpu": resources.get("cpu"),
            "memory": resources.get("memory"),
            "cpu_nanocores": _quantity_nanocores(
                resources.get("cpu"), f"node {name} allocatable cpu", True),
            "memory_bytes": _quantity_bytes(
                resources.get("memory"), f"node {name} allocatable memory", True),
        }
    usage = {}
    seen = set()
    for item in metrics_items:
        name = _node_name(item, "node metrics", seen)
        if name not in allocatable:
            raise InstrumentationError(
                f"node metrics returned for unexpected node {name}")
        resources = item.get("usage")
        if not isinstance(resources, dict):
            raise InstrumentationError(f"node {name} metrics have no usage")
        timestamp = _timestamp(item.get("timestamp"),
                               f"node {name} metrics timestamp")
        window = item.get("window")
        window_seconds = _duration_seconds(
            window, f"node {name} metrics window")
        usage[name] = {
            "cpu": resources.get("cpu"),
            "memory": resources.get("memory"),
            "cpu_nanocores": _quantity_nanocores(
                resources.get("cpu"), f"node {name} usage cpu"),
            "memory_bytes": _quantity_bytes(
                resources.get("memory"), f"node {name} usage memory"),
            "timestamp": timestamp,
            "window": window,
            "window_seconds": window_seconds,
        }
    missing = sorted(set(allocatable) - set(usage))
    if missing:
        raise InstrumentationError(
            "node metrics missing for " + ", ".join(missing))
    nodes = []
    for name in sorted(usage):
        observed = usage[name]
        capacity = allocatable[name]
        cpu_percent = float(
            Decimal(observed["cpu_nanocores"]) * 100
            / Decimal(capacity["cpu_nanocores"]))
        memory_percent = float(
            Decimal(observed["memory_bytes"]) * 100
            / Decimal(capacity["memory_bytes"]))
        if not math.isfinite(cpu_percent) or not math.isfinite(memory_percent):
            raise InstrumentationError(f"node {name} percentage is not finite")
        nodes.append({
            "name": name,
            "cpu_usage": observed["cpu"],
            "memory_usage": observed["memory"],
            "cpu_allocatable": capacity["cpu"],
            "memory_allocatable": capacity["memory"],
            "cpu_usage_nanocores": observed["cpu_nanocores"],
            "cpu_allocatable_nanocores": capacity["cpu_nanocores"],
            "memory_usage_bytes": observed["memory_bytes"],
            "memory_allocatable_bytes": capacity["memory_bytes"],
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "metrics_timestamp": observed["timestamp"],
            "metrics_window": observed["window"],
            "metrics_window_seconds": observed["window_seconds"],
            "acquisition": {
                "metrics": copy.deepcopy(metrics_bounds),
                "allocatable": copy.deepcopy(allocatable_bounds),
            },
        })
    return nodes


class Kubectl:
    def __init__(self, clock: Clock, timeout: float = 30, recorder=None):
        self.clock = clock
        self.timeout = timeout
        self.recorder = recorder if recorder is not None else []

    def run(self, argv, input_text=None, mutating=False, timeout=None) -> CommandResult:
        started = self.clock.now()
        try:
            completed = subprocess.run(
                ["kubectl", *argv],
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                check=False,
            )
            code, stdout, stderr = (completed.returncode, completed.stdout or "",
                                    completed.stderr or "")
        except subprocess.TimeoutExpired:
            code, stdout, stderr = 124, "", "kubectl timed out"
        except OSError as error:
            raise InstrumentationError(
                f"kubectl could not start: {type(error).__name__}") from None
        finished = self.clock.now()
        result = CommandResult(argv=list(argv), returncode=code, stdout=stdout,
                               stderr=stderr, started=started, finished=finished)
        if mutating:
            self.recorder.append(result)
        return result

    def get(self, kind, name=None, namespace=None, selector=None):
        payload, _ = self.read(kind, name, namespace, selector)
        return payload

    def read(self, kind, name=None, namespace=None, selector=None):
        argv = ["get", kind]
        if name:
            argv.append(name)
        if namespace:
            argv.extend(["-n", namespace])
        elif name is None and kind not in ("Namespace", "Node"):
            argv.append("--all-namespaces")
        if selector:
            argv.extend(["-l", selector])
        argv.extend(["-o", "json", "--ignore-not-found",
                     "--request-timeout=15s"])
        attempts = []
        result = self.run(argv)
        attempts.append(_attempt_bounds(result))
        for attempt in range(2):
            if result.returncode == 0:
                break
            stderr = result.stderr.lower()
            transient = any(token in stderr for token in (
                "unexpected error when reading response body",
                "request canceled", "client.timeout",
                "connection reset", "tls handshake timeout",
                "i/o timeout", "temporarily unavailable"))
            if not transient:
                break
            time.sleep(0.5 * (attempt + 1))
            result = self.run(argv)
            attempts.append(_attempt_bounds(result))
        if result.returncode != 0:
            error = InstrumentationError(
                f"kubectl get {kind} failed: {result.stderr.strip()[:300]}")
            error.read_bounds = _read_bounds(
                kind, name, namespace, attempts, present=False, ok=False)
            raise error
        if not result.stdout.strip():
            return None, _read_bounds(
                kind, name, namespace, attempts, present=False, ok=True)
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            error = InstrumentationError(
                f"kubectl get {kind} returned invalid JSON")
            error.read_bounds = _read_bounds(
                kind, name, namespace, attempts, present=False, ok=False)
            raise error from None
        if isinstance(payload, dict) and payload.get("kind") == "List":
            items = payload.get("items") or []
            return (items if name is None else None), _read_bounds(
                kind, name, namespace, attempts, present=True, ok=True)
        return payload, _read_bounds(
            kind, name, namespace, attempts, present=True, ok=True)

    def patch(self, kind, name, namespace, patch, patch_type="merge") -> CommandResult:
        argv = ["patch", kind, name]
        if namespace:
            argv.extend(["-n", namespace])
        argv.extend(["--type", patch_type, "-p", json.dumps(patch, sort_keys=True)])
        return self.run(argv, mutating=True)

    def annotate(self, kind, name, namespace, key, value=None) -> CommandResult:
        argv = ["annotate", kind, name]
        if namespace:
            argv.extend(["-n", namespace])
        argv.append(key + ("=" + value if value is not None else "-"))
        if value is not None:
            argv.append("--overwrite")
        return self.run(argv, mutating=True)

    def apply(self, manifest) -> CommandResult:
        return self.run(["apply", "-f", "-"], input_text=json.dumps(manifest),
                        mutating=True)

    def delete(self, kind, name, namespace=None, wait=False,
               timeout=90) -> CommandResult:
        argv = ["delete", kind, name]
        if namespace:
            argv.extend(["-n", namespace])
        if not wait:
            argv.append("--wait=false")
        return self.run(argv, mutating=True, timeout=timeout)

    def top_nodes(self) -> list:
        result = self.run(["get", "--raw",
                           "/apis/metrics.k8s.io/v1beta1/nodes",
                           "--request-timeout=15s"])
        if result.returncode != 0:
            raise InstrumentationError(
                f"metrics-server node read failed: {result.stderr.strip()[:300]}")
        try:
            metrics = json.loads(result.stdout)
        except ValueError:
            raise InstrumentationError(
                "metrics-server node read returned invalid JSON") from None
        allocatable_started = self.clock.now()
        nodes = self.get("Node")
        allocatable_finished = self.clock.now()
        return parse_node_metrics(
            metrics, nodes, _command_bounds(result),
            _point_bounds(allocatable_started, allocatable_finished))

    def pods(self, namespace) -> list:
        items = self.get("Pod", namespace=namespace) or []
        pods = []
        for item in items:
            status = item.get("status") or {}
            phase = status.get("phase")
            if phase == "Succeeded":
                continue
            statuses = (status.get("containerStatuses") or []) + (
                status.get("initContainerStatuses") or [])
            ready = bool(statuses) and all(item.get("ready") is True
                                           for item in statuses)
            pods.append({"name": (item.get("metadata") or {}).get("name"),
                         "phase": phase, "ready": ready})
        return pods


class Snapshotter:
    def __init__(self, kubectl, namespace, quarantine, clock,
                 configmap_name=None, argo_namespace=ARGO_NAMESPACE,
                 app=DEFAULT_APP):
        self.kubectl = kubectl
        self.namespace = namespace
        self.quarantine = quarantine
        self.clock = clock
        self.configmap_name = configmap_name
        self.argo_namespace = argo_namespace
        self.app = app

    def discover_configmap(self, deployment, reads=None, guard=None) -> str | None:
        if deployment:
            for source in (deployment.get("spec", {}).get("template", {}).get(
                    "spec", {}).get("containers", [{}])[0].get("envFrom") or []):
                name = (source.get("configMapRef") or {}).get("name")
                if name and name.startswith(CONFIG_PREFIX):
                    return name
        self._guard_stop(reads or {}, guard)
        configmaps = self.kubectl.get("ConfigMap", namespace=self.namespace) or []
        names = [item.get("metadata", {}).get("name") for item in configmaps
                 if str(item.get("metadata", {}).get("name", "")).startswith(
                     CONFIG_PREFIX)]
        return names[0] if len(names) == 1 else None

    def _read(self, reads, key, kind, name=None, namespace=None, guard=None):
        self._guard_stop(reads, guard)
        try:
            payload, bounds = self.kubectl.read(kind, name, namespace)
        except InstrumentationError as error:
            bounds = getattr(error, "read_bounds", None)
            if bounds:
                reads[key] = copy.deepcopy(bounds)
            started = (self._capture_started
                       if getattr(self, "_capture_started", None) else None)
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

    def _guard_stop(self, reads, guard):
        if guard is None:
            return
        reason = guard()
        if not reason:
            return
        started = (self._capture_started
                   if getattr(self, "_capture_started", None) else None)
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

    def capture(self, at: Point | None = None, guard=None) -> Observation:
        at = at or self.clock.now()
        self._capture_started = at
        reads = {}
        deployment = self._read(
            reads, "Deployment/" + WEB_DEPLOYMENT, "Deployment",
            WEB_DEPLOYMENT, self.namespace, guard=guard)
        if deployment and self.configmap_name is None:
            self.configmap_name = self.discover_configmap(
                deployment, reads, guard)
        configmap = (self._read(
            reads, "ConfigMap/" + self.configmap_name, "ConfigMap",
            self.configmap_name, self.namespace, guard=guard)
            if self.configmap_name else None)
        secret = self._read(
            reads, "SealedSecret/" + SEALED_SECRET, "SealedSecret",
            SEALED_SECRET, self.namespace, guard=guard)
        service = self._read(
            reads, "Service/" + WEB_SERVICE, "Service", WEB_SERVICE,
            self.namespace, guard=guard)
        hpa_doc = self._read(
            reads, "HorizontalPodAutoscaler/" + WEB_HPA,
            "HorizontalPodAutoscaler", WEB_HPA, self.namespace, guard=guard)
        objects = [item for item in (deployment, configmap, secret, service) if item]
        apps = {}
        for name in (APP_OF_APPS, self.app):
            app = self._read(
                reads, "Application/" + name, "Application", name,
                self.argo_namespace, guard=guard)
            if app is None:
                raise InstrumentationError(f"Argo Application {name} is missing")
            apps[name] = application_state(app)
        extras = []
        quarantine_key = "Namespace/" + self.quarantine
        if self._read(reads, quarantine_key, "Namespace",
                      self.quarantine, guard=guard) is not None:
            quarantine_deployment = self._read(
                reads,
                f"{self.quarantine}/Deployment/" + WEB_DEPLOYMENT,
                "Deployment", WEB_DEPLOYMENT, self.quarantine, guard=guard)
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
        return observation_from_objects(objects, at=at, argo=apps, hpa=hpa,
                                         extras=extras, acquisition=acquisition)


def _observation_key(observation: Observation) -> str:
    # Node metrics fluctuate between reads; the quiet-window threshold is
    # checked separately, so configuration stability excludes them.
    return _canonical({
        "resources": {key: value.get("fields")
                      for key, value in sorted(observation.resources.items())},
        "extras": sorted(observation.extra_resources),
        "argo": observation.argo,
        "hpa": observation.hpa,
        "pods": observation.pods,
    })


def _baseline_issues(observation: Observation, arm: str,
                     app: str = DEFAULT_APP) -> list:
    issues = []

    def add(code, detail, retryable=False):
        issues.append({"code": code, "detail": detail,
                       "retryable": retryable})

    if not any(key.startswith("ConfigMap/" + CONFIG_PREFIX)
               for key in observation.resources):
        add("missing_configmap",
            "generated invenio-app-config ConfigMap is missing")
    if "Deployment/" + WEB_DEPLOYMENT not in observation.resources:
        add("missing_deployment", "invenio-web Deployment is missing")
    if "SealedSecret/" + SEALED_SECRET not in observation.resources:
        add("missing_sealed_secret",
            "invenio-app-secrets SealedSecret is missing")
    else:
        sealed = observation.resources["SealedSecret/" + SEALED_SECRET]
        if sealed["fields"].get(
                "/metadata/annotations/" + DRIFT_ANNOTATION) is not None:
            add("contamination",
                "drift annotation is already present on SealedSecret")
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
            add("hpa_settling", "HPA is not settled at baseline",
                retryable=True)
    if observation.extra_resources:
        add("quarantine_preexisting",
            "quarantine resources exist before the run")
    if not observation.pods:
        add("pod_readiness", "no pods observed", retryable=True)
    for pod in observation.pods:
        if not isinstance(pod, dict):
            raise InstrumentationError("pod telemetry is malformed")
        if pod.get("phase") != "Running" or pod.get("ready") is not True:
            add("pod_readiness",
                f"pod {pod.get('name')} is not Running and Ready",
                retryable=True)
    if not observation.nodes:
        add("missing_node_metrics", "no node metrics observed")
    for node in observation.nodes:
        if not isinstance(node, dict):
            raise InstrumentationError("node telemetry is malformed")
        name = node.get("name")
        for metric in ("cpu_percent", "memory_percent"):
            value = node.get(metric)
            finite = (type(value) is int
                      or (type(value) is float and math.isfinite(value)))
            if not finite or value < 0:
                raise InstrumentationError(
                    f"node {name} {metric} is not a finite percentage")
            if value >= 70:
                add("capacity",
                    f"node {name} {metric} >= 70%", retryable=True)
    if arm == "gitops":
        for name in (APP_OF_APPS, app):
            state = observation.argo.get(name) or {}
            if state.get("sync") != "Synced" or state.get("health") != "Healthy":
                add("argo_state",
                    f"Argo Application {name} is not Synced/Healthy")
    return issues


def baseline_gate(observation: Observation, arm: str,
                  app: str = DEFAULT_APP) -> None:
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


def _raise_readiness(error, failures):
    error.readiness_failures = failures
    raise error


def _instrumentation_record(error, started, finished, observation=None) -> dict:
    record = {
        "kind": "instrumentation_failure",
        "at": _point_dict(started),
        "acquisition": {"snapshot": _point_bounds(started, finished)},
        "reason": "instrumentation_failure",
        "detail": str(error),
        "reasons": [{"code": "instrumentation_failure",
                     "detail": str(error), "retryable": False}],
        "pods": [],
        "nodes": [],
        "hpa": None,
        "argo": {},
        "extra_resources": [],
    }
    if observation is not None:
        record.update({
            "at": _point_dict(observation.at),
            "pods": copy.deepcopy(observation.pods),
            "nodes": copy.deepcopy(observation.nodes),
            "hpa": copy.deepcopy(observation.hpa),
            "argo": copy.deepcopy(observation.argo),
            "extra_resources": copy.deepcopy(observation.extra_resources),
        })
        acquisition = copy.deepcopy(observation.acquisition)
        if acquisition:
            record["acquisition"] = acquisition
    else:
        acquisition = getattr(error, "acquisition", None)
        if isinstance(acquisition, dict) and acquisition:
            record["acquisition"] = copy.deepcopy(acquisition)
    return record


def stabilize_baseline(snapshotter, kubectl, arm, timeout, interval,
                       clock, sleep=time.sleep, app=DEFAULT_APP) -> Observation:
    deadline = clock.now().mono + timeout
    previous_key = None
    failures = []
    attempted = False
    while True:
        if attempted and clock.now().mono >= deadline:
            _raise_readiness(BaselineError(
                f"baseline did not stabilize within {timeout}s"), failures)
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
            observation.acquisition["pods"] = _point_bounds(
                pods_started, pods_finished)
            nodes_started = clock.now()
            observation.nodes = kubectl.top_nodes()
            nodes_finished = clock.now()
            observation.acquisition["nodes"] = _point_bounds(
                nodes_started, nodes_finished)
            issues = _baseline_issues(observation, arm, app)
        except InstrumentationError as error:
            finished = clock.now()
            if observation is not None:
                if pods_started is not None and "pods" not in observation.acquisition:
                    observation.acquisition["pods"] = _point_bounds(
                        pods_started, finished)
                elif (nodes_started is not None
                      and "nodes" not in observation.acquisition):
                    observation.acquisition["nodes"] = _point_bounds(
                        nodes_started, finished)
            failures.append(_instrumentation_record(
                error, started, finished, observation))
            _raise_readiness(error, failures)
        now = clock.now().mono
        if issues:
            previous_key = None
            failures.append(_readiness_record(observation, issues, "gate"))
            fatal = [issue for issue in issues if not issue["retryable"]]
            if fatal:
                _raise_readiness(BaselineError(fatal[0]["detail"]), failures)
            if now >= deadline:
                _raise_readiness(BaselineError(
                    f"baseline not ready within {timeout}s: "
                    + "; ".join(issue["detail"] for issue in issues)), failures)
            sleep(min(interval, deadline - now))
            continue
        key = _observation_key(observation)
        if now >= deadline:
            failures.append(_readiness_record(observation, [{
                "code": "deadline",
                "detail": "baseline read crossed the settling deadline",
                "retryable": True,
            }], "deadline"))
            _raise_readiness(BaselineError(
                f"baseline did not stabilize within {timeout}s"), failures)
        if previous_key == key:
            observation.readiness_failures = failures
            return observation
        if previous_key is not None:
            failures.append(_readiness_record(observation, [{
                "code": "unmatched_read",
                "detail": "baseline read did not match the previous read",
                "retryable": True,
            }], "unmatched"))
        previous_key = key
        sleep(min(interval, deadline - now))


class ArmController:
    def __init__(self, kubectl, app=DEFAULT_APP, apps_app=APP_OF_APPS,
                 argo_namespace=ARGO_NAMESPACE):
        self.kubectl = kubectl
        self.app = app
        self.apps_app = apps_app
        self.argo_namespace = argo_namespace
        self.original = None

    def get_app(self, name):
        app = self.kubectl.get("Application", name, self.argo_namespace)
        if app is None:
            raise ArmStateError(f"Argo Application {name} is missing")
        return app

    @staticmethod
    def automated(app):
        return ((app.get("spec") or {}).get("syncPolicy") or {}).get("automated")

    def enabled(self, app):
        automated = self.automated(app)
        return isinstance(automated, dict) and automated.get("selfHeal") is True

    def activate(self, arm) -> ArmEvidence:
        if arm not in ARMS:
            raise SafetyError(f"unknown arm {arm!r}")
        apps = {name: self.get_app(name) for name in (self.apps_app, self.app)}
        if arm == "gitops":
            for name, app in apps.items():
                if not self.enabled(app):
                    raise ArmStateError(
                        f"{name} does not have automated sync/selfHeal enabled")
            return ArmEvidence(arm=arm, original={}, applications={
                name: sanitize_application(app) for name, app in apps.items()
            }, paused=False)
        for name, app in apps.items():
            if not self.enabled(app):
                raise ArmStateError(
                    f"{name} is not enabled; refusing to stack arm state")
        self.original = {
            name: {"spec": sanitize_application(app)["spec"],
                   "automated": copy.deepcopy(self.automated(app))}
            for name, app in apps.items()
        }
        try:
            for name in (self.apps_app, self.app):
                result = self.kubectl.patch(
                    "Application", name, self.argo_namespace,
                    {"spec": {"syncPolicy": {"automated": None}}}, "merge")
                if not result.ok:
                    raise ArmStateError(
                        f"failed to pause {name}: {result.stderr.strip()[:200]}")
                current = self.get_app(name)
                if self.automated(current) is not None:
                    raise ArmStateError(f"{name} is still auto-syncing")
        except Exception:
            try:
                self.restore()
            except ArmRestoreError as error:
                raise ArmRestoreError(
                    f"pause failed and restore failed: {error}") from None
            raise
        current = {name: self.get_app(name)
                   for name in (self.apps_app, self.app)}
        return ArmEvidence(arm=arm, original={
            name: copy.deepcopy(item["spec"]) for name, item in self.original.items()
        }, applications={name: sanitize_application(app)
                         for name, app in current.items()},
            paused=True)

    def restore(self):
        if not self.original:
            return None
        errors = []
        for name in (self.app, self.apps_app):
            patch = {"spec": {"syncPolicy": {
                "automated": copy.deepcopy(self.original[name]["automated"])}}}
            result = self.kubectl.patch("Application", name, self.argo_namespace,
                                        patch, "merge")
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


def _short(run_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", run_id)[-8:]


def _deployment_manifest(contract: Contract) -> dict:
    resource = next((item for item in contract.resources
                     if item["id"] == "Deployment/" + WEB_DEPLOYMENT), None)
    if resource is None:
        raise InjectionError("baseline Deployment/invenio-web is missing")
    return resource["manifest"]


def _field(contract: Contract, resource_id_value: str, path: str):
    resource = next((item for item in contract.resources
                     if item["id"] == resource_id_value), None)
    if resource is None:
        raise InjectionError(f"baseline resource {resource_id_value} is missing")
    if path not in resource["fields"]:
        raise InjectionError(f"baseline field {path} is missing")
    return resource["fields"][path]


def _configmap_name(contract: Contract) -> str:
    if not contract.configmap_name:
        raise InjectionError("generated invenio-app-config ConfigMap is missing")
    return contract.configmap_name


def inject(kubectl, contract: Contract, scenario: str, run_id: str,
           clock: Clock) -> Injection:
    if scenario not in SCENARIOS:
        raise SafetyError(f"unknown scenario {scenario!r}")
    started = clock.now()
    short = _short(run_id)
    commands = []
    changed = []
    expected_path = None
    expected_value = None
    expected_baseline = None
    effect = "value_changed"
    try:
        if scenario == "A":
            baseline_replicas = (contract.baseline_hpa or {}).get(
                "deployment_spec_replicas")
            if type(baseline_replicas) is not int:
                raise InjectionError(
                    "baseline HPA did not retain the observed replicas")
            minimum = (contract.baseline_hpa or {}).get("min") or 2
            target = max(1, int(minimum) - 1) if int(minimum) > 1 else int(minimum) + 1
            if target == baseline_replicas:
                candidates = (max(1, int(minimum) - 1), int(minimum) + 1)
                target = next(value for value in candidates
                              if value != baseline_replicas)
            commands.append(kubectl.patch(
                "Deployment", WEB_DEPLOYMENT, contract.namespace,
                {"spec": {"replicas": target}}, "merge"))
            expected_path = "/spec/replicas"
            expected_value = target
            expected_baseline = baseline_replicas
        elif scenario == "B":
            image = _field(contract, "Deployment/" + WEB_DEPLOYMENT,
                           "/spec/template/spec/containers/web/image")
            repository = image.split("@")[0]
            if ":" in repository.rsplit("/", 1)[-1]:
                repository = repository.rsplit(":", 1)[0]
            target = repository + ":drift-" + short
            if target == image:
                raise InjectionError(
                    "drift image is identical to the declared image")
            commands.append(kubectl.patch(
                "Deployment", WEB_DEPLOYMENT, contract.namespace,
                {"spec": {"template": {"spec": {"containers": [
                    {"name": "web", "image": target}]}}}}, "strategic"))
            expected_path = "/spec/template/spec/containers/web/image"
            expected_value = target
            expected_baseline = image
        elif scenario == "C":
            name = _configmap_name(contract)
            key = CONFIG_KEY
            expected_baseline = _field(contract, "ConfigMap/" + name,
                                       "/data/" + key)
            target = CONFIG_DRIFT + "-" + short
            if target == expected_baseline:
                raise InjectionError(
                    "drift ConfigMap value is identical to the declared value")
            commands.append(kubectl.patch(
                "ConfigMap", name, contract.namespace,
                {"data": {key: target}}, "merge"))
            expected_path = "/data/" + key
            expected_value = target
        elif scenario == "D":
            commands.append(kubectl.delete(
                "Deployment", WEB_DEPLOYMENT, contract.namespace, wait=True))
            expected_path = "/metadata/name"
            expected_baseline = "present"
            effect = "deleted"
        elif scenario == "E":
            path = ("/spec/template/spec/containers/web/"
                    "resources/limits/memory")
            baseline = _field(contract, "Deployment/" + WEB_DEPLOYMENT, path)
            target = next(
                (candidate for candidate in (
                    MEMORY_LIMIT_DRIFT, MEMORY_LIMIT_DRIFT_FALLBACK)
                 if not _field_matches(path, baseline, candidate)),
                None)
            if target is None:
                raise InjectionError(
                    "no distinct memory limit drift quantity is available")
            commands.append(kubectl.patch(
                "Deployment", WEB_DEPLOYMENT, contract.namespace,
                {"spec": {"template": {"spec": {"containers": [
                    {"name": "web", "resources": {
                        "limits": {"memory": target}}}]}}}}, "strategic"))
            expected_path = path
            expected_value = target
            expected_baseline = baseline
        elif scenario == "F":
            manifest = copy.deepcopy(_deployment_manifest(contract))
            manifest["metadata"]["namespace"] = contract.quarantine_namespace
            manifest["metadata"].setdefault("labels", {})[
                "experiment.invenio.ugm/quarantine"] = short
            manifest["metadata"]["labels"][
                "experiment.invenio.ugm/run-id"] = run_id
            manifest.setdefault("spec", {})["replicas"] = 0
            manifest = recovery_manifest(manifest)
            if kubectl.get("Namespace", contract.quarantine_namespace) is None:
                commands.append(kubectl.apply({
                    "apiVersion": "v1", "kind": "Namespace",
                    "metadata": {
                        "name": contract.quarantine_namespace,
                        "labels": {
                            "experiment.invenio.ugm/quarantine": short,
                            "experiment.invenio.ugm/run-id": run_id,
                        },
                    }}))
            commands.append(kubectl.apply(manifest))
            expected_path = "/metadata/namespace"
            expected_value = contract.quarantine_namespace
            expected_baseline = "absent"
            effect = "created"
        elif scenario == "G":
            target = "scenario-g-" + short
            commands.append(kubectl.annotate(
                "SealedSecret", SEALED_SECRET, contract.namespace,
                DRIFT_ANNOTATION, target))
            expected_path = "/metadata/annotations/" + DRIFT_ANNOTATION
            expected_value = target
            expected_baseline = None
    except HarnessError:
        raise
    except Exception as error:
        raise InjectionError(
            f"injection command failed: {type(error).__name__}") from None

    acknowledged = clock.now()
    failed = next((command for command in commands if not command.ok), None)
    if failed is not None:
        error = InjectionError(
            f"kubectl mutation failed with exit {failed.returncode}")
        error.injection = Injection(
            started=started, acknowledged=acknowledged, verified=None,
            accepted=False, changed=[], commands=commands, error=str(error))
        raise error

    try:
        if scenario == "A":
            observed = kubectl.get("Deployment", WEB_DEPLOYMENT, contract.namespace)
            actual = (observed or {}).get("spec", {}).get("replicas")
            if actual != expected_value:
                raise InjectionError("/spec/replicas did not change")
            changed.append({"resource": "Deployment/" + WEB_DEPLOYMENT,
                            "path": expected_path, "effect": effect,
                            "matches_desired": False,
                            "expected": expected_baseline, "actual": actual})
        elif scenario == "B":
            observed = kubectl.get("Deployment", WEB_DEPLOYMENT, contract.namespace)
            container = _container(observed or {})
            actual = container.get("image") if container else None
            if actual != expected_value:
                raise InjectionError(
                    "/spec/template/spec/containers/web/image did not change")
            changed.append({"resource": "Deployment/" + WEB_DEPLOYMENT,
                            "path": expected_path, "effect": effect,
                            "matches_desired": False,
                            "expected": expected_baseline, "actual": actual})
        elif scenario == "C":
            name = _configmap_name(contract)
            observed = kubectl.get("ConfigMap", name, contract.namespace)
            actual = (observed or {}).get("data", {}).get(CONFIG_KEY)
            if actual != expected_value:
                raise InjectionError("/data/" + CONFIG_KEY + " did not change")
            changed.append({"resource": "ConfigMap/" + name,
                            "path": expected_path, "effect": effect,
                            "matches_desired": False,
                            "expected": expected_baseline, "actual": actual})
        elif scenario == "D":
            if kubectl.get("Deployment", WEB_DEPLOYMENT,
                           contract.namespace) is not None:
                raise InjectionError("Deployment/invenio-web was not deleted")
            changed.append({"resource": "Deployment/" + WEB_DEPLOYMENT,
                            "path": expected_path, "effect": effect,
                            "matches_desired": False,
                            "expected": expected_baseline, "actual": "deleted"})
        elif scenario == "E":
            observed = kubectl.get("Deployment", WEB_DEPLOYMENT, contract.namespace)
            container = _container(observed or {})
            actual = ((container or {}).get("resources", {}).get("limits", {})
                      .get("memory"))
            if actual is None or not _field_matches(
                    expected_path, expected_value, actual):
                raise InjectionError(
                    "/spec/template/spec/containers/web/resources/limits/memory "
                    "did not change")
            changed.append({"resource": "Deployment/" + WEB_DEPLOYMENT,
                            "path": expected_path, "effect": effect,
                            "matches_desired": False,
                            "expected": expected_baseline, "actual": actual})
        elif scenario == "F":
            observed = kubectl.get("Deployment", WEB_DEPLOYMENT,
                                   contract.quarantine_namespace)
            if observed is None:
                raise InjectionError("quarantine Deployment was not created")
            changed.append({
                "resource": f"{contract.quarantine_namespace}/Deployment/"
                            + WEB_DEPLOYMENT,
                "path": expected_path, "effect": effect,
                "matches_desired": False,
                "expected": expected_baseline,
                "actual": contract.quarantine_namespace})
        elif scenario == "G":
            observed = kubectl.get("SealedSecret", SEALED_SECRET,
                                   contract.namespace)
            actual = ((observed or {}).get("metadata", {}).get("annotations") or {}
                      ).get(DRIFT_ANNOTATION)
            if actual != expected_value:
                raise InjectionError("metadata annotation did not change")
            changed.append({"resource": "SealedSecret/" + SEALED_SECRET,
                            "path": expected_path, "effect": effect,
                            "matches_desired": False,
                            "expected": expected_baseline, "actual": actual})
    except InjectionError as error:
        error.injection = Injection(
            started=started, acknowledged=acknowledged, verified=None,
            accepted=False, changed=changed, commands=commands, error=str(error),
            verification_started=acknowledged)
        raise error
    except HarnessError as error:
        error.injection = Injection(
            started=started, acknowledged=acknowledged, verified=None,
            accepted=False, changed=changed, commands=commands, error=str(error),
            verification_started=acknowledged)
        raise
    except Exception as error:
        raise InjectionError(
            f"injection verification failed: {type(error).__name__}") from None

    return Injection(started=started, acknowledged=acknowledged,
                     verified=clock.now(), accepted=True, changed=changed,
                     commands=commands, error=None,
                     verification_started=acknowledged)


def repair(kubectl, contract: Contract, observation: Observation,
           clock: Clock) -> list:
    commands = []
    for expected in contract.resources:
        actual = observation.resources.get(expected["id"])
        if actual is None:
            if expected["kind"] == "SealedSecret":
                continue
            manifest = recovery_manifest(
                expected["manifest"],
                hpa_owned=expected["id"] in contract.hpa_targets)
            commands.append(kubectl.apply(manifest))
            continue
        values = actual.get("fields") or {}
        diffs = [diff for diff in field_diffs(contract, observation)
                 if diff["resource"] == expected["id"] and not diff.get("missing")]
        if not diffs:
            continue
        if expected["kind"] == "Deployment":
            fields = {diff["path"]: diff["expected"] for diff in diffs}
            container_patch = {"name": "web"}
            image = fields.get("/spec/template/spec/containers/web/image")
            if image is not None:
                container_patch["image"] = image
            resources = {}
            for path, value in fields.items():
                prefix = "/spec/template/spec/containers/web/resources/"
                if path.startswith(prefix):
                    parts = path[len(prefix):].split("/")
                    if len(parts) == 2:
                        resources.setdefault(parts[0], {})[parts[1]] = value
            if resources:
                container_patch["resources"] = resources
            if len(container_patch) > 1:
                commands.append(kubectl.patch(
                    "Deployment", expected["name"], contract.namespace,
                    {"spec": {"template": {"spec": {"containers": [
                        container_patch]}}}}, "strategic"))
            else:
                commands.append(kubectl.apply(
                    recovery_manifest(expected["manifest"],
                                      hpa_owned=expected["id"] in
                                      contract.hpa_targets)))
        elif expected["kind"] == "ConfigMap":
            patch = {}
            for diff in diffs:
                if diff["path"].startswith("/data/"):
                    patch[diff["path"][len("/data/"):]] = diff["expected"]
            if patch:
                commands.append(kubectl.patch(
                    "ConfigMap", expected["name"], contract.namespace,
                    {"data": patch}, "merge"))
        elif expected["kind"] == "SealedSecret":
            for diff in diffs:
                if diff["path"].startswith("/metadata/annotations/"):
                    key = diff["path"][len("/metadata/annotations/"):]
                    if values.get(diff["path"]) is not None:
                        commands.append(kubectl.annotate(
                            "SealedSecret", expected["name"], contract.namespace,
                            key, None))
        else:
            commands.append(kubectl.apply(
                recovery_manifest(expected["manifest"],
                                  hpa_owned=expected["id"] in contract.hpa_targets)))
    return commands


def cleanup_g_annotation(kubectl, namespace: str) -> CleanupReport:
    """Remove the test annotation from the Git-managed SealedSecret."""
    try:
        sealed = kubectl.get("SealedSecret", SEALED_SECRET, namespace)
        annotations = ((sealed or {}).get("metadata") or {}).get("annotations") or {}
        if DRIFT_ANNOTATION not in annotations:
            return CleanupReport(ok=True, results=[], errors=[])
        result = kubectl.annotate("SealedSecret", SEALED_SECRET, namespace,
                                  DRIFT_ANNOTATION, None)
        if not result.ok:
            return CleanupReport(
                ok=False, results=[result],
                errors=[f"remove {DRIFT_ANNOTATION} failed: "
                        f"{result.stderr.strip()[:200]}"])
        return CleanupReport(ok=True, results=[result], errors=[])
    except HarnessError as error:
        return CleanupReport(ok=False, results=[],
                             errors=[f"annotation cleanup failed: {error}"])


def cleanup_quarantine(kubectl, quarantine: str, owner: str | None = None,
                       wait_seconds: float = 30.0) -> CleanupReport:
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
            "experiment.invenio.ugm/run-id")
        if label != owner:
            return CleanupReport(
                ok=False, results=[],
                errors=[f"refusing to delete {quarantine}: owner label mismatch"])
    for kind, name in (("Deployment", WEB_DEPLOYMENT), ("Namespace", quarantine)):
        try:
            result = kubectl.delete(kind, name, quarantine if kind == "Deployment"
                                    else None)
            results.append(result)
            if not result.ok and "not found" not in result.stderr.lower():
                errors.append(
                    f"delete {kind}/{name} failed: {result.stderr.strip()[:200]}")
        except HarnessError as error:
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
    diffs = field_diffs(contract, observation)
    sanitized = []
    for diff in diffs:
        item = {"resource": diff["resource"], "path": diff.get("path"),
                "missing": bool(diff.get("missing"))}
        if "expected" in diff:
            item["expected"] = diff["expected"]
            item["actual"] = diff["actual"]
        sanitized.append(item)
    return sanitized


def _metric_status(value, stop_reason):
    if value is not None:
        return "observed"
    return "right_censored" if stop_reason == "timeout" else "unobserved_before_stop"


def _finite_mono(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _validate_acquisition(observation: Observation) -> dict:
    acquisition = observation.acquisition
    if not isinstance(acquisition, dict):
        raise InstrumentationError("observation has no acquisition bounds")
    started = acquisition.get("started_mono")
    finished = acquisition.get("finished_mono")
    if not _finite_mono(started) or not _finite_mono(finished):
        raise InstrumentationError("capture bounds are not finite")
    if started > finished:
        raise InstrumentationError("capture bounds are not ordered")
    reads = acquisition.get("reads")
    if not isinstance(reads, dict) or not reads:
        raise InstrumentationError("observation has no read bounds")
    for key, record in reads.items():
        if not isinstance(record, dict):
            raise InstrumentationError(f"read bounds for {key} are not an object")
        read_started = record.get("started_mono")
        read_finished = record.get("finished_mono")
        if not _finite_mono(read_started) or not _finite_mono(read_finished):
            raise InstrumentationError(f"read bounds for {key} are not finite")
        if read_started > read_finished:
            raise InstrumentationError(f"read bounds for {key} are not ordered")
        if read_started < started or read_finished > finished:
            raise InstrumentationError(
                f"read bounds for {key} fall outside the capture")
        if type(record.get("ok")) is not bool:
            raise InstrumentationError(f"read outcome for {key} is not boolean")
    return acquisition


def _read(sample: Observation, key: str) -> dict | None:
    reads = sample.acquisition.get("reads") or {}
    record = reads.get(key)
    return record if isinstance(record, dict) else None


def _read_eligible(sample: Observation, key: str, t0: float,
                   deadline: float) -> bool:
    record = _read(sample, key)
    if record is None or record.get("ok") is not True:
        return False
    return (record["started_mono"] >= t0
            and record["finished_mono"] <= deadline)


def _reads_eligible(sample: Observation, keys, t0: float,
                    deadline: float) -> bool:
    return all(_read_eligible(sample, key, t0, deadline) for key in keys)


def _read_completion(sample: Observation, keys) -> Point:
    latest = max((_read(sample, key) for key in keys),
                 key=lambda record: record["finished_mono"])
    return Point(latest["finished_mono"], latest["finished_utc"])


def _complete_match_completion(sample: Observation, keys) -> Point | None:
    records = [_read(sample, key) for key in keys]
    if not records or any(record is None or record.get("ok") is not True
                          for record in records):
        return None
    latest = max(records, key=lambda record: record["finished_mono"])
    return Point(latest["finished_mono"], latest["finished_utc"])


def _diff_keys(contract: Contract, sample: Observation) -> list:
    return sorted({diff["resource"] for diff in field_diffs(contract, sample)})


def _r1_keys(contract: Contract) -> list:
    return [resource["id"] for resource in contract.resources]


def _hpa_keys() -> list:
    return ["Deployment/" + WEB_DEPLOYMENT,
            "HorizontalPodAutoscaler/" + WEB_HPA]


def _recovery_keys(contract: Contract, scenario: str,
                   sample: Observation) -> list:
    keys = _r1_keys(contract)
    if scenario == "A":
        keys = list(dict.fromkeys(keys + _hpa_keys()))
    elif scenario == "F":
        keys.append("Namespace/" + contract.quarantine_namespace)
        if sample.extra_resources:
            keys.append(
                f"{contract.quarantine_namespace}/Deployment/" + WEB_DEPLOYMENT)
    return keys


def _post_injection(sample: Observation, t0: float) -> bool:
    acquisition = sample.acquisition
    return acquisition["finished_mono"] >= t0


def _imperative_event_keys(contract: Contract, sample: Observation,
                           event: Point, t0: float, deadline: float) -> list | None:
    if event is None or not _finite_mono(event.mono):
        return None
    if event.mono < t0 or event.mono > deadline:
        return None
    keys = _diff_keys(contract, sample)
    if not keys or not _reads_eligible(sample, keys, t0, deadline):
        return None
    if _read_completion(sample, keys).mono > event.mono:
        return None
    return keys


def _evaluation_keys(contract: Contract, sample: Observation,
                     scenario: str) -> list | None:
    if sample.evaluated_signal is not True:
        return None
    if scenario == "A":
        return _hpa_keys()
    keys = list(sample.evaluated_reads or [])
    if not keys:
        return None
    if not set(keys).issubset(set(_diff_keys(contract, sample))):
        return None
    return keys


def _evaluation_evidence(post, contract: Contract, scenario: str,
                         t0: float, deadline: float, evidence_at=None):
    for sample in post:
        keys = _evaluation_keys(contract, sample, scenario)
        if keys is None:
            continue
        event = sample.evaluated_at
        if evidence_at is not None:
            if event is not None and not math.isclose(
                    event.mono, evidence_at.mono, rel_tol=1e-9, abs_tol=1e-9):
                raise InstrumentationError(
                    "evidence evaluation disagrees with the persisted event")
            event = evidence_at
        if event is None or not _finite_mono(event.mono):
            continue
        if event.mono < t0 or event.mono > deadline:
            continue
        if not _reads_eligible(sample, keys, t0, deadline):
            continue
        if any(_read(sample, key)["finished_mono"] > event.mono
               for key in keys):
            continue
        return event, keys
    return None, []


def _recovered(contract, observation, scenario):
    if score(contract, observation) != 100:
        return False
    if scenario == "A":
        return hpa_settled(observation.hpa)
    if scenario == "F":
        return not observation.extra_resources
    return True


def analyze_timeline(contract: Contract, samples: list, injection: Injection,
                     arm: str, scenario: str, timeout: float,
                     imperative: ImperativeRun | None = None,
                     evidence_at: Point | None = None,
                     provided_evidence_ref: str | None = None,
                     app: str = DEFAULT_APP,
                     baseline: Observation | None = None,
                     window_completed: bool | None = None,
                     window_end: Point | None = None) -> dict:
    samples = sorted(samples, key=lambda item: item.at.mono)
    for sample in samples:
        _validate_acquisition(sample)
    t0 = injection.started.mono
    deadline = t0 + timeout
    post = [sample for sample in samples if _post_injection(sample, t0)]
    detection = None
    evidence = None
    recovery = None
    recovery_pair = None
    detection_reads = []
    evidence_reads = []
    recovery_reads = []
    t_r_first = None
    t_r_confirmed = None
    confirmation = "none"
    argo_seen = False

    if injection.accepted:
        for sample in post:
            if scenario in "BCDEFG":
                state = sample.argo.get(app)
                if state and argo_signal(state) and _read_eligible(
                        sample, "Application/" + app, t0, deadline):
                    argo_seen = True
            if detection is None and scenario == "A" and hpa_changed(
                    contract.baseline_hpa, sample.hpa):
                keys = _hpa_keys()
                if _reads_eligible(sample, keys, t0, deadline):
                    detection = _read_completion(sample, keys)
                    detection_reads = keys
            if (detection is None and arm == "gitops"
                    and scenario in "BCDEG"
                    and argo_signal(sample.argo.get(app))):
                key = "Application/" + app
                if _read_eligible(sample, key, t0, deadline):
                    detection = _read_completion(sample, [key])
                    detection_reads = [key]

        if scenario != "F" and not (imperative and scenario in "BCDEG"):
            evidence, evidence_reads = _evaluation_evidence(
                post, contract, scenario, t0, deadline, evidence_at)

        if imperative and scenario in "BCDEG":
            for sample in post:
                if imperative.detection_at is not None:
                    keys = _imperative_event_keys(
                        contract, sample, imperative.detection_at, t0, deadline)
                    if keys:
                        detection = imperative.detection_at
                        detection_reads = keys
                        break
            for sample in post:
                if imperative.evidence_at is not None:
                    keys = _imperative_event_keys(
                        contract, sample, imperative.evidence_at, t0, deadline)
                    if keys:
                        evidence = imperative.evidence_at
                        evidence_reads = keys
                        break

        previous_match = None
        first_match = None
        late_match = False
        for sample in post:
            keys = _recovery_keys(contract, scenario, sample)
            eligible = _reads_eligible(sample, keys, t0, deadline)
            match = _recovered(contract, sample, scenario)
            if not match:
                previous_match = None
                continue
            completion = _complete_match_completion(sample, keys)
            if completion is not None and completion.mono > deadline:
                late_match = True
            if not eligible:
                previous_match = None
                continue
            completion = _read_completion(sample, keys)
            if first_match is None:
                first_match = completion
            if previous_match is not None:
                recovery_pair = (previous_match, completion)
                recovery = previous_match
                t_r_first = previous_match
                t_r_confirmed = completion
                recovery_reads = keys
                confirmation = "confirmed"
                break
            previous_match = completion
        if recovery is None and first_match is not None:
            t_r_first = first_match
            confirmation = ("late_confirmation" if late_match
                            else "missing_confirmation")

    if scenario == "A":
        detection_ref = "hpa:invenio-web-hpa" if detection else None
    elif scenario == "F":
        detection_ref = None
    elif arm == "imperative":
        detection_ref = "imperative:contract-diff" if detection else None
    else:
        detection_ref = "argo:invenio-bootstrap" if detection else None
    evidence_ref = None
    if evidence is not None:
        if imperative and scenario in "BCDEG" and imperative.evidence_ref:
            evidence_ref = imperative.evidence_ref
        elif scenario == "A":
            evidence_ref = "samples.jsonl"
        elif provided_evidence_ref:
            evidence_ref = provided_evidence_ref
    stop_reason = "recovery" if recovery is not None else "timeout"
    if not injection.accepted:
        status = "invalid_injection"
    elif imperative and (imperative.failed or any(
            not command.ok for command in imperative.commands)):
        status = "recovery_failure"
    elif recovery is not None:
        status = "observed"
    else:
        status = "right_censored"

    if scenario == "A":
        detection_controller = "hpa"
        recovery_controller = "hpa" if recovery is not None else "unattributed"
    elif scenario == "F":
        detection_controller = "unattributed"
        recovery_controller = "unattributed"
    elif arm == "imperative":
        detection_controller = "imperative" if detection else "unattributed"
        recovery_controller = ("imperative" if any(
            command.ok for command in (imperative.commands if imperative else []))
            else "unattributed")
    else:
        detection_controller = "argocd" if detection else "unattributed"
        recovery_controller = "argocd" if argo_seen and recovery else "unattributed"

    def duration(at):
        return None if at is None else at.mono - t0

    r1_keys = _r1_keys(contract)
    eligible_r1 = [sample for sample in post
                   if _reads_eligible(sample, r1_keys, t0, deadline)]
    r1_first = eligible_r1[0] if eligible_r1 else None
    r1_last = eligible_r1[-1] if eligible_r1 else None
    if not post:
        r1_reason = "no_samples"
    elif not eligible_r1:
        r1_reason = "no_eligible_capture"
    else:
        r1_reason = None

    gaps = [right.at.mono - left.at.mono
            for left, right in zip(samples, samples[1:])]
    observation_end = None
    if samples:
        acquisition = samples[-1].acquisition
        observation_end = Point(acquisition["finished_mono"],
                                acquisition["finished_utc"])
    return {
        "schema_version": 2,
        "timing_convention": TIMING_CONVENTION,
        "status": status,
        "stop_reason": stop_reason,
        "window_completed": (True if recovery is not None else window_completed),
        "window_end": window_end,
        "detection_seconds": duration(detection),
        "evidence_seconds": duration(evidence),
        "recovery_seconds": duration(recovery),
        "detection_status": _metric_status(detection, stop_reason),
        "evidence_status": _metric_status(evidence, stop_reason),
        "recovery_status": _metric_status(recovery, stop_reason),
        "injection_seconds": injection.acknowledged.mono - t0,
        "censor_seconds": timeout,
        "max_sample_gap_seconds": max(gaps) if gaps else None,
        "observation_end": observation_end,
        "detection_controller": detection_controller,
        "recovery_controller": recovery_controller,
        "detection_ref": detection_ref,
        "evidence_ref": evidence_ref,
        "detection_reads": detection_reads,
        "evidence_reads": evidence_reads,
        "recovery_reads": recovery_reads,
        "t_r_first_seconds": duration(t_r_first),
        "t_r_confirmed_seconds": duration(t_r_confirmed),
        "recovery_confirmation": confirmation,
        "r1_baseline": (score(contract, baseline) if baseline is not None
                        else None),
        "r1_first": score(contract, r1_first) if r1_first else None,
        "r1_last": score(contract, r1_last) if r1_last else None,
        "r1_baseline_details": (resource_results(contract, baseline)
                                if baseline is not None else None),
        "r1_first_details": (resource_results(contract, r1_first)
                             if r1_first is not None else None),
        "r1_last_details": (resource_results(contract, r1_last)
                            if r1_last is not None else None),
        "r1_baseline_reason": (None if baseline is not None
                               else "baseline_not_observed"),
        "r1_first_reason": r1_reason,
        "r1_last_reason": r1_reason,
        "kubectl_cmds": len(imperative.commands) if imperative else 0,
        "analysis_group": ("hpa_control" if scenario == "A" else
                           "visibility_boundary" if scenario == "F" else
                           "managed_drift"),
        "efficacy_eligible": scenario not in ("A", "F"),
        "t0": injection.started,
        "t_a": injection.acknowledged,
        "t_d": detection,
        "t_e": evidence,
        "t_r": recovery,
        "t_r_first": t_r_first,
        "t_r_confirmed": t_r_confirmed,
        "t_e_store": (imperative.evidence_store_at
                      if imperative and evidence is not None else None),
        "recovery_pair": recovery_pair,
        "samples": len(samples),
    }


def dry_run_row(run_id, arm, scenario, rep, namespace, app, args) -> dict:
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
        "analysis_group": ("hpa_control" if scenario == "A" else
                           "visibility_boundary" if scenario == "F" else
                           "managed_drift"),
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
        "planned_mutations": planned_mutations(scenario,
                                               quarantine_namespace(namespace)),
        "safety": {
            "live": False,
            "namespace_allowed": True,
            "one_stack_required": True,
        },
    }


def planned_mutations(scenario, quarantine="exp-<namespace>-drift"):
    table = {
        "A": ["patch Deployment/invenio-web /spec/replicas (HPA-owned)"],
        "B": ["patch Deployment/invenio-web container web image"],
        "C": ["patch ConfigMap/invenio-app-config-<hash> data key"],
        "D": ["delete Deployment/invenio-web"],
        "E": ["patch Deployment/invenio-web container web memory limit"],
        "F": [f"apply sanitized Deployment into {quarantine}"],
        "G": ["annotate SealedSecret/invenio-app-secrets metadata only"],
    }
    return table.get(scenario, [])


def parse_args(argv=None):
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
        token == "--namespace" or token.startswith("--namespace=")
        for token in tokens)
    args.app_explicit = any(
        token == "--app" or token.startswith("--app=") for token in tokens)
    args.namespace = args.namespace or DEFAULT_NAMESPACE
    args.app = args.app or DEFAULT_APP
    if args.rep < 1:
        parser.error("--rep must be >= 1")
    for name in ("timeout", "sample_interval", "imperative_interval",
                 "baseline_timeout", "reset_timeout"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.source_revision and not re.fullmatch(r"[0-9a-f]{40}",
                                                 args.source_revision):
        parser.error("--source-revision must be 40 lowercase hex")
    if args.render_sha256 and not re.fullmatch(r"[0-9a-f]{64}",
                                               args.render_sha256):
        parser.error("--render-sha256 must be 64 lowercase hex")
    if args.run_id and not re.fullmatch(r"[A-Za-z0-9._-]+", args.run_id):
        parser.error("--run-id may only contain letters, digits, dot, dash, underscore")
    if args.run_id and len(args.run_id) > 63:
        parser.error("--run-id must be at most 63 characters for label values")
    return args


def validate_live_args(args, environ=None):
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
        raise SafetyError(
            "--render-sha256 is required in live mode; freeze the render first")
    if not args.source_revision:
        raise SafetyError(
            "--source-revision is required in live mode; freeze the revision first")
    if not args.render_file:
        raise SafetyError(
            "--render-file is required in live mode; freeze the render bundle first")
    if "://" in args.render_file:
        raise SafetyError("--render-file must be a local file, not a URL")
    try:
        frozen = load_declaration(
            args.render_file, args.render_sha256, args.source_revision,
            args.namespace)
    except DeclarationError as error:
        raise SafetyError(f"invalid frozen render: {error}") from None
    http = Http(token, base_url=args.invenio_url)
    seed = verify_seed(http, args.seed_record, args.seed_file, args.seed_size,
                       args.seed_md5, args.seed_sha256)
    return {"http": http, "seed": seed, "declaration": frozen}


class Sampler(threading.Thread):
    def __init__(self, capture, clock, interval, join_timeout=10.0,
                 guarded=False):
        super().__init__(daemon=True)
        self.capture = capture
        self.clock = clock
        self.interval = interval
        self.join_timeout = join_timeout
        self.guarded = guarded
        self.samples = []
        self.error = None
        self.late_error = None
        self.deadline = None
        self.stopped_at_deadline = False
        self.stopped_capture = None
        self.capture_stop_reason = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._closed = False
        self._late_result = None
        self._late_result_at = None
        self._late_result_acquisition = None

    def _guard(self):
        if self._stop_event.is_set():
            return "stop"
        if (self.deadline is not None
                and self.clock.now().mono >= self.deadline):
            self.stopped_at_deadline = True
            return "deadline"
        return None

    def run(self):
        while True:
            if self._stop_event.is_set():
                return
            if (self.deadline is not None
                    and self.clock.now().mono >= self.deadline):
                self.stopped_at_deadline = True
                self._ready_event.set()
                return
            if self._stop_event.is_set():
                return
            started = self.clock.now()
            try:
                if self.guarded:
                    sample = self.capture(guard=self._guard)
                else:
                    sample = self.capture()
            except CaptureStopped as stopped:
                with self._lock:
                    self.stopped_capture = copy.deepcopy(stopped.acquisition)
                    self.capture_stop_reason = stopped.reason
                self._ready_event.set()
                return
            except Exception as error:  # noqa: BLE001 - preserved as evidence
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
                        self._late_result_acquisition = copy.deepcopy(
                            sample.acquisition)
                else:
                    self.samples.append(sample)
                self._ready_event.set()
            elapsed = self.clock.now().mono - started.mono
            self._stop_event.wait(max(0.0, self.interval - elapsed))

    def wait_ready(self, timeout=10.0):
        return self._ready_event.wait(timeout)

    def snapshot(self):
        with self._lock:
            return list(self.samples)

    def stop(self, timeout=None):
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
                "late_result_acquisition": copy.deepcopy(
                    self._late_result_acquisition),
                "late_error": (str(self.late_error)
                               if self.late_error else None),
                "stopped_at_deadline": self.stopped_at_deadline,
                "partial_acquisition": copy.deepcopy(self.stopped_capture),
                "capture_stop_reason": self.capture_stop_reason,
            }


def verify_one_stack(kubectl, namespace, app, argo_namespace):
    deployments = kubectl.get(
        "Deployment",namespace=None,
        selector="app.kubernetes.io/name=" + WEB_DEPLOYMENT)
    if not isinstance(deployments, list):
        raise SafetyError("could not inventory invenio-web Deployments")
    namespaces = {(item.get("metadata") or {}).get("namespace")
                  for item in deployments}
    if namespaces != {namespace}:
        raise SafetyError(
            "one stack only: expected invenio-web only in "
            f"{namespace}, found {sorted(namespaces)}")
    application = kubectl.get("Application", app, argo_namespace)
    if application is None:
        raise SafetyError(f"Argo Application {app} is missing")
    destination = ((application.get("spec") or {}).get("destination") or {}).get(
        "namespace")
    if destination != namespace:
        raise SafetyError(
            f"Argo Application {app} targets {destination}, not {namespace}")
    if kubectl.get("Namespace", quarantine_namespace(namespace)) is not None:
        raise SafetyError("quarantine namespace already exists; clean it first")


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def ensure_new_run(args, run_id):
    out = Path(args.out)
    jsonl = out / (run_id + ".jsonl")
    evidence_dir = out / run_id
    if jsonl.exists() or (evidence_dir.exists() and any(evidence_dir.iterdir())):
        raise SafetyError(f"refusing to overwrite existing run output {run_id}")


def write_outputs(row, args, evidence_dir: Path, evidence: dict) -> None:
    try:
        from .convert import write_csv
    except ImportError:
        from convert import write_csv  # direct script execution
    run_id = row["run_id"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    jsonl = out / (run_id + ".jsonl")
    if jsonl.exists():
        raise SafetyError(f"refusing to overwrite existing run output {jsonl}")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    jsonl.write_text(
        json.dumps(row, sort_keys=True, default=str) + "\n")
    write_csv([row], out / (run_id + ".csv"))
    for name, payload in evidence.items():
        if name in ("samples", "commands"):
            with (evidence_dir / (name + ".jsonl")).open("w") as handle:
                for item in payload:
                    handle.write(json.dumps(item, sort_keys=True,
                                            default=str) + "\n")
        else:
            _write_json(evidence_dir / (name + ".json"), payload)


def _point_dict(point):
    return {"mono": point.mono, "utc": point.utc} if point else None


class LiveRunner:
    def __init__(self, args, preflight, kubectl, clock):
        self.args = args
        self.preflight = preflight
        self.kubectl = kubectl
        self.clock = clock
        self.quarantine = quarantine_namespace(args.namespace)
        self.collector_started = None

    def _declaration(self) -> Declaration:
        frozen = (self.preflight or {}).get("declaration")
        if not isinstance(frozen, Declaration):
            raise SafetyError(
                "live runner requires a validated frozen render declaration")
        if (frozen.source_revision != self.args.source_revision
                or frozen.render_sha256 != self.args.render_sha256):
            raise SafetyError(
                "frozen render identity does not match the live run arguments")
        if any(resource["namespace"] != self.args.namespace
               for resource in frozen.resources):
            raise SafetyError(
                "frozen render namespace does not match --namespace")
        return frozen

    @staticmethod
    def _require_baseline_agreement(contract: Contract,
                                    baseline: Observation) -> None:
        diffs = field_diffs(contract, baseline)
        if not diffs:
            return
        first = diffs[0]
        if first.get("missing"):
            detail = (f"live baseline is missing {first['resource']}; "
                      "the frozen declaration requires it")
        else:
            detail = ("live baseline differs from the frozen declaration at "
                      f"{first['resource']} {first['path']} "
                      f"({len(diffs)} field(s))")
        baseline.readiness_failures.append(_readiness_record(
            baseline,
            [{"code": "declaration_mismatch", "detail": detail,
              "retryable": False}],
            "declaration"))
        error = BaselineError(detail)
        error.readiness_failures = baseline.readiness_failures
        raise error

    def run(self) -> int:
        args = self.args
        run_id = args.run_id or (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + f"-{args.arm}-{args.scenario}-r{args.rep}-" + secrets.token_hex(3))
        evidence_dir = Path(args.out) / run_id
        ensure_new_run(args, run_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        arm_controller = ArmController(self.kubectl, app=args.app,
                                       argo_namespace=args.argocd_namespace)
        arm_evidence = None
        cleanup = None
        injection = None
        timeline = None
        contract = None
        baseline = None
        readiness_failures = []
        samples = []
        imperative = None
        collector_evidence_at = None
        collector_evidence_store_at = None
        collector_evidence_ref = None
        sampler = None
        sampler_stop = None
        restore_error = None
        postcondition = None
        failure = None
        window_end = None
        allow_cleanup = False
        try:
            frozen = self._declaration()
            verify_one_stack(self.kubectl, args.namespace, args.app,
                             args.argocd_namespace)
            allow_cleanup = True
            snapshotter = Snapshotter(self.kubectl, args.namespace,
                                      self.quarantine, self.clock,
                                      configmap_name=frozen.configmap_name,
                                      argo_namespace=args.argocd_namespace,
                                      app=args.app)
            arm_evidence = arm_controller.activate(args.arm)
            baseline = stabilize_baseline(
                snapshotter, self.kubectl, args.arm, args.baseline_timeout,
                args.sample_interval, self.clock, app=args.app)
            readiness_failures = list(baseline.readiness_failures)
            contract = build_contract(
                frozen, baseline, args.namespace, self.quarantine,
                app=args.app)
            self._require_baseline_agreement(contract, baseline)
            sampler = Sampler(snapshotter.capture, self.clock,
                              args.sample_interval, guarded=True)
            self.collector_started = self.clock.now()
            sampler.start()
            if not sampler.wait_ready(timeout=10):
                raise InstrumentationError(
                    "collector did not produce an initial sample")
            if sampler.error:
                raise InstrumentationError(str(sampler.error))
            if not sampler.snapshot():
                raise InstrumentationError("collector produced no sample")
            try:
                injection = inject(self.kubectl, contract, args.scenario,
                                   run_id, self.clock)
                deadline = injection.started.mono + args.timeout
                sampler.deadline = deadline
                t0 = injection.started.mono
                next_repair = self.clock.now().mono
                while self.clock.now().mono < deadline:
                    if sampler.error:
                        raise InstrumentationError(str(sampler.error))
                    samples = sampler.snapshot()
                    now = self.clock.now().mono
                    if now >= deadline:
                        break
                    if (samples and collector_evidence_at is None
                            and args.scenario != "F"):
                        latest = samples[-1]
                        if args.scenario == "A":
                            changed = hpa_changed(
                                contract.baseline_hpa, latest.hpa)
                            keys = _hpa_keys()
                        else:
                            diffs = field_diffs(contract, latest)
                            changed = bool(diffs)
                            keys = sorted({diff["resource"]
                                           for diff in diffs})
                        evaluated = self.clock.now()
                        latest.evaluated_at = evaluated
                        latest.evaluated_signal = bool(changed)
                        latest.evaluated_reads = list(keys)
                        if (changed and _reads_eligible(latest, keys, t0,
                                                        deadline)):
                            collector_evidence_at = evaluated
                            if args.scenario == "A":
                                collector_evidence_ref = "samples.jsonl"
                            else:
                                collector_evidence_ref = (
                                    "diff-" + _short(run_id) + "-collector.json")
                                try:
                                    _write_json(
                                        evidence_dir / collector_evidence_ref, {
                                            "run_id": run_id,
                                            "at": _point_dict(latest.at),
                                            "diffs": read_diff_evidence(
                                                contract, latest),
                                        })
                                except OSError as error:
                                    raise InstrumentationError(
                                        "collector evidence write failed: "
                                        f"{type(error).__name__}") from None
                                collector_evidence_store_at = self.clock.now()
                    if args.arm == "imperative" and args.scenario in "BCDEG":
                        if now >= next_repair and samples:
                            latest = samples[-1]
                            diffs = field_diffs(contract, latest)
                            keys = sorted({diff["resource"] for diff in diffs})
                            evaluated = self.clock.now()
                            if keys and _reads_eligible(latest, keys, t0,
                                                        deadline):
                                if imperative is None:
                                    imperative = ImperativeRun()
                                if imperative.detection_at is None:
                                    imperative.detection_at = evaluated
                                    imperative.detection_reads = keys
                                    imperative.evidence_at = evaluated
                                    imperative.evidence_reads = keys
                                    imperative.evidence_ref = (
                                        "diff-" + _short(run_id) + ".json")
                                    try:
                                        _write_json(
                                            evidence_dir / imperative.evidence_ref,
                                            {"run_id": run_id,
                                             "at": _point_dict(latest.at),
                                             "diffs": read_diff_evidence(
                                                 contract, latest)})
                                    except OSError as error:
                                        raise InstrumentationError(
                                            "imperative evidence write failed: "
                                            f"{type(error).__name__}") from None
                                    imperative.evidence_store_at = self.clock.now()
                                commands = repair(self.kubectl, contract,
                                                  latest, self.clock)
                                imperative.commands.extend(commands)
                                if any(not command.ok for command in commands):
                                    imperative.failed = True
                            next_repair = now + args.imperative_interval
                    if len(samples) >= 2:
                        candidate = analyze_timeline(
                            contract, samples, injection, args.arm,
                            args.scenario, args.timeout, imperative,
                            evidence_at=collector_evidence_at,
                            provided_evidence_ref=collector_evidence_ref,
                            app=args.app, baseline=baseline)
                        if candidate["recovery_seconds"] is not None:
                            break
                    time.sleep(args.sample_interval)
            finally:
                if sampler is not None:
                    sampler_stop = sampler.stop()
                    samples = sampler.snapshot()
            if injection is not None:
                window_end = self.clock.now()
                timeline = analyze_timeline(
                    contract, samples, injection, args.arm, args.scenario,
                    args.timeout, imperative,
                    evidence_at=collector_evidence_at,
                    provided_evidence_ref=collector_evidence_ref,
                    app=args.app, baseline=baseline,
                    window_end=window_end)
                if timeline is not None:
                    timeline["window_completed"] = (
                        timeline["recovery_seconds"] is not None
                        or window_end.mono >= injection.started.mono + args.timeout)
                    if (timeline["recovery_seconds"] is None
                            and not timeline["window_completed"]
                            and failure is None):
                        failure = InstrumentationError(
                            "observation window did not reach its deadline")
                if (timeline is not None and collector_evidence_store_at
                        and timeline.get("t_e") is not None
                        and not (args.arm == "imperative"
                                 and args.scenario in "BCDEG")):
                    timeline["t_e_store"] = collector_evidence_store_at
            if sampler is not None and sampler.error is not None:
                raise InstrumentationError(str(sampler.error))
            if sampler_stop is not None and sampler_stop.get("in_flight"):
                raise InstrumentationError(
                    "collector did not join before evidence finalization")
        except HarnessError as error:
            failure = error
            readiness_failures = list(getattr(
                error, "readiness_failures", readiness_failures))
            injection = getattr(error, "injection", injection)
            if arm_evidence is None and arm_controller.original:
                arm_evidence = ArmEvidence(
                    arm=args.arm,
                    original={name: copy.deepcopy(item["spec"])
                              for name, item in arm_controller.original.items()},
                    applications={}, paused=True)
        except Exception as error:  # noqa: BLE001 - preserve evidence, then fail
            failure = error
        finally:
            if sampler is not None and sampler_stop is None:
                sampler_stop = sampler.stop()
                samples = sampler.snapshot()
            g_annotation_owned = bool(
                args.scenario == "G" and injection is not None
                and any(command.argv[:2] == ["annotate", "SealedSecret"]
                        for command in injection.commands))
            try:
                cleanup = (cleanup_quarantine(self.kubectl, self.quarantine,
                                              owner=run_id)
                           if allow_cleanup else CleanupReport(True, [], []))
                if args.scenario == "G" and allow_cleanup and g_annotation_owned:
                    annotation_cleanup = cleanup_g_annotation(
                        self.kubectl, args.namespace)
                    cleanup = CleanupReport(
                        ok=cleanup.ok and annotation_cleanup.ok,
                        results=cleanup.results + annotation_cleanup.results,
                        errors=cleanup.errors + annotation_cleanup.errors)
            except Exception as error:  # noqa: BLE001 - cleanup must not skip restore
                cleanup = CleanupReport(
                    ok=False, results=[],
                    errors=[f"cleanup failed: {type(error).__name__}"])
            try:
                arm_controller.restore()
            except Exception as error:  # noqa: BLE001 - report, do not skip output
                restore_error = str(error)
            if contract is not None:
                for attempt in range(3):
                    try:
                        snapshotter = Snapshotter(self.kubectl, args.namespace,
                                                  self.quarantine, self.clock,
                                                  configmap_name=contract.configmap_name,
                                                  argo_namespace=args.argocd_namespace,
                                                  app=args.app)
                        postcondition = self._postcondition(
                            snapshotter, contract, args.scenario, args.arm)
                        break
                    except Exception as error:  # noqa: BLE001 - retry transient reads
                        if attempt == 2:
                            postcondition = {
                                "verified": False,
                                "error": f"{type(error).__name__}: {error}"}
                        else:
                            time.sleep(1)
        row = self._row(run_id, args, contract, injection, timeline, failure,
                        arm_evidence, cleanup, restore_error, postcondition)
        if sampler is not None and sampler_stop is not None:
            sampler_stop["partial_acquisition"] = copy.deepcopy(
                getattr(sampler, "stopped_capture", None))
            sampler_stop["capture_stop_reason"] = getattr(
                sampler, "capture_stop_reason", None)
        evidence = {
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
            ([command.as_dict() for command in injection.commands]
             if injection else [])
            + ([command.as_dict() for command in imperative.commands]
               if imperative else [])
            + ([command.as_dict() for command in cleanup.results]
               if cleanup else [])
        )
        if baseline:
            evidence["baseline"] = {
                "at": _point_dict(baseline.at),
                "acquisition": baseline.acquisition,
                "readiness_failures": baseline.readiness_failures,
                "resources": {key: {"fields": value.get("fields"),
                                    "manifest": value.get("manifest")}
                              for key, value in baseline.resources.items()},
                "argo": baseline.argo, "hpa": baseline.hpa,
                "pods": baseline.pods, "nodes": baseline.nodes,
                "extra_resources": baseline.extra_resources,
            }
        if readiness_failures:
            evidence["readiness"] = readiness_failures
        evidence["samples"] = [{
            "at": _point_dict(sample.at),
            "acquisition": copy.deepcopy(sample.acquisition),
            "evaluated_at": _point_dict(sample.evaluated_at),
            "evaluated_signal": sample.evaluated_signal,
            "evaluated_reads": list(sample.evaluated_reads),
            "resources": {key: value.get("fields")
                          for key, value in sample.resources.items()},
            "extra_resources": sample.extra_resources,
            "argo": sample.argo, "hpa": sample.hpa,
        } for sample in samples]
        write_outputs(row, args, evidence_dir, evidence)
        print(json.dumps({"run_id": run_id, "status": row["status"],
                          "jsonl": str(Path(args.out) / (run_id + ".jsonl")),
                          "csv": str(Path(args.out) / (run_id + ".csv"))},
                         sort_keys=True))
        return 0 if row["status"] in ("observed", "right_censored") and not (
            cleanup and not cleanup.ok) and not restore_error else 1

    def _postcondition(self, snapshotter, contract, scenario, arm):
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
            ok = (score(contract, observation) == 100
                  and not observation.extra_resources
                  and bool(observation.pods)
                  and all(pod.get("phase") == "Running"
                          and pod.get("ready") is True
                          for pod in observation.pods))
            if scenario == "A":
                ok = ok and hpa_settled(observation.hpa)
            if arm == "gitops":
                for name in (APP_OF_APPS, self.args.app):
                    state = observation.argo.get(name) or {}
                    ok = ok and state.get("sync") == "Synced" and \
                        state.get("health") == "Healthy"
            if finished.mono > deadline:
                return {"verified": False,
                        "reason": "deadline",
                        "deadline_mono": deadline,
                        "error": "postcondition read completed after the reset deadline",
                        "acquisition": acquisition}
            if ok and previous_ok:
                return {"verified": True, "at": _point_dict(observation.at),
                        "acquisition": acquisition}
            previous_ok = ok
            if self.clock.now().mono >= deadline:
                return {"verified": False,
                        "reason": "deadline",
                        "deadline_mono": deadline,
                        "error": "two consecutive postcondition reads did not match",
                        "acquisition": acquisition}
            time.sleep(self.args.sample_interval)

    def _row(self, run_id, args, contract, injection, timeline, failure,
             arm_evidence, cleanup, restore_error, postcondition):
        base = {
            "schema_version": 2, "run_id": run_id, "synthetic": False,
            "timing_convention": TIMING_CONVENTION,
            "formal_execution_approved": False, "env": args.arm,
            "arm": args.arm, "scenario": args.scenario, "rep": args.rep,
            "namespace": args.namespace, "app": args.app,
            "quarantine_namespace": self.quarantine,
            "source_revision": getattr(args, "source_revision", None),
            "render_sha256": getattr(args, "render_sha256", None),
            "detection_seconds": None, "evidence_seconds": None,
            "evidence_store_seconds": None,
            "recovery_seconds": None, "detection_status": "not_observed",
            "evidence_status": "not_observed", "recovery_status": "not_observed",
            "t_r_first_seconds": None, "t_r_confirmed_seconds": None,
            "recovery_confirmation": None,
            "detection_reads": [], "evidence_reads": [], "recovery_reads": [],
            "censor_seconds": args.timeout, "detection_controller": None,
            "recovery_controller": None, "r1_baseline": None, "r1_first": None,
            "r1_last": None, "r1_baseline_details": None,
            "r1_first_details": None, "r1_last_details": None,
            "r1_baseline_reason": None, "r1_first_reason": None,
            "r1_last_reason": None,
            "kubectl_cmds": 0, "t0_utc": None,
            "t0_mono": None, "t_a_utc": None, "t_a_mono": None,
            "t_d_utc": None, "t_d_mono": None, "t_e_utc": None,
            "t_e_mono": None, "t_e_store_utc": None, "t_e_store_mono": None,
            "t_r_utc": None, "t_r_mono": None,
            "t_r_first_utc": None, "t_r_first_mono": None,
            "t_r_confirmed_utc": None, "t_r_confirmed_mono": None,
            "window_completed": False,
            "window_end_utc": None, "window_end_mono": None,
            "arm_restore_status": "failed" if restore_error else "restored",
            "arm_restore_error": restore_error,
            "cleanup_status": "failed" if cleanup and not cleanup.ok else "ok",
            "cleanup_errors": cleanup.errors if cleanup else [],
            "postcondition": postcondition,
            "max_sample_gap_seconds": None,
            "observation_end_utc": None,
            "observation_end_mono": None,
            "collector_started_utc": (self.collector_started.utc
                                      if self.collector_started else None),
            "collector_started_mono": (self.collector_started.mono
                                       if self.collector_started else None),
            "analysis_group": ("hpa_control" if args.scenario == "A" else
                               "visibility_boundary" if args.scenario == "F" else
                               "managed_drift"),
            "efficacy_eligible": args.scenario not in ("A", "F"),
        }
        if contract:
            base["configmap_name"] = contract.configmap_name
            base["baseline_sha256"] = contract.baseline_sha256
        if timeline:
            for key in ("analysis_group", "efficacy_eligible", "stop_reason",
                        "injection_seconds", "detection_seconds",
                        "evidence_seconds", "recovery_seconds",
                        "detection_status", "evidence_status", "recovery_status",
                        "detection_controller", "recovery_controller",
                        "detection_ref", "evidence_ref",
                        "detection_reads", "evidence_reads", "recovery_reads",
                        "t_r_first_seconds", "t_r_confirmed_seconds",
                        "recovery_confirmation", "r1_baseline_reason",
                        "r1_first_reason", "r1_last_reason",
                        "window_completed",
                        "r1_baseline", "r1_first", "r1_last", "kubectl_cmds",
                        "r1_baseline_details", "r1_first_details",
                        "r1_last_details",
                        "max_sample_gap_seconds"):
                base[key] = timeline[key]
            for key in ("t_d", "t_e", "t_e_store", "t_r", "t_r_first",
                        "t_r_confirmed", "window_end"):
                point = timeline[key]
                base[key + "_utc"] = point.utc if point else None
                base[key + "_mono"] = point.mono if point else None
            if timeline.get("t_e_store") is not None:
                base["t_e_store_utc"] = timeline["t_e_store"].utc
                base["t_e_store_mono"] = timeline["t_e_store"].mono
                base["evidence_store_seconds"] = (
                    timeline["t_e_store"].mono - timeline["t0"].mono)
            observation_end = timeline.get("observation_end")
            base["observation_end_utc"] = (
                observation_end.utc if observation_end else None)
            base["observation_end_mono"] = (
                observation_end.mono if observation_end else None)
        if injection:
            base.update({
                "t0_utc": injection.started.utc,
                "t0_mono": injection.started.mono,
                "t_a_utc": injection.acknowledged.utc,
                "t_a_mono": injection.acknowledged.mono,
                "injection": injection.as_dict(),
            })
        if failure:
            base["status"] = (
                "arm_state_mismatch" if isinstance(failure, ArmStateError) else
                "invalid_injection" if isinstance(failure, InjectionError) else
                "instrumentation_failure" if isinstance(failure, InstrumentationError)
                else "baseline_failure" if isinstance(failure, BaselineError) else
                "safety_refusal" if isinstance(failure, SafetyError) else
                "failure")
            base["error"] = str(failure)
        elif timeline is None:
            base["status"] = "failure"
        else:
            base["status"] = timeline["status"]
        if restore_error:
            base["status"] = "arm_restore_failure"
        if cleanup and not cleanup.ok:
            base["cleanup_status"] = "failed"
        if (postcondition and not postcondition.get("verified")
                and base["status"] in ("observed", "right_censored")):
            base["status"] = "reset_failure"
        return base


def _run_dry(args):
    run_id = args.run_id or ("dryrun-" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3))
    ensure_new_run(args, run_id)
    row = dry_run_row(run_id, args.arm, args.scenario, args.rep,
                      args.namespace, args.app, args)
    evidence_dir = Path(args.out) / run_id
    write_outputs(row, args, evidence_dir, {"row": row})
    print(json.dumps({"run_id": run_id, "status": "dry_run",
                      "jsonl": str(Path(args.out) / (run_id + ".jsonl")),
                      "csv": str(Path(args.out) / (run_id + ".csv"))},
                     sort_keys=True))
    return 0


def main(argv=None):
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


if __name__ == "__main__":
    sys.exit(main())
