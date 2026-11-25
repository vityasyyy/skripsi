#!/usr/bin/env python3
"""Inferential and descriptive analysis for the formal live batch.

Consumes `<batch_id>.analysis.jsonl` from `experiments/live/run_matrix.py`,
optionally `<batch_id>.rows.jsonl` for exclusion accounting, and writes a JSON
result plus thesis-ready LaTeX tables. Standard library only.

Statistical scope is frozen by Bab III:

* B--E are the managed-drift efficacy population.
* A is the HPA control, F a declared Service drift reported separately, G a
descriptive non-Argo
  case. They are reported separately and never pooled into efficacy.
* R2 uses repetitions 1..10; R1 uses repetitions 11..15.
* Observed times stay observed, right-censored times stay censored. A missing
  value is never replaced by zero.
* Paired Wilcoxon signed-rank is used only when every scenario/rep block has
  both arms fully observed (at least two pairs). Otherwise Mann--Whitney U is
  reported as exploratory, never as a silently chosen alternative.
* The Holm family is the twelve predeclared B--E x {detection, evidence,
  recovery} comparisons. Untestable hypotheses are treated conservatively.
* Kaplan--Meier and RMST handle right censoring; the RMST horizon is the
  smallest frozen censor limit in the group.
* No claim is confirmatory: the design is a single-case sequential study.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from statistics import median
from typing import cast

if __package__:
    from . import core as core
else:  # direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import core as core  # type: ignore[no-redef]

if __package__:
    from . import data as data
else:  # direct script execution
    import data as data  # type: ignore[no-redef]

if __package__:
    from . import formatting as formatting
else:  # direct script execution
    import formatting as formatting  # type: ignore[no-redef]

if __package__:
    from . import latex as latex
else:  # direct script execution
    import latex as latex  # type: ignore[no-redef]

if __package__:
    from . import stats as stats
else:  # direct script execution
    import stats as stats  # type: ignore[no-redef]

if __package__:
    from . import survival as survival
else:  # direct script execution
    import survival as survival  # type: ignore[no-redef]

# Stable re-exports: the facade keeps the original analyzer namespace available.
SCENARIOS = core.SCENARIOS
EFFICACY_SCENARIOS = core.EFFICACY_SCENARIOS
METRICS = core.METRICS
STATUSES = core.STATUSES
METRIC_STATUSES = core.METRIC_STATUSES
TIMING_CONVENTION = core.TIMING_CONVENTION
POPULATIONS = core.POPULATIONS
ROW_GROUPS = core.ROW_GROUPS
ARM_ENV = core.ARM_ENV
ARM_ORDER = core.ARM_ORDER
METRIC_LABELS = core.METRIC_LABELS
MIN_PAIRS = core.MIN_PAIRS
MIN_GROUP = core.MIN_GROUP
FAMILY_SIZE = core.FAMILY_SIZE
DEFAULT_SEED = core.DEFAULT_SEED
DEFAULT_BOOTSTRAP = core.DEFAULT_BOOTSTRAP
DEFAULT_ALPHA = core.DEFAULT_ALPHA
_EndpointCounts = core._EndpointCounts
LiveAnalysisError = core.LiveAnalysisError
_number = core._number
_require = core._require
_excluded_count = core._excluded_count

_average_ranks = stats._average_ranks
cliffs_delta = stats.cliffs_delta
mann_whitney_u = stats.mann_whitney_u
wilcoxon_signed_rank = stats.wilcoxon_signed_rank
holm_adjust = stats.holm_adjust
_percentile = stats._percentile
_bootstrap_cliff = stats._bootstrap_cliff
_bootstrap_median = stats._bootstrap_median
_pairing = stats._pairing
_comparison = stats._comparison

kaplan_meier = survival.kaplan_meier
_survival_entries = survival._survival_entries

load_jsonl = data.load_jsonl
_load_jsonl = data.load_jsonl
tex_escape = formatting.tex_escape
format_num = formatting.format_num
format_p = formatting.format_p
format_interval = formatting.format_interval
_tex_escape = formatting.tex_escape
_num = formatting.format_num
_p = formatting.format_p
_interval = formatting.format_interval
_overview_tex = latex._overview_tex
_exclusions_tex = latex._exclusions_tex
_r1_cell = latex._r1_cell
_r1_tex = latex._r1_tex
_survival_tex = latex._survival_tex
_tests_tex = latex._tests_tex
_effects_tex = latex._effects_tex

BATCH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
REVISION = re.compile(r"[0-9a-f]{40}")
RENDER = re.compile(r"[0-9a-f]{64}")
RETRY_SUFFIX = re.compile(r"retry([1-9][0-9]*)")
ATTEMPT_FIELDS = ("batch_attempt", "batch_retry_of")
RAW_ANALYSIS_FIELDS = (
    "batch_phase",
    "batch_mode",
    "source_revision",
    "render_sha256",
    "censor_seconds",
    "analysis_group",
    "efficacy_eligible",
    "synthetic",
    "formal_execution_approved",
    "stack_isolated",
    "r3_status",
    "stop_reason",
    "t0_mono",
    "t_a_mono",
    "t_d_mono",
    "t_e_mono",
    "t_e_store_mono",
    "t_r_mono",
    "t_r_first_mono",
    "t_r_confirmed_mono",
    "window_completed",
    "window_end_mono",
    "window_end_utc",
    "recovery_confirmation",
    "t_r_first_seconds",
    "t_r_confirmed_seconds",
    "evidence_store_seconds",
    "detection_reads",
    "evidence_reads",
    "recovery_reads",
    "detection_ref",
    "evidence_ref",
    "detection_controller",
    "recovery_controller",
    "r1_baseline",
    "r1_first",
    "r1_last",
    "detection_seconds",
    "detection_status",
    "evidence_seconds",
    "evidence_status",
    "recovery_seconds",
    "recovery_status",
)

REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "batch_id",
        "batch_phase",
        "batch_mode",
        "scenario",
        "arm",
        "env",
        "rep",
        "analysis_group",
        "efficacy_eligible",
        "synthetic",
        "status",
        "censor_seconds",
        "r1_baseline",
        "r1_first",
        "r1_last",
        "source_revision",
        "render_sha256",
        "formal_execution_approved",
        "stack_isolated",
        "r3_status",
    }
)


def _validate_metric(row: dict, metric: str) -> None:
    value = row.get(metric + "_seconds")
    status = row.get(metric + "_status")
    limit = row["censor_seconds"]
    _require(
        isinstance(status, str) and status in METRIC_STATUSES,
        f"{metric}_status is not a supported metric status",
    )
    if status == "observed":
        _require(_number(value), f"{metric}_seconds is not a finite number")
        _require(
            0 <= cast(float, value) <= cast(float, limit),
            f"{metric}_seconds is outside [0, censor_seconds]",
        )
    elif status == "right_censored":
        _require(value is None, f"{metric}_seconds must be null when right_censored")
    else:
        _require(value is None, f"{metric}_seconds must be null when unobserved_before_stop")
        _require(
            row.get("status") == "observed"
            and row.get("stop_reason") == "recovery"
            and row.get("recovery_status") == "observed",
            f"{metric}_status lacks a confirmed early-recovery provenance",
        )


def _validate_timing_header(row: dict, strict: bool) -> tuple[float, float, float] | None:
    """Validate required bounds and return t0, censor limit, and window end."""
    if not strict:
        return None
    required = (
        "t0_mono",
        "t_a_mono",
        "t_d_mono",
        "t_e_mono",
        "t_r_mono",
        "t_r_first_mono",
        "t_r_confirmed_mono",
        "window_completed",
        "window_end_mono",
    )
    missing = [field for field in required if field not in row]
    _require(not missing, f"new-convention row is missing timing fields: {missing}")
    t0 = cast(float, row.get("t0_mono"))
    limit = cast(float, row.get("censor_seconds"))
    _require(_number(t0), "t0_mono is not finite")
    t_a = cast(float, row.get("t_a_mono"))
    _require(_number(t_a) and t_a >= t0, "t_a_mono is not after t0_mono")
    if row.get("injection_seconds") is not None:
        _require(
            math.isclose(row["injection_seconds"], t_a - t0, rel_tol=1e-9, abs_tol=1e-9),
            "injection_seconds disagrees with its bounds",
        )
    _require(
        row.get("window_completed") is True,
        "new-convention row lacks completed observation-window provenance",
    )
    window_end = cast(float, row.get("window_end_mono"))
    _require(
        _number(window_end) and window_end >= t0,
        "window_end_mono is not a finite completion after t0",
    )
    if row.get("status") == "observed":
        _require(
            row.get("stop_reason") == "recovery",
            "observed row does not record recovery as its stop reason",
        )
    else:
        _require(
            row.get("stop_reason") == "timeout", "right-censored row does not record a timeout stop"
        )
        _require(
            window_end >= t0 + limit, "right-censored row did not complete its observation window"
        )
    return t0, limit, window_end


def _validate_metric_points(row: dict, t0: float, limit: float, window_end: float) -> None:
    """Validate each metric's point bound and duration."""
    for metric in METRICS:
        key = {"detection": "t_d", "evidence": "t_e", "recovery": "t_r"}[metric]
        point: float | None = row.get(key + "_mono")
        value: float | None = row.get(metric + "_seconds")
        status = row.get(metric + "_status")
        if point is None:
            _require(
                value is None and status != "observed",
                f"{key}_mono is missing for an observed metric",
            )
            continue
        _require(_number(point), f"{key}_mono is not finite")
        _require(point >= t0, f"{key}_mono precedes t0_mono")
        _require(point <= t0 + limit, f"{key}_mono exceeds the censor limit")
        _require(point <= window_end, f"{key}_mono occurs after the observation window ended")
        _require(
            _number(value)
            and math.isclose(cast(float, value), point - t0, rel_tol=1e-9, abs_tol=1e-9),
            f"{metric}_seconds disagrees with its bounds",
        )
        _require(status == "observed", f"{key}_mono is present for a non-observed metric")


