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
import hashlib
import json
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

ARMS = ("gitops", "imperative")
SCENARIOS = tuple("ABCDEFG")
DEFAULT_NAMESPACE = "invenio"
DEFAULT_APP = "invenio-bootstrap"
APP_OF_APPS = "apps"
ARGO_NAMESPACE = "argocd"
WEB_DEPLOYMENT = "invenio-web"
WEB_HPA = "invenio-web-hpa"
WEB_SERVICE = "invenio-web"
SEALED_SECRET = "invenio-app-secrets"
CONFIG_PREFIX = "invenio-app-config-"
DRIFT_ANNOTATION = "experiment.invenio.ugm/drift"
CONFIG_KEY = "INSTANCE_TAGLINE"
CONFIG_DRIFT = "drift-config-value"
MEMORY_LIMIT_DRIFT = "1536Mi"
MEMORY_LIMIT_DRIFT_FALLBACK = "1024Mi"
SEED_RECORD = "4ben9-bgh38"
SEED_FILE = "seed.bin"
SEED_SIZE = 65536
SEED_MD5 = "8f1445bafe2c2095044af7789462f475"
SEED_SHA256 = "7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2"
DEFAULT_INVENIO_URL = "https://invenio.vityasy.me"
USER_AGENT = "invenio-live-harness/1.0"
MISSING = "<missing>"


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

    def as_dict(self) -> dict:
        return {
            "started_utc": self.started.utc,
            "started_mono": self.started.mono,
            "acknowledged_utc": self.acknowledged.utc,
            "acknowledged_mono": self.acknowledged.mono,
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
    evidence_ref: str | None = None
    commands: list = field(default_factory=list)
    failed: bool = False

    def as_dict(self) -> dict:
        return {
            "detection_at_utc": self.detection_at.utc if self.detection_at else None,
            "detection_at_mono": self.detection_at.mono if self.detection_at else None,
            "evidence_at_utc": self.evidence_at.utc if self.evidence_at else None,
            "evidence_at_mono": self.evidence_at.mono if self.evidence_at else None,
            "evidence_ref": self.evidence_ref,
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
    kind = doc.get("kind")
    if kind == "Deployment":
        container = _container(doc)
        if container is None:
            raise InstrumentationError("invenio-web has no container named 'web'")
        resources = container.get("resources") or {}
        requests = resources.get("requests") or {}
        limits = resources.get("limits") or {}
        fields = {
            "/spec/template/spec/containers/web/image": container.get("image"),
            "/spec/template/spec/containers/web/resources/requests/cpu":
                requests.get("cpu"),
            "/spec/template/spec/containers/web/resources/requests/memory":
                requests.get("memory"),
            "/spec/template/spec/containers/web/resources/limits/cpu":
                limits.get("cpu"),
            "/spec/template/spec/containers/web/resources/limits/memory":
                limits.get("memory"),
        }
        if "replicas" in doc.get("spec", {}):
            fields["/spec/replicas"] = doc["spec"]["replicas"]
        return fields
    if kind == "ConfigMap":
        return {"/data/" + key: value
                for key, value in (doc.get("data") or {}).items()}
    if kind == "SealedSecret":
        annotations = (doc.get("metadata") or {}).get("annotations") or {}
        return {"/metadata/annotations/" + DRIFT_ANNOTATION:
                annotations.get(DRIFT_ANNOTATION)}
    if kind == "Service":
        spec = doc.get("spec") or {}
        ports = spec.get("ports") or [{}]
        selector = spec.get("selector") or {}
        return {
            "/spec/type": spec.get("type"),
            "/spec/selector/app.kubernetes.io/name":
                selector.get("app.kubernetes.io/name"),
            "/spec/ports/0/port": ports[0].get("port"),
            "/spec/ports/0/targetPort": ports[0].get("targetPort"),
        }
    return {}


def resource_id(doc: dict) -> str:
    return f"{doc.get('kind')}/{(doc.get('metadata') or {}).get('name')}"


def observation_from_objects(objects, at: Point, argo=None, hpa=None,
                             extras=None) -> Observation:
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
                       argo=copy.deepcopy(argo or {}), hpa=copy.deepcopy(hpa))


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


def build_contract(observation: Observation, namespace: str,
                   quarantine_namespace: str, source_revision=None,
                   render_sha256=None, app=DEFAULT_APP) -> Contract:
    resources = []
    for observed in observation.resources.values():
        resources.append(copy.deepcopy(observed))
    hpa_targets = []
    if observation.hpa and observation.hpa.get("target"):
        hpa_targets.append(observation.hpa["target"])
    for resource in resources:
        if resource["id"] in hpa_targets:
            resource["fields"].pop("/spec/replicas", None)
    configmap_name = ""
    for resource in resources:
        if resource["kind"] == "ConfigMap" and str(resource["name"]).startswith(
                CONFIG_PREFIX):
            configmap_name = resource["name"]
    if source_revision is None and observation.argo.get(app):
        source_revision = observation.argo[app].get("revision")
    observed_revision = (observation.argo.get(app) or {}).get("revision")
    if (source_revision is not None and observed_revision is not None
            and source_revision != observed_revision):
        raise InstrumentationError(
            "frozen source revision does not match the observed Argo revision")
    if source_revision is not None and not re.fullmatch(r"[0-9a-f]{40}",
                                                        source_revision):
        raise InstrumentationError("source revision must be 40 lowercase hex")
    if render_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}",
                                                      render_sha256):
        raise InstrumentationError("render SHA-256 must be 64 lowercase hex")
    digest_payload = {
        "resources": [{key: resource[key] for key in
                       ("id", "kind", "name", "namespace", "fields")}
                      for resource in resources],
        "hpa_targets": hpa_targets,
        "configmap_name": configmap_name,
        "source_revision": source_revision,
        "render_sha256": render_sha256,
    }
    return Contract(
        namespace=namespace,
        quarantine_namespace=quarantine_namespace,
        resources=resources,
        hpa_targets=hpa_targets,
        configmap_name=configmap_name,
        source_revision=source_revision,
        render_sha256=render_sha256,
        baseline_sha256=hashlib.sha256(_canonical(digest_payload).encode()).hexdigest(),
        baseline_hpa=copy.deepcopy(observation.hpa),
    )


