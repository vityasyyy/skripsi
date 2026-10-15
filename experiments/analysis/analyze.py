#!/usr/bin/env python3
"""Analyze validated schema-v2 run summaries or explicitly synthetic legacy CSV."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import statistics
from typing import NoReturn

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

METRICS = ["t0", "td", "trci", "t2", "r1_t0", "r1_t1", "r1_t2", "kubectl_cmds"]
R2_METRICS = ["t0", "td", "trci", "t2"]
R1_METRICS = ["r1_t0", "r1_t1", "r1_t2"]
# kubectl_cmds is an operational-cost metric collected during the timed R2 runs,
# so it belongs to the R2 family (reps 1..10) for both descriptives and MW tests.
R2_FAMILY = ["t0", "td", "trci", "t2", "kubectl_cmds"]
ALPHA = 0.05

V2_STATUSES = (
    "complete",
    "timeout",
    "baseline_failed",
    "injection_failed",
    "instrumentation_failed",
    "correction_failed",
)
EVENT_STATES = ("observed", "right_censored", "not_evaluable")
EVENT_FIELDS = {
    "detection": ("detection_status", "td_mono_s"),
    "evidence": ("evidence_status", "te_mono_s"),
    "recovery": ("recovery_status", "tr_mono_s"),
}
V2_FIELDS = {
    "schema_version", "run_id", "phase", "subject", "env", "scenario", "rep",
    "status", "reason", "started_at_utc", "t0_mono_s", "ta_mono_s", "td_mono_s",
    "te_mono_s", "tr_mono_s", "timeout_s", "poll_interval_s", "detection_status",
    "evidence_status", "recovery_status", "r1_baseline_pct", "r1_post_pct",
    "r1_recovered_pct", "healthy_baseline", "healthy_final", "evidence",
}
R1_FIELDS = ("r1_baseline_pct", "r1_post_pct", "r1_recovered_pct")
TIMESTAMP_FIELDS = ("t0_mono_s", "ta_mono_s", "td_mono_s", "te_mono_s", "tr_mono_s")


def holm_adjust(p_values: list[float]) -> list[float]:
    """Return Holm step-down adjusted p-values in their original order."""
    if any(not math.isfinite(p) or p < 0 or p > 1 for p in p_values):
        raise ValueError("p-values must be finite values in [0, 1]")
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [0.0] * len(p_values)
    running = 0.0
    count = len(p_values)
    for rank, index in enumerate(order):
        running = max(running, (count - rank) * p_values[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def _fail(message: str) -> NoReturn:
    raise ValueError(message)


def _nonempty_string(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    _fail(f"non-finite JSON number: {value}")


def _read_json(path: Path):
    try:
        with path.open(encoding="utf-8") as source:
            return json.load(source, object_pairs_hook=_duplicate_keys, parse_constant=_reject_constant)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"cannot read {path}: {error}") from error


def _validate_run(run, phase: str, source: str) -> dict:
    if not isinstance(run, dict):
        _fail(f"{source}: each run must be a JSON object")
    missing = V2_FIELDS - set(run)
    extra = set(run) - V2_FIELDS
    if missing or extra:
        _fail(f"{source}: schema fields mismatch (missing={sorted(missing)}, extra={sorted(extra)})")
    if type(run["schema_version"]) is not int or run["schema_version"] != 2:
        _fail(f"{source}: schema_version must be integer 2")
    if run["phase"] not in ("fixture", "pilot", "formal"):
        _fail(f"{source}: invalid phase")
    if run["phase"] != phase:
        _fail(f"{source}: mixed phase or phase does not match --phase {phase}")
    if not _nonempty_string(run["subject"]):
        _fail(f"{source}: subject must be a nonempty string")
    if phase == "formal" and run["subject"].strip().casefold() in {"s1", "s2"}:
        _fail(f"{source}: reserved pilot/fixture subject cannot be formal")
    if run["env"] not in ("manual", "gitops"):
        _fail(f"{source}: invalid env")
    if run["scenario"] not in tuple("ABCDEFG"):
        _fail(f"{source}: scenario must be A through G")
    if type(run["rep"]) is not int or run["rep"] <= 0:
        _fail(f"{source}: rep must be a positive integer")
    if run["status"] not in V2_STATUSES:
        _fail(f"{source}: invalid run status")
    if run["reason"] is not None and not isinstance(run["reason"], str):
        _fail(f"{source}: reason must be a string or null")
    if not _nonempty_string(run["run_id"]):
        _fail(f"{source}: run_id must be a nonempty string")
    try:
        started = datetime.fromisoformat(run["started_at_utc"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        _fail(f"{source}: started_at_utc must be an RFC 3339 UTC string")
    if started.tzinfo is None or started.utcoffset().total_seconds() != 0:
        _fail(f"{source}: started_at_utc must use UTC")
    for name in TIMESTAMP_FIELDS:
        value = run[name]
        if value is not None and not _finite_number(value):
            _fail(f"{source}: {name} timestamp must be finite numeric seconds or null")
    for name in ("timeout_s", "poll_interval_s"):
        if not _finite_number(run[name]) or run[name] <= 0:
            _fail(f"{source}: {name} must be a positive finite number")
    for status_name, timestamp_name in EVENT_FIELDS.values():
        state = run[status_name]
        timestamp = run[timestamp_name]
        if state not in EVENT_STATES:
            _fail(f"{source}: invalid {status_name}")
        if (state == "observed") != (timestamp is not None):
            _fail(f"{source}: {status_name} and {timestamp_name} timestamp disagree")
    for name in R1_FIELDS:
        value = run[name]
        if value is not None and (not _finite_number(value) or not 0 <= value <= 100):
            _fail(f"{source}: {name} must be null or a finite percent in [0, 100]")
    for name in ("healthy_baseline", "healthy_final"):
        if run[name] is not None and type(run[name]) is not bool:
            _fail(f"{source}: {name} must be boolean or null")
    if not isinstance(run["evidence"], list):
        _fail(f"{source}: evidence must be an array")
    for item in run["evidence"]:
        evidence_fields = {"resource", "field_paths", "source", "observed_at_mono_s"}
        if not isinstance(item, dict) or set(item) != evidence_fields:
            _fail(f"{source}: evidence items must contain only sanitized provenance fields")
        if not _nonempty_string(item["resource"]) or not _nonempty_string(item["source"]):
            _fail(f"{source}: evidence resource and source must be nonempty strings")
        if not isinstance(item["field_paths"], list) or not item["field_paths"] or any(
            not _nonempty_string(path) for path in item["field_paths"]
        ):
            _fail(f"{source}: evidence field_paths must be a nonempty string array")
        if not _finite_number(item["observed_at_mono_s"]):
            _fail(f"{source}: evidence observation timestamp must be finite numeric seconds")

    t0 = run["t0_mono_s"]
    if t0 is None:
        if any(run[name] is not None for name in TIMESTAMP_FIELDS[1:]):
            _fail(f"{source}: event timestamp exists without dispatch t0")
    else:
        cutoff = t0 + run["timeout_s"]
        if not _finite_number(cutoff):
            _fail(f"{source}: observation cutoff is not finite")
        for name in TIMESTAMP_FIELDS[1:]:
            value = run[name]
            if value is not None and value < t0:
                _fail(f"{source}: {name} timestamp precedes dispatch t0")
            if value is not None and not _finite_number(value - t0):
                _fail(f"{source}: {name} elapsed time from dispatch is not finite")
        for name in ("td_mono_s", "te_mono_s", "tr_mono_s"):
            value = run[name]
            if value is not None and value > cutoff:
                _fail(f"{source}: {name} timestamp exceeds the observation cutoff")
    for item in run["evidence"]:
        if t0 is None or item["observed_at_mono_s"] < t0 or item["observed_at_mono_s"] > t0 + run["timeout_s"]:
            _fail(f"{source}: evidence observation timestamp is outside the observation window")
    if run["evidence_status"] == "observed":
        if not run["evidence"] or not any(
            item["observed_at_mono_s"] == run["te_mono_s"] for item in run["evidence"]
        ):
            _fail(f"{source}: observed evidence requires a matching stored evidence observation")
    elif run["evidence"]:
        _fail(f"{source}: evidence records require evidence_status=observed")

    states = [run[name] for name, _ in EVENT_FIELDS.values()]
    timestamps = [run[name] for name in TIMESTAMP_FIELDS]
    status = run["status"]
    scenario_f = run["scenario"] == "F"
    if run["recovery_status"] == "observed" and run["r1_recovered_pct"] != 100:
        _fail(f"{source}: observed recovery requires r1_recovered_pct=100")
    if scenario_f and (run["recovery_status"] != "not_evaluable" or run["tr_mono_s"] is not None):
        _fail(f"{source}: scenario F recovery must remain not_evaluable")
    if status == "baseline_failed":
        valid = t0 is None and all(value is None for value in timestamps) and all(
            state == "not_evaluable" for state in states
        )
    elif status == "injection_failed":
        valid = t0 is not None and all(run[name] is None for _, name in EVENT_FIELDS.values()) and all(
            state == "not_evaluable" for state in states
        )
    elif status == "instrumentation_failed":
        valid = "not_evaluable" in states
    elif status == "correction_failed":
        valid = not scenario_f and run["detection_status"] == "observed" and run[
            "recovery_status"
        ] == "not_evaluable"
    elif status == "timeout":
        non_evaluable = [
            state for event, state in zip(EVENT_FIELDS, states)
            if not (scenario_f and event == "recovery")
        ]
        valid = t0 is not None and run["ta_mono_s"] is not None
        valid = valid and "right_censored" in states and "not_evaluable" not in non_evaluable
    else:
        valid = (
            t0 is not None
            and run["ta_mono_s"] is not None
            and (scenario_f or all(state == "observed" for state in states))
        )
    if not valid:
        _fail(f"{source}: timestamps and event statuses are inconsistent with status={status}")
    return run


def load_v2_runs(input_path: Path, phase: str) -> list[dict]:
    if input_path.is_dir():
        paths = sorted(
            path for path in input_path.iterdir()
            if path.suffix == ".json" and path.is_file() and not path.is_symlink()
        )
        if not paths:
            _fail(f"{input_path}: directory contains no direct JSON run summaries")
    elif input_path.is_file() and input_path.suffix == ".json":
        paths = [input_path]
    else:
        _fail(f"{input_path}: input must be one JSON run or a directory of direct JSON summaries")
    runs = [_validate_run(_read_json(path), phase, str(path)) for path in paths]
    run_ids = set()
    replicates = set()
    for run in runs:
        if run["run_id"] in run_ids:
            _fail(f"duplicate run_id: {run['run_id']}")
        run_ids.add(run["run_id"])
        key = (run["subject"], run["env"], run["scenario"], run["rep"])
        if key in replicates:
            _fail(f"duplicate replicate: {key}")
        replicates.add(key)
    return runs


def _numeric_summary(values: list[float]) -> dict:
    return {
        "n": len(values),
        "mean": statistics.mean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def _summarize_group(runs: list[dict]) -> dict:
    result = {
        "subject": runs[0]["subject"],
        "scenario": runs[0]["scenario"],
        "env": runs[0]["env"],
        "run_count": len(runs),
        "run_status_counts": {status: sum(run["status"] == status for run in runs) for status in V2_STATUSES},
        "events": {},
        "r1_percent": {},
        "health": {},
    }
    for event, (state_name, time_name) in EVENT_FIELDS.items():
        observed = [
            run[time_name] - run["t0_mono_s"]
            for run in runs
            if run[state_name] == "observed"
        ]
        result["events"][event] = {
            "status_counts": {state: sum(run[state_name] == state for run in runs) for state in EVENT_STATES},
            "observed_duration_s": _numeric_summary(observed),
            "duration_selection": "observed only; censored and not-evaluable runs remain in status counts",
        }
    for field in R1_FIELDS:
        values = [run[field] for run in runs if run[field] is not None]
        result["r1_percent"][field] = {
            **_numeric_summary(values),
            "not_evaluable": len(runs) - len(values),
            "basis": "expected inventory only",
        }
    for field in ("healthy_baseline", "healthy_final"):
        result["health"][field] = {
            "true": sum(run[field] is True for run in runs),
            "false": sum(run[field] is False for run in runs),
            "not_evaluable": sum(run[field] is None for run in runs),
        }
    return result


def _build_v2_report(runs: list[dict], phase: str) -> dict:
    groups = defaultdict(list)
    for run in runs:
        groups[(run["subject"], run["scenario"], run["env"])].append(run)
    summaries = [_summarize_group(groups[key]) for key in sorted(groups)]
    formal_label = "FORMAL-LABELED INPUT — COLLECTION AUTHORIZATION NOT VERIFIED"
    return {
        "schema_version": 2,
        "phase": phase,
        "label": {
            "fixture": "SYNTHETIC FIXTURE — NOT EMPIRICAL",
            "pilot": "PILOT ONLY — NOT FORMAL EVIDENCE",
            "formal": formal_label,
        }[phase],
        "run_count": len(runs),
        "groups": [group for group in summaries if group["scenario"] != "F"],
        "visibility_boundary": [group for group in summaries if group["scenario"] == "F"],
        "exploratory_comparisons": {
            "performed": False,
            "reason": "descriptive default; requires an explicit approved policy and formal phase",
        },
    }


def _load_comparison_policy(path: Path, runs: list[dict]) -> dict:
    policy = _read_json(path)
    fields = {
        "policy_id", "approved", "approval_reference", "prespecified",
        "independence_confirmed", "independence_basis", "collection_run_ids", "holm_family",
    }
    if not isinstance(policy, dict) or set(policy) != fields:
        _fail("comparison policy must contain exactly the approved policy fields")
    if not _nonempty_string(policy["policy_id"]) or policy["approved"] is not True:
        _fail("comparison policy is not approved")
    if not _nonempty_string(policy["approval_reference"]):
        _fail("comparison policy needs an approval reference")
    if policy["prespecified"] is not True:
        _fail("Holm family must be prespecified")
    if policy["independence_confirmed"] is not True or not _nonempty_string(policy["independence_basis"]):
        _fail("comparison policy must document independent observations")
    collection = policy["collection_run_ids"]
    if not isinstance(collection, list) or any(not _nonempty_string(value) for value in collection):
        _fail("comparison policy must explicitly list the collection run IDs")
    actual = {run["run_id"] for run in runs}
    if len(collection) != len(set(collection)) or set(collection) != actual:
        _fail("comparison policy collection_run_ids must exactly match the input collection")
    family = policy["holm_family"]
    if not isinstance(family, list) or not family:
        _fail("comparison policy must provide a nonempty prespecified Holm family")
    seen = set()
    for item in family:
        if not isinstance(item, dict) or set(item) != {"subject", "scenario", "metric"}:
            _fail("each Holm family entry must name subject, scenario, and metric")
        key = (item["subject"], item["scenario"], item["metric"])
        if (
            not _nonempty_string(key[0]) or not isinstance(key[1], str)
            or key[1] not in tuple("ABCDEG") or not isinstance(key[2], str)
            or key[2] not in EVENT_FIELDS or key in seen
        ):
            _fail("Holm family entries must be unique R2 tests for non-F scenarios")
        seen.add(key)
    return policy


def _run_exploratory_comparisons(runs: list[dict], policy: dict) -> list[dict]:
    results = []
    for item in policy["holm_family"]:
        subject, scenario, metric = item["subject"], item["scenario"], item["metric"]
        arms = {}
        for env in ("manual", "gitops"):
            cell = [run for run in runs if (
                run["subject"] == subject and run["scenario"] == scenario and run["env"] == env
            )]
            if not cell or any(run["status"] != "complete" or run[f"{metric}_status"] != "observed" for run in cell):
                _fail(f"cannot compare {subject}/{scenario}/{metric}: both arms need complete observed runs")
            time_field = EVENT_FIELDS[metric][1]
            arms[env] = [run[time_field] - run["t0_mono_s"] for run in cell]
        mw = stats.mannwhitneyu(arms["manual"], arms["gitops"], alternative="two-sided")
        results.append({
            "subject": subject,
            "scenario": scenario,
            "metric": metric,
            "n_manual": len(arms["manual"]),
            "n_gitops": len(arms["gitops"]),
            "u_two_sided": float(mw.statistic),
            "p_two_sided": float(mw.pvalue),
            "cliffs_delta_manual_minus_gitops": cliff_delta(arms["manual"], arms["gitops"]),
        })
    adjusted = holm_adjust([result["p_two_sided"] for result in results])
    for result, p_holm in zip(results, adjusted):
        result["p_holm"] = p_holm
    return results


def write_v2_report(runs: list[dict], phase: str, output_dir: Path, policy_path: Path | None = None) -> None:
    report_path = output_dir / "analysis-v2.json"
    if report_path.exists():
        _fail(f"output already exists; refusing to overwrite {report_path}")
    report = _build_v2_report(runs, phase)
    if policy_path is not None:
        if phase != "formal":
            _fail("exploratory comparisons require formal phase")
        policy = _load_comparison_policy(policy_path, runs)
        report["exploratory_comparisons"] = {
            "performed": True,
            "policy_id": policy["policy_id"],
            "direction": "manual minus gitops",
            "tests": _run_exploratory_comparisons(runs, policy),
        }
    payload = json.dumps(report, indent=2, allow_nan=False) + "\n"
    output_dir.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as target:
        target.write(payload)


def cell_values(df, skenario: str, env: str, metric: str) -> np.ndarray:
    """Values for one (skenario, env, metric) cell with protocol rep filtering."""
    sel = (df["skenario"] == skenario) & (df["env"] == env)
    if metric in R1_METRICS:
        sel &= df["rep"] >= 11
    else:
        sel &= df["rep"] <= 10
    return df[sel][metric].dropna().to_numpy(float)


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """Cohen's d for a (manual) vs b (gitops), pooled std. Positive => a larger."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return float("nan")
    s1, s2 = float(np.std(a, ddof=1)), float(np.std(b, ddof=1))
    denom = (n1 - 1) * s1**2 + (n2 - 1) * s2**2
    pooled = np.sqrt(denom / (n1 + n2 - 2)) if denom > 0 else 0.0
    if pooled == 0:
        return 0.0 if np.mean(a) == np.mean(b) else float("nan")
    return float((np.mean(a) - np.mean(b)) / pooled)