def _validate_recovery_bounds(row: dict, t0: float, limit: float, window_end: float) -> None:
    """Validate the recovery confirmation bounds and evidence-store bound."""
    t_r_first: float | None = row.get("t_r_first_mono")
    t_r_confirmed: float | None = row.get("t_r_confirmed_mono")
    if t_r_first is not None:
        _require(
            _number(t_r_first) and t0 <= t_r_first <= t0 + limit,
            "t_r_first_mono is outside the observation window",
        )
        _require(
            t_r_first <= window_end, "t_r_first_mono occurs after the observation window ended"
        )
        if row.get("t_r_first_seconds") is not None:
            _require(
                math.isclose(row["t_r_first_seconds"], t_r_first - t0, rel_tol=1e-9, abs_tol=1e-9),
                "t_r_first_seconds disagrees with its bounds",
            )
    if t_r_confirmed is not None:
        _require(
            _number(t_r_confirmed) and t0 <= t_r_confirmed <= t0 + limit,
            "t_r_confirmed_mono is outside the observation window",
        )
        _require(
            t_r_confirmed <= window_end,
            "t_r_confirmed_mono occurs after the observation window ended",
        )
        _require(
            t_r_first is not None and t_r_confirmed >= t_r_first,
            "confirmation bounds are not ordered",
        )
        if row.get("t_r_confirmed_seconds") is not None:
            _require(
                math.isclose(
                    row["t_r_confirmed_seconds"], t_r_confirmed - t0, rel_tol=1e-9, abs_tol=1e-9
                ),
                "t_r_confirmed_seconds disagrees with its bounds",
            )
    if row.get("recovery_status") == "observed":
        _require(
            row.get("t_r_mono") is not None
            and t_r_first is not None
            and t_r_confirmed is not None
            and math.isclose(row["t_r_mono"], t_r_first, rel_tol=1e-9, abs_tol=1e-9)
            and window_end >= t_r_confirmed
            and row.get("recovery_confirmation") == "confirmed",
            "confirmed recovery lacks ordered first/confirmation bounds and window-stop support",
        )
    else:
        _require(
            row.get("t_r_mono") is None
            and t_r_confirmed is None
            and row.get("recovery_confirmation") != "confirmed",
            "unconfirmed recovery carries a primary recovery bound",
        )
    store: float | None = row.get("t_e_store_mono")
    if store is not None:
        _require(
            _number(store) and row.get("t_e_mono") is not None and store >= row["t_e_mono"],
            "t_e_store_mono precedes the evidence evaluation",
        )
        if row.get("evidence_store_seconds") is not None:
            _require(
                math.isclose(row["evidence_store_seconds"], store - t0, rel_tol=1e-9, abs_tol=1e-9),
                "evidence_store_seconds disagrees with its bounds",
            )


