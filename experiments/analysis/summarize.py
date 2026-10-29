#!/usr/bin/env python3
"""Descriptive v2 evidence summaries; never pool controls or discard censoring."""
import argparse
import json
import math
from pathlib import Path
from statistics import median
import sys


def summarize(rows):
    groups = {}
    identities = set()
    for row in rows:
        if row["schema_version"] != 2 or row["run_id"] in identities:
            raise ValueError("wrong schema or duplicate run identity")
        identities.add(row["run_id"])
        scenario = row["scenario"]
        if scenario not in "ABCDEFG" or len(scenario) != 1 or row["env"] not in ("manual", "gitops"):
            raise ValueError("unknown scenario/arm")
        group = "hpa_control" if scenario == "A" else "visibility_boundary" if scenario == "F" else "managed_drift"
        if row["analysis_group"] != group or type(row["synthetic"]) is not bool:
            raise ValueError("invalid analysis classification")
        key = (scenario, row["env"], group, row["synthetic"], row["source_revision"], row["render_sha256"])
        groups.setdefault(key, []).append(row)
    result = []
    for key, runs in sorted(groups.items()):
        scenario, env, group, synthetic, revision, digest = key
        summary = {"scenario": scenario, "env": env, "analysis_group": group,
                   "synthetic": synthetic, "source_revision": revision,
                   "render_sha256": digest, "runs": len(runs),
                   "complete_time_observations": True}
        for metric in ("detection", "evidence", "recovery"):
            observed, censored, missing = [], 0, 0
            for row in runs:
                value = row[metric + "_seconds"]
                status = row[metric + "_status"]
                limit = row["censor_seconds"]
                if type(limit) not in (int, float) or not math.isfinite(limit) or limit <= 0:
                    raise ValueError("invalid observation limit")
                if status == "right_censored" and value is None:
                    censored += 1
                elif status == "unobserved_before_stop" and value is None:
                    missing += 1
                elif status == "observed" and type(value) in (int, float) and math.isfinite(value) and 0 <= value <= limit:
                    observed.append(value)
                else:
                    raise ValueError("invalid event time/status; no imputation allowed")
            summary[metric] = {"observed": len(observed), "right_censored": censored,
                               "missing": missing,
                               "observed_median_seconds": median(observed) if observed else None}
            summary["complete_time_observations"] &= censored == 0 and missing == 0
        result.append(summary)
    if not result:
        raise ValueError("empty dataset")
    return {"schema_version": 2, "formal_execution_approved": False,
            "note": "Observed-only medians are not censoring-adjusted comparisons; no efficacy inference.",
            "groups": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="source", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows = [json.loads(line) for line in args.source.read_text().splitlines() if line.strip()]
        print(json.dumps(summarize(rows), allow_nan=False, sort_keys=True))
    except (KeyError, TypeError, ValueError, OSError):
        print("Invalid v2 dataset; preserve failed-run evidence separately, never invent times.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
