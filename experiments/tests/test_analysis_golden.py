"""Golden end-to-end analysis over a deterministic synthetic matrix."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

import analyze_live  # noqa: E402

REVISION = "a" * 40
RENDER = "b" * 64
BATCH = "golden-batch"
CENSOR = 20.0


def row(scenario, arm, rep, index, detection, evidence, recovery):
    env = "manual" if arm == "imperative" else "gitops"
    group = (
        "hpa_control"
        if scenario == "A"
        else "visibility_boundary"
        if scenario == "F"
        else "managed_drift"
    )
    payload = {
        "schema_version": 2,
        "run_id": f"{BATCH}-{arm}-{scenario}-r{rep:02d}",
        "batch_id": BATCH,
        "batch_phase": "R2" if rep <= 10 else "R1",
        "batch_mode": "live",
        "scenario": scenario,
        "arm": arm,
        "env": env,
        "rep": rep,
        "analysis_group": group,
        "efficacy_eligible": scenario not in ("A", "F"),
        "synthetic": False,
        "status": "observed",
        "stop_reason": "recovery",
        "censor_seconds": CENSOR,
        "r1_baseline": 100.0,
        "r1_first": float(50 + index),
        "r1_last": 100.0,
        "source_revision": REVISION,
        "render_sha256": RENDER,
        "formal_execution_approved": True,
        "stack_isolated": False,
        "r3_status": "not_measured",
        "timing_convention": analyze_live.TIMING_CONVENTION,
        "t0_mono": 100.0,
        "t_a_mono": 100.1,
        "t_d_mono": 100.0 + detection,
        "t_e_mono": 100.0 + evidence,
        "t_r_mono": 100.0 + recovery,
        "t_r_first_mono": 100.0 + recovery,
        "t_r_confirmed_mono": 100.0 + recovery + 1.0,
        "window_completed": True,
        "window_end_mono": 100.0 + CENSOR,
        "recovery_confirmation": "confirmed",
        "t_e_store_mono": None,
    }
    for metric, value in (
        ("detection", detection),
        ("evidence", evidence),
        ("recovery", recovery),
    ):
        payload[metric + "_seconds"] = value
        payload[metric + "_status"] = "observed"
    return payload


def matrix():
    rows = []
    index = 0
    for scenario in ("B", "C", "D", "E"):
        for arm in ("imperative", "gitops"):
            for rep in (1, 2, 3):
                offset = 3.0 + index * 0.1 if arm == "imperative" else 1.0 + index * 0.1
                rows.append(
                    row(
                        scenario,
                        arm,
                        rep,
                        index,
                        detection=offset,
                        evidence=offset + 1.0,
                        recovery=offset + 2.0,
                    )
                )
                index += 1
    for scenario in ("A", "F", "G"):
        rows.append(row(scenario, "imperative", 1, index, 4.0, 5.0, 6.0))
        index += 1
    for scenario in ("B", "C"):
        for arm in ("imperative", "gitops"):
            rows.append(row(scenario, arm, 11, index, 3.0, 4.0, 5.0))
            index += 1
    return rows


def compact(result):
    overview = [
        [item["scenario"], item["arm"], item["rows"], item["observed_runs"]]
        for item in result["overview"]
    ]
    r1 = [
        [
            item["scenario"],
            item["arm"],
            item["phase"],
            item["baseline"]["median"],
            item["first"]["median"],
            item["last"]["median"],
        ]
        for item in result["r1"]
    ]
    efficacy = [
        [
            item["scenario"],
            item["metric"],
            item["pairing"]["method"],
            item["test"]["name"],
            None if item["test"]["p_value"] is None else round(item["test"]["p_value"], 6),
            None
            if item["effect"]["cliffs_delta"] is None
            else round(item["effect"]["cliffs_delta"], 6),
            None if item["holm_adjusted_p"] is None else round(item["holm_adjusted_p"], 6),
            item["reject_holm"],
        ]
        for item in result["efficacy"]
    ]
    return {
        "analysis_rows": result["batch"]["analysis_rows"],
        "r2_rows": result["batch"]["r2_rows"],
        "r1_rows": result["batch"]["r1_rows"],
        "overview": overview,
        "r1": r1,
        "efficacy": efficacy,
    }


class GoldenAnalysisTest(unittest.TestCase):
    def test_synthetic_matrix_matches_the_frozen_summary(self):
        expected = json.loads((Path(__file__).parent / "fixtures/golden_analysis.json").read_text())
        self.assertEqual(compact(analyze_live.analyze(matrix(), bootstrap=100, seed=11)), expected)


if __name__ == "__main__":
    unittest.main()
