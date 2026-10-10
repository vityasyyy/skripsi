#!/usr/bin/env python3
"""Bab-3 comparative analysis: descriptives + Mann-Whitney U + effect sizes + boxplots.

Usage:
  python3 experiments/analysis/analyze.py --in experiments/analysis/outputs/mock_runs.csv --out experiments/analysis/outputs

Inputs: CSV with header
  subject,env,skenario,rep,t0,td,trci,t2,r1_t0,r1_t1,r1_t2,kubectl_cmds,notes

Outputs in <out dir>:
  descriptives.tex  — mean/median/range/std per metric per env per scenario
  mannwhitney.tex   — Mann-Whitney U (two-sided, alpha=0.05) manual vs gitops
  effects.tex       — Cohen d (manual-minus-gitops) + Cliff delta + interpretation
  boxplot_<metric>_<skenario>.png — one per R2 sub-metric per scenario

R2 sub-metrics for boxplots: t0, td, trci, t2 (timing metrics).
Rep filtering per Bab-3 protocol (mockgen labels rep 1..10 as R2, 11..15 as R1):
  R2 family (t0, td, trci, t2, kubectl_cmds): reps 1..10 only, pooled across
    subjects S1+S2 -> n=20 per (skenario, env) cell, MW on 20-vs-20 cells.
  R1 family (r1_t0, r1_t1, r1_t2): reps 11..15 only, pooled -> n=10 per cell,
    MW on 10-vs-10 cells.
"""

from __future__ import annotations

import argparse
from pathlib import Path

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
    ap.add_argument("--in", dest="inp", required=True, help="Input CSV path")
    ap.add_argument("--out", dest="out", required=True, help="Output directory")
    args = ap.parse_args()

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
        f.write("% Auto-generated by analyze.py — descriptive stats per metric per env per scenario\n")
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
        f.write("% Auto-generated by analyze.py — Mann-Whitney U manual vs gitops, two-sided, alpha=0.05\n")
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
        f.write("% Auto-generated by analyze.py — Cohen d (manual-minus-gitops) + Cliff delta\n")
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
            ax.set_title(f"Skenario {sk} — {m} (manual vs gitops)")
            ax.set_ylabel(f"{m} (s)" if m in ("t0", "td", "trci", "t2") else m)
            fig.tight_layout()
            fig.savefig(outdir / f"boxplot_{m}_{sk}.png", dpi=150)
            plt.close(fig)

    n_png = len(scenarios) * len(R2_METRICS)
    r2_ns = sorted({r["n"] for r in desc_rows if r["metric"] in R2_FAMILY})
    r1_ns = sorted({r["n"] for r in desc_rows if r["metric"] in R1_METRICS})
    print(
        f"OK: {len(desc_rows)} descriptive cells "
        f"(R2-family cell n={r2_ns}, R1-family cell n={r1_ns}), "
        f"{len(mw_rows)} MW tests (R2 20-vs-20 expected, R1 10-vs-10 expected), "
        f"{n_png} boxplots (reps<=10) -> {outdir}"
    )


if __name__ == "__main__":
    main()
