#!/usr/bin/env python3
"""Thesis-facing RQ timing view over the frozen live analyzer.

The timing research question is the only comparative question. R1 is exposed
only as a recovery-completeness validity check, never as a comparative table.
The frozen analyzer remains the primary analysis; this module selects its
fields, renames the historical ``env=manual`` alias for display, and derives
the descriptive repair interval ``t_r - t_d`` without a test or imputation.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import median

if __package__:
    from . import analyze_live as analyze_live
    from . import data as data
    from . import rq2_tables
    from . import stats as stats
else:  # direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import analyze_live  # type: ignore[no-redef]
    import data  # type: ignore[no-redef]
    import rq2_tables  # type: ignore[no-redef]
    import stats  # type: ignore[no-redef]

RQ_FIELDS = ("batch", "exclusions", "overview", "survival", "efficacy", "families")
VIEW_SCHEMA_VERSION = 1
LEGACY_ARM = "manual"
DISPLAY_ARMS = {LEGACY_ARM: "imperative", "gitops": "gitops"}
ARM_LABELS = rq2_tables.ARM_LABELS
COMPLETENESS_LEVELS = (100, 75, 50, 25)
OUTPUT_NAMES = (
    "rq2_analysis.json",
    "rq2_overview.tex",
    "rq2_survival.tex",
    "rq2_tests.tex",
    "rq2_effects.tex",
    "rq2_repair.tex",
    "recovery_completeness.tex",
)


def select_rq_fields(result: dict) -> dict:
    """Return only the analyzer fields the thesis timing view consumes."""
    return {field: result[field] for field in RQ_FIELDS}


def _display_entries(entries: list) -> list:
    """Rename the historical env alias while preserving it for audit."""
    return [
        {**entry, "arm": DISPLAY_ARMS[entry["arm"]], "legacy_env": entry["arm"]}
        for entry in entries
    ]


def repair_entries(rows: list) -> list:
    """Describe ``t_r - t_d`` per scenario/arm; never test and never impute."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        if row["batch_phase"] == "R2":
            groups.setdefault((row["scenario"], row["env"]), []).append(row)
    entries = []
    for (scenario, arm), group in sorted(
        groups.items(), key=lambda item: (item[0][0], analyze_live.ARM_ORDER[item[0][1]])
    ):
        values: list[float] = []
        censored = 0
        missing = 0
        for row in group:
            if row["detection_status"] == "observed" and row["recovery_status"] == "observed":
                values.append(row["recovery_seconds"] - row["detection_seconds"])
            elif "unobserved_before_stop" in (
                row["detection_status"],
                row["recovery_status"],
            ):
                missing += 1
            else:
                censored += 1
        values.sort()
        entry = {
            "scenario": scenario,
            "arm": DISPLAY_ARMS[arm],
            "legacy_env": arm,
            "rows": len(group),
            "n": len(values),
            "censored": censored,
            "missing": missing,
            "median": median(values) if values else None,
            "iqr": [
                stats.percentile(values, 0.25),
                stats.percentile(values, 0.75),
            ]
            if values
            else None,
            "min": values[0] if values else None,
            "max": values[-1] if values else None,
        }
        entries.append(entry)
    return entries


def recovery_completeness(rows: list) -> list:
    """Count the R1 recovery predicate at 100/75/50/25 per scenario/arm."""
    groups: dict[tuple[str, str], list] = {}
    for row in rows:
        if row["batch_phase"] == "R1":
            groups.setdefault((row["scenario"], row["env"]), []).append(row["r1_last"])
    entries = []
    for (scenario, arm), values in sorted(
        groups.items(), key=lambda item: (item[0][0], analyze_live.ARM_ORDER[item[0][1]])
    ):
        counts = {str(level): 0 for level in COMPLETENESS_LEVELS}
        missing = 0
        other = 0
        for value in values:
            if value is None:
                missing += 1
            elif value in COMPLETENESS_LEVELS:
                counts[str(int(value))] += 1
            else:
                other += 1
        entries.append(
            {
                "scenario": scenario,
                "arm": DISPLAY_ARMS[arm],
                "legacy_env": arm,
                "rows": len(values),
                "counts": counts,
                "missing": missing,
                "other": other,
            }
        )
    return entries


