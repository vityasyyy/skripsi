"""Shared constants, failures, and records for the live harness."""

from __future__ import annotations

import copy
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

if __package__:
    from . import declaration as _declaration
else:  # direct script execution
    import declaration as _declaration  # type: ignore[no-redef]

declaration = _declaration

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
_RESOURCE_QUANTITY_PATHS = frozenset(
    {
        "/spec/template/spec/containers/web/resources/requests/cpu",
        "/spec/template/spec/containers/web/resources/requests/memory",
        "/spec/template/spec/containers/web/resources/limits/cpu",
        "/spec/template/spec/containers/web/resources/limits/memory",
    }
)
SEED_RECORD = "4ben9-bgh38"
SEED_FILE = "seed.bin"
SEED_SIZE = 65536
SEED_MD5 = "8f1445bafe2c2095044af7789462f475"
SEED_SHA256 = "7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2"
DEFAULT_INVENIO_URL = "https://invenio.vityasy.me"
USER_AGENT = "invenio-live-harness/1.0"
HTTP_RETRY_ATTEMPTS = 3
HTTP_RETRY_BACKOFF_SECONDS = (0.5, 1.0)
TRANSIENT_HTTP_STATUSES = frozenset({429, 502, 503, 504})
MISSING = "<missing>"
TIMING_CONVENTION = "completed-observation-v1"
MAX_SAMPLE_END_AGE_SECONDS = 30.0
MAX_AGGREGATION_WINDOW_SECONDS = 30.0
FUTURE_SAMPLE_TOLERANCE_SECONDS = 2.0


class HarnessError(Exception):
    """Base class for harness failures that map to exit code 1."""

    readiness_failures: list
    injection: Injection


class SafetyError(HarnessError):
    """A refused operation that maps to exit code 2."""


class ArmStateError(HarnessError):
    """Argo automation state does not match the requested arm."""


class ArmRestoreError(HarnessError):
    """The original Argo automation state could not be restored."""


class InjectionError(HarnessError):
    """A drift mutation or its verification failed."""


class InstrumentationError(HarnessError):
    """An observation or command result could not be trusted."""

    read_bounds: dict | None
    acquisition: dict | None


class SeedVerificationError(HarnessError):
    """The live seed record failed closed verification."""


class BaselineError(HarnessError):
    """The starting state did not satisfy the baseline gate."""


class CaptureStopped(HarnessError):
    """A cooperative between-read stop; carries safe partial acquisition."""

    def __init__(self, acquisition: dict, reason: str) -> None:
        super().__init__(f"capture stopped before the next read: {reason}")
        self.acquisition = acquisition
        self.reason = reason


class ReadStopped(HarnessError):
    """A cooperative stop inside one logical read/retry sequence."""

    def __init__(self, reason: str, read_bounds: dict | None = None) -> None:
        super().__init__(f"read stopped before the next request: {reason}")
        self.reason = reason
        self.read_bounds = read_bounds


@dataclass(frozen=True)
class Point:
    """One observation instant in monotonic and UTC form."""

    mono: float
    utc: str


@dataclass
class Clock:
    """Real monotonic and UTC clock."""

    def now(self) -> Point:
        return Point(time.monotonic(), datetime.now(timezone.utc).isoformat())


class FakeClock:
    """Deterministic clock for tests; repeats the last value when exhausted."""

    def __init__(self, values: list) -> None:
        self.values = list(values)
        self.index = 0

    def now(self) -> Point:
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        stamp = datetime(2026, 10, 27, tzinfo=timezone.utc)
        return Point(float(value), stamp.isoformat())