def _validate_timing(row: dict, strict: bool) -> None:
    """Validate completed-observation bounds for new-convention rows.

    Legacy rows predate the convention and are validated by the older field
    contract only; no new bound is invented for them.
    """
    bounds = _validate_timing_header(row, strict)
    if bounds is None:
        return
    t0, limit, window_end = bounds
    _validate_metric_points(row, t0, limit, window_end)
    _validate_recovery_bounds(row, t0, limit, window_end)


def _run_attempt(row: dict, label: str, base_run_id: str) -> int:
    """Attempt number encoded by the run id; retries use `-retry<N>`."""
    run_id = row["run_id"]
    if run_id == base_run_id:
        return 0
    prefix = base_run_id + "-"
    _require(run_id.startswith(prefix), f"{label} has run_id/identity mismatch")
    match = RETRY_SUFFIX.fullmatch(run_id[len(prefix) :])
    _require(match is not None, f"{label} has malformed retry suffix")
    assert match is not None
    return int(match.group(1))


def _validate_attempt_metadata(row: dict, label: str, base_run_id: str, attempt: int) -> None:
    """Check optional attempt fields; legacy unsuffixed rows omit them."""
    present = [field for field in ATTEMPT_FIELDS if field in row]
    _require(len(present) in (0, 2), f"{label} has incomplete attempt metadata")
    if not present:
        _require(attempt == 0, f"{label} retry lacks batch_attempt/batch_retry_of")
        return
    value = row["batch_attempt"]
    _require(type(value) is int and value >= 0, f"{label} has invalid batch_attempt")
    retry_of = row["batch_retry_of"]
    if value == 0:
        _require(retry_of is None, f"{label} has invalid batch_retry_of")
    else:
        _require(retry_of == base_run_id, f"{label} has mismatched batch_retry_of")
    _require(value == attempt, f"{label} has inconsistent retry suffix")


