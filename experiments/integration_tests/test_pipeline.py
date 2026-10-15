"""Exercise actual producer summaries at the analysis boundary, without clients."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.analysis import analyze
from experiments.scripts import apparatus
from experiments.tests.test_apparatus import FakeAdapter


class PipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def emit_and_analyze(self, adapter, scenario="C"):
        record = apparatus.run_experiment(
            adapter, adapter.subject, adapter.env, scenario,
            timeout_s=0.15, poll_interval_s=0.001, run_id="fixture-integration",
        )
        source = self.root / "run.json"
        source.write_text(json.dumps(record, allow_nan=False), encoding="utf-8")
        runs = analyze.load_v2_runs(source, "fixture")
        analyze.write_v2_report(runs, "fixture", self.root / "report")
        report = json.loads((self.root / "report" / "analysis-v2.json").read_text())
        self.assertEqual(report["label"], "SYNTHETIC FIXTURE — NOT EMPIRICAL")
        self.assertFalse(report["exploratory_comparisons"]["performed"])
        return record, report

    def test_complete_emitted_run_is_accepted_by_the_cli(self):
        record, report = self.emit_and_analyze(FakeAdapter())
        self.assertEqual(record["status"], "complete")
        detection = report["groups"][0]["events"]["detection"]
        self.assertEqual(detection["observed_duration_s"]["n"], 1)
        self.assertGreaterEqual(detection["observed_duration_s"]["median"], 0)
        self.assertLess(detection["observed_duration_s"]["median"], 0.15)
        result = subprocess.run(
            [sys.executable, str(ROOT / "experiments/analysis/analyze.py"),
             "--schema-version", "2", "--phase", "fixture", "--in", str(self.root / "run.json"),
             "--out", str(self.root / "cli-report")],
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_baseline_failure_has_no_injection_or_durations(self):
        adapter = FakeAdapter()
        adapter.node_cpu_pct = []
        record, report = self.emit_and_analyze(adapter)
        self.assertEqual(record["status"], "baseline_failed")
        self.assertIsNone(record["t0_mono_s"])
        self.assertEqual(report["groups"][0]["events"]["detection"]["observed_duration_s"]["n"], 0)

    def test_unverified_injection_retains_ack_but_no_response_events(self):
        adapter = FakeAdapter()
        def unverified(scenario):
            raise apparatus.ApparatusError("injection_acceptance_unverified", time.monotonic())
        adapter.inject = unverified
        record, report = self.emit_and_analyze(adapter)
        self.assertEqual(record["status"], "injection_failed")
        self.assertIsNotNone(record["ta_mono_s"])
        self.assertEqual(report["groups"][0]["run_status_counts"]["injection_failed"], 1)

    def test_correction_failure_does_not_create_a_recovery_duration(self):
        adapter = FakeAdapter()
        adapter.correction_error = "external_command_failed"
        record, report = self.emit_and_analyze(adapter)
        self.assertEqual(record["status"], "correction_failed")
        self.assertEqual(report["groups"][0]["events"]["recovery"]["observed_duration_s"]["n"], 0)

    def test_missed_controller_signal_does_not_erase_verified_restoration(self):
        adapter = FakeAdapter(env="gitops")
        adapter.gitops_signal = False
        adapter.auto_restore_after = 3
        record, report = self.emit_and_analyze(adapter)
        self.assertEqual(record["status"], "instrumentation_failed")
        events = report["groups"][0]["events"]
        self.assertEqual(events["detection"]["status_counts"]["right_censored"], 1)
        self.assertEqual(events["evidence"]["status_counts"]["not_evaluable"], 1)
        self.assertEqual(events["recovery"]["observed_duration_s"]["n"], 1)

    def test_censored_endpoints_are_counts_not_zero_times(self):
        adapter = FakeAdapter(env="gitops")
        adapter.gitops_signal = False
        adapter.gitops_evidence = []
        record, report = self.emit_and_analyze(adapter)
        self.assertEqual(record["status"], "timeout")
        for event in report["groups"][0]["events"].values():
            self.assertEqual(event["status_counts"]["right_censored"], 1)
            self.assertIsNone(event["observed_duration_s"]["median"])

    def test_boundary_run_is_not_reported_as_managed_recovery(self):
        record, report = self.emit_and_analyze(FakeAdapter(), "F")
        self.assertEqual(record["status"], "complete")
        self.assertEqual(report["groups"], [])
        recovery = report["visibility_boundary"][0]["events"]["recovery"]
        self.assertEqual(recovery["status_counts"]["not_evaluable"], 1)
        self.assertEqual(recovery["observed_duration_s"]["n"], 0)

    def test_emitted_fixture_cannot_be_read_as_formal_evidence(self):
        self.emit_and_analyze(FakeAdapter())
        with self.assertRaisesRegex(ValueError, "phase"):
            analyze.load_v2_runs(self.root / "run.json", "formal")


if __name__ == "__main__":
    unittest.main()
