#!/usr/bin/env python3
"""Inferential and descriptive analysis for the formal live batch.

Consumes `<batch_id>.analysis.jsonl` from `experiments/live/run_matrix.py`,
optionally `<batch_id>.rows.jsonl` for exclusion accounting, and writes a JSON
result plus thesis-ready LaTeX tables. Standard library only.

Statistical scope is frozen by Bab III:

* B--E are the managed-drift efficacy population.
* A is the HPA control, F the visibility boundary, G a descriptive non-Argo
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
import itertools
import json
import math
from pathlib import Path
import random
import re
from statistics import median
import sys

SCENARIOS = tuple("ABCDEFG")
EFFICACY_SCENARIOS = frozenset("BCDE")
METRICS = ("detection", "evidence", "recovery")
STATUSES = frozenset({"observed", "right_censored"})
METRIC_STATUSES = STATUSES | {"unobserved_before_stop"}
TIMING_CONVENTION = "completed-observation-v1"
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
BATCH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
REVISION = re.compile(r"[0-9a-f]{40}")
RENDER = re.compile(r"[0-9a-f]{64}")
RETRY_SUFFIX = re.compile(r"retry([1-9][0-9]*)")
ATTEMPT_FIELDS = ("batch_attempt", "batch_retry_of")
RAW_ANALYSIS_FIELDS = (
    "batch_phase", "batch_mode", "source_revision", "render_sha256",
    "censor_seconds", "analysis_group", "efficacy_eligible", "synthetic",
    "formal_execution_approved", "stack_isolated", "r3_status", "stop_reason",
    "t0_mono", "t_a_mono", "t_d_mono", "t_e_mono", "t_e_store_mono",
    "t_r_mono", "t_r_first_mono", "t_r_confirmed_mono",
    "window_completed", "window_end_mono", "window_end_utc",
    "recovery_confirmation", "t_r_first_seconds", "t_r_confirmed_seconds",
    "evidence_store_seconds",
    "detection_reads", "evidence_reads", "recovery_reads",
    "detection_ref", "evidence_ref",
    "detection_controller", "recovery_controller",
    "r1_baseline", "r1_first", "r1_last",
    "detection_seconds", "detection_status",
    "evidence_seconds", "evidence_status",
    "recovery_seconds", "recovery_status",
)

REQUIRED_FIELDS = frozenset({
    "schema_version", "run_id", "batch_id", "batch_phase", "batch_mode",
    "scenario", "arm", "env", "rep", "analysis_group", "efficacy_eligible",
    "synthetic", "status", "censor_seconds", "r1_baseline", "r1_first",
    "r1_last", "source_revision", "render_sha256",
    "formal_execution_approved", "stack_isolated", "r3_status",
})


class LiveAnalysisError(ValueError):
    """Input is not a valid batch analysis dataset."""


def _number(value):
    return (type(value) in (int, float) and math.isfinite(value))


def _load_jsonl(path):
    rows = []
    try:
        text = Path(path).read_text()
    except (OSError, UnicodeError) as error:
        raise LiveAnalysisError(f"cannot read {path}: {error}") from error
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise LiveAnalysisError(
                f"invalid JSON on line {number}") from error
        if not isinstance(row, dict):
            raise LiveAnalysisError(f"line {number} is not a JSON object")
        rows.append(row)
    if not rows:
        raise LiveAnalysisError("empty JSONL input")
    return rows


def _require(condition, message):
    if not condition:
        raise LiveAnalysisError(message)


def _validate_metric(row, metric):
    value = row.get(metric + "_seconds")
    status = row.get(metric + "_status")
    limit = row["censor_seconds"]
    _require(isinstance(status, str) and status in METRIC_STATUSES,
             f"{metric}_status is not a supported metric status")
    if status == "observed":
        _require(_number(value), f"{metric}_seconds is not a finite number")
        _require(0 <= value <= limit,
                 f"{metric}_seconds is outside [0, censor_seconds]")
    elif status == "right_censored":
        _require(value is None,
                 f"{metric}_seconds must be null when right_censored")
    else:
        _require(value is None,
                 f"{metric}_seconds must be null when unobserved_before_stop")
        _require(row.get("status") == "observed"
                 and row.get("stop_reason") == "recovery"
                 and row.get("recovery_status") == "observed",
                 f"{metric}_status lacks a confirmed early-recovery provenance")


def _validate_timing(row, strict):
    """Validate completed-observation bounds for new-convention rows.

    Legacy rows predate the convention and are validated by the older field
    contract only; no new bound is invented for them.
    """
    if not strict:
        return
    required = (
        "t0_mono", "t_a_mono", "t_d_mono", "t_e_mono", "t_r_mono",
        "t_r_first_mono", "t_r_confirmed_mono", "window_completed",
        "window_end_mono",
    )
    missing = [field for field in required if field not in row]
    _require(not missing,
             f"new-convention row is missing timing fields: {missing}")
    t0 = row.get("t0_mono")
    limit = row.get("censor_seconds")
    _require(_number(t0), "t0_mono is not finite")
    t_a = row.get("t_a_mono")
    _require(_number(t_a) and t_a >= t0, "t_a_mono is not after t0_mono")
    if row.get("injection_seconds") is not None:
        _require(math.isclose(row["injection_seconds"], t_a - t0,
                              rel_tol=1e-9, abs_tol=1e-9),
                 "injection_seconds disagrees with its bounds")
    _require(row.get("window_completed") is True,
             "new-convention row lacks completed observation-window provenance")
    window_end = row.get("window_end_mono")
    _require(_number(window_end) and window_end >= t0,
             "window_end_mono is not a finite completion after t0")
    if row.get("status") == "observed":
        _require(row.get("stop_reason") == "recovery",
                 "observed row does not record recovery as its stop reason")
    else:
        _require(row.get("stop_reason") == "timeout",
                 "right-censored row does not record a timeout stop")
        _require(window_end >= t0 + limit,
                 "right-censored row did not complete its observation window")
    for metric in METRICS:
        key = {"detection": "t_d", "evidence": "t_e",
               "recovery": "t_r"}[metric]
        point = row.get(key + "_mono")
        value = row.get(metric + "_seconds")
        status = row.get(metric + "_status")
        if point is None:
            _require(value is None and status != "observed",
                     f"{key}_mono is missing for an observed metric")
            continue
        _require(_number(point), f"{key}_mono is not finite")
        _require(point >= t0, f"{key}_mono precedes t0_mono")
        _require(point <= t0 + limit, f"{key}_mono exceeds the censor limit")
        _require(point <= window_end,
                 f"{key}_mono occurs after the observation window ended")
        _require(_number(value)
                 and math.isclose(value, point - t0, rel_tol=1e-9,
                                  abs_tol=1e-9),
                 f"{metric}_seconds disagrees with its bounds")
        _require(status == "observed",
                 f"{key}_mono is present for a non-observed metric")
    t_r_first = row.get("t_r_first_mono")
    t_r_confirmed = row.get("t_r_confirmed_mono")
    if t_r_first is not None:
        _require(_number(t_r_first) and t0 <= t_r_first <= t0 + limit,
                 "t_r_first_mono is outside the observation window")
        _require(t_r_first <= window_end,
                 "t_r_first_mono occurs after the observation window ended")
        if row.get("t_r_first_seconds") is not None:
            _require(math.isclose(row["t_r_first_seconds"],
                                  t_r_first - t0, rel_tol=1e-9,
                                  abs_tol=1e-9),
                     "t_r_first_seconds disagrees with its bounds")
    if t_r_confirmed is not None:
        _require(_number(t_r_confirmed)
                 and t0 <= t_r_confirmed <= t0 + limit,
                 "t_r_confirmed_mono is outside the observation window")
        _require(t_r_confirmed <= window_end,
                 "t_r_confirmed_mono occurs after the observation window ended")
        _require(t_r_first is not None and t_r_confirmed >= t_r_first,
                 "confirmation bounds are not ordered")
        if row.get("t_r_confirmed_seconds") is not None:
            _require(math.isclose(row["t_r_confirmed_seconds"],
                                  t_r_confirmed - t0, rel_tol=1e-9,
                                  abs_tol=1e-9),
                     "t_r_confirmed_seconds disagrees with its bounds")
    if row.get("recovery_status") == "observed":
        _require(row.get("t_r_mono") is not None
                 and t_r_first is not None
                 and t_r_confirmed is not None
                 and math.isclose(row["t_r_mono"], t_r_first,
                                  rel_tol=1e-9, abs_tol=1e-9)
                 and window_end >= t_r_confirmed
                 and row.get("recovery_confirmation") == "confirmed",
                 "confirmed recovery lacks ordered first/confirmation bounds "
                 "and window-stop support")
    else:
        _require(row.get("t_r_mono") is None and t_r_confirmed is None
                 and row.get("recovery_confirmation") != "confirmed",
                 "unconfirmed recovery carries a primary recovery bound")
    store = row.get("t_e_store_mono")
    if store is not None:
        _require(_number(store) and row.get("t_e_mono") is not None
                 and store >= row["t_e_mono"],
                 "t_e_store_mono precedes the evidence evaluation")
        if row.get("evidence_store_seconds") is not None:
            _require(math.isclose(row["evidence_store_seconds"],
                                  store - t0, rel_tol=1e-9, abs_tol=1e-9),
                     "evidence_store_seconds disagrees with its bounds")


def _run_attempt(row, label, base_run_id):
    """Attempt number encoded by the run id; retries use `-retry<N>`."""
    run_id = row["run_id"]
    if run_id == base_run_id:
        return 0
    prefix = base_run_id + "-"
    _require(run_id.startswith(prefix),
             f"{label} has run_id/identity mismatch")
    match = RETRY_SUFFIX.fullmatch(run_id[len(prefix):])
    _require(match is not None, f"{label} has malformed retry suffix")
    return int(match.group(1))


def _validate_attempt_metadata(row, label, base_run_id, attempt):
    """Check optional attempt fields; legacy unsuffixed rows omit them."""
    present = [field for field in ATTEMPT_FIELDS if field in row]
    _require(len(present) in (0, 2),
             f"{label} has incomplete attempt metadata")
    if not present:
        _require(attempt == 0,
                 f"{label} retry lacks batch_attempt/batch_retry_of")
        return
    value = row["batch_attempt"]
    _require(type(value) is int and value >= 0,
             f"{label} has invalid batch_attempt")
    retry_of = row["batch_retry_of"]
    if value == 0:
        _require(retry_of is None, f"{label} has invalid batch_retry_of")
    else:
        _require(retry_of == base_run_id,
                 f"{label} has mismatched batch_retry_of")
    _require(value == attempt, f"{label} has inconsistent retry suffix")


def validate_rows(rows):
    """Validate one batch analysis dataset; raise on any inconsistency."""
    _require(isinstance(rows, list) and rows, "dataset must be a non-empty list")
    batches, revisions, renders = set(), set(), set()
    approvals, isolated, modes = set(), set(), set()
    conventions = set()
    seen_runs, seen_blocks = set(), set()
    for index, row in enumerate(rows, 1):
        _require(isinstance(row, dict), f"row {index} is not an object")
        missing = sorted(REQUIRED_FIELDS - set(row))
        _require(not missing, f"row {index} missing fields: {missing}")
        marker = row.get("timing_convention")
        _require(marker is None or isinstance(marker, str),
                 f"row {index} has an invalid timing_convention")
        if marker is not None:
            _require(marker == TIMING_CONVENTION,
                     f"row {index} has an unsupported timing_convention")
        conventions.add(marker)
        _require(type(row["schema_version"]) is int
                 and row["schema_version"] == 2,
                 f"row {index} has unsupported schema_version")
        run_id = row["run_id"]
        _require(isinstance(run_id, str) and 0 < len(run_id) <= 128,
                 f"row {index} has invalid run_id")
        _require(run_id not in seen_runs, f"row {index} repeats a run_id")
        seen_runs.add(run_id)

        scenario = row["scenario"]
        _require(scenario in SCENARIOS, f"row {index} has invalid scenario")
        arm = row["arm"]
        _require(isinstance(arm, str) and arm in ARM_ENV,
                 f"row {index} has invalid arm")
        _require(row["env"] == ARM_ENV[arm],
                 f"row {index} violates arm/env mapping")
        rep = row["rep"]
        _require(type(rep) is int and 1 <= rep <= 15,
                 f"row {index} has invalid rep")
        expected_phase = "R2" if rep <= 10 else "R1"
        _require(row["batch_phase"] == expected_phase,
                 f"row {index} has phase/rep mismatch")
        _require(row["analysis_group"] == ROW_GROUPS[scenario],
                 f"row {index} has invalid analysis_group")
        _require(type(row["efficacy_eligible"]) is bool
                 and row["efficacy_eligible"] == (scenario not in ("A", "F")),
                 f"row {index} has invalid efficacy_eligible")
        _require(row["synthetic"] is False,
                 f"row {index} is synthetic and cannot be analyzed")
        _require(isinstance(row["status"], str) and row["status"] in STATUSES,
                 f"row {index} is not an analyzable run status")
        _require(row["batch_mode"] == "live",
                 f"row {index} is not from a live batch")
        batch_id = row["batch_id"]
        _require(isinstance(batch_id, str) and BATCH_ID.fullmatch(batch_id),
                 f"row {index} has invalid batch_id")
        base_run_id = f"{batch_id}-{arm}-{scenario}-r{rep:02d}"
        attempt = _run_attempt(row, f"row {index}", base_run_id)
        _validate_attempt_metadata(row, f"row {index}", base_run_id, attempt)
        _require(REVISION.fullmatch(str(row["source_revision"])),
                 f"row {index} has invalid source_revision")
        _require(RENDER.fullmatch(str(row["render_sha256"])),
                 f"row {index} has invalid render_sha256")
        _require(type(row["formal_execution_approved"]) is bool,
                 f"row {index} has invalid formal_execution_approved")
        _require(type(row["stack_isolated"]) is bool,
                 f"row {index} has invalid stack_isolated")
        _require(row["r3_status"] == "not_measured",
                 f"row {index} has unsupported r3_status")
        limit = row["censor_seconds"]
        _require(_number(limit) and limit > 0,
                 f"row {index} has invalid censor_seconds")
        for metric in METRICS:
            _validate_metric(row, metric)
        _validate_timing(row, marker == TIMING_CONVENTION)
        for field in ("r1_baseline", "r1_first", "r1_last"):
            value = row[field]
            _require(value is None or (_number(value) and 0 <= value <= 100),
                     f"row {index} has invalid {field}")
        if row["status"] == "observed":
            _require(row["recovery_status"] == "observed",
                     f"row {index} has inconsistent run/recovery status")
        else:
            _require(row["recovery_status"] == "right_censored",
                     f"row {index} has inconsistent run/recovery status")

        block = (scenario, row["env"], rep)
        _require(block not in seen_blocks,
                 f"row {index} duplicates a scenario/arm/rep block")
        seen_blocks.add(block)
        batches.add(batch_id)
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
    _require(len(conventions) == 1,
             "dataset mixes completed-observation timing conventions")
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


def _average_ranks(values):
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[order[position]] = rank
        start = end
    return ranks


def cliffs_delta(first, second):
    """P(first > second) - P(first < second), in [-1, 1]."""
    if not first or not second:
        return None
    greater = sum(1 for left in first for right in second if left > right)
    less = sum(1 for left in first for right in second if left < right)
    return (greater - less) / (len(first) * len(second))


def mann_whitney_u(first, second):
    """Two-sided Mann--Whitney U via the tie-corrected normal approximation."""
    n1, n2 = len(first), len(second)
    if n1 < MIN_GROUP or n2 < MIN_GROUP:
        return {"statistic": None, "p_value": None, "method": "not_estimable",
                "n_manual": n1, "n_gitops": n2, "note": "fewer than 3 per arm"}
    combined = list(first) + list(second)
    ranks = _average_ranks(combined)
    rank_sum = sum(ranks[:n1])
    u1 = rank_sum - n1 * (n1 + 1) / 2.0
    u2 = n1 * n2 - u1
    total = n1 + n2
    tie_sum = 0
    for value in set(combined):
        count = combined.count(value)
        tie_sum += count ** 3 - count
    variance = (n1 * n2 / 12.0) * ((total + 1) - tie_sum / (total * (total - 1)))
    if variance <= 0:
        return {"statistic": min(u1, u2), "p_value": 1.0,
                "method": "normal_approximation_tie_corrected",
                "n_manual": n1, "n_gitops": n2,
                "note": "all observations tied"}
    z = (abs(u1 - n1 * n2 / 2.0) - 0.5) / math.sqrt(variance)
    p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
    p_value = min(1.0, max(0.0, p_value))
    return {"statistic": min(u1, u2), "p_value": p_value,
            "method": "normal_approximation_tie_corrected",
            "n_manual": n1, "n_gitops": n2, "note": None}


def wilcoxon_signed_rank(differences):
    """Two-sided Wilcoxon signed-rank test with exact p for n <= 16."""
    nonzero = [value for value in differences if value != 0]
    n = len(nonzero)
    if n == 0:
        return {"statistic": 0.0, "w_plus": 0.0, "w_minus": 0.0,
                "p_value": 1.0, "method": "all_zero", "n_nonzero": 0,
                "n_pairs": len(differences), "rank_biserial": 0.0}
    ranks = _average_ranks([abs(value) for value in nonzero])
    w_plus = sum(rank for rank, value in zip(ranks, nonzero) if value > 0)
    w_minus = sum(rank for rank, value in zip(ranks, nonzero) if value < 0)
    if n <= 16:
        observed = round(w_plus, 9)
        lower = upper = 0
        for signs in itertools.product((1, -1), repeat=n):
            total = round(sum(rank for rank, sign in zip(ranks, signs)
                              if sign > 0), 9)
            if total <= observed + 1e-9:
                lower += 1
            if total >= observed - 1e-9:
                upper += 1
        p_value = min(1.0, 2.0 * min(lower, upper) / (2 ** n))
        method = "exact_sign_flip"
    else:
        mean = n * (n + 1) / 4.0
        tie_sum = 0
        for value in set(abs(item) for item in nonzero):
            count = sum(1 for item in nonzero if abs(item) == value)
            tie_sum += count ** 3 - count
        variance = n * (n + 1) * (2 * n + 1) / 24.0 - tie_sum / 48.0
        z = (abs(w_plus - mean) - 0.5) / math.sqrt(variance)
        p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
        p_value = min(1.0, max(0.0, p_value))
        method = "normal_approximation_tie_corrected"
    total_rank = w_plus + w_minus
    rank_biserial = ((w_plus - w_minus) / total_rank) if total_rank else 0.0
    return {"statistic": w_plus, "w_plus": w_plus, "w_minus": w_minus,
            "p_value": p_value, "method": method, "n_nonzero": n,
            "n_pairs": len(differences), "rank_biserial": rank_biserial}


def kaplan_meier(events, censored, horizon):
    """Kaplan--Meier curve and restricted mean survival to `horizon`.

    Events beyond the horizon are administratively censored at the horizon.
    Censored observations contribute risk time but never an event or a zero.
    """
    _require(_number(horizon) and horizon > 0, "horizon must be positive")
    _require(all(_number(value) and 0 <= value for value in events),
             "event times must be finite and non-negative")
    _require(all(_number(value) and 0 <= value for value in censored),
             "censor times must be finite and non-negative")
    n = len(events) + len(censored)
    if n == 0:
        return {"n": 0, "events": 0, "censored": 0, "horizon_seconds": horizon,
                "median_seconds": None, "median_reached": False,
                "rmst_seconds": None, "survival_at_horizon": None}
    timeline = {}
    observed = 0
    for value in events:
        if value > horizon:
            timeline[horizon] = timeline.get(horizon, [0, 0])
            timeline[horizon][1] += 1
        else:
            timeline.setdefault(value, [0, 0])[0] += 1
            observed += 1
    for value in censored:
        at = min(value, horizon)
        timeline.setdefault(at, [0, 0])[1] += 1
    at_risk = n
    survival = 1.0
    previous = 0.0
    rmst = 0.0
    median_time = None
    for time in sorted(timeline):
        deaths, stopped = timeline[time]
        rmst += survival * (time - previous)
        previous = time
        if at_risk > 0 and deaths:
            survival *= 1.0 - deaths / at_risk
            if median_time is None and survival <= 0.5:
                median_time = time
        at_risk -= deaths + stopped
    rmst += survival * max(0.0, horizon - previous)
    return {"n": n, "events": observed, "censored": n - observed,
            "horizon_seconds": horizon, "median_seconds": median_time,
            "median_reached": median_time is not None,
            "rmst_seconds": rmst, "survival_at_horizon": survival}


def holm_adjust(p_values, family_size):
    """Holm step-down adjusted p-values, preserving input order."""
    _require(family_size >= len(p_values),
             "family size cannot be smaller than tested hypotheses")
    _require(all(_number(value) and 0 <= value <= 1 for value in p_values),
             "p-values must be in [0, 1]")
    adjusted = [None] * len(p_values)
    running = 0.0
    for rank, index in enumerate(
            sorted(range(len(p_values)), key=lambda item: p_values[item]), 1):
        candidate = min(1.0, (family_size - rank + 1) * p_values[index])
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def _percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _bootstrap_cliff(first, second, resamples, seed, pairs=None):
    if not first or not second:
        return None
    rng = random.Random(f"{seed}:cliff")
    values = []
    if pairs:
        for _ in range(resamples):
            sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
            values.append(cliffs_delta([item[0] for item in sample],
                                       [item[1] for item in sample]))
    else:
        for _ in range(resamples):
            left = [rng.choice(first) for _ in first]
            right = [rng.choice(second) for _ in second]
            values.append(cliffs_delta(left, right))
    values.sort()
    return [_percentile(values, 0.025), _percentile(values, 0.975)]


def _bootstrap_median(values, resamples, seed):
    if not values:
        return None
    rng = random.Random(f"{seed}:paired")
    draws = sorted(median([rng.choice(values) for _ in values])
                   for _ in range(resamples))
    return [_percentile(draws, 0.025), _percentile(draws, 0.975)]


def _excluded_count(exclusions, scenario, arm, phase="R2"):
    if exclusions is None or exclusions.get("count") is None:
        return None
    return sum(
        1 for item in exclusions["rows"]
        if item.get("scenario") == scenario
        and ARM_ENV.get(item.get("arm"), item.get("arm")) == arm
        and item.get("phase") == phase)


def _pairing(rows, metric):
    arms = {"manual": {}, "gitops": {}}
    for row in rows:
        arms[row["env"]][row["rep"]] = row
    blocks = sorted(set(arms["manual"]) | set(arms["gitops"]))
    matched = [rep for rep in blocks
               if rep in arms["manual"] and rep in arms["gitops"]]
    complete = [rep for rep in matched
                if arms["manual"][rep][metric + "_status"] == "observed"
                and arms["gitops"][rep][metric + "_status"] == "observed"]
    missing = [rep for rep in matched
               if "unobserved_before_stop" in (
                   arms["manual"][rep][metric + "_status"],
                   arms["gitops"][rep][metric + "_status"])]
    censored = [rep for rep in matched
                if rep not in missing
                and "right_censored" in (
                    arms["manual"][rep][metric + "_status"],
                    arms["gitops"][rep][metric + "_status"])]
    unmatched = len(blocks) - len(matched)
    if (blocks and not unmatched and not missing and not censored
            and len(complete) >= MIN_PAIRS):
        return {"method": "paired", "reason": "complete_paired_blocks",
                "blocks": len(blocks), "complete_pairs": len(complete),
                "right_censored_blocks": 0, "missing_blocks": 0,
                "unmatched_blocks": 0, "censored_blocks": 0}
    if not blocks:
        reason = "no_r2_rows"
    elif unmatched:
        reason = "unmatched_arm_blocks"
    elif missing:
        reason = "missing_blocks"
    elif censored:
        reason = "censored_blocks"
    else:
        reason = "fewer_than_2_pairs"
    return {"method": "unpaired", "reason": reason, "blocks": len(blocks),
            "complete_pairs": len(complete),
            "right_censored_blocks": len(censored),
            "missing_blocks": len(missing),
            "unmatched_blocks": unmatched,
            "censored_blocks": len(censored)}


def _comparison(rows, scenario, metric, bootstrap, seed, exclusions=None):
    pairing = _pairing(rows, metric)
    manual = {row["rep"]: row for row in rows if row["env"] == "manual"}
    gitops = {row["rep"]: row for row in rows if row["env"] == "gitops"}
    observed = {"manual": [], "gitops": []}
    counts = {}
    for arm, rows_by_rep in (("manual", manual), ("gitops", gitops)):
        counts[arm] = {"observed": 0, "right_censored": 0,
                       "missing": 0,
                       "excluded": _excluded_count(
                           exclusions, scenario, arm)}
        for row in rows_by_rep.values():
            status = row[metric + "_status"]
            if status == "observed":
                observed[arm].append(row[metric + "_seconds"])
                counts[arm]["observed"] += 1
            elif status == "right_censored":
                counts[arm]["right_censored"] += 1
            else:
                counts[arm]["missing"] += 1
    differences = []
    pairs = []
    if pairing["method"] == "paired":
        for rep in sorted(set(manual) & set(gitops)):
            left = manual[rep][metric + "_seconds"]
            right = gitops[rep][metric + "_seconds"]
            differences.append(left - right)
            pairs.append((left, right))
    effect = {
        "cliffs_delta": cliffs_delta(observed["manual"], observed["gitops"]),
        "cliffs_delta_ci": _bootstrap_cliff(
            observed["manual"], observed["gitops"], bootstrap, seed,
            pairs=pairs or None),
        "cliffs_delta_bootstrap": ("paired_blocks" if pairs
                                   else "independent_arms"),
        "median_paired_difference": None,
        "median_paired_difference_ci": None,
        "rank_biserial": None,
    }
    if pairing["method"] == "paired":
        difference_median = median(differences)
        effect["median_paired_difference"] = difference_median
        effect["median_paired_difference_ci"] = _bootstrap_median(
            differences, bootstrap, seed)
        test = wilcoxon_signed_rank(differences)
        effect["rank_biserial"] = test["rank_biserial"]
        test_name = "wilcoxon_signed_rank"
        statistic = test["statistic"]
        p_value = test["p_value"]
        method = test["method"]
        size = {"n_pairs": len(differences),
                "n_nonzero": test["n_nonzero"]}
    elif (len(observed["manual"]) >= MIN_GROUP
          and len(observed["gitops"]) >= MIN_GROUP):
        test = mann_whitney_u(observed["manual"], observed["gitops"])
        test_name = "mann_whitney_u"
        statistic = test["statistic"]
        p_value = test["p_value"]
        method = test["method"]
        size = {"n_manual": len(observed["manual"]),
                "n_gitops": len(observed["gitops"])}
    else:
        test_name, statistic, p_value = "not_estimable", None, None
        method = "not_estimable"
        size = {"n_manual": len(observed["manual"]),
                "n_gitops": len(observed["gitops"])}
    if pairing["method"] == "paired":
        analysis_set = "paired_complete_blocks"
        note = ("Paired complete-case comparison; censored blocks are not "
                "used in the efficacy test.")
    elif test_name == "not_estimable":
        analysis_set = "not_estimable"
        note = "Not estimable from the available observations."
    else:
        analysis_set = "observed_values_only"
        note = ("Unpaired fallback uses observed values only; censoring is "
                "not adjusted.")
    if pairing["missing_blocks"]:
        note += (" Missing endpoints are excluded from the numeric test and "
                 "are not treated as censored observations.")
    return {
        "scenario": scenario,
        "metric": metric,
        "population": "managed_drift",
        "pairing": pairing,
        "analysis_set": analysis_set,
        "censoring_adjusted": False,
        "note": note,
        "endpoints": counts,
        "test": {"name": test_name, "statistic": statistic,
                 "p_value": p_value, "method": method, **size},
        "effect": effect,
    }


def _survival_entries(rows, exclusions=None):
    groups = {}
    for row in rows:
        groups.setdefault((row["scenario"], row["env"]), []).append(row)
    entries = []
    for (scenario, arm), group in sorted(
            groups.items(), key=lambda item: (item[0][0],
                                              ARM_ORDER[item[0][1]])):
        for metric in METRICS:
            events = [row[metric + "_seconds"] for row in group
                      if row[metric + "_status"] == "observed"]
            censored = [row["censor_seconds"] for row in group
                        if row[metric + "_status"] == "right_censored"]
            missing = sum(1 for row in group
                          if row[metric + "_status"] == "unobserved_before_stop")
            excluded = _excluded_count(exclusions, scenario, arm)
            horizon = min(row["censor_seconds"] for row in group)
            curve = kaplan_meier(events, censored, horizon)
            administrative = sum(1 for value in events if value > horizon)
            estimable = bool(events or censored)
            note = None
            if not estimable:
                note = ("not estimable: all endpoints are missing before stop; "
                        "they are not censored observations")
            elif administrative:
                note = ("observed events beyond the RMST horizon are "
                        "administratively censored")
            elif curve["events"] == 0:
                note = "all observations censored"
            elif missing:
                note = "missing endpoints excluded from survival, not censored"
            elif not curve["median_reached"]:
                note = "median not reached within horizon"
            entries.append({
                "scenario": scenario,
                "arm": arm,
                "metric": metric,
                "population": POPULATIONS[scenario],
                "included_in_efficacy": scenario in EFFICACY_SCENARIOS,
                **curve,
                "observed": len(events),
                "right_censored": len(censored),
                "missing": missing,
                "excluded_runs": excluded,
                "estimable": estimable,
                "censor_limits_seconds": sorted(
                    {row["censor_seconds"] for row in group}),
                "administratively_censored": administrative,
                "median_estimable": curve["median_reached"],
                "note": note,
            })
    return entries


def _r1_entries(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row["scenario"], row["env"],
                           row["batch_phase"]), []).append(row)
    entries = []
    for (scenario, arm, phase), group in sorted(
            groups.items(), key=lambda item: (item[0][0],
                                              ARM_ORDER[item[0][1]],
                                              item[0][2])):
        entry = {"scenario": scenario, "arm": arm, "phase": phase,
                 "rows": len(group)}
        for field in ("r1_baseline", "r1_first", "r1_last"):
            values = [row[field] for row in group if row[field] is not None]
            entry[field[3:]] = {
                "present": len(values),
                "missing": len(group) - len(values),
                "median": median(values) if values else None,
            }
        entry["excluded_rows"] = sum(
            1 for row in group
            if row["r1_first"] is None and row["r1_last"] is None)
        entries.append(entry)
    return entries


def _classify_raw(row):
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
    if (not REVISION.fullmatch(str(row.get("source_revision")))
            or not RENDER.fullmatch(str(row.get("render_sha256")))):
        return "invalid_provenance"
    limit = row.get("censor_seconds")
    if not (_number(limit) and limit > 0):
        return "invalid_censor_seconds"
    for metric in METRICS:
        value = row.get(metric + "_seconds")
        status = row.get(metric + "_status")
        if status == "right_censored" and value is None:
            continue
        if (status == "unobserved_before_stop" and value is None
                and row.get("status") == "observed"
                and row.get("stop_reason") == "recovery"
                and row.get("recovery_status") == "observed"):
            continue
        if (status == "observed" and _number(value)
                and 0 <= value <= limit):
            continue
        return "invalid_metric_observation"
    return None


def _raw_identity(row, index, batch_id):
    """Return the raw row's cell and attempt, validated against its run id."""
    arm = row.get("arm")
    _require(isinstance(arm, str) and arm in ARM_ENV,
             f"raw row {index} has invalid arm")
    scenario = row.get("scenario")
    _require(scenario in SCENARIOS, f"raw row {index} has invalid scenario")
    rep = row.get("rep")
    _require(type(rep) is int and 1 <= rep <= 15,
             f"raw row {index} has invalid rep")
    base_run_id = f"{batch_id}-{arm}-{scenario}-r{rep:02d}"
    attempt = _run_attempt(row, f"raw row {index}", base_run_id)
    _validate_attempt_metadata(row, f"raw row {index}", base_run_id, attempt)
    return (arm, scenario, rep), attempt


