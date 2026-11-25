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
    from . import stats as stats
else:  # direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import analyze_live  # type: ignore[no-redef]
    import stats  # type: ignore[no-redef]

RQ_FIELDS = ("batch", "exclusions", "overview", "survival", "efficacy", "families")
VIEW_SCHEMA_VERSION = 1
LEGACY_ARM = "manual"
DISPLAY_ARMS = {LEGACY_ARM: "imperative", "gitops": "gitops"}
ARM_LABELS = {"imperative": "Imperatif", "gitops": "GitOps"}
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
                stats._percentile(values, 0.25),
                stats._percentile(values, 0.75),
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


def _overview_tex(view: dict) -> str:
    escape = analyze_live._tex_escape
    lines = [
        "% Generated by experiments/analysis/rq2_report.py; do not edit.",
        r"\begin{table}[H]",
        r"\centering",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{4pt}",
        r"\caption{Ringkasan populasi dan baris blok waktu per mode}",
        r"\label{tab:rq2-overview}",
        r"\begin{tabular}{llrrrl}",
        r"\hline",
        r"Skenario & Mode & Baris & Teramati & Tersensor & Populasi \\",
        r"\hline",
    ]
    totals = [0, 0, 0]
    for item in view["overview"]:
        totals[0] += item["rows"]
        totals[1] += item["observed_runs"]
        totals[2] += item["right_censored_runs"]
        lines.append(
            f"{item['scenario']} & {ARM_LABELS[item['arm']]} & {item['rows']} & "
            f"{item['observed_runs']} & {item['right_censored_runs']} & "
            f"{escape(item['population'])} \\\\"
        )
    lines.extend(
        [
            r"\hline",
            f"Total & -- & {totals[0]} & {totals[1]} & {totals[2]} & -- \\\\",
            r"\hline",
            r"\end{tabular}",
            r"\end{table}",
            r"\par\smallskip",
        ]
    )
    batch = view["batch"]
    excluded = view["exclusions"]
    if excluded["count"] is None:
        exclusion_text = "Eksklusi tidak dihitung karena rows.jsonl tidak diberikan."
    else:
        exclusion_text = (
            f"Eksklusi: {excluded['count']} baris dari {excluded['raw_rows']} baris mentah."
        )
    lines.extend(
        [
            r"\noindent\footnotesize Batch: "
            + escape(batch["batch_id"])
            + f"; baris waktu: {batch['r2_rows']}; baris validitas: {batch['r1_rows']}.",
            r"\par\noindent\footnotesize " + exclusion_text,
            (
                r"\par\noindent\footnotesize Klaim: eksploratif studi kasus tunggal; "
                r"tidak ada klaim konfirmatoris."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _survival_tex(view: dict) -> str:
    num = analyze_live._num
    lines = [
        "% Generated by experiments/analysis/rq2_report.py; do not edit.",
        r"\begin{table}[H]",
        r"\centering",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{3pt}",
        r"\caption{Kaplan--Meier dan RMST waktu per skenario dan mode}",
        r"\label{tab:rq2-survival}",
        r"\begin{tabular}{lllrrrrrrrrr}",
        r"\hline",
        (
            r"Skenario & Mode & Metrik & $n$ & Event & Tersensor & Hilang & "
            r"Eksklusi & Horizon (s) & Median (s) & RMST (s) \\"
        ),
        r"\hline",
    ]
    for item in view["survival"]:
        median_text = num(item["median_seconds"])
        if not item["estimable"]:
            median_text = r"--$^{\dagger}$"
        elif not item["median_reached"]:
            median_text = r"--$^{*}$"
        lines.append(
            f"{item['scenario']} & {ARM_LABELS[item['arm']]} & "
            f"{analyze_live.METRIC_LABELS[item['metric']]} & {item['n']} & "
            f"{item['events']} & {item['censored']} & {item['missing']} & "
            f"{item['excluded_runs'] if item['excluded_runs'] is not None else '--'} & "
            f"{num(item['horizon_seconds'])} & {median_text} & "
            f"{num(item['rmst_seconds'])} \\\\"
        )
    lines.extend(
        [
            r"\hline",
            r"\end{tabular}",
            r"\end{table}",
            r"\par\smallskip",
            (
                r"\noindent\footnotesize $^{*}$ Median tidak tercapai dalam horizon. "
                r"$^{\dagger}$ Tidak terestimasi karena seluruh titik akhir hilang "
                r"sebelum berhenti, bukan tersensor. Nilai tersensor tidak diimputasi "
                r"nol; RMST memakai horizon batas penyensoran terkecil per kelompok. "
                r"Hanya B--E yang masuk keluarga uji; A, F, dan G dilaporkan terpisah."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _tests_tex(view: dict) -> str:
    num = analyze_live._num
    p_value = analyze_live._p
    lines = [
        "% Generated by experiments/analysis/rq2_report.py; do not edit.",
        r"\begin{table}[H]",
        r"\centering",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{2pt}",
        r"\caption{Uji eksploratif waktu B--E}",
        r"\label{tab:rq2-tests}",
        r"\begin{tabular}{lllrrrrl}",
        r"\hline",
        (
            r"Skenario & Metrik & Uji & $n$ & Statistik & $p$ & "
            r"$p_{\mathrm{Holm}}$ & Keputusan \\"
        ),
        r"\hline",
    ]
    for item in view["efficacy"]:
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
            decision = r"$p < \alpha$"
        else:
            decision = r"$p \geq \alpha$"
        lines.append(
            f"{item['scenario']} & {analyze_live.METRIC_LABELS[item['metric']]} & "
            f"{test_text} & {size} & {num(test['statistic'])} & "
            f"{p_value(test['p_value'])} & {p_value(item['holm_adjusted_p'])} & "
            f"{decision} \\\\"
        )
    lines.extend(
        [
            r"\hline",
            r"\end{tabular}",
            r"\end{table}",
            r"\par\smallskip",
            (
                r"\noindent\footnotesize P = berpasangan; U = tidak berpasangan. "
                r"Keputusan memakai ambang $\alpha=0{,}05$ setelah koreksi Holm pada "
                r"keluarga 12 hipotesis B--E yang ditetapkan sebelum data. "
                r"Nilai $p$ adalah ringkasan eksploratif, bukan estimasi populasi; "
                r"pengulangan bersifat pseudoreplikat dan seluruh run GitOps "
                r"mendahului seluruh run imperatif."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _effects_tex(view: dict) -> str:
    num = analyze_live._num
    interval = analyze_live._interval
    lines = [
        "% Generated by experiments/analysis/rq2_report.py; do not edit.",
        r"\begin{table}[H]",
        r"\centering",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{4pt}",
        r"\caption{Ukuran efek waktu, imperatif terhadap GitOps (B--E)}",
        r"\label{tab:rq2-effects}",
        r"\begin{tabular}{lllll}",
        r"\hline",
        (
            r"Skenario & Metrik & Cliff $\delta$ [IK 95\%] & "
            r"$\Delta$ median [IK 95\%] & RB \\"
        ),
        r"\hline",
    ]
    for item in view["efficacy"]:
        effect = item["effect"]
        rank = num(effect["rank_biserial"]) if effect["rank_biserial"] is not None else "--"
        difference = interval(
            effect["median_paired_difference"],
            effect["median_paired_difference_ci"],
        )
        lines.append(
            f"{item['scenario']} & {analyze_live.METRIC_LABELS[item['metric']]} & "
            f"{interval(effect['cliffs_delta'], effect['cliffs_delta_ci'])} & "
            f"{difference} & {rank} \\\\"
        )
    lines.extend(
        [
            r"\hline",
            r"\end{tabular}",
            r"\end{table}",
            r"\par\smallskip",
            (
                r"\noindent\footnotesize $\Delta$ = imperatif $-$ GitOps; nilai positif "
                r"berarti prosedur imperatif lebih lama pada sinyal yang teramati di "
                r"bawah cadence masing-masing. RB = rank-biserial. Interval adalah "
                r"percentile bootstrap deterministik."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _repair_tex(view: dict) -> str:
    num = analyze_live._num
    lines = [
        "% Generated by experiments/analysis/rq2_report.py; do not edit.",
        r"\begin{table}[H]",
        r"\centering",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{4pt}",
        r"\caption{Selisih deskriptif $t_r-t_d$ per skenario dan mode (detik)}",
        r"\label{tab:rq2-repair}",
        r"\begin{tabular}{llrrrrrrr}",
        r"\hline",
        (
            r"Skenario & Mode & $n$ & Median & IQR & Min & Maks & "
            r"Tersensor & Hilang \\"
        ),
        r"\hline",
    ]
    for item in view["repair"]:
        iqr = f"{num(item['iqr'][0])}--{num(item['iqr'][1])}" if item["iqr"] else "--"
        lines.append(
            f"{item['scenario']} & {ARM_LABELS[item['arm']]} & {item['n']} & "
            f"{num(item['median'])} & {iqr} & {num(item['min'])} & {num(item['max'])} & "
            f"{item['censored']} & {item['missing']} \\\\"
        )
    lines.extend(
        [
            r"\hline",
            r"\end{tabular}",
            r"\end{table}",
            r"\par\smallskip",
            (
                r"\noindent\footnotesize $t_r-t_d$ hanya dihitung bila deteksi dan "
                r"pemulihan sama-sama teramati. Baris lain dihitung sebagai tersensor "
                r"atau hilang dan tidak diimputasi. Tidak ada uji pada tabel ini."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _completeness_tex(view: dict) -> str:
    lines = [
        "% Generated by experiments/analysis/rq2_report.py; do not edit.",
        r"\begin{table}[H]",
        r"\centering",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{5pt}",
        r"\caption{Audit validitas manipulasi: cacah skor R1 terakhir per skenario dan mode}",
        r"\label{tab:rq2-recovery-completeness}",
        r"\begin{tabular}{llrrrrrr}",
        r"\hline",
        r"Skenario & Mode & 100 & 75 & 50 & 25 & Hilang & Lain \\",
        r"\hline",
    ]
    for item in view["recovery_completeness"]:
        counts = item["counts"]
        lines.append(
            f"{item['scenario']} & {ARM_LABELS[item['arm']]} & "
            f"{counts['100']} & {counts['75']} & {counts['50']} & {counts['25']} & "
            f"{item['missing']} & {item['other']} \\\\"
        )
    lines.extend(
        [
            r"\hline",
            r"\end{tabular}",
            r"\end{table}",
            r"\par\smallskip",
            (
                r"\noindent\footnotesize R1 $= 100$ adalah predikat pemulihan. Tabel "
                r"audit ini hanya melaporkan cacah; tidak ada perbandingan R1 "
                r"antarmode dan tidak ada uji R1."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def render_tables(view: dict) -> dict[str, str]:
    """Render the thesis tables keyed by output file name."""
    return {
        "rq2_overview.tex": _overview_tex(view),
        "rq2_survival.tex": _survival_tex(view),
        "rq2_tests.tex": _tests_tex(view),
        "rq2_effects.tex": _effects_tex(view),
        "rq2_repair.tex": _repair_tex(view),
        "recovery_completeness.tex": _completeness_tex(view),
    }


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
        rows = analyze_live._load_jsonl(args.source)
        raw_rows = analyze_live._load_jsonl(args.rows) if args.rows else None
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
