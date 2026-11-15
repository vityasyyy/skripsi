#!/usr/bin/env python3
"""Sensitivity analysis for the excluded C-r02 run.

The frozen primary analysis excludes ``gitops-C-r02`` as ``batch_stop``
because the harness process exited with a non-zero code. The run itself is
complete and observed. This script reads the frozen raw rows, adds that one
row only to the C-scenario comparisons, and reports the resulting tests and
effect sizes. It never writes to the frozen evidence directories.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise SystemExit(f"{path}:{number}: invalid JSON: {error}") from error
        if not isinstance(row, dict):
            raise SystemExit(f"{path}:{number}: row is not an object")
        rows.append(row)
    return rows


def _load_analyzer(path: Path):
    spec = importlib.util.spec_from_file_location("analyze_live_sensitivity", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load analyzer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _reject_frozen_output(out: Path | None, batch_dir: Path, analysis_json: Path):
    if out is None:
        return
    for label, root in (
        ("batch", batch_dir),
        ("analysis", analysis_json.parent),
    ):
        if _is_within(out, root):
            raise SystemExit(
                f"refusing --out inside frozen {label} directory: {root}"
            )


def main(argv: list[str] | None = None) -> int:
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch-dir",
        type=Path,
        default=home / "skripsi" / "experiments" / "formal-20261029",
        help="frozen formal batch directory (default: %(default)s)",
    )
    parser.add_argument(
        "--analysis-json",
        type=Path,
        default=home / "skripsi" / "experiments"
        / "analysis-formal-20261029" / "live_analysis.json",
        help="frozen primary live_analysis.json (default: %(default)s)",
    )
    parser.add_argument(
        "--analyzer",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "analysis" / "analyze_live.py",
        help="frozen analysis module (default: %(default)s)",
    )
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    _reject_frozen_output(args.out, args.batch_dir, args.analysis_json)

    analysis_module = _load_analyzer(args.analyzer)
    rows = _load_jsonl(args.batch_dir / "formal-20261029.analysis.jsonl")
    raw = _load_jsonl(args.batch_dir / "formal-20261029.rows.jsonl")
    primary = json.loads(args.analysis_json.read_text())

    if len(rows) != 207 or len(raw) != 211:
        raise SystemExit(
            f"unexpected frozen row counts: analysis={len(rows)}, raw={len(raw)}"
        )
    matches = [row for row in raw if row.get("run_id") == "formal-20261029-gitops-C-r02"]
    if len(matches) != 1:
        raise SystemExit("expected exactly one gitops-C-r02 raw row")
    c_r02 = matches[0]
    if c_r02.get("status") != "observed" or c_r02.get("recovery_status") != "observed":
        raise SystemExit("gitops-C-r02 is not a complete observed run")

    c_rows = [
        row for row in rows + [c_r02]
        if row.get("scenario") == "C" and row.get("batch_phase") == "R2"
    ]
    sensitivity = {}
    for metric in analysis_module.METRICS:
        result = analysis_module._comparison(
            c_rows, "C", metric, args.bootstrap, args.seed
        )
        sensitivity[metric] = {
            "n_manual": result["test"].get("n_manual"),
            "n_gitops": result["test"].get("n_gitops"),
            "pairing": result["pairing"]["method"],
            "pairing_reason": result["pairing"]["reason"],
            "statistic": result["test"]["statistic"],
            "p_value": result["test"]["p_value"],
            "cliffs_delta": result["effect"]["cliffs_delta"],
            "cliffs_delta_ci": result["effect"]["cliffs_delta_ci"],
            "median_paired_difference": result["effect"]["median_paired_difference"],
        }

    p_values = []
    family = []
    for scenario in ("B", "C", "D", "E"):
        for metric in analysis_module.METRICS:
            if scenario == "C":
                p_value = sensitivity[metric]["p_value"]
            else:
                match = next(
                    item for item in primary["efficacy"]
                    if item["scenario"] == scenario and item["metric"] == metric
                )
                p_value = match["test"]["p_value"]
            family.append({"scenario": scenario, "metric": metric, "p_value": p_value})
            p_values.append(p_value)
    adjusted = analysis_module.holm_adjust(p_values, 12)
    for item, holm in zip(family, adjusted):
        item["holm_adjusted_p"] = holm

    primary_c = {
        item["metric"]: {
            "n_manual": item["test"].get("n_manual"),
            "n_gitops": item["test"].get("n_gitops"),
            "pairing": item["pairing"]["method"],
            "p_value": item["test"]["p_value"],
            "holm_adjusted_p": item["holm_adjusted_p"],
            "cliffs_delta": item["effect"]["cliffs_delta"],
            "cliffs_delta_ci": item["effect"]["cliffs_delta_ci"],
        }
        for item in primary["efficacy"]
        if item["scenario"] == "C"
    }
    output = {
        "source": {
            "batch_dir": str(args.batch_dir),
            "analysis_json": str(args.analysis_json),
            "bootstrap": args.bootstrap,
            "seed": args.seed,
        },
        "c_r02": {
            "run_id": c_r02["run_id"],
            "status": c_r02["status"],
            "batch_stop_reason": c_r02.get("batch_stop_reason"),
            "detection_seconds": c_r02["detection_seconds"],
            "evidence_seconds": c_r02["evidence_seconds"],
            "recovery_seconds": c_r02["recovery_seconds"],
            "r1_baseline": c_r02["r1_baseline"],
            "r1_first": c_r02["r1_first"],
            "r1_last": c_r02["r1_last"],
        },
        "primary_c": primary_c,
        "sensitivity_c": sensitivity,
        "holm_family": family,
    }
    text = json.dumps(output, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