def _same(expected, actual) -> bool:
    return type(expected) is type(actual) and expected == actual


def score(contract: Contract, observation: Observation) -> float:
    if not contract.resources:
        return 0.0
    matches = 0
    for expected in contract.resources:
        actual = observation.resources.get(expected["id"])
        if actual is None:
            continue
        values = actual.get("fields") or {}
        if all(key in values and _same(value, values[key])
               for key, value in expected["fields"].items()):
            matches += 1
    return 100.0 * matches / len(contract.resources)


def field_diffs(contract: Contract, observation: Observation) -> list:
    diffs = []
    for expected in contract.resources:
        actual = observation.resources.get(expected["id"])
        if actual is None:
            diffs.append({"resource": expected["id"], "missing": True,
                          "path": None, "expected": "present", "actual": "missing"})
            continue
        values = actual.get("fields") or {}
        for path, expected_value in expected["fields"].items():
            actual_value = values.get(path, MISSING)
            if actual_value is MISSING or not _same(expected_value, actual_value):
                diffs.append({
                    "resource": expected["id"],
                    "path": path,
                    "expected": expected_value,
                    "actual": None if actual_value is MISSING else actual_value,
                })
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
        result = self.run(argv)
        if result.returncode != 0:
            raise InstrumentationError(
                f"kubectl get {kind} failed: {result.stderr.strip()[:300]}")
        if not result.stdout.strip():
            return None
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            raise InstrumentationError(
                f"kubectl get {kind} returned invalid JSON") from None
        if isinstance(payload, dict) and payload.get("kind") == "List":
            items = payload.get("items") or []
            return items if name is None else None
        return payload

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
        result = self.run(["top", "nodes", "--no-headers"])
        if result.returncode != 0:
            raise InstrumentationError(
                f"kubectl top nodes failed: {result.stderr.strip()[:300]}")
        nodes = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                nodes.append({"name": parts[0],
                              "cpu_percent": float(parts[2].rstrip("%")),
                              "memory_percent": float(parts[4].rstrip("%"))})
            except ValueError:
                raise InstrumentationError("invalid kubectl top nodes output") from None
        if not nodes:
            raise InstrumentationError("no node metrics returned")
        return nodes

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

    def discover_configmap(self, deployment) -> str | None:
        if deployment:
            for source in (deployment.get("spec", {}).get("template", {}).get(
                    "spec", {}).get("containers", [{}])[0].get("envFrom") or []):
                name = (source.get("configMapRef") or {}).get("name")
                if name and name.startswith(CONFIG_PREFIX):
                    return name
        configmaps = self.kubectl.get("ConfigMap", namespace=self.namespace) or []
        names = [item.get("metadata", {}).get("name") for item in configmaps
                 if str(item.get("metadata", {}).get("name", "")).startswith(
                     CONFIG_PREFIX)]
        return names[0] if len(names) == 1 else None

    def capture(self, at: Point | None = None) -> Observation:
        at = at or self.clock.now()
        deployment = self.kubectl.get("Deployment", WEB_DEPLOYMENT, self.namespace)
        if deployment and self.configmap_name is None:
            self.configmap_name = self.discover_configmap(deployment)
        configmap = (self.kubectl.get("ConfigMap", self.configmap_name, self.namespace)
                     if self.configmap_name else None)
        secret = self.kubectl.get("SealedSecret", SEALED_SECRET, self.namespace)
        service = self.kubectl.get("Service", WEB_SERVICE, self.namespace)
        hpa_doc = self.kubectl.get("HorizontalPodAutoscaler", WEB_HPA, self.namespace)
        objects = [item for item in (deployment, configmap, secret, service) if item]
        apps = {}
        for name in (APP_OF_APPS, self.app):
            app = self.kubectl.get("Application", name, self.argo_namespace)
            if app is None:
                raise InstrumentationError(f"Argo Application {name} is missing")
            apps[name] = application_state(app)
        extras = []
        if self.kubectl.get("Namespace", self.quarantine) is not None:
            if self.kubectl.get("Deployment", WEB_DEPLOYMENT, self.quarantine):
                extras.append(f"{self.quarantine}/Deployment/{WEB_DEPLOYMENT}")
        hpa = hpa_state(hpa_doc, deployment) if hpa_doc else None
        return observation_from_objects(objects, at=at, argo=apps, hpa=hpa,
                                         extras=extras)


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


