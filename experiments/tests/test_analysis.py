import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

import summarize  # noqa: E402


class AnalysisTest(unittest.TestCase):
    def test_v2_summary_keeps_hpa_and_censoring_separate(self):
        rows = [
            {"run_id": "control", "schema_version": 2, "scenario": "A", "env": "gitops",
             "analysis_group": "hpa_control", "synthetic": True, "offline_only": True,
             "source_revision": "fixture", "render_sha256": "fixture",
             "detection_status": "right_censored", "detection_seconds": None,
             "evidence_status": "right_censored", "evidence_seconds": None,
             "recovery_status": "observed", "recovery_seconds": 4, "censor_seconds": 10},
            {"run_id": "drift", "schema_version": 2, "scenario": "B", "env": "gitops",
             "analysis_group": "managed_drift", "synthetic": True, "offline_only": True,
             "source_revision": "fixture", "render_sha256": "fixture",
             "detection_status": "observed", "detection_seconds": 2,
             "evidence_status": "observed", "evidence_seconds": 3,
             "recovery_status": "right_censored", "recovery_seconds": None, "censor_seconds": 10},
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rows.jsonl"
            source.write_text("\n".join(json.dumps(row) for row in rows))
            result = subprocess.run([sys.executable, str(ROOT / "analysis/summarize.py"),
                                     "--in", str(source)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            groups = json.loads(result.stdout)["groups"]
            self.assertEqual(len(groups), 2)
            self.assertEqual(groups[0]["analysis_group"], "hpa_control")
            self.assertEqual(groups[0]["detection"]["right_censored"], 1)
            self.assertIsNone(groups[0]["detection"]["observed_median_seconds"])
            self.assertEqual(groups[1]["recovery"]["right_censored"], 1)
            self.assertFalse(groups[1]["complete_time_observations"])

    def test_v2_summary_counts_missing_endpoints_separately(self):
        row = {
            "run_id": "missing", "schema_version": 2, "scenario": "B",
            "env": "gitops", "analysis_group": "managed_drift",
            "synthetic": True, "source_revision": "fixture",
            "render_sha256": "fixture",
            "detection_status": "unobserved_before_stop",
            "detection_seconds": None,
            "evidence_status": "unobserved_before_stop",
            "evidence_seconds": None,
            "recovery_status": "observed", "recovery_seconds": 4,
            "censor_seconds": 10,
        }
        group = summarize.summarize([row])["groups"][0]
        self.assertEqual(group["detection"]["missing"], 1)
        self.assertEqual(group["detection"]["right_censored"], 0)
        self.assertIsNone(group["detection"]["observed_median_seconds"])
        self.assertFalse(group["complete_time_observations"])

    def test_legacy_analyzer_requires_explicit_historical_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ROOT / "analysis/analyze.py"),
                                     "--in", str(ROOT / "analysis/outputs/mock_runs.csv"),
                                     "--out", directory], capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("historical", result.stderr)


if __name__ == "__main__":
    unittest.main()
