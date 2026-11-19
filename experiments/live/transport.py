"""Kubernetes, HTTP, and process transport for the live harness."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from http.client import HTTPMessage
from typing import IO, Any, cast
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

if __package__:
    from . import model as _model
else:  # direct script execution
    import model as _model  # type: ignore[no-redef]

ARGO_NAMESPACE = _model.ARGO_NAMESPACE
DEFAULT_APP = _model.DEFAULT_APP
DEFAULT_INVENIO_URL = _model.DEFAULT_INVENIO_URL
HTTP_RETRY_ATTEMPTS = _model.HTTP_RETRY_ATTEMPTS
HTTP_RETRY_BACKOFF_SECONDS = _model.HTTP_RETRY_BACKOFF_SECONDS
TRANSIENT_HTTP_STATUSES = _model.TRANSIENT_HTTP_STATUSES
USER_AGENT = _model.USER_AGENT
WEB_DEPLOYMENT = _model.WEB_DEPLOYMENT
Clock = _model.Clock
CommandResult = _model.CommandResult
HarnessError = _model.HarnessError
InstrumentationError = _model.InstrumentationError
Point = _model.Point
ReadStopped = _model.ReadStopped
SafetyError = _model.SafetyError
SeedVerificationError = _model.SeedVerificationError


def validate_namespace(namespace: str) -> str:
    """Accept only the real namespace or an exp-* experiment namespace."""
    if namespace == "invenio":
        return namespace
    if len(namespace or "") <= 63 and re.fullmatch(
        r"exp-[a-z0-9]([-a-z0-9]*[a-z0-9])?", namespace or ""
    ):
        return namespace
    raise SafetyError(
        f"namespace must be 'invenio' or an 'exp-*' experiment namespace; refusing {namespace!r}"
    )


def quarantine_namespace(namespace: str) -> str:
    """Derive the validated exp-<namespace>-drift quarantine name."""
    namespace = validate_namespace(namespace)
    name = "exp-" + namespace + "-drift"
    if len(name) > 63:
        raise SafetyError("derived quarantine namespace exceeds 63 characters")
    return name


def load_token(environ: Mapping[str, str] | None = None) -> str:
    """Read the Invenio API token or fail closed."""
    environ = os.environ if environ is None else environ
    token = environ.get("INVENIO_TOKEN", "")
    if not token or not token.strip():
        raise SeedVerificationError(
            "INVENIO_TOKEN is required for live seed verification; failing closed"
        )
    return token


class _CrossHostRedirectHandler(urlrequest.HTTPRedirectHandler):
    """Do not forward API auth headers to a presigned object-store redirect."""

    def redirect_request(
        self,
        req: urlrequest.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urlrequest.Request | None:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:  # pragma: no cover - base handler returns a request or raises
            return None
        old_host = urlparse.urlparse(req.full_url).hostname
        new_host = urlparse.urlparse(newurl).hostname
        if old_host != new_host:
            redirected.remove_header("Authorization")
            redirected.remove_header("Accept")
        return redirected


# --------------------------------------------------------------------------
# Seed verification
# --------------------------------------------------------------------------


class Http:
    def __init__(self, token: str, base_url: str = DEFAULT_INVENIO_URL, timeout: float = 15):
        parsed = urlparse.urlparse(base_url)
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1"):
            raise SafetyError("Invenio URL must use HTTPS unless it is a loopback address")
        self._token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = urlrequest.build_opener(_CrossHostRedirectHandler())

    def __repr__(self) -> str:
        return "Http(token=<redacted>)"

    def get(self, path: str, accept: str = "application/json") -> tuple[int, bytes]:
        url = self.base_url + path if path.startswith("/") else path
        headers = {
            "Authorization": "Bearer " + self._token,
            "Accept": accept,
            "User-Agent": USER_AGENT,
        }
        for attempt in range(HTTP_RETRY_ATTEMPTS):
            request = urlrequest.Request(url, headers=headers)
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    return response.status, response.read()
            except urlerror.HTTPError as error:
                if error.code not in TRANSIENT_HTTP_STATUSES or attempt + 1 == HTTP_RETRY_ATTEMPTS:
                    try:
                        body = error.read()
                    finally:
                        error.close()
                    return error.code, body
                error.close()
            except (urlerror.URLError, TimeoutError, ConnectionError) as error:
                if attempt + 1 == HTTP_RETRY_ATTEMPTS:
                    raise HarnessError(
                        f"Invenio API request failed: {type(error).__name__}"
                    ) from None
            except OSError as error:
                raise HarnessError(f"Invenio API request failed: {type(error).__name__}") from None
            time.sleep(HTTP_RETRY_BACKOFF_SECONDS[attempt])
        return None  # type: ignore[return-value]  # pragma: no cover - retry loop is non-empty


def verify_seed(
    http: Http,
    record: str,
    file_name: str,
    expected_size: int,
    expected_md5: str,
    expected_sha256: str,
) -> dict:
    """Verify the draft seed file by identity, size, and checksums."""
    status, body = http.get(f"/api/records/{record}/draft")
    if status != 200:
        raise SeedVerificationError(f"seed draft endpoint returned HTTP {status}; failing closed")
    try:
        draft = json.loads(body)
    except (TypeError, ValueError):
        raise SeedVerificationError("seed draft response is not JSON") from None
    files = draft.get("files") if isinstance(draft, dict) else None
    if isinstance(files, dict) and files.get("enabled") is False:
        raise SeedVerificationError("seed draft has files disabled; failing closed")

    status, body = http.get(f"/api/records/{record}/draft/files")
    if status != 200:
        raise SeedVerificationError(f"seed file listing returned HTTP {status}; failing closed")
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
        raise SeedVerificationError(f"seed content endpoint returned HTTP {status}; failing closed")
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


_QUANTITY_RE = re.compile(
    r"^(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+))"
    r"(?P<suffix>Ki|Mi|Gi|Ti|Pi|Ei|[numkKMGTPE]|[eE][+-]?\d+)?$"
)
_BINARY_FACTORS = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "Pi": 1024**5,
    "Ei": 1024**6,
}
_DECIMAL_FACTORS = {
    None: Decimal(1),
    "n": Decimal("1e-9"),
    "u": Decimal("1e-6"),
    "m": Decimal("1e-3"),
    "k": Decimal(1000),
    "M": Decimal(1000**2),
    "G": Decimal(1000**3),
    "T": Decimal(1000**4),
    "P": Decimal(1000**5),
    "E": Decimal(1000**6),
}
_DURATION_PART = re.compile(r"(\d+(?:\.\d*)?|\.\d+)(ns|us|µs|ms|s|m|h)")
_DURATION_FACTORS = {
    "ns": Decimal("1e-9"),
    "us": Decimal("1e-6"),
    "µs": Decimal("1e-6"),
    "ms": Decimal("1e-3"),
    "s": Decimal(1),
    "m": Decimal(60),
    "h": Decimal(3600),
}


def _quantity(value: Any, field: str) -> Decimal:
    if not isinstance(value, str) or not value or value != value.strip():
        raise InstrumentationError(f"{field} is not a valid Kubernetes quantity")
    match = _QUANTITY_RE.fullmatch(value)
    if match is None:
        raise InstrumentationError(f"{field} is not a valid Kubernetes quantity")
    try:
        number = Decimal(match.group("number"))
    except InvalidOperation:  # pragma: no cover - the quantity regex only yields valid decimals
        raise InstrumentationError(
            f"{field} is not a valid Kubernetes quantity"
        ) from None  # pragma: no cover
    suffix = match.group("suffix")
    try:
        if suffix in _BINARY_FACTORS:
            factor = Decimal(_BINARY_FACTORS[suffix])
        elif suffix in _DECIMAL_FACTORS:
            factor = Decimal(_DECIMAL_FACTORS[suffix])
        elif suffix and suffix[0] in "eE":
            factor = Decimal(10) ** int(suffix[1:])
        else:
            raise InstrumentationError(f"{field} is not a valid Kubernetes quantity")
        result = number * factor
    except ArithmeticError:
        raise InstrumentationError(f"{field} is not a valid Kubernetes quantity") from None
    if result == 0 and number != 0:
        raise InstrumentationError(f"{field} underflows")
    if not result.is_finite():  # pragma: no cover - finite operands cannot become infinite
        raise InstrumentationError(
            f"{field} is not a finite Kubernetes quantity"
        )  # pragma: no cover
    return result


def _quantity_nanocores(value: Any, field: str, positive: bool = False) -> int:
    try:
        amount = _quantity(value, field) * Decimal(10**9)
    except ArithmeticError:
        raise InstrumentationError(f"{field} is not a valid CPU quantity") from None
    if amount != amount.to_integral_value():
        raise InstrumentationError(f"{field} is not representable in nanocores")
    result = int(amount)
    if result < 0 or (positive and result == 0):
        raise InstrumentationError(f"{field} must be {'positive' if positive else 'non-negative'}")
    return result


def _quantity_bytes(value: Any, field: str, positive: bool = False) -> int:
    amount = _quantity(value, field)
    if amount != amount.to_integral_value():
        raise InstrumentationError(f"{field} is not representable in bytes")
    result = int(amount)
    if result < 0 or (positive and result == 0):
        raise InstrumentationError(f"{field} must be {'positive' if positive else 'non-negative'}")
    return result


def _duration_seconds(value: Any, field: str) -> float:
    if not isinstance(value, str) or not value:
        raise InstrumentationError(f"{field} is not a valid duration")
    position = 0
    total = Decimal(0)
    try:
        for match in _DURATION_PART.finditer(value):
            if match.start() != position:
                raise InstrumentationError(f"{field} is not a valid duration")
            total += Decimal(match.group(1)) * Decimal(_DURATION_FACTORS[match.group(2)])
            position = match.end()
        if position != len(value) or total <= 0:
            raise InstrumentationError(f"{field} is not a valid duration")
        seconds = float(total)
    except ArithmeticError:
        raise InstrumentationError(f"{field} is not a valid duration") from None
    if not math.isfinite(seconds):
        raise InstrumentationError(f"{field} is not a finite duration")
    return seconds


def _timestamp_instant(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise InstrumentationError(f"{field} is not a valid timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InstrumentationError(f"{field} is not a valid timestamp") from None
    if parsed.tzinfo is None:
        raise InstrumentationError(f"{field} has no timezone")
    return parsed


def _timestamp(value: Any, field: str) -> str:
    _timestamp_instant(value, field)
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


def _read_bounds(
    kind: str,
    name: str | None,
    namespace: str | None,
    attempts: list,
    present: bool,
    ok: bool,
) -> dict:
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


def _node_name(item: Any, field: str, seen: set) -> str:
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


def parse_node_metrics(
    metrics_payload: Any,
    nodes_payload: Any,
    metrics_bounds: dict,
    allocatable_bounds: dict,
) -> list:
    if not isinstance(metrics_payload, dict):
        raise InstrumentationError("node metrics payload is not an object")
    metrics_items = metrics_payload.get("items")
    if not isinstance(metrics_items, list) or not metrics_items:
        raise InstrumentationError("no node metrics returned")
    if isinstance(nodes_payload, dict):
        nodes_payload = nodes_payload.get("items")
    if not isinstance(nodes_payload, list) or not nodes_payload:
        raise InstrumentationError("no node inventory returned")
    allocatable: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for item in nodes_payload:
        name = _node_name(item, "node inventory", seen)
        status = item.get("status")
        if not isinstance(status, dict):
            raise InstrumentationError(f"node {name} has no status")
        resources = status.get("allocatable")
        if not isinstance(resources, dict):
            raise InstrumentationError(f"node {name} has no allocatable resources")
        allocatable[name] = {
            "cpu": resources.get("cpu"),
            "memory": resources.get("memory"),
            "cpu_nanocores": _quantity_nanocores(
                resources.get("cpu"), f"node {name} allocatable cpu", True
            ),
            "memory_bytes": _quantity_bytes(
                resources.get("memory"), f"node {name} allocatable memory", True
            ),
        }
    usage: dict[str, dict[str, Any]] = {}
    seen = set()
    for item in metrics_items:
        name = _node_name(item, "node metrics", seen)
        if name not in allocatable:
            raise InstrumentationError(f"node metrics returned for unexpected node {name}")
        resources = item.get("usage")
        if not isinstance(resources, dict):
            raise InstrumentationError(f"node {name} metrics have no usage")
        timestamp = _timestamp(item.get("timestamp"), f"node {name} metrics timestamp")
        window = item.get("window")
        window_seconds = _duration_seconds(window, f"node {name} metrics window")
        usage[name] = {
            "cpu": resources.get("cpu"),
            "memory": resources.get("memory"),
            "cpu_nanocores": _quantity_nanocores(resources.get("cpu"), f"node {name} usage cpu"),
            "memory_bytes": _quantity_bytes(resources.get("memory"), f"node {name} usage memory"),
            "timestamp": timestamp,
            "window": window,
            "window_seconds": window_seconds,
        }
    missing = sorted(set(allocatable) - set(usage))
    if missing:
        raise InstrumentationError("node metrics missing for " + ", ".join(missing))
    nodes = []
    for name in sorted(usage):
        observed = usage[name]
        capacity = allocatable[name]
        cpu_percent = float(
            Decimal(observed["cpu_nanocores"]) * 100 / Decimal(capacity["cpu_nanocores"])
        )
        memory_percent = float(
            Decimal(observed["memory_bytes"]) * 100 / Decimal(capacity["memory_bytes"])
        )
        if not math.isfinite(cpu_percent) or not math.isfinite(memory_percent):
            raise InstrumentationError(f"node {name} percentage is not finite")
        nodes.append(
            {
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
            }
        )
    return nodes


class Kubectl:
    """Thin kubectl wrapper with bounded reads and a mutation recorder."""

    def __init__(self, clock: Clock, timeout: float = 30, recorder: list | None = None) -> None:
        self.clock = clock
        self.timeout = timeout
        self.recorder = recorder if recorder is not None else []

    def run(
        self,
        argv: list,
        input_text: str | None = None,
        mutating: bool = False,
        timeout: float | None = None,
    ) -> CommandResult:
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
            code, stdout, stderr = (
                completed.returncode,
                completed.stdout or "",
                completed.stderr or "",
            )
        except subprocess.TimeoutExpired:
            code, stdout, stderr = 124, "", "kubectl timed out"
        except OSError as error:
            raise InstrumentationError(f"kubectl could not start: {type(error).__name__}") from None
        finished = self.clock.now()
        result = CommandResult(
            argv=list(argv),
            returncode=code,
            stdout=stdout,
            stderr=stderr,
            started=started,
            finished=finished,
        )
        if mutating:
            self.recorder.append(result)
        return result

    def get(
        self,
        kind: str,
        name: str | None = None,
        namespace: str | None = None,
        selector: str | None = None,
    ) -> Any:
        payload, _ = self.read(kind, name, namespace, selector)
        return payload

    def read(
        self,
        kind: str,
        name: str | None = None,
        namespace: str | None = None,
        selector: str | None = None,
        guard: Callable[[], str | None] | None = None,
    ) -> tuple[Any, dict]:
        argv = ["get", kind]
        if name:
            argv.append(name)
        if namespace:
            argv.extend(["-n", namespace])
        elif name is None and kind not in ("Namespace", "Node"):
            argv.append("--all-namespaces")
        if selector:
            argv.extend(["-l", selector])
        argv.extend(["-o", "json", "--ignore-not-found", "--request-timeout=15s"])
        attempts: list[dict] = []

        def stopped() -> ReadStopped | None:
            if guard is None:
                return None
            reason = guard()
            if not reason:
                return None
            bounds = (
                _read_bounds(kind, name, namespace, attempts, present=False, ok=False)
                if attempts
                else None
            )
            return ReadStopped(reason, bounds)

        reason = stopped()
        if reason is not None:
            raise reason

        def request() -> CommandResult:
            try:
                return self.run(argv)
            except InstrumentationError:
                reason = stopped()
                if reason is not None:
                    raise reason from None
                raise

        result = request()
        attempts.append(_attempt_bounds(result))
        for attempt in range(2):
            if result.returncode == 0:
                break
            stderr = result.stderr.lower()
            transient = any(
                token in stderr
                for token in (
                    "unexpected error when reading response body",
                    "request canceled",
                    "client.timeout",
                    "connection reset",
                    "tls handshake timeout",
                    "i/o timeout",
                    "temporarily unavailable",
                )
            )
            if not transient:
                break
            reason = stopped()
            if reason is not None:
                raise reason
            time.sleep(0.5 * (attempt + 1))
            reason = stopped()
            if reason is not None:
                raise reason
            result = request()
            attempts.append(_attempt_bounds(result))
        if result.returncode != 0:
            reason = stopped()
            if reason is not None:
                raise reason
            error = InstrumentationError(
                f"kubectl get {kind} failed: {result.stderr.strip()[:300]}"
            )
            error.read_bounds = _read_bounds(
                kind, name, namespace, attempts, present=False, ok=False
            )
            raise error
        if not result.stdout.strip():
            return None, _read_bounds(kind, name, namespace, attempts, present=False, ok=True)
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            error = InstrumentationError(f"kubectl get {kind} returned invalid JSON")
            error.read_bounds = _read_bounds(
                kind, name, namespace, attempts, present=False, ok=False
            )
            raise error from None
        if isinstance(payload, dict) and payload.get("kind") == "List":
            items = payload.get("items") or []
            return (items if name is None else None), _read_bounds(
                kind, name, namespace, attempts, present=True, ok=True
            )
        return payload, _read_bounds(kind, name, namespace, attempts, present=True, ok=True)

    def patch(
        self, kind: str, name: str, namespace: str, patch: dict, patch_type: str = "merge"
    ) -> CommandResult:
        argv = ["patch", kind, name]
        if namespace:
            argv.extend(["-n", namespace])
        argv.extend(["--type", patch_type, "-p", json.dumps(patch, sort_keys=True)])
        return self.run(argv, mutating=True)

    def annotate(
        self, kind: str, name: str, namespace: str, key: str, value: str | None = None
    ) -> CommandResult:
        argv = ["annotate", kind, name]
        if namespace:
            argv.extend(["-n", namespace])
        argv.append(key + ("=" + value if value is not None else "-"))
        if value is not None:
            argv.append("--overwrite")
        return self.run(argv, mutating=True)

    def apply(self, manifest: dict) -> CommandResult:
        return self.run(["apply", "-f", "-"], input_text=json.dumps(manifest), mutating=True)

    def delete(
        self,
        kind: str,
        name: str,
        namespace: str | None = None,
        wait: bool = False,
        timeout: int = 90,
    ) -> CommandResult:
        argv = ["delete", kind, name]
        if namespace:
            argv.extend(["-n", namespace])
        if not wait:
            argv.append("--wait=false")
        return self.run(argv, mutating=True, timeout=timeout)

    def top_nodes(self) -> list:
        result = self.run(
            ["get", "--raw", "/apis/metrics.k8s.io/v1beta1/nodes", "--request-timeout=15s"]
        )
        if result.returncode != 0:
            raise InstrumentationError(
                f"metrics-server node read failed: {result.stderr.strip()[:300]}"
            )
        try:
            metrics = json.loads(result.stdout)
        except ValueError:
            raise InstrumentationError("metrics-server node read returned invalid JSON") from None
        allocatable_started = self.clock.now()
        nodes = self.get("Node")
        allocatable_finished = self.clock.now()
        return parse_node_metrics(
            metrics,
            nodes,
            _command_bounds(result),
            _point_bounds(allocatable_started, allocatable_finished),
        )

    def pods(self, namespace: str) -> list:
        items = self.get("Pod", namespace=namespace) or []
        pods = []
        for item in items:
            status = item.get("status") or {}
            phase = status.get("phase")
            if phase == "Succeeded":
                continue
            statuses = (status.get("containerStatuses") or []) + (
                status.get("initContainerStatuses") or []
            )
            ready = bool(statuses) and all(item.get("ready") is True for item in statuses)
            pods.append(
                {"name": (item.get("metadata") or {}).get("name"), "phase": phase, "ready": ready}
            )
        return pods


def verify_one_stack(kubectl: Kubectl, namespace: str, app: str, argo_namespace: str) -> None:
    """Refuse a cluster that is not exactly the one declared stack."""
    deployments = kubectl.get(
        "Deployment", namespace=None, selector="app.kubernetes.io/name=" + WEB_DEPLOYMENT
    )
    if not isinstance(deployments, list):
        raise SafetyError("could not inventory invenio-web Deployments")
    namespaces = {cast(str, (item.get("metadata") or {}).get("namespace")) for item in deployments}
    if namespaces != {namespace}:
        raise SafetyError(
            f"one stack only: expected invenio-web only in {namespace}, found {sorted(namespaces)}"
        )
    application = kubectl.get("Application", app, argo_namespace)
    if application is None:
        raise SafetyError(f"Argo Application {app} is missing")
    destination = ((application.get("spec") or {}).get("destination") or {}).get("namespace")
    if destination != namespace:
        raise SafetyError(f"Argo Application {app} targets {destination}, not {namespace}")
    if kubectl.get("Namespace", quarantine_namespace(namespace)) is not None:
        raise SafetyError("quarantine namespace already exists; clean it first")


__all__ = [
    "Http",
    "Kubectl",
    "_CrossHostRedirectHandler",
    "_attempt_bounds",
    "_command_bounds",
    "_duration_seconds",
    "_node_name",
    "_point_bounds",
    "_quantity",
    "_quantity_bytes",
    "_quantity_nanocores",
    "_read_bounds",
    "_timestamp",
    "_timestamp_instant",
    "load_token",
    "parse_node_metrics",
    "quarantine_namespace",
    "urlrequest",
    "validate_namespace",
    "verify_one_stack",
    "verify_seed",
]
