"""Edge coverage for the v2 descriptive summarizer; all rows are synthetic."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

import summarize  # noqa: E402


def row(**overrides):
    base = {
        "schema_version": 2,
        "run_id": "run-1",
        "timing_convention": "completed-observation-v1",
        "scenario": "B",
        "env": "manual",
        "analysis_group": "managed_drift",
        "synthetic": True,
        "source_revision": "a" * 40,
        "render_sha256": "b" * 64,
        "status": "observed",
        "stop_reason": "recovery",
        "recovery_status": "observed",
        "censor_seconds": 10,
        "detection_seconds": 2,
        "detection_status": "observed",
        "evidence_seconds": 3,
        "evidence_status": "observed",
        "recovery_seconds": 4,
    }
    base.update(overrides)
    return base


class SummarizeEdgesTest(unittest.TestCase):
    def test_success_counts_observed_censored_and_missing(self):
        rows = [
            row(),
            row(
                run_id="run-2",
                detection_seconds=None,
                detection_status="right_censored",
                evidence_seconds=None,
                evidence_status="unobserved_before_stop",
            ),
        ]
        result = summarize.summarize(rows)
        group = result["groups"][0]
        self.assertEqual(
            group["detection"],
            {
                "observed": 1,
                "right_censored": 1,
                "missing": 0,
                "observed_median_seconds": 2,
            },
        )
        self.assertEqual(group["evidence"]["missing"], 1)
        self.assertFalse(group["complete_time_observations"])

    def test_duplicate_run_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate run identity"):
            summarize.summarize([row(), row()])

    def test_unknown_timing_convention_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown timing convention"):
            summarize.summarize([row(timing_convention="other")])

    def test_unknown_scenario_or_arm_is_rejected(self):
        for change in ({"scenario": "Z"}, {"scenario": "BB"}, {"env": "other"}):
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(ValueError, "unknown scenario/arm"),
            ):
                summarize.summarize([row(**change)])

    def test_analysis_classification_must_match(self):
        with self.assertRaisesRegex(ValueError, "invalid analysis classification"):
            summarize.summarize([row(analysis_group="hpa_control")])

    def test_mixed_timing_conventions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "mixed timing conventions"):
            summarize.summarize([row(), row(run_id="run-2", timing_convention=None)])

    def test_invalid_observation_limit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid observation limit"):
            summarize.summarize([row(censor_seconds=0)])

    def test_missing_endpoint_requires_early_stop_provenance(self):
        with self.assertRaisesRegex(ValueError, "early-stop provenance"):
            summarize.summarize(
                [
                    row(
                        evidence_seconds=None,
                        evidence_status="unobserved_before_stop",
                        stop_reason="timeout",
                    )
                ]
            )

    def test_invalid_event_status_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no imputation allowed"):
            summarize.summarize([row(detection_status="unknown")])

    def test_main_prints_summary_and_reports_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rows.jsonl"
            source.write_text(json.dumps(row()) + "\n")
            with (
                mock.patch.object(sys, "argv", ["summarize.py", "--in", str(source)]),
                mock.patch("sys.stdout") as stdout,
            ):
                self.assertEqual(summarize.main(), 0)
            self.assertIn('"schema_version": 2', stdout.write.call_args_list[0][0][0])
            source.write_text("{broken}\n")
            with (
                mock.patch.object(sys, "argv", ["summarize.py", "--in", str(source)]),
                mock.patch("sys.stderr"),
            ):
                self.assertEqual(summarize.main(), 1)


if __name__ == "__main__":
    unittest.main()