def _validate_analyzed_raw(raw, analysis, index):
    """Reject raw evidence that disagrees with its analyzed run."""
    raw_marker = raw.get("timing_convention")
    analysis_marker = analysis.get("timing_convention")
    _require((raw_marker is None) == (analysis_marker is None),
             f"raw row {index} timing_convention disagrees with analysis row")
    if raw_marker is not None:
        _require(raw_marker == analysis_marker,
                 f"raw row {index} timing_convention disagrees with analysis row")
    for field in RAW_ANALYSIS_FIELDS:
        if field in raw:
            _require(raw[field] == analysis.get(field),
                     f"raw row {index} {field} disagrees with analysis row")
    if "env" in raw:
        raw_env = raw["env"]
        _require(isinstance(raw_env, str),
                 f"raw row {index} has invalid env")
        _require(ARM_ENV.get(raw_env, raw_env) == analysis["env"],
                 f"raw row {index} env disagrees with analysis row")
    for label, row in ((f"raw row {index}", raw),
                       (f"analysis row {index}", analysis)):
        for field, expected in (("cleanup_status", "ok"),
                                ("arm_restore_status", "restored")):
            if field in row:
                _require(row[field] == expected,
                         f"{label} has failed {field}")
        if "postcondition" in row:
            postcondition = row["postcondition"]
            _require(isinstance(postcondition, dict)
                     and postcondition.get("verified") is True,
                     f"{label} postcondition is not verified")
        for field in ("batch_stop_reason", "error"):
            if field in row:
                _require(not row[field], f"{label} has {field}")


