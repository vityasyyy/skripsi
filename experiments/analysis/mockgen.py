#!/usr/bin/env python3
"""Synthetic mock data generator for Bab-3 drift experiments.

Generates 420 rows: (7 scenarios x (10 R2 reps + 5 R1 reps)) x 2 subjects x 2 envs.
GitOps is faster / lower-variance than manual by construction, with per-scenario
variation in base means.

Rep convention (documented in README.md):
  rep  1..10 -> R2 measurement replicates (timing-focused)
  rep 11..15 -> R1 measurement replicates (consistency-focused)
All metric columns are populated in every row so analyze.py can pool
subjects x reps per (skenario, env) -> n=30 per cell.

Usage:
  python3 experiments/analysis/mockgen.py --seed 42 --out experiments/analysis/outputs/mock_runs.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

HEADER = [
    "subject",
    "env",
    "skenario",
    "rep",
    "t0",
    "td",
    "trci",
    "t2",
    "r1_t0",
    "r1_t1",
    "r1_t2",
    "kubectl_cmds",
    "notes",
]

SUBJECTS = ["S1", "S2"]
ENVS = ["manual", "gitops"]
SCENARIOS = ["A", "B", "C", "D", "E", "F", "G"]

# GitOps base means (seconds) per scenario: detection / root-cause / recovery.
GITOPS_BASE = {
    "A": {"td": 15.0, "trci": 30.0, "t2": 60.0},
    "B": {"td": 20.0, "trci": 45.0, "t2": 90.0},
    "C": {"td": 12.0, "trci": 25.0, "t2": 50.0},
    "D": {"td": 25.0, "trci": 60.0, "t2": 120.0},
    "E": {"td": 18.0, "trci": 35.0, "t2": 75.0},
    "F": {"td": 30.0, "trci": 70.0, "t2": 150.0},
    "G": {"td": 22.0, "trci": 50.0, "t2": 100.0},
}

# Manual slowdown factors vs GitOps.
MANUAL_FACTOR = {"td": 2.1, "trci": 2.2, "t2": 1.9}
CV_GITOPS = 0.15
CV_MANUAL = 0.30

# Drifted consistency level r1_t1 per scenario (env-independent: pre-remediation state).
R1_T1_BASE = {"A": 0.70, "B": 0.65, "C": 0.80, "D": 0.60, "E": 0.75, "F": 0.55, "G": 0.68}
# Recovered consistency r1_t2 mean per env (manual worse on hard scenarios D/F).
R1_T2_MANUAL = {"A": 0.92, "B": 0.90, "C": 0.94, "D": 0.87, "E": 0.93, "F": 0.86, "G": 0.91}

# kubectl command counts (Poisson lambdas).
KUBECTL_LAM_MANUAL = {"A": 8, "B": 10, "C": 6, "D": 12, "E": 7, "F": 14, "G": 9}
KUBECTL_LAM_GITOPS = 1.0


def _positive_normal(rng: np.random.Generator, mean: float, std: float, lo: float = 1.0) -> float:
    return float(max(lo, rng.normal(mean, std)))


def generate_rows(seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    for subject in SUBJECTS:
        for env in ENVS:
            is_gitops = env == "gitops"
            for sk in SCENARIOS:
                base = GITOPS_BASE[sk]
                for rep in range(1, 16):  # 1..10 R2, 11..15 R1
                    run_kind = "R2" if rep <= 10 else "R1"
                    # t0: drift-injection latency, ~env-independent.
                    t0 = _positive_normal(rng, 5.0, 0.8 if is_gitops else 1.5)
                    # Timing metrics with env-dependent mean + variance.
                    vals = {}
                    for m in ("td", "trci", "t2"):
                        gmean = base[m]
                        mean = gmean if is_gitops else gmean * MANUAL_FACTOR[m]
                        cv = CV_GITOPS if is_gitops else CV_MANUAL
                        vals[m] = _positive_normal(rng, mean, mean * cv)
                    # Consistency metrics in [0, 1].
                    r1_t0 = float(np.clip(rng.normal(1.0, 0.005), 0.95, 1.0))
                    r1_t1 = float(np.clip(rng.normal(R1_T1_BASE[sk], 0.05), 0.0, 1.0))
                    if is_gitops:
                        r1_t2 = float(np.clip(rng.normal(0.99, 0.01), 0.95, 1.0))
                    else:
                        r1_t2 = float(np.clip(rng.normal(R1_T2_MANUAL[sk], 0.04), 0.75, 1.0))
                    lam = KUBECTL_LAM_GITOPS if is_gitops else KUBECTL_LAM_MANUAL[sk]
                    kcmds = int(rng.poisson(lam))
                    rows.append(
                        {
                            "subject": subject,
                            "env": env,
                            "skenario": sk,
                            "rep": rep,
                            "t0": round(t0, 2),
                            "td": round(vals["td"], 2),
                            "trci": round(vals["trci"], 2),
                            "t2": round(vals["t2"], 2),
                            "r1_t0": round(r1_t0, 4),
                            "r1_t1": round(r1_t1, 4),
                            "r1_t2": round(r1_t2, 4),
                            "kubectl_cmds": kcmds,
                            "notes": f"mock seed={seed} {run_kind}",
                        }
                    )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic mock_runs.csv (420 rows).")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default="experiments/analysis/outputs/mock_runs.csv")
    args = ap.parse_args()

    rows = generate_rows(args.seed)
    assert len(rows) == 420, f"expected 420 rows, got {len(rows)}"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out} (seed={args.seed})")


if __name__ == "__main__":
    main()
