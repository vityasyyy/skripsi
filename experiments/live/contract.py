"""Frozen declarations, baseline contracts, and field scoring."""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any, cast

if __package__:
    from . import declaration as _declaration
else:  # direct script execution
    import declaration as _declaration  # type: ignore[no-redef]

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

declaration = _declaration

DEFAULT_APP = _model.DEFAULT_APP
Contract = _model.Contract
Declaration = _model.Declaration
DeclarationError = _model.DeclarationError
InstrumentationError = _model.InstrumentationError
MISSING = _model.MISSING
Observation = _model.Observation
_RESOURCE_QUANTITY_PATHS = _model._RESOURCE_QUANTITY_PATHS
_canonical = _model._canonical

sanitize_object = _sampling.sanitize_object
_quantity_bytes = _transport._quantity_bytes
_quantity_nanocores = _transport._quantity_nanocores


def build_contract(
    frozen: Declaration,
    observation: Observation,
    namespace: str,
    quarantine_namespace: str,
    app: str = DEFAULT_APP,
) -> Contract:
    """Freeze the four scoped resources and the baseline digest."""
    if not isinstance(frozen, Declaration):
        raise InstrumentationError("contract requires an independently loaded frozen declaration")
    if not re.fullmatch(r"[0-9a-f]{40}", frozen.source_revision):
        raise InstrumentationError("source revision must be 40 lowercase hex")
    if not re.fullmatch(r"[0-9a-f]{64}", frozen.render_sha256):
        raise InstrumentationError("render SHA-256 must be 64 lowercase hex")
    observed_revision = (observation.argo.get(app) or {}).get("revision")
    if observed_revision != frozen.source_revision:
        raise InstrumentationError(
            "frozen source revision does not match the observed Argo revision"
        )
    hpa_targets = []
    if observation.hpa and observation.hpa.get("target"):
        hpa_targets.append(observation.hpa["target"])
    resources = []
    for declared in frozen.resources:
        if declared["namespace"] != namespace:
            raise InstrumentationError(
                f"declared {declared['id']} is not in namespace {namespace!r}"
            )
        resource = {
            key: copy.deepcopy(declared[key])
            for key in ("id", "kind", "name", "namespace", "fields")
        }
        manifest = sanitize_object(declared["manifest"])
        if resource["kind"] == "Deployment":
            manifest.get("spec", {}).pop("replicas", None)
        resource["manifest"] = manifest
        resources.append(resource)
    if len(resources) != 4:
        raise InstrumentationError("frozen declaration must select exactly four scoped resources")
    digest_payload = {
        "resources": [
            {key: resource[key] for key in ("id", "kind", "name", "namespace", "fields")}
            for resource in resources
        ],
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
        baseline_sha256=hashlib.sha256(_canonical(digest_payload).encode()).hexdigest(),
        baseline_hpa=copy.deepcopy(observation.hpa),
    )


def _same(expected: Any, actual: Any) -> bool:
    return type(expected) is type(actual) and expected == actual


def _normalized_value(path: str, value: Any) -> Any:
    if path == "/spec/type":
        return "ClusterIP" if value is None else value
    if path in _RESOURCE_QUANTITY_PATHS:
        if value is None:
            return None
        if path.endswith("/cpu"):
            return _quantity_nanocores(value, path)
        return _quantity_bytes(value, path)
    return value


def _field_matches(path: str, expected: Any, actual: Any) -> bool:
    return _same(_normalized_value(path, expected), _normalized_value(path, actual))


def _resource_diffs(expected: dict, actual: dict | None) -> list:
    if actual is None:
        return [
            {
                "resource": expected["id"],
                "missing": True,
                "path": None,
                "expected": "present",
                "actual": "missing",
            }
        ]
    values = actual.get("fields") or {}
    diffs = []
    for path, expected_value in expected["fields"].items():
        actual_value = values.get(path, MISSING)
        if actual_value is MISSING or not _field_matches(path, expected_value, actual_value):
            diffs.append(
                {
                    "resource": expected["id"],
                    "path": path,
                    "expected": expected_value,
                    "actual": None if actual_value is MISSING else actual_value,
                }
            )
    return diffs