def _validate_row_identity(
    row: dict, index: int, seen_runs: set[str], conventions: set[str | None]
) -> dict:
    """Validate the row's identity, phase, grouping, and convention."""
    missing = sorted(REQUIRED_FIELDS - set(row))
    _require(not missing, f"row {index} missing fields: {missing}")
    marker = row.get("timing_convention")
    _require(
        marker is None or isinstance(marker, str),
        f"row {index} has an invalid timing_convention",
    )
    if marker is not None:
        _require(marker == TIMING_CONVENTION, f"row {index} has an unsupported timing_convention")
    conventions.add(marker)
    _require(
        type(row["schema_version"]) is int and row["schema_version"] == 2,
        f"row {index} has unsupported schema_version",
    )
    run_id = row["run_id"]
    _require(isinstance(run_id, str) and 0 < len(run_id) <= 128, f"row {index} has invalid run_id")
    _require(run_id not in seen_runs, f"row {index} repeats a run_id")
    seen_runs.add(run_id)

    scenario = row["scenario"]
    _require(scenario in SCENARIOS, f"row {index} has invalid scenario")
    arm = row["arm"]
    _require(isinstance(arm, str) and arm in ARM_ENV, f"row {index} has invalid arm")
    _require(row["env"] == ARM_ENV[arm], f"row {index} violates arm/env mapping")
    rep = row["rep"]
    _require(type(rep) is int and 1 <= rep <= 15, f"row {index} has invalid rep")
    expected_phase = "R2" if rep <= 10 else "R1"
    _require(row["batch_phase"] == expected_phase, f"row {index} has phase/rep mismatch")
    _require(
        row["analysis_group"] == ROW_GROUPS[scenario], f"row {index} has invalid analysis_group"
    )
    _require(
        type(row["efficacy_eligible"]) is bool
        and row["efficacy_eligible"] == (scenario not in ("A", "F")),
        f"row {index} has invalid efficacy_eligible",
    )
    _require(row["synthetic"] is False, f"row {index} is synthetic and cannot be analyzed")
    _require(
        isinstance(row["status"], str) and row["status"] in STATUSES,
        f"row {index} is not an analyzable run status",
    )
    _require(row["batch_mode"] == "live", f"row {index} is not from a live batch")
    batch_id = row["batch_id"]
    _require(
        isinstance(batch_id, str) and BATCH_ID.fullmatch(batch_id),
        f"row {index} has invalid batch_id",
    )
    return {
        "marker": marker,
        "scenario": scenario,
        "arm": arm,
        "env": row["env"],
        "rep": rep,
        "batch_id": batch_id,
    }


def _validate_row_provenance(row: dict, index: int, identity: dict) -> None:
    """Validate the frozen revision, render, approval, and censor limit."""
    base_run_id = (
        f"{identity['batch_id']}-{identity['arm']}-{identity['scenario']}-r{identity['rep']:02d}"
    )
    attempt = _run_attempt(row, f"row {index}", base_run_id)
    _validate_attempt_metadata(row, f"row {index}", base_run_id, attempt)
    _require(
        REVISION.fullmatch(str(row["source_revision"])),
        f"row {index} has invalid source_revision",
    )
    _require(RENDER.fullmatch(str(row["render_sha256"])), f"row {index} has invalid render_sha256")
    _require(
        type(row["formal_execution_approved"]) is bool,
        f"row {index} has invalid formal_execution_approved",
    )
    _require(type(row["stack_isolated"]) is bool, f"row {index} has invalid stack_isolated")
    _require(row["r3_status"] == "not_measured", f"row {index} has unsupported r3_status")
    limit = row["censor_seconds"]
    _require(_number(limit) and limit > 0, f"row {index} has invalid censor_seconds")


def _validate_r1_fields(row: dict, index: int) -> None:
    for field in ("r1_baseline", "r1_first", "r1_last"):
        value = row[field]
        _require(
            value is None or (_number(value) and 0 <= value <= 100),
            f"row {index} has invalid {field}",
        )


def _validate_run_status(row: dict, index: int) -> None:
    if row["status"] == "observed":
        _require(
            row["recovery_status"] == "observed",
            f"row {index} has inconsistent run/recovery status",
        )
    else:
        _require(
            row["recovery_status"] == "right_censored",
            f"row {index} has inconsistent run/recovery status",
        )


def validate_rows(rows: list) -> dict:
    """Validate one batch analysis dataset; raise on any inconsistency."""
    _require(isinstance(rows, list) and rows, "dataset must be a non-empty list")
    batches: set[str] = set()
    revisions: set[str] = set()
    renders: set[str] = set()
    approvals: set[bool] = set()
    isolated: set[bool] = set()
    modes: set[str] = set()
    conventions: set[str | None] = set()
    seen_runs: set[str] = set()
    seen_blocks: set[tuple[str, str, int]] = set()
    for index, row in enumerate(rows, 1):
        _require(isinstance(row, dict), f"row {index} is not an object")
        identity = _validate_row_identity(row, index, seen_runs, conventions)
        _validate_row_provenance(row, index, identity)
        for metric in METRICS:
            _validate_metric(row, metric)
        _validate_timing(row, identity["marker"] == TIMING_CONVENTION)
        _validate_r1_fields(row, index)
        _validate_run_status(row, index)

        block = (identity["scenario"], identity["env"], identity["rep"])
        _require(block not in seen_blocks, f"row {index} duplicates a scenario/arm/rep block")
        seen_blocks.add(block)
        batches.add(identity["batch_id"])
        revisions.add(row["source_revision"])
        renders.add(row["render_sha256"])
        approvals.add(row["formal_execution_approved"])
        isolated.add(row["stack_isolated"])
        modes.add(row["batch_mode"])

    _require(len(batches) == 1, "dataset mixes multiple batch_id values")
    _require(len(revisions) == 1, "dataset mixes source revisions")
    _require(len(renders) == 1, "dataset mixes render digests")
    _require(len(approvals) == 1, "dataset mixes approval attestations")
    _require(len(isolated) == 1, "dataset mixes stack isolation attestations")
    _require(len(modes) == 1, "dataset mixes batch modes")
    _require(len(conventions) == 1, "dataset mixes completed-observation timing conventions")
    return {
        "batch_id": batches.pop(),
        "source_revision": revisions.pop(),
        "render_sha256": renders.pop(),
        "formal_execution_approved": approvals.pop(),
        "stack_isolated": isolated.pop(),
        "batch_mode": modes.pop(),
        "timing_convention": conventions.pop(),
        "analysis_rows": len(rows),
    }