def baseline_gate(observation: Observation, arm: str, app: str = DEFAULT_APP) -> None:
    if not any(key.startswith("ConfigMap/" + CONFIG_PREFIX)
               for key in observation.resources):
        raise BaselineError("generated invenio-app-config ConfigMap is missing")
    if "Deployment/" + WEB_DEPLOYMENT not in observation.resources:
        raise BaselineError("invenio-web Deployment is missing")
    if "SealedSecret/" + SEALED_SECRET not in observation.resources:
        raise BaselineError("invenio-app-secrets SealedSecret is missing")
    sealed = observation.resources["SealedSecret/" + SEALED_SECRET]
    if sealed["fields"].get("/metadata/annotations/" + DRIFT_ANNOTATION) is not None:
        raise BaselineError("drift annotation is already present on SealedSecret")
    if "Service/" + WEB_SERVICE not in observation.resources:
        raise BaselineError("invenio-web Service is missing")
    if observation.hpa is None:
        raise BaselineError("invenio-web-hpa is missing")
    if observation.hpa.get("target") != "Deployment/" + WEB_DEPLOYMENT:
        raise BaselineError("HPA does not target invenio-web")
    if not hpa_settled(observation.hpa):
        raise BaselineError("HPA is not settled at baseline")
    if observation.extra_resources:
        raise BaselineError("quarantine resources exist before the run")
    if not observation.pods:
        raise BaselineError("no pods observed")
    for pod in observation.pods:
        if pod.get("phase") != "Running" or pod.get("ready") is not True:
            raise BaselineError(
                f"pod {pod.get('name')} is not Running and Ready")
    if not observation.nodes:
        raise BaselineError("no node metrics observed")
    for node in observation.nodes:
        for metric in ("cpu_percent", "memory_percent"):
            if node.get(metric) is None or node[metric] >= 70:
                raise BaselineError(f"node {node.get('name')} {metric} >= 70%")
    if arm == "gitops":
        for name in (APP_OF_APPS, app):
            state = observation.argo.get(name) or {}
            if state.get("sync") != "Synced" or state.get("health") != "Healthy":
                raise BaselineError(
                    f"Argo Application {name} is not Synced/Healthy")