def resource_results(contract: Contract, observation: Observation) -> dict:
    """Score and explain every contract resource against an observation."""
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
                {"path": diff["path"], "expected": diff["expected"], "actual": diff["actual"]}
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
    """Return the R1 field-match percentage."""
    return resource_results(contract, observation)["score"]


def field_diffs(contract: Contract, observation: Observation) -> list:
    """List every contract field mismatch for an observation."""
    diffs = []
    for expected in contract.resources:
        diffs.extend(_resource_diffs(expected, observation.resources.get(expected["id"])))
    return diffs


def hpa_settled(state: dict | None) -> bool:
    """True when the HPA and Deployment replica state has converged."""
    if not state:
        return False
    values = (
        state.get("desired"),
        state.get("current"),
        state.get("deployment_spec_replicas"),
        state.get("min"),
        state.get("max"),
    )
    if any(type(value) is not int for value in values):
        return False
    desired, current, replicas, minimum, maximum = (cast(int, item) for item in values)
    generation = state.get("generation")
    observed = state.get("observed_generation")
    if generation is None and observed is None:
        generation_ok = True
    elif type(generation) is int and type(observed) is int:
        generation_ok = generation == observed
    else:
        generation_ok = False
    return (
        state.get("able_to_scale") is True
        and minimum <= desired <= maximum
        and desired == current == replicas
        and generation_ok
    )


def hpa_telemetry_valid(state: dict) -> bool:
    """True when HPA telemetry is a well-formed non-negative state."""
    values = (
        state.get("desired"),
        state.get("current"),
        state.get("deployment_spec_replicas"),
        state.get("min"),
        state.get("max"),
    )
    if any(type(value) is not int or value < 0 for value in values):
        return False
    if cast(int, values[3]) <= 0 or cast(int, values[4]) < cast(int, values[3]):
        return False
    if type(state.get("able_to_scale")) is not bool:
        return False
    generation = state.get("generation")
    observed = state.get("observed_generation")
    if generation is None and observed is None:
        return True
    return type(generation) is int and type(observed) is int


def hpa_changed(baseline: dict | None, current: dict | None) -> bool:
    """True when HPA replica telemetry moved away from its baseline."""
    if not baseline or not current:
        return False
    keys = ("desired", "current", "deployment_spec_replicas", "last_scale_time")
    return any(baseline.get(key) != current.get(key) for key in keys)


def argo_signal(state: dict | None) -> bool:
    """True when Argo reports a drift-shaped sync or operation signal."""
    if not state:
        return False
    if state.get("sync") == "OutOfSync":
        return True
    if state.get("operation_phase") in ("Running", "Error", "Failed"):
        return True
    return any(
        item.get("type") in ("ComparisonError", "SyncError") and item.get("status") == "True"
        for item in state.get("conditions") or []
    )


def load_declaration(
    path: str | Path, expected_sha256: str, expected_revision: str, namespace: str
) -> Declaration:
    """Load and sanitize a frozen render declaration from a file."""
    return _prepare_declaration(
        declaration.load(path, expected_sha256, expected_revision, namespace)
    )


def load_declaration_bytes(
    data: bytes, expected_sha256: str, expected_revision: str, namespace: str
) -> Declaration:
    """Load and sanitize a frozen render declaration from bytes."""
    return _prepare_declaration(
        declaration.loads(data, expected_sha256, expected_revision, namespace)
    )


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


__all__ = [
    "_field_matches",
    "_normalized_value",
    "_prepare_declaration",
    "_resource_diffs",
    "_same",
    "_validate_declared_quantities",
    "argo_signal",
    "build_contract",
    "field_diffs",
    "hpa_changed",
    "hpa_settled",
    "hpa_telemetry_valid",
    "load_declaration",
    "load_declaration_bytes",
    "resource_results",
    "score",
]