def _r1_entries(rows: list) -> list:
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["scenario"], row["env"], row["batch_phase"]), []).append(row)
    entries = []
    for (scenario, arm, phase), group in sorted(
        groups.items(), key=lambda item: (item[0][0], ARM_ORDER[item[0][1]], item[0][2])
    ):
        entry = {"scenario": scenario, "arm": arm, "phase": phase, "rows": len(group)}
        for field in ("r1_baseline", "r1_first", "r1_last"):
            values = [row[field] for row in group if row[field] is not None]
            entry[field[3:]] = {
                "present": len(values),
                "missing": len(group) - len(values),
                "median": median(values) if values else None,
            }
        entry["excluded_rows"] = sum(
            1 for row in group if row["r1_first"] is None and row["r1_last"] is None
        )
        entries.append(entry)
    return entries


def _classify_raw(row: dict) -> str | None:
    """Conservative exclusion reason for a raw batch row; None if analyzable."""
    if row.get("batch_mode") == "dry_run" or row.get("status") == "dry_run":
        return "dry_run"
    status = row.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        return "status_not_analyzable"
    if row.get("cleanup_status") != "ok":
        return "cleanup_failure"
    if row.get("arm_restore_status") != "restored":
        return "arm_restore_failure"
    if row.get("batch_stop_reason"):
        return "batch_stop"
    if row.get("error"):
        return "row_error"
    postcondition = row.get("postcondition")
    if not isinstance(postcondition, dict) or postcondition.get("verified") is not True:
        return "postcondition_not_verified"
    if row.get("synthetic") is not False:
        return "synthetic"
    if row.get("scenario") not in SCENARIOS:
        return "invalid_scenario"
    if row.get("analysis_group") != ROW_GROUPS[row["scenario"]]:
        return "invalid_analysis_group"
    if not REVISION.fullmatch(str(row.get("source_revision"))) or not RENDER.fullmatch(
        str(row.get("render_sha256"))
    ):
        return "invalid_provenance"
    limit = cast(float, row.get("censor_seconds"))
    if not (_number(limit) and limit > 0):
        return "invalid_censor_seconds"
    for metric in METRICS:
        value: float | None = row.get(metric + "_seconds")
        status = row.get(metric + "_status")
        if status == "right_censored" and value is None:
            continue
        if (
            status == "unobserved_before_stop"
            and value is None
            and row.get("status") == "observed"
            and row.get("stop_reason") == "recovery"
            and row.get("recovery_status") == "observed"
        ):
            continue
        if status == "observed" and _number(value) and 0 <= cast(float, value) <= limit:
            continue
        return "invalid_metric_observation"
    return None


def _raw_identity(row: dict, index: int, batch_id: str) -> tuple[tuple[str, str, int], int]:
    """Return the raw row's cell and attempt, validated against its run id."""
    arm = row.get("arm")
    _require(isinstance(arm, str) and arm in ARM_ENV, f"raw row {index} has invalid arm")
    scenario = row.get("scenario")
    _require(scenario in SCENARIOS, f"raw row {index} has invalid scenario")
    rep = row.get("rep")
    _require(type(rep) is int and 1 <= rep <= 15, f"raw row {index} has invalid rep")
    base_run_id = f"{batch_id}-{arm}-{scenario}-r{rep:02d}"
    attempt = _run_attempt(row, f"raw row {index}", base_run_id)
    _validate_attempt_metadata(row, f"raw row {index}", base_run_id, attempt)
    return (cast(str, arm), cast(str, scenario), cast(int, rep)), attempt


def _validate_analyzed_raw(raw: dict, analysis: dict, index: int) -> None:
    """Reject raw evidence that disagrees with its analyzed run."""
    raw_marker = raw.get("timing_convention")
    analysis_marker = analysis.get("timing_convention")
    _require(
        (raw_marker is None) == (analysis_marker is None),
        f"raw row {index} timing_convention disagrees with analysis row",
    )
    if raw_marker is not None:
        _require(
            raw_marker == analysis_marker,
            f"raw row {index} timing_convention disagrees with analysis row",
        )
    if raw_marker == TIMING_CONVENTION:
        one_sided = [
            field for field in RAW_ANALYSIS_FIELDS if (field in raw) != (field in analysis)
        ]
        _require(not one_sided, f"raw row {index} has one-sided timing fields: {one_sided}")
    for field in RAW_ANALYSIS_FIELDS:
        if field in raw and field in analysis:
            _require(
                raw[field] == analysis[field],
                f"raw row {index} {field} disagrees with analysis row",
            )
    if "env" in raw:
        raw_env = raw["env"]
        _require(isinstance(raw_env, str), f"raw row {index} has invalid env")
        _require(
            ARM_ENV.get(raw_env, raw_env) == analysis["env"],
            f"raw row {index} env disagrees with analysis row",
        )
    for label, row in ((f"raw row {index}", raw), (f"analysis row {index}", analysis)):
        for field, expected in (("cleanup_status", "ok"), ("arm_restore_status", "restored")):
            if field in row:
                _require(row[field] == expected, f"{label} has failed {field}")
        if "postcondition" in row:
            postcondition = row["postcondition"]
            _require(
                isinstance(postcondition, dict) and postcondition.get("verified") is True,
                f"{label} postcondition is not verified",
            )
        for field in ("batch_stop_reason", "error"):
            if field in row:
                _require(not row[field], f"{label} has {field}")