def stabilize_baseline(snapshotter, kubectl, arm, timeout, interval,
                       clock, sleep=time.sleep, app=DEFAULT_APP) -> Observation:
    deadline = clock.now().mono + timeout
    previous = None
    while True:
        observation = snapshotter.capture()
        observation.pods = kubectl.pods(snapshotter.namespace)
        observation.nodes = kubectl.top_nodes()
        baseline_gate(observation, arm, app)
        if previous and _observation_key(previous) == _observation_key(observation):
            return observation
        previous = observation
        if clock.now().mono >= deadline:
            raise BaselineError("two consecutive baseline reads did not match")
        sleep(interval)


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
            manifest = _deployment_manifest(contract)
            baseline_replicas = manifest.get("spec", {}).get("replicas", 2)
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
            baseline = _field(
                contract, "Deployment/" + WEB_DEPLOYMENT,
                "/spec/template/spec/containers/web/resources/limits/memory")
            target = (MEMORY_LIMIT_DRIFT if baseline != MEMORY_LIMIT_DRIFT
                      else MEMORY_LIMIT_DRIFT_FALLBACK)
            commands.append(kubectl.patch(
                "Deployment", WEB_DEPLOYMENT, contract.namespace,
                {"spec": {"template": {"spec": {"containers": [
                    {"name": "web", "resources": {
                        "limits": {"memory": target}}}]}}}}, "strategic"))
            expected_path = ("/spec/template/spec/containers/web/"
                             "resources/limits/memory")
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
            if actual != expected_value:
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
            accepted=False, changed=changed, commands=commands, error=str(error))
        raise error
    except HarnessError as error:
        error.injection = Injection(
            started=started, acknowledged=acknowledged, verified=None,
            accepted=False, changed=changed, commands=commands, error=str(error))
        raise
    except Exception as error:
        raise InjectionError(
            f"injection verification failed: {type(error).__name__}") from None

    return Injection(started=started, acknowledged=acknowledged,
                     verified=clock.now(), accepted=True, changed=changed,
                     commands=commands, error=None)


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