def cliff_delta(a: np.ndarray, b: np.ndarray) -> float:
    """Cliff's delta P(a>b) - P(a<b) via pairwise comparisons."""
    a = np.asarray(a, dtype=float).ravel()
    b = np.asarray(b, dtype=float).ravel()
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    greater = sum(1 for x in a for y in b if x > y)
    lesser = sum(1 for x in a for y in b if x < y)
    return (greater - lesser) / (len(a) * len(b))


def interpret_d(d: float) -> str:
    ad = abs(d)
    if np.isnan(ad):
        return "n/a"
    if ad < 0.2:
        return "negligible"
    if ad < 0.5:
        return "small"
    if ad < 0.8:
        return "medium"
    return "large"


def interpret_cliff(c: float) -> str:
    ac = abs(c)
    if np.isnan(ac):
        return "n/a"
    if ac < 0.147:
        return "negligible"
    if ac < 0.33:
        return "small"
    if ac < 0.474:
        return "medium"
    return "large"


def tex_escape(s: str) -> str:
    return s.replace("_", r"\_")


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze drift experiment runs.")
    ap.add_argument("--in", dest="inp", required=True, help="Input file or directory")
    ap.add_argument("--out", dest="out", required=True, help="Output directory")
    ap.add_argument("--schema-version", type=int, choices=(2,), help="Explicitly select the JSON run schema")
    ap.add_argument("--phase", choices=("fixture", "pilot", "formal"), help="Required phase for schema v2")
    ap.add_argument(
        "--legacy-synthetic-csv",
        action="store_true",
        help="Run the legacy CSV analyzer, labeling every output as synthetic and nonempirical",
    )
    ap.add_argument(
        "--exploratory-comparisons",
        action="store_true",
        help="Opt in to gated two-sided R2 comparisons (formal phase and --policy required)",
    )
    ap.add_argument("--policy", help="Approved, prespecified comparison policy JSON")
    args = ap.parse_args()

    if args.schema_version == 2:
        if args.legacy_synthetic_csv:
            ap.error("choose schema v2 or --legacy-synthetic-csv, not both")
        if args.phase is None:
            ap.error("schema v2 requires an explicit --phase")
        if args.policy and not args.exploratory_comparisons:
            ap.error("--policy requires --exploratory-comparisons")
        if args.exploratory_comparisons:
            if args.phase != "formal":
                ap.error("exploratory comparisons require formal phase")
            if not args.policy:
                ap.error("exploratory comparisons require an approved --policy")
        try:
            runs = load_v2_runs(Path(args.inp), args.phase)
            write_v2_report(runs, args.phase, Path(args.out), Path(args.policy) if args.policy else None)
        except (OSError, ValueError) as error:
            ap.error(str(error))
        print(f"Wrote schema-v2 analysis report for {args.phase}: {Path(args.out) / 'analysis-v2.json'}")
        return

    if not args.legacy_synthetic_csv:
        ap.error("select --schema-version 2 or explicitly opt in to --legacy-synthetic-csv")
    if args.phase or args.policy or args.exploratory_comparisons:
        ap.error("--phase and comparison options apply only to schema v2")

    inp = Path(args.inp)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(inp)
    required = {"subject", "env", "skenario", "rep", *METRICS}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"Input CSV missing columns: {sorted(missing)}")

    scenarios = sorted(df["skenario"].unique().tolist())
    envs = ["manual", "gitops"]

    # --- Descriptives (with rep filtering per metric family) ---
    desc_rows = []
    for sk in scenarios:
        for env in envs:
            for m in METRICS:
                vals = pd.Series(cell_values(df, sk, env, m))
                n = int(len(vals))
                if n == 0:
                    mean = med = sstd = vmin = vmax = rng = float("nan")
                else:
                    mean = float(vals.mean())
                    med = float(vals.median())
                    sstd = float(vals.std(ddof=1)) if n > 1 else 0.0
                    vmin = float(vals.min())
                    vmax = float(vals.max())
                    rng = vmax - vmin
                desc_rows.append(
                    {
                        "skenario": sk,
                        "env": env,
                        "metric": m,
                        "n": n,
                        "mean": mean,
                        "median": med,
                        "std": sstd,
                        "min": vmin,
                        "max": vmax,
                        "range": rng,
                    }
                )
    desc = pd.DataFrame(desc_rows)

    with (outdir / "descriptives.tex").open("w") as f:
        f.write("% SYNTHETIC LEGACY CSV — NOT EMPIRICAL; auto-generated by analyze.py\n")
        f.write("% Descriptive stats per metric per env per scenario\n")
        f.write(r"\begin{tabular}{lllrrrrrr}" + "\n")
        f.write(r"\hline" + "\n")
        f.write("Skenario & Env & Metric & n & Mean & Median & Std & Range \\\\\n")
        f.write(r"\hline" + "\n")
        for r in desc_rows:
            f.write(
                f"{r['skenario']} & {r['env']} & {tex_escape(r['metric'])} & {r['n']} & "
                f"{r['mean']:.4g} & {r['median']:.4g} & {r['std']:.4g} & {r['range']:.4g} \\\\\n"
            )
        f.write(r"\hline" + "\n")
        f.write(r"\end{tabular}" + "\n")

    # --- Mann-Whitney U + effects ---
    mw_rows = []
    eff_rows = []
    for sk in scenarios:
        for m in METRICS:
            a = cell_values(df, sk, "manual", m)
            b = cell_values(df, sk, "gitops", m)
            if len(a) == 0 or len(b) == 0:
                u = p = float("nan")
            else:
                try:
                    res = stats.mannwhitneyu(a, b, alternative="two-sided")
                    u, p = float(res.statistic), float(res.pvalue)
                except ValueError:  # e.g. identical values
                    u, p = float("nan"), 1.0
            signif = "yes" if (not np.isnan(p) and p < ALPHA) else "no"
            mw_rows.append({"skenario": sk, "metric": m, "U": u, "p": p, "signif": signif})
            d = cohens_d(a, b)
            c = cliff_delta(a, b)
            eff_rows.append(
                {
                    "skenario": sk,
                    "metric": m,
                    "d": d,
                    "d_interp": interpret_d(d),
                    "cliff": c,
                    "cliff_interp": interpret_cliff(c),
                }
            )

    with (outdir / "mannwhitney.tex").open("w") as f:
        f.write("% SYNTHETIC LEGACY CSV — NOT EMPIRICAL; auto-generated by analyze.py\n")
        f.write("% Mann-Whitney U manual vs gitops, two-sided, alpha=0.05\n")
        f.write(r"\begin{tabular}{llrrl}" + "\n")
        f.write(r"\hline" + "\n")
        f.write("Skenario & Metric & U & p & Signif ($p<0.05$) \\\\\n")
        f.write(r"\hline" + "\n")
        for r in mw_rows:
            f.write(
                f"{r['skenario']} & {tex_escape(r['metric'])} & {r['U']:.4g} & {r['p']:.4g} & {r['signif']} \\\\\n"
            )
        f.write(r"\hline" + "\n")
        f.write(r"\end{tabular}" + "\n")

    with (outdir / "effects.tex").open("w") as f:
        f.write("% SYNTHETIC LEGACY CSV — NOT EMPIRICAL; auto-generated by analyze.py\n")
        f.write("% Cohen d (manual-minus-gitops) + Cliff delta\n")
        f.write("% Cohen bands: |d|<0.2 negligible, <0.5 small, <0.8 medium, else large.\n")
        f.write("% Cliff bands: |delta|<0.147 negligible, <0.33 small, <0.474 medium, else large.\n")
        f.write(r"\begin{tabular}{llrr}" + "\n")
        f.write(r"\hline" + "\n")
        f.write("Skenario & Metric & Cohen $d$ (interp.) & Cliff $\\delta$ (interp.) \\\\\n")
        f.write(r"\hline" + "\n")
        for r in eff_rows:
            f.write(
                f"{r['skenario']} & {tex_escape(r['metric'])} & "
                f"{r['d']:.4g} ({r['d_interp']}) & {r['cliff']:.4g} ({r['cliff_interp']}) \\\\\n"
            )
        f.write(r"\hline" + "\n")
        f.write(r"\end{tabular}" + "\n")

    # --- Boxplots: one PNG per R2 sub-metric per scenario (reps 1..10 only) ---
    for sk in scenarios:
        for m in R2_METRICS:
            a = cell_values(df, sk, "manual", m)
            b = cell_values(df, sk, "gitops", m)
            fig, ax = plt.subplots(figsize=(4, 3))
            ax.boxplot([a, b], tick_labels=["manual", "gitops"])
            ax.set_title(f"SYNTHETIC MOCK DATA — NOT EMPIRICAL\nSkenario {sk} — {m} (manual vs gitops)")
            ax.set_ylabel(f"{m} (s)" if m in ("t0", "td", "trci", "t2") else m)
            ax.text(
                0.5, 0.5, "SYNTHETIC MOCK DATA — NOT EMPIRICAL",
                transform=ax.transAxes, ha="center", va="center", rotation=30,
                color="darkred", alpha=0.35, fontsize=8,
            )
            fig.tight_layout()
            fig.savefig(
                outdir / f"boxplot_{m}_{sk}.png",
                dpi=150,
                metadata={"Title": "SYNTHETIC MOCK DATA — NOT EMPIRICAL"},
            )
            plt.close(fig)

    n_png = len(scenarios) * len(R2_METRICS)
    r2_ns = sorted({r["n"] for r in desc_rows if r["metric"] in R2_FAMILY})
    r1_ns = sorted({r["n"] for r in desc_rows if r["metric"] in R1_METRICS})
    print(
        f"SYNTHETIC LEGACY CSV — NOT EMPIRICAL. Wrote {len(desc_rows)} descriptive cells "
        f"(R2-family cell n={r2_ns}, R1-family cell n={r1_ns}), "
        f"{len(mw_rows)} MW tests (R2 20-vs-20 expected, R1 10-vs-10 expected), "
        f"{n_png} boxplots (reps<=10) -> {outdir}"
    )


if __name__ == "__main__":
    main()
