"""Offline tests for the formal sequential batch runner.

No test reaches a cluster. Dry-run tests use the real harness with
`subprocess.run` blocked; live-path tests inject an in-memory runner and never
call `harness.main`.
"""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "live"
sys.path.insert(0, str(LIVE))

import run_matrix  # noqa: E402


def analysis_group(scenario):
    return ("hpa_control" if scenario == "A" else
            "visibility_boundary" if scenario == "F" else "managed_drift")


def make_row(item, status="observed", **overrides):
    row = {
        "schema_version": 2,
        "run_id": overrides.pop("run_id", None),
        "synthetic": False,
        "formal_execution_approved": False,
        "dry_run": False,
        "mutations_executed": 1,
        "env": item["arm"],
        "arm": item["arm"],
        "scenario": item["scenario"],
        "rep": item["rep"],
        "status": status,
        "analysis_group": analysis_group(item["scenario"]),
        "efficacy_eligible": item["scenario"] not in ("A", "F"),
        "source_revision": "a" * 40,
        "render_sha256": "b" * 64,
        "censor_seconds": 30.0,
        "detection_seconds": 1.0,
        "detection_status": "observed",
        "evidence_seconds": 1.5,
        "evidence_status": "observed",
        "recovery_seconds": 2.0,
        "recovery_status": "observed",
        "cleanup_status": "ok",
        "arm_restore_status": "restored",
        "postcondition": {"verified": True},
    }
    row.update(overrides)
    return row


def write_row(out, run_id, row):
    row["run_id"] = run_id
    path = Path(out) / (run_id + ".jsonl")
    path.write_text(json.dumps(row, sort_keys=True) + "\n")
    return path


def fake_runner(statuses=None, cleanup="ok", restore="restored",
                mutate=None):
    calls = []

    def runner(args, item, run_id):
        index = len(calls)
        calls.append(run_id)
        status = statuses[index] if statuses and index < len(statuses) else "observed"
        row = make_row(item, status=status, cleanup_status=cleanup,
                       arm_restore_status=restore)
        if mutate:
            mutate(row)
        write_row(args.out, run_id, row)
        return 0, row, None

    return runner, calls


def run_quiet(args, run_one=None):
    with redirect_stdout(io.StringIO()):
        return run_matrix.run_batch(args, run_one=run_one)


def base_args(out, batch_id, *extra):
    return ["--out", str(out), "--batch-id", batch_id, "--seed", "17", *extra]


def full_args(out, batch_id, arms="gitops imperative",
              scenarios="A-G", reps="15", *extra):
    return base_args(out, batch_id, "--arms", *arms.split(),
                     "--scenarios", scenarios, "--reps", reps, *extra)


def live_args(out, batch_id, arms="gitops imperative",
              scenarios="A-G", reps="15", *extra):
    return full_args(
        out, batch_id, arms, scenarios, reps, "--live",
        "--confirm-single-stack", "--namespace", "exp-a",
        "--app", "invenio-bootstrap", "--source-revision", "a" * 40,
        "--render-sha256", "b" * 64, *extra)


class PlanTests(unittest.TestCase):
    def test_seed_reproduces_order_and_both_arms_share_scenarios(self):
        first = run_matrix.build_plan(
            ["gitops", "imperative"], list("ABCDEFG"), 15, 123)
        second = run_matrix.build_plan(
            ["gitops", "imperative"], list("ABCDEFG"), 15, 123)
        other = run_matrix.build_plan(
            ["gitops", "imperative"], list("ABCDEFG"), 15, 124)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(len(first["runs"]), 210)
        for arm in first["arm_order"]:
            arm_runs = [run for run in first["runs"] if run["arm"] == arm]
            seen = []
            for run in arm_runs:
                if run["scenario"] not in seen:
                    seen.append(run["scenario"])
            self.assertEqual(seen, first["scenario_order"])
            for scenario in first["scenario_order"]:
                reps = [run["rep"] for run in arm_runs
                        if run["scenario"] == scenario]
                self.assertEqual(reps, list(range(1, 16)))

    def test_reps_one_to_ten_are_r2_and_eleven_to_fifteen_are_r1(self):
        plan = run_matrix.build_plan(["gitops"], ["B"], 15, 5)
        phases = [run["phase"] for run in plan["runs"]]
        self.assertEqual(phases, ["R2"] * 10 + ["R1"] * 5)
        self.assertEqual(run_matrix.phase_for(10), "R2")
        self.assertEqual(run_matrix.phase_for(11), "R1")
        with self.assertRaises(ValueError):
            run_matrix.phase_for(16)

    def test_plan_keeps_one_stack_and_records_dry_run_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(live_args(
                directory, "meta", "gitops", "A", "1"))
            code = run_quiet(args, run_one=fake_runner()[0])
            self.assertEqual(code, 0)
            manifest = json.loads(
                (Path(directory) / "meta.manifest.json").read_text())
            self.assertFalse(manifest["stack_isolated"])
            self.assertEqual(manifest["r3_status"], "not_measured")
            self.assertFalse(manifest["formal_execution_approved"])
            self.assertEqual(manifest["counts"]["total"], 1)
            self.assertEqual(manifest["seed"], 17)
            self.assertIn(manifest["arm_order"][0], run_matrix.ARMS)


