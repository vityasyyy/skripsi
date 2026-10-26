#!/usr/bin/env python3
"""Map live harness JSONL rows to the historical Bab-3 CSV columns.

The historical analyzer is mock-only and rejects these rows; this converter is
an archival bridge, not formal inference. `trci` is a legacy column name and
here means evidence latency (`t_e - t0`), never human root-cause time.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

COLUMNS = ["subject", "env", "skenario", "rep", "t0", "td", "trci", "t2",
           "r1_t0", "r1_t1", "r1_t2", "kubectl_cmds", "notes"]


def _number(value):
    if value is None:
        return ""
    if type(value) is int:
        return str(value)
    if type(value) is float:
        return format(value, ".6g")
    return str(value)


def _notes(row):
    parts = [
        "status=" + str(row.get("status", "")),
        "detection_controller=" + str(row.get("detection_controller")),
        "recovery_controller=" + str(row.get("recovery_controller")),
        "detection_status=" + str(row.get("detection_status")),
        "recovery_status=" + str(row.get("recovery_status")),
        "censor_seconds=" + _number(row.get("censor_seconds")),
        "cleanup=" + str(row.get("cleanup_status", "n/a")),
        "arm_restore=" + str(row.get("arm_restore_status", "n/a")),
        "trci=evidence_seconds_not_root_cause",
    ]
    if row.get("dry_run"):
        parts.append("dry_run_no_cluster_access")
    if row.get("error"):
        parts.append("error=" + str(row["error"]).replace(";", ","))
    return "; ".join(parts)


def row_to_csv(row):
    env = row.get("env") or row.get("arm")
    if env == "imperative":
        env = "manual"
    return {
        "subject": row.get("subject", "invenio-live"),
        "env": env,
        "skenario": row.get("scenario", ""),
        "rep": _number(row.get("rep")),
        # t0 is the injection acknowledgement latency; t_d/t_r are durations
        # from injection start. Missing values stay blank, never zero.
        "t0": _number(row.get("injection_seconds")),
        "td": _number(row.get("detection_seconds")),
        "trci": _number(row.get("evidence_seconds")),
        "t2": _number(row.get("recovery_seconds")),
        "r1_t0": _number(row.get("r1_baseline")),
        "r1_t1": _number(row.get("r1_first")),
        "r1_t2": _number(row.get("r1_last")),
        "kubectl_cmds": _number(row.get("kubectl_cmds")),
        "notes": _notes(row),
    }


def write_csv(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row_to_csv(row))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="source", type=Path, required=True)
    parser.add_argument("--out", dest="target", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rows = [json.loads(line) for line in
                args.source.read_text().splitlines() if line.strip()]
        if not rows:
            raise ValueError("empty JSONL")
        write_csv(rows, args.target)
    except (OSError, ValueError, KeyError) as error:
        print(f"invalid JSONL input: {type(error).__name__}: {error}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