def cleanup_quarantine(kubectl, quarantine: str, owner: str | None = None) -> CleanupReport:
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
    try:
        if kubectl.get("Namespace", quarantine) is not None:
            errors.append(f"quarantine namespace {quarantine} still exists")
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
                     app: str = DEFAULT_APP) -> dict:
    samples = sorted(samples, key=lambda item: item.at.mono)
    post = [sample for sample in samples
            if sample.at.mono >= injection.acknowledged.mono]
    if not post:
        post = [sample for sample in samples
                if sample.at.mono >= injection.started.mono]
    first = post[0] if post else None
    detection = None
    evidence = None
    recovery = None
    recovery_pair = None
    argo_seen = False

    if injection.accepted:
        for index, sample in enumerate(post):
            if scenario in "BCDEFG":
                state = sample.argo.get(app)
                if state and argo_signal(state):
                    argo_seen = True
            if detection is None:
                if imperative and scenario in "BCDEG" and imperative.detection_at:
                    detection = imperative.detection_at
                elif scenario == "A" and hpa_changed(contract.baseline_hpa,
                                                     sample.hpa):
                    detection = sample.at
                elif arm == "gitops" and scenario in "BCDEG" and argo_signal(
                        sample.argo.get(app)):
                    detection = sample.at
            if evidence is None and scenario in "ABCDEG":
                if scenario == "A":
                    if hpa_changed(contract.baseline_hpa, sample.hpa):
                        evidence = sample.at
                elif field_diffs(contract, sample):
                    evidence = sample.at
            if (recovery is None and recovery_pair is None
                    and _recovered(contract, sample, scenario)):
                if index + 1 < len(post) and _recovered(
                        contract, post[index + 1], scenario):
                    recovery_pair = (sample.at, post[index + 1].at)
                    recovery = sample.at
        if scenario in "ABCDEG" and evidence_at is not None:
            evidence = evidence_at
        if imperative and scenario in "BCDEG":
            if imperative.detection_at is not None:
                detection = imperative.detection_at
            if imperative.evidence_at is not None:
                evidence = imperative.evidence_at

    if not injection.accepted:
        detection = None
        evidence = None
        recovery = None
        recovery_pair = None
    if detection is not None and detection.mono < injection.started.mono:
        detection = None
    if evidence is not None and evidence.mono < injection.started.mono:
        evidence = None
    if recovery is not None and recovery.mono < injection.started.mono:
        recovery = None
        recovery_pair = None

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

    t0 = injection.started.mono
    ack = injection.acknowledged.mono

    def duration(at):
        return None if at is None else at.mono - t0

    gaps = [right.at.mono - left.at.mono
            for left, right in zip(samples, samples[1:])]
    return {
        "status": status,
        "stop_reason": stop_reason,
        "detection_seconds": duration(detection),
        "evidence_seconds": duration(evidence),
        "recovery_seconds": duration(recovery),
        "detection_status": _metric_status(detection, stop_reason),
        "evidence_status": _metric_status(evidence, stop_reason),
        "recovery_status": _metric_status(recovery, stop_reason),
        "injection_seconds": ack - t0,
        "censor_seconds": timeout,
        "max_sample_gap_seconds": max(gaps) if gaps else None,
        "observation_end": samples[-1].at if samples else None,
        "detection_controller": detection_controller,
        "recovery_controller": recovery_controller,
        "detection_ref": detection_ref,
        "evidence_ref": evidence_ref,
        "r1_baseline": 100.0,
        "r1_first": score(contract, first) if first else None,
        "r1_last": score(contract, samples[-1]) if samples else None,
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
        "recovery_pair": recovery_pair,
        "samples": len(samples),
    }