class DryRunTests(unittest.TestCase):
    def test_dry_run_is_zero_mutation_and_writes_analysis_ready_summary(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = temporary.name
        with mock.patch("harness.subprocess.run") as run, \
                mock.patch("harness.Kubectl", side_effect=AssertionError), \
                mock.patch("sys.stdout", new_callable=io.StringIO), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            code = run_matrix.main([
                "--out", directory, "--batch-id", "dry", "--seed", "3",
                "--arms", "gitops", "imperative", "--scenarios", "AB",
                "--reps", "2",
            ])
        self.assertEqual(code, 0)
        run.assert_not_called()
        out = Path(directory)
        manifest = json.loads((out / "dry.manifest.json").read_text())
        self.assertEqual(manifest["state"], "complete")
        self.assertEqual(manifest["mode"], "dry_run")
        self.assertEqual(manifest["counts"]["by_status"], {"dry_run": 8})
        self.assertFalse(manifest["formal_execution_approved"])
        self.assertFalse(manifest["stack_isolated"])
        self.assertEqual(manifest["r3_status"], "not_measured")
        self.assertEqual(len(manifest["arm_order"]), 2)
        self.assertEqual(sorted(manifest["scenario_order"]), ["A", "B"])
        rows = [json.loads(line) for line in
                (out / "dry.rows.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 8)
        for row in rows:
            self.assertEqual(row["status"], "dry_run")
            self.assertEqual(row["mutations_executed"], 0)
            self.assertIsNone(row["detection_seconds"])
            self.assertFalse(row["formal_execution_approved"])
            self.assertFalse(row["stack_isolated"])
            self.assertEqual(row["r3_status"], "not_measured")
            self.assertIn(row["batch_phase"], ("R1", "R2"))
        self.assertEqual((out / "dry.analysis.jsonl").read_text(), "")
        summary = json.loads((out / "dry.summary.json").read_text())
        self.assertEqual(summary["analysis_rows"], 0)
        self.assertEqual(len(summary["exclusions"]), 8)
        self.assertEqual(summary["exclusions"][0]["reason"], "status:dry_run")

    def test_dry_run_rejects_production_like(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as raised:
                run_matrix.parse_args([
                    "--out", directory, "--production-like"])
            self.assertEqual(raised.exception.code, 2)


class BatchSafetyTests(unittest.TestCase):
    def test_live_requires_confirm_explicit_namespace_and_app(self):
        with tempfile.TemporaryDirectory() as directory:
            cases = [
                ["--live", "--namespace", "exp-a", "--app", "app"],
                ["--live", "--confirm-single-stack", "--app", "app"],
                ["--live", "--confirm-single-stack", "--namespace", "exp-a"],
            ]
            for extra in cases:
                with self.subTest(extra=extra):
                    args = run_matrix.parse_args([
                        "--out", directory, "--batch-id", "x",
                        "--arms", "gitops", "--scenarios", "A", "--reps", "1",
                        *extra])
                    with self.assertRaises(run_matrix.BatchSafetyError):
                        run_matrix.validate_batch_args(args)

    def test_production_like_metadata_needs_the_explicit_flag(self):
        with tempfile.TemporaryDirectory() as unapproved, \
                tempfile.TemporaryDirectory() as approved:
            self.assertEqual(run_quiet(
                run_matrix.parse_args(live_args(
                    unapproved, "plain", "gitops", "A", "1")),
                run_one=fake_runner()[0]), 0)
            manifest = json.loads(
                (Path(unapproved) / "plain.manifest.json").read_text())
            row = json.loads(
                (Path(unapproved) / "plain.rows.jsonl").read_text())
            self.assertFalse(manifest["production_like"])
            self.assertFalse(manifest["formal_execution_approved"])
            self.assertFalse(row["production_like"])
            self.assertFalse(row["formal_execution_approved"])
            self.assertFalse(row["stack_isolated"])
            self.assertEqual(row["r3_status"], "not_measured")

            self.assertEqual(run_quiet(
                run_matrix.parse_args(live_args(
                    approved, "approved", "gitops", "A", "1",
                    "--production-like")),
                run_one=fake_runner()[0]), 0)
            manifest = json.loads(
                (Path(approved) / "approved.manifest.json").read_text())
            row = json.loads(
                (Path(approved) / "approved.rows.jsonl").read_text())
            self.assertTrue(manifest["production_like"])
            self.assertTrue(manifest["formal_execution_approved"])
            self.assertTrue(row["production_like"])
            self.assertTrue(row["formal_execution_approved"])
            self.assertFalse(row["stack_isolated"])
            self.assertEqual(row["r3_status"], "not_measured")


class StopAndResumeTests(unittest.TestCase):
    def _stop_args(self, out, batch_id="stop", scenarios="ABC", *extra):
        return run_matrix.parse_args(live_args(
            out, batch_id, "gitops imperative", scenarios, "1", *extra))

    def test_invalid_injection_stops_and_preserves_run_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, calls = fake_runner(statuses=["invalid_injection"])
            code = run_quiet(
                self._stop_args(directory), run_one=runner)
            self.assertEqual(code, 1)
            self.assertEqual(len(calls), 1)
            out = Path(directory)
            manifest = json.loads((out / "stop.manifest.json").read_text())
            self.assertEqual(manifest["state"], "stopped")
            self.assertEqual(manifest["stop_reason"], "invalid_injection")
            self.assertEqual(manifest["stop_run_id"], calls[0])
            self.assertEqual(manifest["runs"][0]["status"], "invalid_injection")
            self.assertEqual(manifest["runs"][1]["status"], "pending")
            self.assertEqual(manifest["counts"]["pending"], 5)
            failed = out / (calls[0] + ".jsonl")
            self.assertEqual(json.loads(failed.read_text())["status"],
                             "invalid_injection")
            summary = json.loads((out / "stop.summary.json").read_text())
            reasons = {item["run_id"]: item["reason"]
                       for item in summary["exclusions"]}
            self.assertEqual(reasons[calls[0]], "status:invalid_injection")
            self.assertIn("not_run", reasons.values())

    def test_instrumentation_and_reset_failures_stop_the_batch(self):
        for status in ("instrumentation_failure", "reset_failure"):
            with self.subTest(status=status), \
                    tempfile.TemporaryDirectory() as directory:
                runner, calls = fake_runner(statuses=[status])
                code = run_quiet(
                    self._stop_args(directory), run_one=runner)
                self.assertEqual(code, 1)
                self.assertEqual(len(calls), 1)
                manifest = json.loads(
                    (Path(directory) / "stop.manifest.json").read_text())
                self.assertEqual(manifest["state"], "stopped")
                self.assertEqual(manifest["stop_reason"], status)
                self.assertEqual(manifest["runs"][0]["status"], status)

    def test_cleanup_and_arm_restore_failures_stop_the_batch(self):
        for cleanup, restore, reason in (
                ("failed", "restored", "cleanup_failure"),
                ("ok", "failed", "arm_restore_failure")):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                runner, calls = fake_runner(cleanup=cleanup, restore=restore)
                code = run_quiet(
                    self._stop_args(directory), run_one=runner)
                self.assertEqual(code, 1)
                self.assertEqual(len(calls), 1)
                manifest = json.loads(
                    (Path(directory) / "stop.manifest.json").read_text())
                self.assertEqual(manifest["state"], "stopped")
                self.assertEqual(manifest["stop_reason"], reason)
                self.assertEqual(manifest["runs"][0]["status"], "observed")
                summary = json.loads(
                    (Path(directory) / "stop.summary.json").read_text())
                self.assertIn(reason, [item["reason"] for item in
                                       summary["exclusions"]])
                self.assertEqual(summary["analysis_rows"], 0)
                self.assertEqual(summary["phases"]["R2"]["observed"], 0)
                self.assertEqual(summary["phases"]["R2"]["excluded"], 1)

    def test_resume_skips_terminal_runs_and_never_rewrites_them(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            args = self._stop_args(directory)
            first_runner, first_calls = fake_runner(
                statuses=["invalid_injection"])
            self.assertEqual(run_quiet(args, run_one=first_runner), 1)
            failed_path = out / (first_calls[0] + ".jsonl")
            failed_before = failed_path.read_text()
            manifest_before = (out / "stop.manifest.json").read_text()

            second_runner, second_calls = fake_runner()
            resume_args = run_matrix.parse_args(live_args(
                directory, "stop", "gitops imperative", "ABC", "1",
                "--resume"))
            code = run_quiet(resume_args, run_one=second_runner)
            self.assertEqual(code, 1)
            self.assertEqual(len(first_calls), 1)
            self.assertNotIn(first_calls[0], second_calls)
            self.assertEqual(len(second_calls), 5)
            self.assertEqual(failed_path.read_text(), failed_before)
            manifest = json.loads((out / "stop.manifest.json").read_text())
            self.assertNotEqual(
                (out / "stop.manifest.json").read_text(), manifest_before)
            self.assertEqual(manifest["state"], "stopped")
            self.assertEqual(manifest["stop_reason"], "invalid_injection")
            self.assertEqual(manifest["runs"][0]["status"], "invalid_injection")
            self.assertEqual([run["status"] for run in manifest["runs"][1:]],
                             ["observed"] * 5)
            self.assertFalse(manifest["formal_execution_approved"])

            # A plain rerun must not overwrite the preserved batch.
            calls_before = list(second_calls)
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(run_matrix.main(live_args(
                    directory, "stop", "gitops imperative", "ABC", "1")), 2)
            self.assertEqual(second_calls, calls_before)

    def test_resume_rejects_tampered_manifest_and_pending_output(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            runner, calls = fake_runner(statuses=["invalid_injection"])
            args = self._stop_args(directory)
            self.assertEqual(run_quiet(args, run_one=runner), 1)
            manifest_path = out / "stop.manifest.json"
            manifest = json.loads(manifest_path.read_text())
            pending_id = manifest["runs"][1]["run_id"]

            pending_output = out / (pending_id + ".jsonl")
            pending_output.write_text("{}\n")
            resume_args = run_matrix.parse_args(live_args(
                directory, "stop", "gitops imperative", "ABC", "1",
                "--resume"))
            with self.assertRaises(run_matrix.BatchSafetyError):
                run_quiet(resume_args, run_one=fake_runner()[0])
            pending_output.unlink()

            manifest["seed"] = 999
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(run_matrix.BatchSafetyError):
                run_quiet(resume_args, run_one=fake_runner()[0])

    def test_resume_rejects_missing_completed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            runner, calls = fake_runner()
            args = run_matrix.parse_args(live_args(
                directory, "kept", "gitops imperative", "A", "1"))
            self.assertEqual(run_quiet(args, run_one=runner), 0)
            (out / (calls[0] + ".jsonl")).unlink()
            resume_args = run_matrix.parse_args(live_args(
                directory, "kept", "gitops imperative", "A", "1", "--resume"))
            with self.assertRaises(run_matrix.BatchSafetyError):
                run_quiet(resume_args, run_one=fake_runner()[0])

    def test_resume_without_batch_id_uses_the_single_existing_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(live_args(
                directory, "solo", "gitops", "A", "1"))
            self.assertEqual(run_quiet(
                args, run_one=fake_runner()[0]), 0)
            resume_args = run_matrix.parse_args([
                "--out", directory, "--seed", "17", "--arms", "gitops",
                "--scenarios", "A", "--reps", "1", "--live",
                "--confirm-single-stack", "--namespace", "exp-a",
                "--app", "invenio-bootstrap",
                "--source-revision", "a" * 40,
                "--render-sha256", "b" * 64, "--resume",
            ])
            self.assertEqual(run_quiet(
                resume_args, run_one=fake_runner()[0]), 0)


class AnalysisOutputTests(unittest.TestCase):
    def test_rows_map_to_summarize_and_csv_without_losing_arm(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(live_args(
                directory, "analysis", "gitops imperative", "B", "15",
                "--production-like"))
            runner, calls = fake_runner()
            self.assertEqual(run_quiet(args, run_one=runner), 0)
            out = Path(directory)
            summary = json.loads((out / "analysis.summary.json").read_text())
            self.assertEqual(summary["phases"]["R2"]["planned"], 20)
            self.assertEqual(summary["phases"]["R1"]["planned"], 10)
            self.assertEqual(summary["phases"]["R2"]["observed"], 20)
            self.assertEqual(summary["phases"]["R1"]["observed"], 10)
            self.assertEqual(summary["analysis_rows"], 30)
            self.assertEqual(
                summary["censoring"]["R2"]["detection"],
                {"observed": 20, "right_censored": 0,
                 "unobserved_before_stop": 0})

            result = subprocess.run(
                [sys.executable, str(ROOT / "analysis/summarize.py"),
                 "--in", str(out / "analysis.analysis.jsonl")],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(len(payload["groups"]), 2)
            self.assertEqual({group["env"] for group in payload["groups"]},
                             {"manual", "gitops"})
            self.assertEqual(sum(group["runs"] for group in payload["groups"]),
                             30)

            import csv
            with (out / "analysis.csv").open(newline="") as source:
                csv_rows = list(csv.DictReader(source))
            self.assertEqual(len(csv_rows), 30)
            self.assertEqual({row["env"] for row in csv_rows},
                             {"manual", "gitops"})
            self.assertTrue(all(row["skenario"] == "B" for row in csv_rows))

    def test_summary_counts_censoring_and_exclusions(self):
        with tempfile.TemporaryDirectory() as directory:
            def mutate(row):
                row["recovery_seconds"] = None
                row["recovery_status"] = "right_censored"

            args = run_matrix.parse_args(live_args(
                directory, "censor", "gitops imperative", "B", "1"))
            runner, calls = fake_runner(mutate=mutate)
            self.assertEqual(run_quiet(args, run_one=runner), 0)
            summary = json.loads(
                (Path(directory) / "censor.summary.json").read_text())
            self.assertEqual(summary["exclusions"], [])
            self.assertEqual(summary["censoring"]["R2"]["recovery"],
                             {"observed": 0, "right_censored": 2,
                              "unobserved_before_stop": 0})
            self.assertEqual(summary["phases"]["R2"]["observed"], 2)


class TokenSafetyTests(unittest.TestCase):
    def test_token_never_appears_in_logs_or_batch_artifacts(self):
        token = "tok-super-secret-123"
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {"INVENIO_TOKEN": token}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            args = run_matrix.parse_args(live_args(
                directory, "secret", "gitops imperative", "A", "1",
                "--production-like"))
            self.assertEqual(run_quiet(
                args, run_one=fake_runner()[0]), 0)
            texts = [stdout.getvalue(), stderr.getvalue()]
            for path in Path(directory).iterdir():
                if path.is_file():
                    texts.append(path.read_text())
            for text in texts:
                self.assertNotIn(token, text)

    def test_runner_exception_is_redacted_and_stops_the_batch(self):
        token = "tok-super-secret-456"
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {"INVENIO_TOKEN": token}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            def runner(args, item, run_id):
                raise RuntimeError("failed with " + token)

            args = run_matrix.parse_args(live_args(
                directory, "boom", "gitops imperative", "A", "1"))
            self.assertEqual(run_quiet(args, run_one=runner), 1)
            manifest = json.loads(
                (Path(directory) / "boom.manifest.json").read_text())
            self.assertEqual(manifest["state"], "stopped")
            self.assertNotIn(token, (Path(directory) / "boom.manifest.json").read_text())
            texts = [stdout.getvalue(), stderr.getvalue()]
            for path in Path(directory).iterdir():
                if path.is_file():
                    texts.append(path.read_text())
            for text in texts:
                self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