def build_view(result: dict, rows: list, *, frozen_check: str = "disabled") -> dict:
    """Select the RQ fields and attach the thesis-only derivations."""
    selected = select_rq_fields(result)
    return {
        "schema_version": VIEW_SCHEMA_VERSION,
        "view": "rq2_timing",
        "source": {"frozen_check": frozen_check},
        "batch": selected["batch"],
        "exclusions": selected["exclusions"],
        "overview": _display_entries(selected["overview"]),
        "survival": _display_entries(selected["survival"]),
        "efficacy": selected["efficacy"],
        "families": selected["families"],
        "recovery_completeness": recovery_completeness(rows),
        "repair": repair_entries(rows),
    }


def compare_frozen(result: dict, frozen: dict) -> list[str]:
    """Return selected analyzer fields whose frozen copy differs."""
    return [
        field
        for field in RQ_FIELDS
        if json.dumps(result.get(field), sort_keys=True)
        != json.dumps(frozen.get(field), sort_keys=True)
    ]


render_tables = rq2_tables.render_tables


def write_outputs(view: dict, outdir: str | Path) -> dict[str, str]:
    """Write the JSON view and the six LaTeX tables atomically."""
    directory = Path(outdir)
    directory.mkdir(parents=True, exist_ok=True)
    documents = {
        **render_tables(view),
        "rq2_analysis.json": json.dumps(view, allow_nan=False, indent=2, sort_keys=True) + "\n",
    }
    paths = {name: directory / name for name in OUTPUT_NAMES}
    for name, text in documents.items():
        target = paths[name]
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(text)
        temporary.replace(target)
    return {name: str(path) for name, path in paths.items()}


def _frozen_check(args: argparse.Namespace, result: dict) -> tuple[str, list[str]]:
    if not args.check_frozen:
        return "disabled", []
    if args.frozen is None or not args.frozen.exists():
        print(
            "PENDING: frozen analysis not provided or absent; frozen equality was not verified.",
            file=sys.stderr,
        )
        return "pending", []
    frozen = json.loads(args.frozen.read_text())
    if not isinstance(frozen, dict):
        raise analyze_live.LiveAnalysisError("frozen analysis must be a JSON object")
    mismatches = compare_frozen(result, frozen)
    if mismatches:
        return "mismatch", mismatches
    return "match", []


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the thesis-view CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--in", dest="source", type=Path, required=True, help="<batch_id>.analysis.jsonl"
    )
    parser.add_argument("--rows", type=Path, help="optional <batch_id>.rows.jsonl")
    parser.add_argument("--frozen", type=Path, help="frozen live_analysis.json to compare")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument(
        "--check-frozen",
        action="store_true",
        help="compare selected RQ fields to --frozen; mismatch exits 1, pending exits 2",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build and write the thesis-facing timing view."""
    args = parse_args(argv)
    try:
        rows = data.load_jsonl(args.source)
        raw_rows = data.load_jsonl(args.rows) if args.rows else None
        result = analyze_live.analyze(
            rows, raw_rows, bootstrap=args.bootstrap, seed=args.seed, alpha=args.alpha
        )
        status, mismatches = _frozen_check(args, result)
        view = build_view(result, rows, frozen_check=status)
        view["source"] = {
            "analysis": str(args.source),
            "rows": str(args.rows) if args.rows else None,
            "frozen": str(args.frozen) if args.frozen else None,
            "frozen_check": status,
        }
        write_outputs(view, args.out)
    except (ValueError, OSError) as error:
        print(f"Invalid RQ2 view: {error}", file=sys.stderr)
        return 1
    if mismatches:
        print("frozen mismatch: " + ", ".join(mismatches), file=sys.stderr)
        return 1
    if status == "pending":
        return 2
    print(
        f"OK: {result['batch']['analysis_rows']} analysis rows, "
        f"{len(view['repair'])} repair cells, "
        f"frozen: {status} -> {args.out}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - executable guard
    sys.exit(main())