def _raw_retry_violation(predecessor):
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


def _validate_raw_chain(cells):
    """Each attempt after 0 must follow one retryable baseline failure."""
    for cell, attempts in cells.items():
        attempts.sort(key=lambda item: item[0])
        numbers = [item[0] for item in attempts]
        _require(numbers == list(range(len(numbers))),
                 f"raw rows for cell {cell} have a broken attempt chain")
        for position in range(1, len(attempts)):
            _, predecessor, _ = attempts[position - 1]
            _, _, index = attempts[position]
            reason = _raw_retry_violation(predecessor)
            _require(reason is None,
                     f"raw row {index} has a retry chain that violates the "
                     f"baseline retry policy ({reason})")


def _exclusions(rows, raw_rows):
    if raw_rows is None:
        return {"source": "not_provided", "raw_rows": None, "count": None,
                "by_reason": {}, "rows": []}
    _require(isinstance(raw_rows, list) and raw_rows,
             "rows.jsonl must contain at least one row")
    batch_id = rows[0]["batch_id"]
    analysis_marker = rows[0].get("timing_convention")
    analyzed = {row["run_id"]: row for row in rows}
    raw_ids = []
    cells = {}
    for index, row in enumerate(raw_rows, 1):
        _require(isinstance(row, dict), f"raw row {index} is not an object")
        run_id = row.get("run_id")
        _require(isinstance(run_id, str) and 0 < len(run_id) <= 128,
                 f"raw row {index} has invalid run_id")
        marker = row.get("timing_convention")
        _require(marker == analysis_marker,
                 f"raw row {index} timing_convention disagrees with analysis rows")
        _validate_timing(
            row, marker == TIMING_CONVENTION and row.get("status") in STATUSES)
        _require(row.get("batch_id") == batch_id,
                 f"raw row {index} belongs to another batch")
        cell, attempt = _raw_identity(row, index, batch_id)
        if run_id in analyzed:
            _require(row.get("status") == analyzed[run_id]["status"],
                     f"raw row {index} status disagrees with analysis row")
            _validate_analyzed_raw(row, analyzed[run_id], index)
        raw_ids.append(run_id)
        cells.setdefault(cell, []).append((attempt, row, index))
    _require(len(raw_ids) == len(set(raw_ids)), "rows.jsonl repeats a run_id")
    _validate_raw_chain(cells)
    _require(not (set(analyzed) - set(raw_ids)),
             "rows.jsonl is missing analyzed runs")
    excluded = []
    for row in raw_rows:
        if row["run_id"] in analyzed:
            continue
        reason = _classify_raw(row)
        _require(reason is not None,
                 "rows.jsonl contains an analyzable run absent from analysis.jsonl")
        arm = row.get("arm") if isinstance(row.get("arm"), str) else None
        excluded.append({
            "run_id": row["run_id"],
            "arm": arm if arm in ARM_ENV else None,
            "scenario": (row.get("scenario")
                         if row.get("scenario") in SCENARIOS else None),
            "rep": row.get("rep") if type(row.get("rep")) is int else None,
            "phase": row.get("batch_phase"),
            "reason": reason,
        })
    by_reason = {}
    for item in excluded:
        by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
    return {"source": "rows_jsonl", "raw_rows": len(raw_rows),
            "count": len(excluded), "by_reason": dict(sorted(by_reason.items())),
            "rows": excluded}