@dataclass
class CommandResult:
    """One recorded kubectl invocation."""

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
    """One scoped configuration snapshot plus telemetry."""

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
    """Frozen baseline identities, fields, and digests compared on every read."""

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
            "resources": [
                {key: copy.deepcopy(value) for key, value in resource.items()}
                for resource in self.resources
            ],
            "hpa_targets": list(self.hpa_targets),
            "configmap_name": self.configmap_name,
            "source_revision": self.source_revision,
            "render_sha256": self.render_sha256,
            "baseline_sha256": self.baseline_sha256,
            "baseline_hpa": copy.deepcopy(self.baseline_hpa),
        }


@dataclass
class Injection:
    """One drift injection attempt and its verification outcome."""

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
            "verification_started_utc": (
                self.verification_started.utc if self.verification_started else None
            ),
            "verification_started_mono": (
                self.verification_started.mono if self.verification_started else None
            ),
            "verified_utc": self.verified.utc if self.verified else None,
            "verified_mono": self.verified.mono if self.verified else None,
            "accepted": self.accepted,
            "changed_fields": copy.deepcopy(self.changed),
            "commands": [command.as_dict() for command in self.commands],
            "error": self.error,
        }


@dataclass
class ImperativeRun:
    """Automated imperative-arm detection, evidence, and repair state."""

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
            "evidence_store_at_utc": (
                self.evidence_store_at.utc if self.evidence_store_at else None
            ),
            "evidence_store_at_mono": (
                self.evidence_store_at.mono if self.evidence_store_at else None
            ),
            "evidence_ref": self.evidence_ref,
            "detection_reads": list(self.detection_reads),
            "evidence_reads": list(self.evidence_reads),
            "commands": [command.as_dict() for command in self.commands],
            "failed": self.failed,
        }


@dataclass
class ArmEvidence:
    """Argo automation state observed before and after arm activation."""

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
    """Aggregated result of quarantine and annotation cleanup."""

    ok: bool
    results: list
    errors: list

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "results": [command.as_dict() for command in self.results],
            "errors": list(self.errors),
        }


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _short(run_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", run_id)[-8:]


def _point_dict(point: Point | None) -> dict | None:
    return {"mono": point.mono, "utc": point.utc} if point else None


__all__ = [
    "APP_OF_APPS",
    "ARGO_NAMESPACE",
    "ARMS",
    "CONFIG_DRIFT",
    "CONFIG_KEY",
    "CONFIG_PREFIX",
    "DEFAULT_APP",
    "DEFAULT_INVENIO_URL",
    "DEFAULT_NAMESPACE",
    "DRIFT_ANNOTATION",
    "FUTURE_SAMPLE_TOLERANCE_SECONDS",
    "HTTP_RETRY_ATTEMPTS",
    "HTTP_RETRY_BACKOFF_SECONDS",
    "MAX_AGGREGATION_WINDOW_SECONDS",
    "MAX_SAMPLE_END_AGE_SECONDS",
    "MEMORY_LIMIT_DRIFT",
    "MEMORY_LIMIT_DRIFT_FALLBACK",
    "MISSING",
    "RENDER_FORMAT",
    "SCENARIOS",
    "SEALED_SECRET",
    "SEED_FILE",
    "SEED_MD5",
    "SEED_RECORD",
    "SEED_SHA256",
    "SEED_SIZE",
    "TIMING_CONVENTION",
    "TRANSIENT_HTTP_STATUSES",
    "USER_AGENT",
    "WEB_DEPLOYMENT",
    "WEB_HPA",
    "WEB_SERVICE",
    "_RESOURCE_QUANTITY_PATHS",
    "ArmEvidence",
    "ArmRestoreError",
    "ArmStateError",
    "BaselineError",
    "CaptureStopped",
    "CleanupReport",
    "Clock",
    "CommandResult",
    "Contract",
    "Declaration",
    "DeclarationError",
    "FakeClock",
    "HarnessError",
    "ImperativeRun",
    "Injection",
    "InjectionError",
    "InstrumentationError",
    "Observation",
    "Point",
    "ReadStopped",
    "SafetyError",
    "SeedVerificationError",
    "_canonical",
    "_point_dict",
    "_short",
]