def dry_run_row(run_id, arm, scenario, rep, namespace, app, args) -> dict:
    return {
        "schema_version": 2,
        "run_id": run_id,
        "synthetic": False,
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
        "recovery_seconds": None,
        "detection_status": "not_observed",
        "evidence_status": "not_observed",
        "recovery_status": "not_observed",
        "censor_seconds": None,
        "detection_controller": None,
        "recovery_controller": None,
        "detection_ref": None,
        "evidence_ref": None,
        "r1_baseline": None,
        "r1_first": None,
        "r1_last": None,
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
    http = Http(token, base_url=args.invenio_url)
    seed = verify_seed(http, args.seed_record, args.seed_file, args.seed_size,
                       args.seed_md5, args.seed_sha256)
    return {"http": http, "seed": seed}


class Sampler(threading.Thread):
    def __init__(self, capture, clock, interval):
        super().__init__(daemon=True)
        self.capture = capture
        self.clock = clock
        self.interval = interval
        self.samples = []
        self.error = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            started = self.clock.now()
            try:
                sample = self.capture()
            except Exception as error:  # noqa: BLE001 - preserved as evidence
                self.error = error
                self._ready_event.set()
                return
            with self._lock:
                self.samples.append(sample)
                self._ready_event.set()
            elapsed = self.clock.now().mono - started.mono
            self._stop_event.wait(max(0.0, self.interval - elapsed))

    def wait_ready(self, timeout=10.0):
        return self._ready_event.wait(timeout)

    def snapshot(self):
        with self._lock:
            return list(self.samples)

    def stop(self):
        self._stop_event.set()
        self.join(timeout=10)


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
        samples = []
        imperative = None
        collector_evidence_at = None
        collector_evidence_ref = None
        restore_error = None
        postcondition = None
        failure = None
        allow_cleanup = False
        try:
            verify_one_stack(self.kubectl, args.namespace, args.app,
                             args.argocd_namespace)
            allow_cleanup = True
            snapshotter = Snapshotter(self.kubectl, args.namespace,
                                      self.quarantine, self.clock,
                                      argo_namespace=args.argocd_namespace,
                                      app=args.app)
            arm_evidence = arm_controller.activate(args.arm)
            baseline = stabilize_baseline(
                snapshotter, self.kubectl, args.arm, args.baseline_timeout,
                args.sample_interval, self.clock, app=args.app)
            contract = build_contract(
                baseline, args.namespace, self.quarantine,
                source_revision=args.source_revision,
                render_sha256=args.render_sha256, app=args.app)
            sampler = Sampler(snapshotter.capture, self.clock,
                              args.sample_interval)
            self.collector_started = self.clock.now()
            sampler.start()
            sampler.wait_ready(timeout=10)
            if sampler.error:
                raise InstrumentationError(str(sampler.error))
            if not sampler.snapshot():
                raise InstrumentationError("collector produced no sample")
            try:
                injection = inject(self.kubectl, contract, args.scenario,
                                   run_id, self.clock)
                deadline = injection.started.mono + args.timeout
                next_repair = self.clock.now().mono
                while self.clock.now().mono < deadline:
                    if sampler.error:
                        raise InstrumentationError(str(sampler.error))
                    samples = sampler.snapshot()
                    if (samples and collector_evidence_at is None
                            and args.scenario != "F"):
                        latest = samples[-1]
                        if args.scenario == "A":
                            if hpa_changed(contract.baseline_hpa, latest.hpa):
                                collector_evidence_at = latest.at
                                collector_evidence_ref = "samples.jsonl"
                        elif field_diffs(contract, latest):
                            collector_evidence_at = latest.at
                            collector_evidence_ref = (
                                "diff-" + _short(run_id) + "-collector.json")
                            _write_json(evidence_dir / collector_evidence_ref, {
                                "run_id": run_id,
                                "at": _point_dict(latest.at),
                                "diffs": read_diff_evidence(contract, latest),
                            })
                    if args.arm == "imperative" and args.scenario in "BCDEG":
                        now = self.clock.now().mono
                        if now >= next_repair and samples:
                            latest = samples[-1]
                            diffs = field_diffs(contract, latest)
                            if diffs:
                                if imperative is None:
                                    imperative = ImperativeRun()
                                if imperative.detection_at is None:
                                    imperative.detection_at = latest.at
                                    imperative.evidence_at = latest.at
                                    imperative.evidence_ref = (
                                        "diff-" + _short(run_id) + ".json")
                                    _write_json(evidence_dir / imperative.evidence_ref,
                                                {"run_id": run_id,
                                                 "at": _point_dict(latest.at),
                                                 "diffs": read_diff_evidence(
                                                     contract, latest)})
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
                            app=args.app)
                        if candidate["recovery_seconds"] is not None:
                            break
                    time.sleep(args.sample_interval)
            finally:
                sampler.stop()
                samples = sampler.snapshot()
            if injection is not None:
                timeline = analyze_timeline(
                    contract, samples, injection, args.arm, args.scenario,
                    args.timeout, imperative,
                    evidence_at=collector_evidence_at,
                    provided_evidence_ref=collector_evidence_ref,
                    app=args.app)
        except HarnessError as error:
            failure = error
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
            try:
                cleanup = (cleanup_quarantine(self.kubectl, self.quarantine,
                                              owner=run_id)
                           if allow_cleanup else CleanupReport(True, [], []))
            except Exception as error:  # noqa: BLE001 - cleanup must not skip restore
                cleanup = CleanupReport(
                    ok=False, results=[],
                    errors=[f"cleanup failed: {type(error).__name__}"])
            try:
                arm_controller.restore()
            except Exception as error:  # noqa: BLE001 - report, do not skip output
                restore_error = str(error)
            if contract is not None:
                try:
                    snapshotter = Snapshotter(self.kubectl, args.namespace,
                                              self.quarantine, self.clock,
                                              configmap_name=contract.configmap_name,
                                              argo_namespace=args.argocd_namespace,
                                              app=args.app)
                    postcondition = self._postcondition(snapshotter, contract,
                                                        args.scenario, args.arm)
                except Exception as error:  # noqa: BLE001 - report postcondition
                    postcondition = {"verified": False,
                                     "error": f"{type(error).__name__}: {error}"}
        row = self._row(run_id, args, contract, injection, timeline, failure,
                        arm_evidence, cleanup, restore_error, postcondition)
        evidence = {
            "baseline": baseline if baseline else None,
            "contract": contract.as_dict() if contract else None,
            "injection": injection.as_dict() if injection else None,
            "imperative": imperative.as_dict() if imperative else None,
            "arm": arm_evidence.as_dict() if arm_evidence else None,
            "cleanup": cleanup.as_dict() if cleanup else None,
            "postcondition": postcondition,
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
                "resources": {key: {"fields": value.get("fields"),
                                    "manifest": value.get("manifest")}
                              for key, value in baseline.resources.items()},
                "argo": baseline.argo, "hpa": baseline.hpa,
                "pods": baseline.pods, "nodes": baseline.nodes,
                "extra_resources": baseline.extra_resources,
            }
        evidence["samples"] = [{
            "at": _point_dict(sample.at),
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
            observation = snapshotter.capture()
            observation.pods = self.kubectl.pods(self.args.namespace)
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
            if ok and previous_ok:
                return {"verified": True, "at": _point_dict(observation.at)}
            previous_ok = ok
            if self.clock.now().mono >= deadline:
                return {"verified": False,
                        "error": "two consecutive postcondition reads did not match"}
            time.sleep(self.args.sample_interval)

    def _row(self, run_id, args, contract, injection, timeline, failure,
             arm_evidence, cleanup, restore_error, postcondition):
        base = {
            "schema_version": 2, "run_id": run_id, "synthetic": False,
            "formal_execution_approved": False, "env": args.arm,
            "arm": args.arm, "scenario": args.scenario, "rep": args.rep,
            "namespace": args.namespace, "app": args.app,
            "quarantine_namespace": self.quarantine,
            "source_revision": getattr(args, "source_revision", None),
            "render_sha256": getattr(args, "render_sha256", None),
            "detection_seconds": None, "evidence_seconds": None,
            "recovery_seconds": None, "detection_status": "not_observed",
            "evidence_status": "not_observed", "recovery_status": "not_observed",
            "censor_seconds": args.timeout, "detection_controller": None,
            "recovery_controller": None, "r1_baseline": None, "r1_first": None,
            "r1_last": None, "kubectl_cmds": 0, "t0_utc": None,
            "t0_mono": None, "t_a_utc": None, "t_a_mono": None,
            "t_d_utc": None, "t_d_mono": None, "t_e_utc": None,
            "t_e_mono": None, "t_r_utc": None, "t_r_mono": None,
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
                        "r1_baseline", "r1_first", "r1_last", "kubectl_cmds",
                        "max_sample_gap_seconds"):
                base[key] = timeline[key]
            for key in ("t_d", "t_e", "t_r"):
                point = timeline[key]
                base[key + "_utc"] = point.utc if point else None
                base[key + "_mono"] = point.mono if point else None
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