def _raw_retry_violation(predecessor: dict) -> str | None:
    """Mirror the runner's pre-injection baseline retry policy."""
    if predecessor.get("status") != "baseline_failure":
        return "predecessor_not_baseline_failure"
    if predecessor.get("t0_utc") is not None:
        return "predecessor_started_injection"
    injection = predecessor.get("injection")
    if isinstance(injection, dict) and injection.get("accepted") is not False:
        return "predecessor_injection_not_rejected"
    if predecessor.get("cleanup_status") not in (None, "ok"):
        return "predecessor_cleanup_not_ok"
    if predecessor.get("arm_restore_status") not in (None, "restored"):
        return "predecessor_arm_not_restored"
    if predecessor.get("mutations_executed") not in (None, 0):
        return "predecessor_mutated"
    return None


def _validate_raw_chain(cells: dict) -> None:
    """Each attempt after 0 must follow one retryable baseline failure."""
    for cell, attempts in cells.items():
        attempts.sort(key=lambda item: item[0])
        numbers = [item[0] for item in attempts]
        _require(
            numbers == list(range(len(numbers))),
            f"raw rows for cell {cell} have a broken attempt chain",
        )
        for position in range(1, len(attempts)):
            _, predecessor, _ = attempts[position - 1]
            _, _, index = attempts[position]
            reason = _raw_retry_violation(predecessor)
            _require(
                reason is None,
                f"raw row {index} has a retry chain that violates the "
                f"baseline retry policy ({reason})",
            )


def _exclusions(rows: list, raw_rows: list | None) -> dict:
    if raw_rows is None:
        return {
            "source": "not_provided",
            "raw_rows": None,
            "count": None,
            "by_reason": {},
            "rows": [],
        }
    _require(isinstance(raw_rows, list) and raw_rows, "rows.jsonl must contain at least one row")
    batch_id = rows[0]["batch_id"]
    analysis_marker = rows[0].get("timing_convention")
    analyzed = {row["run_id"]: row for row in rows}
    raw_ids: list[str] = []
    cells: dict[tuple[str, str, int], list[tuple[int, dict, int]]] = {}
    for index, row in enumerate(raw_rows, 1):
        _require(isinstance(row, dict), f"raw row {index} is not an object")
        run_id = row.get("run_id")
        _require(
            isinstance(run_id, str) and 0 < len(run_id) <= 128,
            f"raw row {index} has invalid run_id",
        )
        marker = row.get("timing_convention")
        _require(
            marker == analysis_marker,
            f"raw row {index} timing_convention disagrees with analysis rows",
        )
        _validate_timing(row, marker == TIMING_CONVENTION and row.get("status") in STATUSES)
        _require(row.get("batch_id") == batch_id, f"raw row {index} belongs to another batch")
        cell, attempt = _raw_identity(row, index, batch_id)
        if run_id in analyzed:
            _require(
                row.get("status") == analyzed[run_id]["status"],
                f"raw row {index} status disagrees with analysis row",
            )
            _validate_analyzed_raw(row, analyzed[run_id], index)
        raw_ids.append(run_id)
        cells.setdefault(cell, []).append((attempt, row, index))
    _require(len(raw_ids) == len(set(raw_ids)), "rows.jsonl repeats a run_id")
    _validate_raw_chain(cells)
    _require(not (set(analyzed) - set(raw_ids)), "rows.jsonl is missing analyzed runs")
    excluded = []
    for row in raw_rows:
        if row["run_id"] in analyzed:
            continue
        reason = _classify_raw(row)
        _require(
            reason is not None, "rows.jsonl contains an analyzable run absent from analysis.jsonl"
        )
        arm = row.get("arm") if isinstance(row.get("arm"), str) else None
        excluded.append(
            {
                "run_id": row["run_id"],
                "arm": arm if arm in ARM_ENV else None,
                "scenario": (row.get("scenario") if row.get("scenario") in SCENARIOS else None),
                "rep": row.get("rep") if type(row.get("rep")) is int else None,
                "phase": row.get("batch_phase"),
                "reason": reason,
            }
        )
    by_reason: dict[str, int] = {}
    for item in excluded:
        by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
    return {
        "source": "rows_jsonl",
        "raw_rows": len(raw_rows),
        "count": len(excluded),
        "by_reason": dict(sorted(by_reason.items())),
        "rows": excluded,
    }