def analyze(rows, raw_rows=None, *, bootstrap=DEFAULT_BOOTSTRAP,
            seed=DEFAULT_SEED, alpha=DEFAULT_ALPHA):
    """Return the complete analysis result; raise on invalid input."""
    _require(type(bootstrap) is int and bootstrap >= 100,
             "bootstrap must be an integer >= 100")
    _require(type(seed) is int and seed >= 0, "seed must be a non-negative integer")
    _require(_number(alpha) and 0 < alpha < 1, "alpha must be in (0, 1)")
    meta = validate_rows(rows)
    exclusions = _exclusions(rows, raw_rows)
    r2_rows = [row for row in rows if row["batch_phase"] == "R2"]
    overview = []
    for scenario in SCENARIOS:
        for arm in ("manual", "gitops"):
            group = [row for row in r2_rows
                     if row["scenario"] == scenario and row["env"] == arm]
            if not group:
                continue
            counts = {}
            for metric in METRICS:
                counts[metric] = {
                    "observed": sum(1 for row in group
                                    if row[metric + "_status"] == "observed"),
                    "right_censored": sum(1 for row in group
                                          if row[metric + "_status"]
                                          == "right_censored"),
                    "missing": sum(1 for row in group
                                   if row[metric + "_status"]
                                   == "unobserved_before_stop"),
                    "excluded": _excluded_count(exclusions, scenario, arm),
                }
            overview.append({
                "scenario": scenario,
                "arm": arm,
                "rows": len(group),
                "observed_runs": sum(1 for row in group
                                     if row["status"] == "observed"),
                "right_censored_runs": sum(1 for row in group
                                           if row["status"] == "right_censored"),
                "population": POPULATIONS[scenario],
                "metrics": counts,
            })
    survival_entries = _survival_entries(r2_rows, exclusions)
    efficacy = []
    for scenario in sorted(EFFICACY_SCENARIOS):
        for metric in METRICS:
            group = [row for row in r2_rows if row["scenario"] == scenario]
            efficacy.append(_comparison(
                group, scenario, metric, bootstrap, seed, exclusions))
    p_values = [item["test"]["p_value"] for item in efficacy
                if item["test"]["p_value"] is not None]
    adjusted = holm_adjust(p_values, FAMILY_SIZE)
    position = 0
    for item in efficacy:
        if item["test"]["p_value"] is None:
            item["holm_adjusted_p"] = None
            item["reject_holm"] = None
        else:
            item["holm_adjusted_p"] = adjusted[position]
            item["reject_holm"] = adjusted[position] < alpha
            position += 1
    ineligible = [scenario for scenario in SCENARIOS
                  if scenario not in EFFICACY_SCENARIOS]
    return {
        "schema_version": 1,
        "analysis": "live_batch_r2_inferential",
        "batch": {
            **meta,
            "r2_rows": len(r2_rows),
            "r1_rows": len(rows) - len(r2_rows),
            "efficacy_population": sorted(EFFICACY_SCENARIOS),
            "efficacy_ineligible": ineligible,
            "efficacy_ineligible_reason": {
                "A": "hpa_control", "F": "visibility_boundary",
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
        },
        "method": {
            "timing_convention": ("completed read/evaluation endpoints; "
                                  "right-censored only after a valid window"),
            "pairing_rule": ("all scenario/rep blocks complete for the "
                             "metric, with at least two pairs"),
            "paired_test": ("two-sided Wilcoxon signed-rank; exact sign-flip "
                            "for <=16 pairs; zero differences dropped"),
            "fallback_test": ("two-sided Mann-Whitney U; tie-corrected normal "
                              "approximation; observed values only"),
            "effect_sizes": ("Cliff's delta with percentile bootstrap CI; "
                             "paired median difference; rank-biserial"),
            "holm_family": ("B-E x detection/evidence/recovery, 12 "
                            "predeclared hypotheses"),
            "survival": ("Kaplan-Meier and RMST to the smallest frozen censor "
                         "limit per group; missing endpoints are excluded"),
            "r1": ("descriptive median baseline/first/last with explicit "
                   "missing counts"),
            "claims": "exploratory case study; no confirmatory claims",
        },
        "exclusions": exclusions,
        "overview": overview,
        "r1": _r1_entries(rows),
        "survival": survival_entries,
        "efficacy": efficacy,
        "families": [{
            "id": "r2_efficacy_managed_drift",
            "description": ("B-E x detection/evidence/recovery, two-sided, "
                            "Holm correction"),
            "predeclared_size": FAMILY_SIZE,
            "tested": len(p_values),
            "untested": FAMILY_SIZE - len(p_values),
            "alpha": alpha,
            "correction": "holm",
            "note": ("Untestable hypotheses are treated as p=1, so the "
                     "correction is conservative."),
        }],
        "r3": {"status": "not_measured", "statement": "R3: not measured",
               "claim": "none"},
        "notes": [
            "Exploratory single-case inference; no confirmatory claim.",
            "A is the HPA control, F the visibility boundary, and G a "
            "descriptive non-Argo case; only B-E enter efficacy.",
            "G is excluded from efficacy even though batch rows carry "
            "efficacy_eligible=true; the frozen method classifies G as "
            "descriptive non-Argo.",
            "Censored observations are never imputed as zero.",
            "Missing endpoints (unobserved_before_stop) are excluded from "
            "survival and numeric tests; they are not censored observations.",
            "Paired and unpaired tests are complete-case/observed-only; "
            "missingness and censoring are not adjusted.",
            "Paired tests require every scenario/rep block to have both arms "
            "fully observed and at least two pairs.",
            "The RMST horizon is the smallest frozen censor limit per group.",
        ],
    }


def _tex_escape(value):
    text = str(value).replace("\n", " ").replace("\r", " ").replace("\t", " ")
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def _num(value, digits=3):
    if value is None:
        return "--"
    return f"{value:.{digits}f}".replace(".", ",")


def _p(value):
    if value is None:
        return "--"
    if value < 0.001:
        return "$<0{,}001$"
    return f"{value:.3f}".replace(".", ",")


def _interval(value, interval):
    if value is None:
        return "--"
    if interval is None:
        return _num(value)
    return (f"{_num(value)} [{_num(interval[0])}; "
            f"{_num(interval[1])}]")


def _overview_tex(result):
    lines = [
        "% Generated by experiments/analysis/analyze_live.py; do not edit.",
        r"\begin{table}[H]",
        r"\centering",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{4pt}",
        r"\caption{Ringkasan populasi dan baris R2 batch live}",
        r"\label{tab:live-overview}",
        r"\begin{tabular}{llrrrl}",
        r"\hline",
        r"Skenario & Lengan & Baris R2 & Run teramati & Run tersensor & "
        r"Populasi analisis \\",
        r"\hline",
    ]
    totals = [0, 0, 0]
    for item in result["overview"]:
        totals[0] += item["rows"]
        totals[1] += item["observed_runs"]
        totals[2] += item["right_censored_runs"]
        lines.append(
            f"{item['scenario']} & {item['arm']} & {item['rows']} & "
            f"{item['observed_runs']} & {item['right_censored_runs']} & "
            f"{_tex_escape(item['population'])} \\\\")
    lines.extend([
        r"\hline",
        f"Total & -- & {totals[0]} & {totals[1]} & {totals[2]} & -- \\\\",
        r"\hline",
        r"\end{tabular}",
        r"\end{table}",
    ])
    batch = result["batch"]
    approved = "true" if batch["formal_execution_approved"] else "false"
    isolated = "true" if batch["stack_isolated"] else "false"
    excluded = result["exclusions"]
    if excluded["count"] is None:
        exclusion_text = ("Eksklusi tidak dihitung karena rows.jsonl tidak "
                          "diberikan.")
    else:
        reasons = ", ".join(f"{_tex_escape(key)}={value}"
                            for key, value in excluded["by_reason"].items())
        exclusion_text = (f"Eksklusi: {excluded['count']} baris dari "
                          f"{excluded['raw_rows']} baris mentah"
                          + (f" ({reasons})" if reasons else "") + ".")
    lines.extend([
        r"\par\smallskip",
        r"\noindent\footnotesize Batch: "
        + _tex_escape(batch["batch_id"])
        + f"; formal execution approved: {approved}; stack isolated: "
        + f"{isolated}; baris R1: {batch['r1_rows']}.",
        r"\par\noindent\footnotesize Klaim: eksploratif studi kasus tunggal; "
        r"tidak ada klaim konfirmatoris.",
        r"\par\noindent\footnotesize " + exclusion_text,
        r"\par\noindent\footnotesize R3: not measured. Tidak ada klaim "
        r"keterlacakan atau audit.",
        "",
    ])
    return "\n".join(lines)


def _exclusions_tex(result):
    excluded = result["exclusions"]
    lines = [
        "% Generated by experiments/analysis/analyze_live.py; do not edit.",
        r"\begin{table}[H]",
        r"\centering",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{4pt}",
        r"\caption{Baris batch yang dieksklusi dari analisis}",
        r"\label{tab:live-exclusions}",
        r"\begin{tabular}{lllrl}",
        r"\hline",
        r"Run ID & Lengan & Skenario & Rep & Alasan \\",
        r"\hline",
    ]
    if excluded["count"] is None:
        lines.append(r"\multicolumn{5}{l}{Tidak dihitung (rows.jsonl tidak diberikan).} \\")
    elif excluded["count"] == 0:
        lines.append(r"\multicolumn{5}{l}{Tidak ada baris tereksklusi.} \\")
    else:
        for item in excluded["rows"]:
            lines.append(
                f"{_tex_escape(item['run_id'])} & "
                f"{_tex_escape(item['arm'] or '--')} & "
                f"{_tex_escape(item['scenario'] or '--')} & "
                f"{item['rep'] if item['rep'] is not None else '--'} & "
                f"{_tex_escape(item['reason'])} \\\\")
    lines.extend([r"\hline", r"\end{tabular}", r"\end{table}", ""])
    return "\n".join(lines)


def _r1_cell(block):
    if block["present"] == 0:
        return "-- (0)"
    return f"{_num(block['median'])} ({block['present']})"


def _r1_tex(result):
    lines = [
        "% Generated by experiments/analysis/analyze_live.py; do not edit.",
        r"\begin{table}[H]",
        r"\centering",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{4pt}",
        r"\caption{Deskriptif R1 per skenario, lengan, dan fase (persen)}",
        r"\label{tab:live-r1}",
        r"\begin{tabular}{llrrrrr}",
        r"\hline",
        r"Skenario & Lengan & Fase & $n$ & Baseline & First & Last \\",
        r"\hline",
    ]
    for item in result["r1"]:
        lines.append(
            f"{item['scenario']} & {item['arm']} & {item['phase']} & "
            f"{item['rows']} & {_r1_cell(item['baseline'])} & "
            f"{_r1_cell(item['first'])} & {_r1_cell(item['last'])} \\\\")
    lines.extend([
        r"\hline",
        r"\end{tabular}",
        r"\end{table}",
        r"\par\smallskip",
        r"\noindent\footnotesize Nilai adalah median bagian teramati; angka "
        r"dalam kurung adalah jumlah observasi. Nilai hilang tidak "
        r"diimputasi.",
        "",
    ])
    return "\n".join(lines)


def _survival_tex(result):
    lines = [
        "% Generated by experiments/analysis/analyze_live.py; do not edit.",
        r"\begin{table}[H]",
        r"\centering",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{3pt}",
        r"\caption{Kaplan--Meier dan RMST waktu R2 per skenario dan lengan}",
        r"\label{tab:live-survival}",
        r"\begin{tabular}{lllrrrrrrrrr}",
        r"\hline",
        r"Skenario & Lengan & Metrik & $n$ & Event & Tersensor & Hilang & "
        r"Eksklusi & Horizon (s) & Median (s) & RMST (s) \\",
        r"\hline",
    ]
    for item in result["survival"]:
        median_text = _num(item["median_seconds"])
        if not item["estimable"]:
            median_text = r"--$^{\dagger}$"
        elif not item["median_reached"]:
            median_text = "--$^{*}$"
        lines.append(
            f"{item['scenario']} & {item['arm']} & "
            f"{METRIC_LABELS[item['metric']]} & {item['n']} & "
            f"{item['events']} & {item['censored']} & {item['missing']} & "
            f"{item['excluded_runs'] if item['excluded_runs'] is not None else '--'} & "
            f"{_num(item['horizon_seconds'])} & {median_text} & "
            f"{_num(item['rmst_seconds'])} \\\\")
    lines.extend([
        r"\hline",
        r"\end{tabular}",
        r"\end{table}",
        r"\par\smallskip",
        r"\noindent\footnotesize $^{*}$ Median tidak tercapai dalam horizon. "
        r"$^{\dagger}$ Tidak terestimasi karena seluruh endpoint hilang "
        r"sebelum berhenti, bukan tersensor. Data tersensor tidak diimputasi "
        r"nol; RMST memakai horizon batas penyensoran terkecil per kelompok. "
        r"Endpoint hilang tidak masuk Kaplan--Meier, RMST, atau uji numerik. "
        r"A = kontrol HPA, F = batas visibilitas, G = deskriptif non-Argo; "
        r"hanya B--E masuk efikasi.",
        "",
    ])
    return "\n".join(lines)


def _tests_tex(result):
    lines = [
        "% Generated by experiments/analysis/analyze_live.py; do not edit.",
        r"\begin{table}[H]",
        r"\centering",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{2pt}",
        r"\caption{Uji eksploratif efikasi drift terkelola B--E}",
        r"\label{tab:live-tests}",
        r"\begin{tabular}{lllrrrrl}",
        r"\hline",
        r"Skenario & Metrik & Uji & $n$ & Statistik & $p$ & "
        r"$p_{\mathrm{Holm}}$ & Keputusan \\",
        r"\hline",
    ]
    for item in result["efficacy"]:
        test = item["test"]
        if test["name"] == "wilcoxon_signed_rank":
            test_text = "Wilcoxon (P)"
            size = f"{test['n_pairs']} pasang"
        elif test["name"] == "mann_whitney_u":
            test_text = "Mann--Whitney (U)"
            size = f"{test['n_manual']} vs {test['n_gitops']}"
        else:
            test_text, size = "Tidak terestimasi", "--"
        if item["reject_holm"] is None:
            decision = "--"
        elif item["reject_holm"]:
            decision = "tolak"
        else:
            decision = "gagal"
        lines.append(
            f"{item['scenario']} & {METRIC_LABELS[item['metric']]} & "
            f"{test_text} & {size} & {_num(test['statistic'])} & "
            f"{_p(test['p_value'])} & {_p(item['holm_adjusted_p'])} & "
            f"{decision} \\\\")
    lines.extend([
        r"\hline",
        r"\end{tabular}",
        r"\end{table}",
        r"\par\smallskip",
        r"\noindent\footnotesize P = berpasangan; U = tidak berpasangan "
        r"(tersensor, hilang, tanpa pasangan, atau kurang dari dua pasangan). "
        r"Keputusan: ``tolak'' = tolak $H_0$ setelah Holm; ``gagal'' = gagal "
        r"menolak $H_0$; ``--'' = tidak terestimasi. Semua uji eksploratif; "
        r"tidak ada klaim konfirmatoris. Keluarga Holm berisi 12 hipotesis "
        r"B--E $\times$ \{deteksi, bukti, pemulihan\} yang ditetapkan sebelum "
        r"data; hipotesis tak teruji diperlakukan sebagai $p=1$. Statistik "
        r"Wilcoxon adalah $W^+$; statistik Mann--Whitney adalah $U$ terkecil. "
        r"Selisih nol diabaikan pada Wilcoxon. Mann--Whitney memakai "
        r"aproksimasi normal dengan koreksi ties, hanya pada nilai teramati, "
        r"dan tidak menyesuaikan penyensoran.",
        "",
    ])
    return "\n".join(lines)


def _effects_tex(result):
    lines = [
        "% Generated by experiments/analysis/analyze_live.py; do not edit.",
        r"\begin{table}[H]",
        r"\centering",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{4pt}",
        r"\caption{Ukuran efek perbandingan manual terhadap gitops (B--E)}",
        r"\label{tab:live-effects}",
        r"\begin{tabular}{lllll}",
        r"\hline",
        r"Skenario & Metrik & Cliff $\delta$ [95\% CI] & "
        r"$\Delta$ median [95\% CI] & RB \\",
        r"\hline",
    ]
    for item in result["efficacy"]:
        effect = item["effect"]
        rank = (f"{_num(effect['rank_biserial'])}"
                if effect["rank_biserial"] is not None else "--")
        lines.append(
            f"{item['scenario']} & {METRIC_LABELS[item['metric']]} & "
            f"{_interval(effect['cliffs_delta'], effect['cliffs_delta_ci'])} & "
            f"{_interval(effect['median_paired_difference'], effect['median_paired_difference_ci'])} & "
            f"{rank} \\\\")
    lines.extend([
        r"\hline",
        r"\end{tabular}",
        r"\end{table}",
        r"\par\smallskip",
        r"\noindent\footnotesize Selisih berpasangan $\Delta$ = manual $-$ "
        r"gitops; nilai positif berarti manual lebih lama. RB = "
        r"rank-biserial. Interval adalah percentile bootstrap deterministik; "
        r"resampling mengikuti blok berpasangan bila pemasangan "
        r"dipertahankan, selain itu per lengan.",
        "",
    ])
    return "\n".join(lines)


def write_outputs(result, outdir, *, force=False):
    """Write JSON and LaTeX artifacts; refuse to overwrite without `force`."""
    directory = Path(outdir)
    directory.mkdir(parents=True, exist_ok=True)
    documents = {
        "json": ("live_analysis.json",
                 json.dumps(result, allow_nan=False, indent=2, sort_keys=True)
                 + "\n"),
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
                "output already exists; use --force to replace: "
                + ", ".join(sorted(existing)))
    for key, (_, text) in documents.items():
        target = paths[key]
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(text)
        temporary.replace(target)
    return {key: str(path) for key, path in paths.items()}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="source", type=Path, required=True,
                        help="<batch_id>.analysis.jsonl")
    parser.add_argument("--rows", type=Path,
                        help="optional <batch_id>.rows.jsonl for exclusions")
    parser.add_argument("--out", type=Path, required=True,
                        help="output directory for JSON and LaTeX tables")
    parser.add_argument("--bootstrap", type=int, default=DEFAULT_BOOTSTRAP,
                        help=f"bootstrap resamples (default {DEFAULT_BOOTSTRAP})")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"deterministic bootstrap seed (default {DEFAULT_SEED})")
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA,
                        help="nominal alpha (default 0.05)")
    parser.add_argument("--force", action="store_true",
                        help="replace existing output files")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        rows = _load_jsonl(args.source)
        raw_rows = _load_jsonl(args.rows) if args.rows else None
        result = analyze(rows, raw_rows, bootstrap=args.bootstrap,
                         seed=args.seed, alpha=args.alpha)
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
        f"({result['families'][0]['tested']} testable) -> {args.out}")
    print(f"JSON: {paths['json']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
