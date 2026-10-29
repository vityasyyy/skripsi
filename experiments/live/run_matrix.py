#!/usr/bin/env python3
"""Formal sequential batch runner for the single-stack InvenioRDM study.

Dry-run by default. Every run is delegated to the existing harness
(`harness.main`, the same path as `run_one.py`), so token, single-stack, arm,
reset, and per-run overwrite gates stay in one place. This module only plans the
order, records the batch manifest, and writes analysis-ready rows.

A batch is 2 arms x 7 scenarios x 15 repetitions = 210 runs. Repetitions 1..10
are the R2 timing block; 11..15 are the R1 consistency block. Arms run
sequentially on the same stack; the arm order is randomized and both arms use
the same scenario permutation. A cooldown separates terminal runs so the shared
stack can settle, and only a pre-injection baseline failure may be retried; each
attempt keeps its own run id. See `README.md`.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
import math
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import convert, harness
except ImportError:
    import convert  # type: ignore[no-redef]
    import harness  # type: ignore[no-redef]

ARMS = ("gitops", "imperative")
SCENARIOS = tuple("ABCDEFG")
DEFAULT_REPS = 15
DEFAULT_SEED = 20261027
DEFAULT_COOLDOWN_SECONDS = 60.0
DEFAULT_BASELINE_RETRIES = 1
BATCH_SCHEMA_VERSION = 2
R2_REPS = range(1, 11)
R1_REPS = range(11, 16)
ANALYSIS_STATUSES = frozenset({"observed", "right_censored"})
PENDING_STATUSES = frozenset({"pending", "running", "retrying"})
STOP_STATUSES = frozenset({
    "invalid_injection",
    "instrumentation_failure",
    "reset_failure",
    "recovery_failure",
    "arm_restore_failure",
    "safety_refusal",
    "baseline_failure",
    "arm_state_mismatch",
    "failure",
})
TERMINAL_STATUSES = (ANALYSIS_STATUSES | STOP_STATUSES
                     | {"dry_run", "refused"})
ROW_REQUIRED_STATUSES = (ANALYSIS_STATUSES | STOP_STATUSES
                         | {"dry_run"}) - {"refused", "failure"}
MANIFEST_KEYS = (
    "schema_version", "batch_id", "state", "mode", "production_like",
    "formal_execution_approved", "stack_isolated", "r3_status", "created_utc",
    "updated_utc", "seed", "arms", "scenarios", "reps", "arm_order",
    "scenario_order", "namespace", "app", "source_revision", "render_sha256",
    "cooldown_seconds", "baseline_retries", "runs", "cooldowns", "counts",
    "stop_reason", "stop_run_id",
)


class BatchError(Exception):
    pass


class BatchSafetyError(BatchError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value) -> str:
    text = str(value)
    token = os.environ.get("INVENIO_TOKEN")
    return text.replace(token, "<redacted>") if token else text


def _as_list(values, label):
    if isinstance(values, str):
        values = [values]
    tokens = []
    for value in values:
        tokens.extend(str(value).replace(",", " ").split())
    if not tokens:
        raise ValueError(f"--{label} must name at least one value")
    return tokens


def parse_arms(values):
    selected = set()
    for token in _as_list(values, "arms"):
        name = token.lower()
        if name not in ARMS:
            raise ValueError(f"unknown arm {token!r}; choose from {ARMS}")
        selected.add(name)
    return [arm for arm in ARMS if arm in selected]


def parse_scenarios(values):
    selected = set()
    for token in _as_list(values, "scenarios"):
        token = token.upper()
        if re.fullmatch(r"[A-Z]-[A-Z]", token):
            start, end = token.split("-")
            if start not in SCENARIOS or end not in SCENARIOS or start > end:
                raise ValueError(f"unknown scenario range {token!r}")
            selected.update(chr(code) for code in range(ord(start), ord(end) + 1))
            continue
        for char in token:
            if char not in SCENARIOS:
                raise ValueError(f"unknown scenario {char!r}; choose from A-G")
            selected.add(char)
    return [scenario for scenario in SCENARIOS if scenario in selected]


def phase_for(rep: int) -> str:
    if rep in R2_REPS:
        return "R2"
    if rep in R1_REPS:
        return "R1"
    raise ValueError(f"rep {rep} is outside the frozen 1..15 protocol")


def build_plan(arms, scenarios, reps, seed):
    """Return the frozen order: shuffled arms, one scenario permutation for both."""
    if not 1 <= reps <= DEFAULT_REPS:
        raise ValueError("reps must be between 1 and 15")
    rng = random.Random(seed)
    arm_order = list(arms)
    rng.shuffle(arm_order)
    scenario_order = list(scenarios)
    rng.shuffle(scenario_order)
    runs = []
    index = 0
    for arm in arm_order:
        for scenario in scenario_order:
            for rep in range(1, reps + 1):
                runs.append({
                    "index": index,
                    "arm": arm,
                    "scenario": scenario,
                    "rep": rep,
                    "phase": phase_for(rep),
                })
                index += 1
    return {"arm_order": arm_order, "scenario_order": scenario_order,
            "runs": runs}


def default_batch_id(args) -> str:
    identity = {
        "arms": list(args.arms),
        "scenarios": list(args.scenarios),
        "reps": args.reps,
        "seed": args.seed,
        "namespace": args.namespace,
        "app": args.app,
        "source_revision": args.source_revision,
        "render_sha256": args.render_sha256,
        "live": bool(args.live),
        "production_like": bool(args.production_like),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode()).hexdigest()[:10]
    return "fb-" + digest


def run_id_for(batch_id, item) -> str:
    return (f"{batch_id}-{item['arm']}-{item['scenario']}"
            f"-r{item['rep']:02d}")


def run_id_for_retry(run_id: str, retry: int) -> str:
    return f"{run_id}-retry{retry}"


def run_slots(run_id: str, retries: int):
    """Yield the base run id and its deterministic retry slots."""
    yield run_id
    for retry in range(1, retries + 1):
        yield run_id_for_retry(run_id, retry)


def final_run_id(entry) -> str:
    attempts = entry.get("attempts") or []
    return attempts[-1]["run_id"] if attempts else entry["run_id"]


def _batch_paths(out, batch_id):
    base = Path(out) / batch_id
    return {
        "manifest": Path(str(base) + ".manifest.json"),
        "rows": Path(str(base) + ".rows.jsonl"),
        "analysis": Path(str(base) + ".analysis.jsonl"),
        "csv": Path(str(base) + ".csv"),
        "summary": Path(str(base) + ".summary.json"),
    }


def _row_path(out, run_id):
    return Path(out) / (run_id + ".jsonl")


def _evidence_path(out, run_id):
    return Path(out) / run_id


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text)
    os.replace(temporary, path)


def _write_json_atomic(path: Path, payload) -> None:
    _write_text_atomic(
        path, json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def _write_csv_atomic(rows, path: Path) -> None:
    temporary = path.with_name(path.name + ".tmp")
    convert.write_csv(rows, temporary)
    os.replace(temporary, path)


def _read_json(path: Path):
    return json.loads(Path(path).read_text())


def _read_last_jsonl(path: Path):
    lines = [line for line in Path(path).read_text().splitlines() if line.strip()]
    if not lines:
        return None
    return json.loads(lines[-1])


def _counts(runs):
    by_status = {}
    for run in runs:
        status = run.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    pending = sum(by_status.get(status, 0) for status in PENDING_STATUSES)
    return {
        "total": len(runs),
        "terminal": len(runs) - pending,
        "pending": pending,
        "by_status": dict(sorted(by_status.items())),
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    tokens = list(sys.argv[1:] if argv is None else argv)
    parser.add_argument("--arms", nargs="+", default=list(ARMS), metavar="ARM")
    parser.add_argument("--scenarios", nargs="+", default=["A-G"],
                        metavar="SCENARIO")
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--baseline-timeout", type=float, default=300.0)
    parser.add_argument("--cooldown-seconds", type=float,
                        default=DEFAULT_COOLDOWN_SECONDS)
    parser.add_argument("--baseline-retries", type=int,
                        default=DEFAULT_BASELINE_RETRIES)
    parser.add_argument(
        "--out", type=Path,
        default=Path(__file__).resolve().parent / "runs")
    parser.add_argument("--namespace", default=harness.DEFAULT_NAMESPACE)
    parser.add_argument("--app", default=harness.DEFAULT_APP)
    parser.add_argument("--source-revision")
    parser.add_argument("--render-sha256")
    parser.add_argument("--render-file")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-single-stack", action="store_true")
    parser.add_argument("--production-like", action="store_true")
    parser.add_argument("--batch-id")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    args.namespace_explicit = any(
        token == "--namespace" or token.startswith("--namespace=")
        for token in tokens)
    args.app_explicit = any(
        token == "--app" or token.startswith("--app=") for token in tokens)
    try:
        args.arms = parse_arms(args.arms)
        args.scenarios = parse_scenarios(args.scenarios)
    except ValueError as error:
        parser.error(str(error))
    if not 1 <= args.reps <= DEFAULT_REPS:
        parser.error("--reps must be between 1 and 15")
    if args.cooldown_seconds < 0 or not math.isfinite(args.cooldown_seconds):
        parser.error("--cooldown-seconds must be a finite value >= 0")
    if args.baseline_retries < 0:
        parser.error("--baseline-retries must be >= 0")
    if args.batch_id and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", args.batch_id):
        parser.error(
            "--batch-id must be 1-32 characters of letters, digits, dot, dash, underscore")
    if args.source_revision and not re.fullmatch(
            r"[0-9a-f]{40}", args.source_revision):
        parser.error("--source-revision must be 40 lowercase hex")
    if args.render_sha256 and not re.fullmatch(
            r"[0-9a-f]{64}", args.render_sha256):
        parser.error("--render-sha256 must be 64 lowercase hex")
    if args.production_like and not args.live:
        parser.error("--production-like requires --live; dry runs are never formal")
    return args


def validate_batch_args(args):
    harness.validate_namespace(args.namespace)
    if not args.live:
        return
    if not args.confirm_single_stack:
        raise BatchSafetyError("--live requires --confirm-single-stack")
    if not args.namespace_explicit:
        raise BatchSafetyError("--namespace must be explicit in live mode")
    if not args.app_explicit:
        raise BatchSafetyError("--app must be explicit in live mode")
    if not args.render_sha256:
        raise BatchSafetyError(
            "--render-sha256 is required in live mode; freeze the render first")
    if not args.source_revision:
        raise BatchSafetyError(
            "--source-revision is required in live mode; freeze the revision first")
    if not args.render_file:
        raise BatchSafetyError(
            "--render-file is required in live mode; freeze the render bundle first")
    if "://" in args.render_file:
        raise BatchSafetyError("--render-file must be a local file, not a URL")
    try:
        harness.load_declaration(
            args.render_file, args.render_sha256, args.source_revision,
            args.namespace)
    except harness.DeclarationError as error:
        raise BatchSafetyError(f"invalid frozen render: {error}") from None


def _new_manifest(args, plan, batch_id):
    runs = []
    for item in plan["runs"]:
        entry = dict(item)
        entry.update({
            "run_id": run_id_for(batch_id, item),
            "status": "pending",
            "started_utc": None,
            "finished_utc": None,
            "exit_code": None,
            "stop_reason": None,
            "error": None,
            "row_path": None,
            "attempts": [],
        })
        runs.append(entry)
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "state": "running",
        "mode": "live" if args.live else "dry_run",
        "production_like": bool(args.production_like),
        "formal_execution_approved": bool(args.live and args.production_like),
        "stack_isolated": False,
        "r3_status": "not_measured",
        "created_utc": _utc_now(),
        "updated_utc": _utc_now(),
        "seed": args.seed,
        "arms": list(args.arms),
        "scenarios": list(args.scenarios),
        "reps": args.reps,
        "arm_order": list(plan["arm_order"]),
        "scenario_order": list(plan["scenario_order"]),
        "namespace": args.namespace,
        "app": args.app,
        "source_revision": args.source_revision,
        "render_sha256": args.render_sha256,
        "cooldown_seconds": args.cooldown_seconds,
        "baseline_retries": args.baseline_retries,
        "runs": runs,
        "cooldowns": [],
        "counts": _counts(runs),
        "stop_reason": None,
        "stop_run_id": None,
    }


def _ensure_new_batch(args, plan, batch_id, paths):
    for name, path in paths.items():
        if path.exists():
            raise BatchSafetyError(
                f"batch output already exists ({name}); use --resume or a new --out/--batch-id")
    for item in plan["runs"]:
        run_id = run_id_for(batch_id, item)
        for candidate in run_slots(run_id, args.baseline_retries):
            if len(candidate) > 63:
                raise BatchSafetyError(
                    "batch id and retry suffix make a run id longer than 63 characters")
            jsonl = _row_path(args.out, candidate)
            evidence = _evidence_path(args.out, candidate)
            if jsonl.exists() or (evidence.exists() and any(evidence.iterdir())):
                raise BatchSafetyError(
                    f"refusing to overwrite existing run output {candidate}")


def _ensure_run_slot(args, run_id):
    jsonl = _row_path(args.out, run_id)
    evidence = _evidence_path(args.out, run_id)
    if jsonl.exists() or (evidence.exists() and any(evidence.iterdir())):
        raise BatchSafetyError(
            f"refusing to overwrite existing run output {run_id}")


def _validate_resume(args, plan, batch_id, paths):
    if not paths["manifest"].exists():
        raise BatchSafetyError("--resume requires an existing manifest")
    try:
        manifest = _read_json(paths["manifest"])
    except (OSError, ValueError, TypeError) as error:
        raise BatchSafetyError(
            f"invalid batch manifest: {type(error).__name__}: {error}") from error
    if not isinstance(manifest, dict):
        raise BatchSafetyError("invalid batch manifest: not an object")
    missing = [key for key in MANIFEST_KEYS if key not in manifest]
    if missing:
        raise BatchSafetyError(
            f"invalid batch manifest: missing {', '.join(missing)}")
    expected = {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "mode": "live" if args.live else "dry_run",
        "production_like": bool(args.production_like),
        "formal_execution_approved": bool(args.live and args.production_like),
        "stack_isolated": False,
        "r3_status": "not_measured",
        "seed": args.seed,
        "arms": list(args.arms),
        "scenarios": list(args.scenarios),
        "reps": args.reps,
        "arm_order": list(plan["arm_order"]),
        "scenario_order": list(plan["scenario_order"]),
        "namespace": args.namespace,
        "app": args.app,
        "source_revision": args.source_revision,
        "render_sha256": args.render_sha256,
        "cooldown_seconds": args.cooldown_seconds,
        "baseline_retries": args.baseline_retries,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise BatchSafetyError(
                f"manifest {key} does not match this batch invocation")
    if manifest.get("state") not in ("running", "stopped", "complete"):
        raise BatchSafetyError("invalid batch manifest state")
    runs = manifest.get("runs")
    if not isinstance(runs, list) or len(runs) != len(plan["runs"]):
        raise BatchSafetyError("manifest run list does not match the plan")
    identities = set()
    pending_found = False
    for entry, item in zip(runs, plan["runs"]):
        run_id = run_id_for(batch_id, item)
        for key in ("index", "arm", "scenario", "rep", "phase"):
            if entry.get(key) != item[key]:
                raise BatchSafetyError(
                    f"manifest run {run_id} does not match the plan")
        if entry.get("run_id") != run_id:
            raise BatchSafetyError("manifest run identity mismatch")
        status = entry.get("status")
        if status not in PENDING_STATUSES | TERMINAL_STATUSES:
            raise BatchSafetyError(
                f"manifest run {run_id} has unknown status {status!r}")
        attempts = entry.get("attempts")
        if not isinstance(attempts, list):
            raise BatchSafetyError(
                f"manifest run {run_id} has no attempt ledger")
        for number, attempt in enumerate(attempts):
            if not isinstance(attempt, dict) or attempt.get("attempt") != number:
                raise BatchSafetyError(
                    f"manifest run {run_id} has an invalid attempt ledger")
            attempt_id = (run_id if number == 0
                          else run_id_for_retry(run_id, number))
            if attempt.get("run_id") != attempt_id:
                raise BatchSafetyError(
                    f"manifest run {run_id} has an unexpected retry identity")
            expected_retry = None if number == 0 else run_id
            if attempt.get("retry_of") != expected_retry:
                raise BatchSafetyError(
                    f"manifest run {run_id} has an invalid retry relationship")
            if attempt_id in identities:
                raise BatchSafetyError("duplicate run identity in manifest")
            identities.add(attempt_id)
            _validate_attempt(args, item, attempt_id, attempt)
        if attempts:
            last = attempts[-1]
            if status == "retrying":
                last_path = _row_path(args.out, last["run_id"])
                last_row = (_read_last_jsonl(last_path)
                            if last_path.exists() else None)
                if (last.get("status") != "baseline_failure"
                        or len(attempts) > args.baseline_retries
                        or not _baseline_retryable("baseline_failure", last_row)):
                    raise BatchSafetyError(
                        f"manifest run {run_id} is retrying without a "
                        "retryable baseline failure")
            elif status != last.get("status"):
                raise BatchSafetyError(
                    f"manifest run {run_id} status does not match its last attempt")
        elif status != "pending":
            raise BatchSafetyError(
                f"manifest run {run_id} has no attempts but is not pending")
        row_path = _row_path(args.out, final_run_id(entry))
        if entry.get("row_path") and not Path(entry["row_path"]).exists():
            raise BatchSafetyError(
                f"manifest run {run_id} points at missing evidence")
        if status in ROW_REQUIRED_STATUSES and not row_path.exists():
            raise BatchSafetyError(
                f"manifest run {run_id} is missing its preserved row")
        if status in PENDING_STATUSES:
            pending_found = True
            if not attempts:
                next_number = 0
            elif status == "retrying":
                next_number = len(attempts)
            else:
                next_number = len(attempts) - 1
            for number in range(next_number, args.baseline_retries + 1):
                slot_id = (run_id if number == 0
                           else run_id_for_retry(run_id, number))
                next_row = _row_path(args.out, slot_id)
                next_evidence = _evidence_path(args.out, slot_id)
                if next_row.exists() or (next_evidence.exists()
                                         and any(next_evidence.iterdir())):
                    raise BatchSafetyError(
                        f"pending run {slot_id} already has output; refusing overwrite")
    if manifest["state"] == "complete" and pending_found:
        raise BatchSafetyError("complete manifest still has pending runs")
    if manifest["state"] == "stopped" and not manifest.get("stop_reason"):
        raise BatchSafetyError("stopped manifest has no stop reason")
    return manifest


def _validate_attempt(args, item, run_id, attempt):
    status = attempt.get("status")
    if status not in PENDING_STATUSES | TERMINAL_STATUSES:
        raise BatchSafetyError(
            f"manifest attempt {run_id} has unknown status {status!r}")
    row_path = _row_path(args.out, run_id)
    if attempt.get("row_path") and not Path(attempt["row_path"]).exists():
        raise BatchSafetyError(
            f"manifest attempt {run_id} points at missing evidence")
    if status in ROW_REQUIRED_STATUSES and not row_path.exists():
        raise BatchSafetyError(
            f"manifest attempt {run_id} is missing its preserved row")
    if row_path.exists():
        try:
            row = _read_last_jsonl(row_path)
        except (OSError, ValueError, TypeError) as error:
            raise BatchSafetyError(
                f"unreadable row for {run_id}: {type(error).__name__}") from error
        if not isinstance(row, dict):
            raise BatchSafetyError(f"invalid row for {run_id}")
        if (row.get("run_id") != run_id
                or row.get("arm") != item["arm"]
                or row.get("scenario") != item["scenario"]
                or row.get("rep") != item["rep"]
                or row.get("status") != status):
            raise BatchSafetyError(
                f"row identity/status mismatch for {run_id}")
    if status in PENDING_STATUSES:
        evidence = _evidence_path(args.out, run_id)
        if row_path.exists() or (evidence.exists() and any(evidence.iterdir())):
            raise BatchSafetyError(
                f"pending run {run_id} already has output; refusing overwrite")


def _rebuild_rows(args, manifest, batch_id):
    rows = []
    for entry in manifest["runs"]:
        for attempt in entry.get("attempts") or []:
            if attempt.get("status") in PENDING_STATUSES:
                continue
            path = _row_path(args.out, attempt["run_id"])
            if not path.exists():
                continue
            rows.append(annotate_row(
                _read_last_jsonl(path), entry, args, batch_id, attempt))
    return rows


def _resolve_batch_id(args, plan):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.batch_id:
        batch_id = args.batch_id
    elif args.resume:
        candidate = default_batch_id(args)
        if _batch_paths(out, candidate)["manifest"].exists():
            batch_id = candidate
        else:
            manifests = sorted(out.glob("*.manifest.json"))
            if len(manifests) != 1:
                raise BatchSafetyError(
                    "--resume needs --batch-id when --out has zero or multiple manifests")
            batch_id = manifests[0].name[:-len(".manifest.json")]
    else:
        batch_id = default_batch_id(args)
    for item in plan["runs"]:
        for candidate in run_slots(
                run_id_for(batch_id, item), args.baseline_retries):
            if len(candidate) > 63:
                raise BatchSafetyError(
                    "batch id and retry suffix make a run id longer than 63 characters")
    return batch_id


def annotate_row(row, entry, args, batch_id, attempt=None):
    annotated = dict(row)
    annotated.update({
        "batch_id": batch_id,
        "batch_index": entry["index"],
        "batch_phase": entry["phase"],
        "batch_attempt": (attempt or {}).get("attempt", 0),
        "batch_retry_of": (attempt or {}).get("retry_of"),
        "batch_mode": "live" if args.live else "dry_run",
        "batch_stop_reason": entry.get("stop_reason"),
        "stack_isolated": False,
        "r3_status": "not_measured",
        "production_like": bool(args.production_like),
        "formal_execution_approved": bool(args.live and args.production_like),
    })
    return annotated


def _analysis_problem(row):
    status = row.get("status")
    if status not in ANALYSIS_STATUSES:
        return f"status:{status}"
    if row.get("cleanup_status") != "ok":
        return "cleanup_failure"
    if row.get("arm_restore_status") != "restored":
        return "arm_restore_failure"
    if row.get("batch_stop_reason"):
        return f"batch_stop:{row['batch_stop_reason']}"
    if row.get("error"):
        return "row_error"
    postcondition = row.get("postcondition")
    if not isinstance(postcondition, dict) or postcondition.get("verified") is not True:
        return "postcondition_not_verified"
    if row.get("synthetic") is not False:
        return "synthetic"
    scenario = row.get("scenario")
    if scenario not in SCENARIOS:
        return "invalid_scenario"
    group = ("hpa_control" if scenario == "A" else
             "visibility_boundary" if scenario == "F" else "managed_drift")
    if row.get("analysis_group") != group:
        return "invalid_analysis_group"
    if not re.fullmatch(r"[0-9a-f]{40}",
                        str(row.get("source_revision") or "")):
        return "invalid_source_revision"
    if not re.fullmatch(r"[0-9a-f]{64}",
                        str(row.get("render_sha256") or "")):
        return "invalid_render_sha256"
    limit = row.get("censor_seconds")
    if (type(limit) not in (int, float) or not math.isfinite(limit)
            or limit <= 0):
        return "invalid_censor_seconds"
    for metric in ("detection", "evidence", "recovery"):
        value = row.get(metric + "_seconds")
        metric_status = row.get(metric + "_status")
        if metric_status == "right_censored" and value is None:
            continue
        if (metric_status == "observed"
                and type(value) in (int, float)
                and math.isfinite(value) and 0 <= value <= limit):
            continue
        return f"invalid_{metric}_observation"
    return None


def _analysis_row(row):
    mapped = dict(row)
    env = row.get("env") or row.get("arm")
    mapped["env"] = "manual" if env == "imperative" else env
    return mapped


def _exclusion(entry, reason):
    return {
        "run_id": entry["run_id"],
        "arm": entry["arm"],
        "scenario": entry["scenario"],
        "rep": entry["rep"],
        "phase": entry["phase"],
        "status": entry["status"],
        "reason": reason,
    }


def _analysis_view(manifest, rows):
    by_id = {row.get("run_id"): row for row in rows}
    analysis_rows = []
    exclusions = []
    for entry in manifest["runs"]:
        if entry["status"] in PENDING_STATUSES:
            exclusions.append(_exclusion(entry, "not_run"))
            continue
        row = by_id.get(final_run_id(entry))
        if row is None:
            exclusions.append(_exclusion(entry, "no_preserved_row"))
            continue
        problem = _analysis_problem(row)
        if problem:
            exclusions.append(_exclusion(entry, problem))
            continue
        analysis_rows.append(_analysis_row(row))
    return analysis_rows, exclusions


def _phase_summary(manifest, analysis_rows):
    phases = {
        "R2": {"planned": 0, "recorded": 0, "observed": 0,
               "right_censored": 0, "excluded": 0},
        "R1": {"planned": 0, "recorded": 0, "observed": 0,
               "right_censored": 0, "excluded": 0},
    }
    for entry in manifest["runs"]:
        phase = phases[entry["phase"]]
        phase["planned"] += 1
        if entry["status"] not in PENDING_STATUSES:
            phase["recorded"] += 1
    for row in analysis_rows:
        phase = phases[row.get("batch_phase")]
        if row.get("status") == "observed":
            phase["observed"] += 1
        else:
            phase["right_censored"] += 1
    for phase in phases.values():
        phase["excluded"] = phase["recorded"] - phase["observed"] - phase["right_censored"]
    return phases


def _censoring(analysis_rows):
    result = {}
    for phase in ("R2", "R1"):
        phase_rows = [row for row in analysis_rows
                      if row.get("batch_phase") == phase]
        result[phase] = {}
        for metric in ("detection", "evidence", "recovery"):
            counts = {"observed": 0, "right_censored": 0,
                      "unobserved_before_stop": 0}
            for row in phase_rows:
                status = row.get(metric + "_status")
                if status in counts:
                    counts[status] += 1
            result[phase][metric] = counts
    return result


def _summary(manifest, analysis_rows, exclusions):
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_id": manifest["batch_id"],
        "state": manifest["state"],
        "mode": manifest["mode"],
        "production_like": manifest["production_like"],
        "formal_execution_approved": manifest["formal_execution_approved"],
        "stack_isolated": False,
        "r3_status": "not_measured",
        "seed": manifest["seed"],
        "arm_order": manifest["arm_order"],
        "scenario_order": manifest["scenario_order"],
        "reps": manifest["reps"],
        "planned": len(manifest["runs"]),
        "recorded": len(manifest["runs"]) - manifest["counts"]["pending"],
        "phases": _phase_summary(manifest, analysis_rows),
        "censoring": _censoring(analysis_rows),
        "analysis_rows": len(analysis_rows),
        "exclusions": exclusions,
        "efficacy_ineligible": [
            row["run_id"] for row in analysis_rows
            if row.get("scenario") in ("A", "F")],
        "status_counts": manifest["counts"]["by_status"],
        "note": ("R2 = repetitions 1..10; R1 = repetitions 11..15. "
                 "Observed medians require a separate censoring-aware analysis. "
                 "Dry runs and failed runs are never observations. "
                 "A retried baseline failure stays one planned cell, not an extra sample."),
    }


def _write_batch_outputs(args, batch_id, paths, manifest, rows):
    by_id = {row.get("run_id"): row for row in rows}
    ordered = []
    for entry in manifest["runs"]:
        for attempt in entry.get("attempts") or []:
            row = by_id.get(attempt["run_id"])
            if row is not None:
                ordered.append(row)
    analysis_rows, exclusions = _analysis_view(manifest, ordered)
    summary = _summary(manifest, analysis_rows, exclusions)
    _write_json_atomic(paths["manifest"], manifest)
    _write_text_atomic(
        paths["rows"],
        "".join(json.dumps(row, sort_keys=True, default=str) + "\n"
                for row in ordered))
    _write_text_atomic(
        paths["analysis"],
        "".join(json.dumps(row, sort_keys=True, default=str) + "\n"
                for row in analysis_rows))
    _write_csv_atomic(ordered, paths["csv"])
    _write_json_atomic(paths["summary"], summary)
    return summary


def _run_one(args, item, run_id):
    """Delegate one run to the existing harness entrypoint path."""
    argv = [
        "--arm", item["arm"],
        "--scenario", item["scenario"],
        "--rep", str(item["rep"]),
        "--namespace", args.namespace,
        "--app", args.app,
        "--out", str(args.out),
        "--run-id", run_id,
    ]
    if args.source_revision:
        argv.extend(["--source-revision", args.source_revision])
    if args.render_sha256:
        argv.extend(["--render-sha256", args.render_sha256])
    if args.render_file:
        argv.extend(["--render-file", args.render_file])
    argv.extend(["--baseline-timeout", str(args.baseline_timeout)])
    if args.live:
        argv.extend(["--live", "--confirm-single-stack"])
    with redirect_stdout(io.StringIO()):
        code = harness.main(argv)
    path = _row_path(args.out, run_id)
    row = _read_last_jsonl(path) if path.exists() else None
    return code, row, None


def _classify(args, code, row, error):
    if error:
        return "failure", "runner_exception"
    if not isinstance(row, dict):
        return "refused", "missing_row"
    status = row.get("status")
    if status not in TERMINAL_STATUSES:
        return "failure", "unknown_status"
    if args.live and status == "dry_run":
        return status, "unexpected_dry_run"
    if not args.live and status != "dry_run":
        return status, "unexpected_live_row"
    stop_reason = None
    if row.get("cleanup_status") not in (None, "ok"):
        stop_reason = "cleanup_failure"
    if row.get("arm_restore_status") not in (None, "restored"):
        stop_reason = "arm_restore_failure"
    if status in STOP_STATUSES:
        stop_reason = status
    if code != 0 and stop_reason is None:
        stop_reason = "nonzero_exit"
    return status, stop_reason


def _baseline_retryable(status, row):
    """A baseline failure is retryable only before any injection or mutation."""
    if status != "baseline_failure" or not isinstance(row, dict):
        return False
    if row.get("t0_utc") is not None:
        return False
    injection = row.get("injection")
    if isinstance(injection, dict) and injection.get("accepted") is not False:
        return False
    if row.get("cleanup_status") not in (None, "ok"):
        return False
    if row.get("arm_restore_status") not in (None, "restored"):
        return False
    return row.get("mutations_executed") in (None, 0)


def _next_pending_run_id(manifest, current):
    seen = False
    for entry in manifest["runs"]:
        if entry is current:
            seen = True
            continue
        if seen and entry["status"] in PENDING_STATUSES:
            return entry["run_id"]
    return None


def _cooldown(args, batch_id, paths, manifest, rows, after_run_id,
              next_run_id, sleep):
    record = {
        "after_run_id": after_run_id,
        "next_run_id": next_run_id,
        "requested_seconds": args.cooldown_seconds,
        "applied": bool(args.live and args.cooldown_seconds > 0),
        "started_utc": _utc_now(),
        "finished_utc": None,
        "elapsed_seconds": 0.0,
    }
    manifest.setdefault("cooldowns", []).append(record)
    manifest["updated_utc"] = _utc_now()
    if not record["applied"]:
        record["finished_utc"] = _utc_now()
        _write_batch_outputs(args, batch_id, paths, manifest, rows)
        return
    _write_batch_outputs(args, batch_id, paths, manifest, rows)
    started = time.monotonic()
    sleep(args.cooldown_seconds)
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    record["finished_utc"] = _utc_now()
    manifest["updated_utc"] = _utc_now()
    _write_batch_outputs(args, batch_id, paths, manifest, rows)


def _print_result(paths, manifest, summary):
    print(json.dumps({
        "batch_id": manifest["batch_id"],
        "state": manifest["state"],
        "planned": summary["planned"],
        "recorded": summary["recorded"],
        "analysis_rows": summary["analysis_rows"],
        "formal_execution_approved": manifest["formal_execution_approved"],
        "manifest": str(paths["manifest"]),
        "summary": str(paths["summary"]),
    }, sort_keys=True))


def run_batch(args, run_one=None, sleep=None):
    sleep = sleep or time.sleep
    validate_batch_args(args)
    plan = build_plan(args.arms, args.scenarios, args.reps, args.seed)
    batch_id = _resolve_batch_id(args, plan)
    paths = _batch_paths(args.out, batch_id)
    if args.resume:
        manifest = _validate_resume(args, plan, batch_id, paths)
        rows = _rebuild_rows(args, manifest, batch_id)
    else:
        _ensure_new_batch(args, plan, batch_id, paths)
        manifest = _new_manifest(args, plan, batch_id)
        rows = []
    manifest["state"] = "running" if args.resume else manifest["state"]
    manifest["updated_utc"] = _utc_now()
    manifest["counts"] = _counts(manifest["runs"])
    _write_batch_outputs(args, batch_id, paths, manifest, rows)

    runner = run_one or _run_one
    for entry in manifest["runs"]:
        if entry["status"] not in PENDING_STATUSES:
            continue
        attempts = entry.setdefault("attempts", [])
        while attempts and attempts[-1].get("status") in PENDING_STATUSES:
            attempts.pop()
        item = {key: entry[key]
                for key in ("index", "arm", "scenario", "rep", "phase")}
        while True:
            number = len(attempts)
            run_id = (entry["run_id"] if number == 0
                      else run_id_for_retry(entry["run_id"], number))
            try:
                _ensure_run_slot(args, run_id)
            except BatchSafetyError as error:
                manifest.update(state="stopped", stop_reason="output_conflict",
                                stop_run_id=run_id, updated_utc=_utc_now())
                manifest["counts"] = _counts(manifest["runs"])
                summary = _write_batch_outputs(
                    args, batch_id, paths, manifest, rows)
                _print_result(paths, manifest, summary)
                raise error
            started = _utc_now()
            attempt = {
                "attempt": number,
                "run_id": run_id,
                "retry_of": entry["run_id"] if number else None,
                "status": "running",
                "started_utc": started,
                "finished_utc": None,
                "exit_code": None,
                "stop_reason": None,
                "error": None,
                "row_path": None,
            }
            attempts.append(attempt)
            entry.update(status="running", started_utc=started,
                         finished_utc=None, exit_code=None, stop_reason=None,
                         error=None, row_path=None)
            manifest["state"] = "running"
            manifest["updated_utc"] = _utc_now()
            manifest["counts"] = _counts(manifest["runs"])
            _write_batch_outputs(args, batch_id, paths, manifest, rows)
            try:
                code, row, error = runner(args, item, run_id)
            except Exception as exception:  # noqa: BLE001 - preserve batch evidence
                code, row = 1, None
                error = _redact(f"{type(exception).__name__}: {exception}")
            if row is not None and not isinstance(row, dict):
                error = "runner returned a non-object row"
                row = None
            status, stop_reason = _classify(args, code, row, error)
            row_path = _row_path(args.out, run_id)
            if row is not None and not row_path.exists():
                stop_reason = stop_reason or "missing_row_file"
                error = error or f"row file missing: {row_path.name}"
            outcome = {
                "status": status,
                "finished_utc": _utc_now(),
                "exit_code": code,
                "stop_reason": stop_reason,
                "error": error,
                "row_path": (str(row_path)
                             if row is not None and row_path.exists() else None),
            }
            attempt.update(outcome)
            entry.update(outcome)
            if row is not None:
                rows.append(annotate_row(row, entry, args, batch_id, attempt))
            manifest["updated_utc"] = _utc_now()
            manifest["counts"] = _counts(manifest["runs"])
            retry = (stop_reason == "baseline_failure"
                     and number < args.baseline_retries
                     and _baseline_retryable(status, row))
            if stop_reason and not retry:
                manifest.update(state="stopped", stop_reason=stop_reason,
                                stop_run_id=run_id)
                summary = _write_batch_outputs(
                    args, batch_id, paths, manifest, rows)
                _print_result(paths, manifest, summary)
                return 1
            if retry:
                entry.update(status="retrying", finished_utc=None, exit_code=None,
                             stop_reason=None, error=None, row_path=None)
                manifest["state"] = "running"
            summary = _write_batch_outputs(args, batch_id, paths, manifest, rows)
            next_run_id = (run_id_for_retry(entry["run_id"], number + 1)
                           if retry
                           else _next_pending_run_id(manifest, entry))
            if next_run_id is not None:
                _cooldown(args, batch_id, paths, manifest, rows, run_id,
                          next_run_id, sleep)
            if not retry:
                break

    failures = [entry for entry in manifest["runs"]
                if entry.get("stop_reason")]
    if failures:
        first = failures[0]
        manifest.update(state="stopped", stop_reason=first["stop_reason"],
                        stop_run_id=final_run_id(first), updated_utc=_utc_now())
    else:
        manifest.update(state="complete", stop_reason=None, stop_run_id=None,
                        updated_utc=_utc_now())
    manifest["counts"] = _counts(manifest["runs"])
    summary = _write_batch_outputs(args, batch_id, paths, manifest, rows)
    _print_result(paths, manifest, summary)
    return 1 if failures else 0


def main(argv=None):
    try:
        args = parse_args(argv)
        return run_batch(args)
    except BatchSafetyError as error:
        print(f"refused: {_redact(error)}", file=sys.stderr)
        return 2
    except BatchError as error:
        print(f"failed: {_redact(error)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
