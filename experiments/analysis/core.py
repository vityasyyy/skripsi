"""Shared constants, failure type, and row helpers for the live analysis."""

from __future__ import annotations

import math
from typing import TypedDict, cast

SCENARIOS = tuple("ABCDEFG")
EFFICACY_SCENARIOS = frozenset("BCDE")
METRICS = ("detection", "evidence", "recovery")
STATUSES = frozenset({"observed", "right_censored"})
METRIC_STATUSES = STATUSES | {"unobserved_before_stop"}
TIMING_CONVENTION = "completed-observation-v1"
# ``visibility_boundary`` is a retained output key for schema compatibility.
# Scenario F is currently the declared Service/invenio-web targetPort drift.
POPULATIONS = {
    "A": "hpa_control",
    "B": "managed_drift",
    "C": "managed_drift",
    "D": "managed_drift",
    "E": "managed_drift",
    "F": "visibility_boundary",
    "G": "descriptive_non_argo",
}
ROW_GROUPS = {
    "A": "hpa_control",
    "B": "managed_drift",
    "C": "managed_drift",
    "D": "managed_drift",
    "E": "managed_drift",
    "F": "visibility_boundary",
    "G": "managed_drift",
}
ARM_ENV = {"imperative": "manual", "gitops": "gitops"}
ARM_ORDER = {"manual": 0, "gitops": 1}
METRIC_LABELS = {
    "detection": "Deteksi",
    "evidence": "Bukti",
    "recovery": "Pemulihan",
}
MIN_PAIRS = 2
MIN_GROUP = 3
FAMILY_SIZE = len(EFFICACY_SCENARIOS) * len(METRICS)
DEFAULT_SEED = 20261027
DEFAULT_BOOTSTRAP = 2000
DEFAULT_ALPHA = 0.05


class _EndpointCounts(TypedDict):
    observed: int
    right_censored: int
    missing: int
    excluded: int | None


class LiveAnalysisError(ValueError):
    """Input is not a valid batch analysis dataset."""


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(cast(float, value))


def _require(condition: object, message: str) -> None:
    if not condition:
        raise LiveAnalysisError(message)


def _excluded_count(
    exclusions: dict | None, scenario: str, arm: str, phase: str = "R2"
) -> int | None:
    if exclusions is None or exclusions.get("count") is None:
        return None
    return sum(
        1
        for item in exclusions["rows"]
        if item.get("scenario") == scenario
        and ARM_ENV.get(item.get("arm"), item.get("arm")) == arm
        and item.get("phase") == phase
    )


__all__ = [
    "ARM_ENV",
    "ARM_ORDER",
    "DEFAULT_ALPHA",
    "DEFAULT_BOOTSTRAP",
    "DEFAULT_SEED",
    "EFFICACY_SCENARIOS",
    "FAMILY_SIZE",
    "METRICS",
    "METRIC_LABELS",
    "METRIC_STATUSES",
    "MIN_GROUP",
    "MIN_PAIRS",
    "POPULATIONS",
    "ROW_GROUPS",
    "SCENARIOS",
    "STATUSES",
    "TIMING_CONVENTION",
    "LiveAnalysisError",
    "_EndpointCounts",
    "_excluded_count",
    "_number",
    "_require",
]