def _overview_entries(r2_rows: list, exclusions: dict) -> list:
    """Count observed, censored, missing, and excluded rows per cell."""
    overview = []
    for scenario in SCENARIOS:
        for arm in ("manual", "gitops"):
            group = [row for row in r2_rows if row["scenario"] == scenario and row["env"] == arm]
            if not group:
                continue
            counts: dict[str, _EndpointCounts] = {}
            for metric in METRICS:
                counts[metric] = {
                    "observed": sum(1 for row in group if row[metric + "_status"] == "observed"),
                    "right_censored": sum(
                        1 for row in group if row[metric + "_status"] == "right_censored"
                    ),
                    "missing": sum(
                        1 for row in group if row[metric + "_status"] == "unobserved_before_stop"
                    ),
                    "excluded": _excluded_count(exclusions, scenario, arm),
                }
            overview.append(
                {
                    "scenario": scenario,
                    "arm": arm,
                    "rows": len(group),
                    "observed_runs": sum(1 for row in group if row["status"] == "observed"),
                    "right_censored_runs": sum(
                        1 for row in group if row["status"] == "right_censored"
                    ),
                    "population": POPULATIONS[scenario],
                    "metrics": counts,
                }
            )
    return overview


def _efficacy_entries(
    r2_rows: list, exclusions: dict, bootstrap: int, seed: int, alpha: float
) -> tuple[list, int]:
    """Build the predeclared comparisons and apply the Holm family."""
    efficacy = []
    for scenario in sorted(EFFICACY_SCENARIOS):
        for metric in METRICS:
            group = [row for row in r2_rows if row["scenario"] == scenario]
            efficacy.append(_comparison(group, scenario, metric, bootstrap, seed, exclusions))
    p_values: list[float] = [
        item["test"]["p_value"] for item in efficacy if item["test"]["p_value"] is not None
    ]
    adjusted = holm_adjust(p_values, FAMILY_SIZE)
    position = 0
    for item in efficacy:
        if item["test"]["p_value"] is None:
            item["holm_adjusted_p"] = None
            item["reject_holm"] = None
        else:
            adjusted_p = cast(float, adjusted[position])
            item["holm_adjusted_p"] = adjusted_p
            item["reject_holm"] = adjusted_p < alpha
            position += 1
    return efficacy, len(p_values)


def _batch_block(
    meta: dict, rows: list, r2_rows: list, alpha: float, bootstrap: int, seed: int
) -> dict:
    """Assemble the batch metadata block."""
    ineligible = [scenario for scenario in SCENARIOS if scenario not in EFFICACY_SCENARIOS]
    return {
        **meta,
        "r2_rows": len(r2_rows),
        "r1_rows": len(rows) - len(r2_rows),
        "efficacy_population": sorted(EFFICACY_SCENARIOS),
        "efficacy_ineligible": ineligible,
        "efficacy_ineligible_reason": {
            "A": "hpa_control",
            "F": "visibility_boundary",
            "G": "descriptive_non_argo",
        },
        "population_by_scenario": POPULATIONS,
        "analysis_group_by_scenario": ROW_GROUPS,
        "alpha": alpha,
        "bootstrap_resamples": bootstrap,
        "bootstrap_seed": seed,
        "timing_convention": meta["timing_convention"],
        "claim_status": "exploratory_case_study",
        "confirmatory_claims": False,
    }


def _method_block() -> dict:
    """Return the frozen method description."""
    return {
        "timing_convention": (
            "completed read/evaluation endpoints; right-censored only after a valid window"
        ),
        "pairing_rule": (
            "all scenario/rep blocks complete for the metric, with at least two pairs"
        ),
        "paired_test": (
            "two-sided Wilcoxon signed-rank; exact sign-flip "
            "for <=16 pairs; zero differences dropped"
        ),
        "fallback_test": (
            "two-sided Mann-Whitney U; tie-corrected normal approximation; observed values only"
        ),
        "effect_sizes": (
            "Cliff's delta with percentile bootstrap CI; paired median difference; rank-biserial"
        ),
        "holm_family": ("B-E x detection/evidence/recovery, 12 predeclared hypotheses"),
        "survival": (
            "Kaplan-Meier and RMST to the smallest frozen censor "
            "limit per group; missing endpoints are excluded"
        ),
        "r1": ("descriptive median baseline/first/last with explicit missing counts"),
        "claims": "exploratory case study; no confirmatory claims",
    }


def _family_block(alpha: float, tested: int) -> list:
    """Return the single predeclared Holm family."""
    return [
        {
            "id": "r2_efficacy_managed_drift",
            "description": ("B-E x detection/evidence/recovery, two-sided, Holm correction"),
            "predeclared_size": FAMILY_SIZE,
            "tested": tested,
            "untested": FAMILY_SIZE - tested,
            "alpha": alpha,
            "correction": "holm",
            "note": (
                "Untestable hypotheses are treated as p=1, so the correction is conservative."
            ),
        }
    ]


def _notes_block() -> list:
    """Return the interpretation limits attached to every analysis."""
    return [
        "Exploratory single-case inference; no confirmatory claim.",
        "A is the HPA control and G a descriptive non-Argo case; only B-E enter efficacy.",
        (
            "F is a declared Service targetPort drift reported separately, not "
            "pooled into efficacy: the twelve-hypothesis family was fixed before "
            "collection, so adding F now would expand it post hoc."
        ),
        (
            "G is excluded from efficacy even though batch rows carry "
            "efficacy_eligible=true; the frozen method classifies G as "
            "descriptive non-Argo."
        ),
        "Censored observations are never imputed as zero.",
        (
            "Missing endpoints (unobserved_before_stop) are excluded from "
            "survival and numeric tests; they are not censored observations."
        ),
        (
            "Paired and unpaired tests are complete-case/observed-only; "
            "missingness and censoring are not adjusted."
        ),
        (
            "Paired tests require every scenario/rep block to have both arms "
            "fully observed and at least two pairs."
        ),
        "The RMST horizon is the smallest frozen censor limit per group.",
    ]


def analyze(
    rows: list,
    raw_rows: list | None = None,
    *,
    bootstrap: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
    alpha: float = DEFAULT_ALPHA,
) -> dict:
    """Return the complete analysis result; raise on invalid input."""
    _require(type(bootstrap) is int and bootstrap >= 100, "bootstrap must be an integer >= 100")
    _require(type(seed) is int and seed >= 0, "seed must be a non-negative integer")
    _require(_number(alpha) and 0 < alpha < 1, "alpha must be in (0, 1)")
    meta = validate_rows(rows)
    exclusions = _exclusions(rows, raw_rows)
    r2_rows = [row for row in rows if row["batch_phase"] == "R2"]
    efficacy, tested = _efficacy_entries(r2_rows, exclusions, bootstrap, seed, alpha)
    return {
        "schema_version": 1,
        "analysis": "live_batch_r2_inferential",
        "batch": _batch_block(meta, rows, r2_rows, alpha, bootstrap, seed),
        "method": _method_block(),
        "exclusions": exclusions,
        "overview": _overview_entries(r2_rows, exclusions),
        "r1": _r1_entries(rows),
        "survival": _survival_entries(r2_rows, exclusions),
        "efficacy": efficacy,
        "families": _family_block(alpha, tested),
        "r3": {"status": "not_measured", "statement": "R3: not measured", "claim": "none"},
        "notes": _notes_block(),
    }


def write_outputs(result: dict, outdir: str | Path, *, force: bool = False) -> dict[str, str]:
    """Write JSON and LaTeX artifacts; refuse to overwrite without `force`."""
    directory = Path(outdir)
    directory.mkdir(parents=True, exist_ok=True)
    documents = {
        "json": (
            "live_analysis.json",
            json.dumps(result, allow_nan=False, indent=2, sort_keys=True) + "\n",
        ),
        "overview": ("live_overview.tex", _overview_tex(result)),
        "exclusions": ("live_exclusions.tex", _exclusions_tex(result)),
        "r1": ("live_r1.tex", _r1_tex(result)),
        "survival": ("live_survival.tex", _survival_tex(result)),
        "tests": ("live_tests.tex", _tests_tex(result)),
        "effects": ("live_effects.tex", _effects_tex(result)),
    }
    paths = {key: directory / name for key, (name, _) in documents.items()}
    if not force:
        existing = [str(path) for path in paths.values() if path.exists()]
        if existing:
            raise LiveAnalysisError(
                "output already exists; use --force to replace: " + ", ".join(sorted(existing))
            )
    for key, (_, text) in documents.items():
        target = paths[key]
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(text)
        temporary.replace(target)
    return {key: str(path) for key, path in paths.items()}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse analyzer CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--in", dest="source", type=Path, required=True, help="<batch_id>.analysis.jsonl"
    )
    parser.add_argument("--rows", type=Path, help="optional <batch_id>.rows.jsonl for exclusions")
    parser.add_argument(
        "--out", type=Path, required=True, help="output directory for JSON and LaTeX tables"
    )
    parser.add_argument(
        "--bootstrap",
        type=int,
        default=DEFAULT_BOOTSTRAP,
        help=f"bootstrap resamples (default {DEFAULT_BOOTSTRAP})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"deterministic bootstrap seed (default {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--alpha", type=float, default=DEFAULT_ALPHA, help="nominal alpha (default 0.05)"
    )
    parser.add_argument("--force", action="store_true", help="replace existing output files")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Load inputs, run the analysis, and write JSON and LaTeX artifacts."""
    args = parse_args(argv)
    try:
        rows = load_jsonl(args.source)
        raw_rows = load_jsonl(args.rows) if args.rows else None
        result = analyze(rows, raw_rows, bootstrap=args.bootstrap, seed=args.seed, alpha=args.alpha)
        paths = write_outputs(result, args.out, force=args.force)
    except (ValueError, OSError) as error:
        print(f"Invalid live analysis: {error}", file=sys.stderr)
        return 1
    excluded = result["exclusions"]["count"]
    excluded_text = "not counted" if excluded is None else str(excluded)
    print(
        f"OK: {result['batch']['analysis_rows']} analysis rows, "
        f"{excluded_text} excluded, "
        f"{len(result['efficacy'])} predeclared comparisons "
        f"({result['families'][0]['tested']} testable) -> {args.out}"
    )
    print(f"JSON: {paths['json']}")
    return 0


if __name__ == "__main__":  # pragma: no cover - executable guard
    sys.exit(main())
