"""Offline tests for the formal sequential batch runner.

No test reaches a cluster. Dry-run tests use the real harness with
`subprocess.run` blocked; live-path tests inject an in-memory runner and never
call `harness.main`.
"""

import argparse
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "live"
sys.path.insert(0, str(LIVE))

import run_matrix  # noqa: E402

RENDER_REVISION = "a" * 40


def render_bundle(namespace="exp-a", revision=RENDER_REVISION, image="ghcr.io/example/invenio:1"):
    return {
        "format": "invenio-frozen-render-v1",
        "source_revision": revision,
        "objects": [
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": "invenio-web", "namespace": namespace},
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": "web",
                                    "image": image,
                                    "envFrom": [
                                        {"configMapRef": {"name": "invenio-app-config-abc123"}}
                                    ],
                                    "resources": {
                                        "requests": {"cpu": "250m", "memory": "512Mi"},
                                        "limits": {"cpu": "1", "memory": "2Gi"},
                                    },
                                }
                            ]
                        }
                    }
                },
            },
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": "invenio-app-config-abc123",
                    "namespace": namespace,
                },
                "data": {"INSTANCE_TAGLINE": "frozen"},
            },
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": "invenio-web", "namespace": namespace},
                "spec": {
                    "selector": {"app.kubernetes.io/name": "invenio-web"},
                    "ports": [{"port": 8000, "targetPort": "http"}],
                },
            },
            {
                "apiVersion": "bitnami.com/v1alpha1",
                "kind": "SealedSecret",
                "metadata": {
                    "name": "invenio-app-secrets",
                    "namespace": namespace,
                },
                "spec": {"encryptedData": {"key": "SECRET-MUST-NOT-LEAK"}},
            },
        ],
    }


def write_render(directory, bundle=None):
    bundle = render_bundle() if bundle is None else bundle
    path = Path(directory) / "render.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(bundle, sort_keys=True).encode()
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def render_args(directory, bundle=None):
    path, digest = write_render(directory, bundle)
    return [
        "--render-file",
        str(path),
        "--source-revision",
        RENDER_REVISION,
        "--render-sha256",
        digest,
    ]


def analysis_group(scenario):
    return (
        "hpa_control"
        if scenario == "A"
        else "visibility_boundary"
        if scenario == "F"
        else "managed_drift"
    )


def make_row(item, status="observed", **overrides):
    row = {
        "schema_version": 2,
        "run_id": overrides.pop("run_id", None),
        "synthetic": False,
        "formal_execution_approved": False,
        "timing_convention": run_matrix.TIMING_CONVENTION,
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
        "window_completed": True,
        "window_end_mono": 130.0,
        "t0_mono": 100.0,
        "t_a_mono": 100.1,
        "t_d_mono": 101.0,
        "t_e_mono": 101.5,
        "t_r_mono": 102.0,
        "t_r_first_mono": 102.0,
        "t_r_confirmed_mono": 103.0,
        "recovery_confirmation": "confirmed",
        "stop_reason": "recovery",
    }
    row.update(overrides)
    return row


def write_row(out, run_id, row):
    row["run_id"] = run_id
    path = Path(out) / (run_id + ".jsonl")
    path.write_text(json.dumps(row, sort_keys=True) + "\n")
    return path


def fake_runner(statuses=None, cleanup="ok", restore="restored", mutate=None):
    calls = []

    def runner(args, item, run_id):
        index = len(calls)
        calls.append(run_id)
        status = statuses[index] if statuses and index < len(statuses) else "observed"
        row = make_row(
            item,
            status=status,
            cleanup_status=cleanup,
            arm_restore_status=restore,
            source_revision=getattr(args, "source_revision", None) or "a" * 40,
            render_sha256=getattr(args, "render_sha256", None) or "b" * 64,
        )
        if status == "baseline_failure":
            row["mutations_executed"] = 0
        if mutate:
            mutate(row)
        write_row(args.out, run_id, row)
        return 0, row, None

    return runner, calls


def run_quiet(args, run_one=None, sleep=None):
    with redirect_stdout(io.StringIO()):
        return run_matrix.run_batch(args, run_one=run_one, sleep=sleep or (lambda seconds: None))


def base_args(out, batch_id, *extra):
    return ["--out", str(out), "--batch-id", batch_id, "--seed", "17", *extra]


def full_args(out, batch_id, arms="gitops imperative", scenarios="A-G", reps="15", *extra):
    return base_args(
        out, batch_id, "--arms", *arms.split(), "--scenarios", scenarios, "--reps", reps, *extra
    )


def live_args(out, batch_id, arms="gitops imperative", scenarios="A-G", reps="15", *extra):
    return full_args(
        out,
        batch_id,
        arms,
        scenarios,
        reps,
        "--live",
        "--confirm-single-stack",
        "--namespace",
        "exp-a",
        "--app",
        "invenio-bootstrap",
        *render_args(out),
        *extra,
    )


class PlanTests(unittest.TestCase):
    def test_seed_reproduces_order_and_both_arms_share_scenarios(self):
        first = run_matrix.build_plan(["gitops", "imperative"], list("ABCDEFG"), 15, 123)
        second = run_matrix.build_plan(["gitops", "imperative"], list("ABCDEFG"), 15, 123)
        other = run_matrix.build_plan(["gitops", "imperative"], list("ABCDEFG"), 15, 124)
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
                reps = [run["rep"] for run in arm_runs if run["scenario"] == scenario]
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
            args = run_matrix.parse_args(live_args(directory, "meta", "gitops", "A", "1"))
            code = run_quiet(args, run_one=fake_runner()[0])
            self.assertEqual(code, 0)
            manifest = json.loads((Path(directory) / "meta.manifest.json").read_text())
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
        with (
            mock.patch("harness.subprocess.run") as run,
            mock.patch("harness.Kubectl", side_effect=AssertionError),
            mock.patch("sys.stdout", new_callable=io.StringIO),
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            code = run_matrix.main(
                [
                    "--out",
                    directory,
                    "--batch-id",
                    "dry",
                    "--seed",
                    "3",
                    "--arms",
                    "gitops",
                    "imperative",
                    "--scenarios",
                    "AB",
                    "--reps",
                    "2",
                ]
            )
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
        self.assertEqual(manifest["timing_convention"], run_matrix.TIMING_CONVENTION)
        self.assertEqual(len(manifest["arm_order"]), 2)
        self.assertEqual(sorted(manifest["scenario_order"]), ["A", "B"])
        rows = [json.loads(line) for line in (out / "dry.rows.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 8)
        for row in rows:
            self.assertEqual(row["status"], "dry_run")
            self.assertEqual(row["mutations_executed"], 0)
            self.assertIsNone(row["detection_seconds"])
            self.assertFalse(row["formal_execution_approved"])
            self.assertFalse(row["stack_isolated"])
            self.assertEqual(row["r3_status"], "not_measured")
            self.assertEqual(row["timing_convention"], run_matrix.TIMING_CONVENTION)
            self.assertIn(row["batch_phase"], ("R1", "R2"))
        self.assertEqual((out / "dry.analysis.jsonl").read_text(), "")
        summary = json.loads((out / "dry.summary.json").read_text())
        self.assertEqual(summary["analysis_rows"], 0)
        self.assertEqual(len(summary["exclusions"]), 8)
        self.assertEqual(summary["exclusions"][0]["reason"], "status:dry_run")

    def test_dry_run_rejects_production_like(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            with self.assertRaises(SystemExit) as raised:
                run_matrix.parse_args(["--out", directory, "--production-like"])
            self.assertEqual(raised.exception.code, 2)


class TimingConventionTests(unittest.TestCase):
    def test_new_batch_records_the_convention_in_manifest_rows_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                run_quiet(
                    run_matrix.parse_args(live_args(directory, "timed", "gitops", "A", "1")),
                    run_one=fake_runner()[0],
                ),
                0,
            )
            manifest = json.loads((Path(directory) / "timed.manifest.json").read_text())
            rows = [
                json.loads(line)
                for line in (Path(directory) / "timed.rows.jsonl").read_text().splitlines()
            ]
            summary = json.loads((Path(directory) / "timed.summary.json").read_text())
            self.assertEqual(manifest["timing_convention"], run_matrix.TIMING_CONVENTION)
            self.assertTrue(rows)
            self.assertTrue(
                all(row["timing_convention"] == run_matrix.TIMING_CONVENTION for row in rows)
            )
            self.assertEqual(summary["timing_convention"], run_matrix.TIMING_CONVENTION)

    def test_resume_rejects_missing_or_changed_convention(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            args = run_matrix.parse_args(live_args(directory, "timed", "gitops", "A", "1"))
            self.assertEqual(run_quiet(args, run_one=fake_runner()[0]), 0)
            manifest_path = out / "timed.manifest.json"
            original = json.loads(manifest_path.read_text())
            resume = run_matrix.parse_args(
                live_args(directory, "timed", "gitops", "A", "1", "--resume")
            )

            changed = dict(original)
            changed["timing_convention"] = "legacy-observation-v0"
            manifest_path.write_text(json.dumps(changed))
            with self.assertRaises(run_matrix.BatchSafetyError):
                run_quiet(resume, run_one=fake_runner()[0])

            missing = dict(original)
            del missing["timing_convention"]
            manifest_path.write_text(json.dumps(missing))
            with self.assertRaises(run_matrix.BatchSafetyError):
                run_quiet(resume, run_one=fake_runner()[0])

    def test_annotation_rejects_an_unsupported_row_convention(self):
        args = run_matrix.parse_args(live_args(tempfile.gettempdir(), "timed", "gitops", "A", "1"))
        entry = {"index": 0, "phase": "R2"}
        for marker in (None, "legacy-observation-v0"):
            with self.subTest(marker=marker):
                row = {"run_id": "timed-gitops-A-r01"}
                if marker is not None:
                    row["timing_convention"] = marker
                with self.assertRaises(run_matrix.BatchSafetyError):
                    run_matrix.annotate_row(row, entry, args, "timed")


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
                    args = run_matrix.parse_args(
                        [
                            "--out",
                            directory,
                            "--batch-id",
                            "x",
                            "--arms",
                            "gitops",
                            "--scenarios",
                            "A",
                            "--reps",
                            "1",
                            *extra,
                        ]
                    )
                    with self.assertRaises(run_matrix.BatchSafetyError):
                        run_matrix.validate_batch_args(args)

    def test_production_like_metadata_needs_the_explicit_flag(self):
        with tempfile.TemporaryDirectory() as unapproved, tempfile.TemporaryDirectory() as approved:
            self.assertEqual(
                run_quiet(
                    run_matrix.parse_args(live_args(unapproved, "plain", "gitops", "A", "1")),
                    run_one=fake_runner()[0],
                ),
                0,
            )
            manifest = json.loads((Path(unapproved) / "plain.manifest.json").read_text())
            row = json.loads((Path(unapproved) / "plain.rows.jsonl").read_text())
            self.assertFalse(manifest["production_like"])
            self.assertFalse(manifest["formal_execution_approved"])
            self.assertFalse(row["production_like"])
            self.assertFalse(row["formal_execution_approved"])
            self.assertFalse(row["stack_isolated"])
            self.assertEqual(row["r3_status"], "not_measured")

            self.assertEqual(
                run_quiet(
                    run_matrix.parse_args(
                        live_args(approved, "approved", "gitops", "A", "1", "--production-like")
                    ),
                    run_one=fake_runner()[0],
                ),
                0,
            )
            manifest = json.loads((Path(approved) / "approved.manifest.json").read_text())
            row = json.loads((Path(approved) / "approved.rows.jsonl").read_text())
            self.assertTrue(manifest["production_like"])
            self.assertTrue(manifest["formal_execution_approved"])
            self.assertTrue(row["production_like"])
            self.assertTrue(row["formal_execution_approved"])
            self.assertFalse(row["stack_isolated"])
            self.assertEqual(row["r3_status"], "not_measured")


class DeclarationBatchTests(unittest.TestCase):
    def test_live_batch_requires_a_render_bundle_before_any_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(
                [
                    "--out",
                    directory,
                    "--batch-id",
                    "no-render",
                    "--seed",
                    "17",
                    "--arms",
                    "gitops",
                    "--scenarios",
                    "A",
                    "--reps",
                    "1",
                    "--live",
                    "--confirm-single-stack",
                    "--namespace",
                    "exp-a",
                    "--app",
                    "invenio-bootstrap",
                    "--source-revision",
                    "a" * 40,
                    "--render-sha256",
                    "b" * 64,
                ]
            )
            runner, calls = fake_runner()
            with self.assertRaises(run_matrix.BatchSafetyError):
                run_quiet(args, run_one=runner)
            self.assertEqual(calls, [])

    def test_live_batch_rejects_a_tampered_render_before_any_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _ = write_render(directory)
            args = run_matrix.parse_args(
                [
                    "--out",
                    directory,
                    "--batch-id",
                    "tampered",
                    "--seed",
                    "17",
                    "--arms",
                    "gitops",
                    "--scenarios",
                    "A",
                    "--reps",
                    "1",
                    "--live",
                    "--confirm-single-stack",
                    "--namespace",
                    "exp-a",
                    "--app",
                    "invenio-bootstrap",
                    "--render-file",
                    str(path),
                    "--source-revision",
                    "a" * 40,
                    "--render-sha256",
                    "0" * 64,
                ]
            )
            runner, calls = fake_runner()
            with self.assertRaises(run_matrix.BatchSafetyError):
                run_quiet(args, run_one=runner)
            self.assertEqual(calls, [])

    def test_resume_rejects_changed_render_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            argv = live_args(directory, "changed", "gitops", "A", "1")
            args = run_matrix.parse_args(argv)
            self.assertEqual(run_quiet(args, run_one=fake_runner()[0]), 0)
            manifest_before = (out / "changed.manifest.json").read_text()
            path = Path(argv[argv.index("--render-file") + 1])
            changed = json.dumps(
                render_bundle(image="ghcr.io/example/invenio:other"), sort_keys=True
            ).encode()
            path.write_bytes(changed)
            resume = run_matrix.parse_args([*argv, "--resume"])
            with self.assertRaises(run_matrix.BatchSafetyError):
                run_quiet(resume, run_one=fake_runner()[0])
            self.assertEqual((out / "changed.manifest.json").read_text(), manifest_before)

    def test_declaration_identity_reaches_manifest_retries_and_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            args = run_matrix.parse_args(live_args(directory, "identity", "gitops", "A", "1"))
            runner, calls = fake_runner(statuses=["baseline_failure", "observed"])
            self.assertEqual(run_quiet(args, run_one=runner), 0)
            manifest = json.loads((out / "identity.manifest.json").read_text())
            self.assertEqual(manifest["source_revision"], RENDER_REVISION)
            self.assertEqual(manifest["render_sha256"], args.render_sha256)
            rows = [
                json.loads(line) for line in (out / "identity.rows.jsonl").read_text().splitlines()
            ]
            self.assertEqual([row["run_id"] for row in rows], calls)
            for row in rows:
                self.assertEqual(row["source_revision"], RENDER_REVISION)
                self.assertEqual(row["render_sha256"], args.render_sha256)


class StopAndResumeTests(unittest.TestCase):
    def _stop_args(self, out, batch_id="stop", scenarios="ABC", *extra):
        return run_matrix.parse_args(
            live_args(out, batch_id, "gitops imperative", scenarios, "1", *extra)
        )

    def test_invalid_injection_stops_and_preserves_run_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, calls = fake_runner(statuses=["invalid_injection"])
            code = run_quiet(self._stop_args(directory), run_one=runner)
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
            self.assertEqual(json.loads(failed.read_text())["status"], "invalid_injection")
            summary = json.loads((out / "stop.summary.json").read_text())
            reasons = {item["run_id"]: item["reason"] for item in summary["exclusions"]}
            self.assertEqual(reasons[calls[0]], "status:invalid_injection")
            self.assertIn("not_run", reasons.values())

    def test_instrumentation_and_reset_failures_stop_the_batch(self):
        for status in ("instrumentation_failure", "reset_failure"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                runner, calls = fake_runner(statuses=[status])
                code = run_quiet(self._stop_args(directory), run_one=runner)
                self.assertEqual(code, 1)
                self.assertEqual(len(calls), 1)
                manifest = json.loads((Path(directory) / "stop.manifest.json").read_text())
                self.assertEqual(manifest["state"], "stopped")
                self.assertEqual(manifest["stop_reason"], status)
                self.assertEqual(manifest["runs"][0]["status"], status)

    def test_cleanup_and_arm_restore_failures_stop_the_batch(self):
        for cleanup, restore, reason in (
            ("failed", "restored", "cleanup_failure"),
            ("ok", "failed", "arm_restore_failure"),
        ):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                runner, calls = fake_runner(cleanup=cleanup, restore=restore)
                code = run_quiet(self._stop_args(directory), run_one=runner)
                self.assertEqual(code, 1)
                self.assertEqual(len(calls), 1)
                manifest = json.loads((Path(directory) / "stop.manifest.json").read_text())
                self.assertEqual(manifest["state"], "stopped")
                self.assertEqual(manifest["stop_reason"], reason)
                self.assertEqual(manifest["runs"][0]["status"], "observed")
                summary = json.loads((Path(directory) / "stop.summary.json").read_text())
                self.assertIn(reason, [item["reason"] for item in summary["exclusions"]])
                self.assertEqual(summary["analysis_rows"], 0)
                self.assertEqual(summary["phases"]["R2"]["observed"], 0)
                self.assertEqual(summary["phases"]["R2"]["excluded"], 1)

    def test_resume_skips_terminal_runs_and_never_rewrites_them(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            args = self._stop_args(directory)
            first_runner, first_calls = fake_runner(statuses=["invalid_injection"])
            self.assertEqual(run_quiet(args, run_one=first_runner), 1)
            failed_path = out / (first_calls[0] + ".jsonl")
            failed_before = failed_path.read_text()
            manifest_before = (out / "stop.manifest.json").read_text()

            second_runner, second_calls = fake_runner()
            resume_args = run_matrix.parse_args(
                live_args(directory, "stop", "gitops imperative", "ABC", "1", "--resume")
            )
            code = run_quiet(resume_args, run_one=second_runner)
            self.assertEqual(code, 1)
            self.assertEqual(len(first_calls), 1)
            self.assertNotIn(first_calls[0], second_calls)
            self.assertEqual(len(second_calls), 5)
            self.assertEqual(failed_path.read_text(), failed_before)
            manifest = json.loads((out / "stop.manifest.json").read_text())
            self.assertNotEqual((out / "stop.manifest.json").read_text(), manifest_before)
            self.assertEqual(manifest["state"], "stopped")
            self.assertEqual(manifest["stop_reason"], "invalid_injection")
            self.assertEqual(manifest["runs"][0]["status"], "invalid_injection")
            self.assertEqual([run["status"] for run in manifest["runs"][1:]], ["observed"] * 5)
            self.assertFalse(manifest["formal_execution_approved"])

            # A plain rerun must not overwrite the preserved batch.
            calls_before = list(second_calls)
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(
                    run_matrix.main(live_args(directory, "stop", "gitops imperative", "ABC", "1")),
                    2,
                )
            self.assertEqual(second_calls, calls_before)

    def test_resume_rejects_tampered_manifest_and_pending_output(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            runner, _calls = fake_runner(statuses=["invalid_injection"])
            args = self._stop_args(directory)
            self.assertEqual(run_quiet(args, run_one=runner), 1)
            manifest_path = out / "stop.manifest.json"
            manifest = json.loads(manifest_path.read_text())
            pending_id = manifest["runs"][1]["run_id"]

            pending_output = out / (pending_id + ".jsonl")
            pending_output.write_text("{}\n")
            resume_args = run_matrix.parse_args(
                live_args(directory, "stop", "gitops imperative", "ABC", "1", "--resume")
            )
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
            args = run_matrix.parse_args(
                live_args(directory, "kept", "gitops imperative", "A", "1")
            )
            self.assertEqual(run_quiet(args, run_one=runner), 0)
            (out / (calls[0] + ".jsonl")).unlink()
            resume_args = run_matrix.parse_args(
                live_args(directory, "kept", "gitops imperative", "A", "1", "--resume")
            )
            with self.assertRaises(run_matrix.BatchSafetyError):
                run_quiet(resume_args, run_one=fake_runner()[0])

    def test_resume_without_batch_id_uses_the_single_existing_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(live_args(directory, "solo", "gitops", "A", "1"))
            self.assertEqual(run_quiet(args, run_one=fake_runner()[0]), 0)
            resume_args = run_matrix.parse_args(
                [
                    "--out",
                    directory,
                    "--seed",
                    "17",
                    "--arms",
                    "gitops",
                    "--scenarios",
                    "A",
                    "--reps",
                    "1",
                    "--live",
                    "--confirm-single-stack",
                    "--namespace",
                    "exp-a",
                    "--app",
                    "invenio-bootstrap",
                    *render_args(directory),
                    "--resume",
                ]
            )
            self.assertEqual(run_quiet(resume_args, run_one=fake_runner()[0]), 0)


class CooldownTests(unittest.TestCase):
    def test_defaults_are_sixty_seconds_and_one_baseline_retry(self):
        args = run_matrix.parse_args(["--out", "/tmp/unused", "--scenarios", "A", "--reps", "1"])
        self.assertEqual(args.cooldown_seconds, 60.0)
        self.assertEqual(args.baseline_retries, 1)

    def test_live_cooldown_runs_between_cells_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(
                live_args(directory, "cool", "gitops", "AB", "1", "--cooldown-seconds", "1.5")
            )
            sleeper = mock.Mock()
            runner, calls = fake_runner()
            self.assertEqual(run_quiet(args, run_one=runner, sleep=sleeper), 0)
            self.assertEqual(len(calls), 2)
            sleeper.assert_called_once_with(1.5)
            manifest = json.loads((Path(directory) / "cool.manifest.json").read_text())
            self.assertEqual(manifest["cooldown_seconds"], 1.5)
            self.assertEqual(manifest["baseline_retries"], 1)
            self.assertEqual(len(manifest["cooldowns"]), 1)
            cooldown = manifest["cooldowns"][0]
            self.assertTrue(cooldown["applied"])
            self.assertEqual(cooldown["after_run_id"], calls[0])
            self.assertEqual(cooldown["next_run_id"], calls[1])
            self.assertEqual(cooldown["requested_seconds"], 1.5)
            self.assertIsNotNone(cooldown["started_utc"])
            self.assertIsNotNone(cooldown["finished_utc"])
            self.assertGreaterEqual(cooldown["elapsed_seconds"], 0.0)

    def test_dry_run_records_cooldowns_without_sleeping(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(
                full_args(
                    directory,
                    "dry-cool",
                    "gitops imperative",
                    "AB",
                    "2",
                    "--cooldown-seconds",
                    "2.5",
                )
            )
            sleeper = mock.Mock()
            self.assertEqual(run_quiet(args, sleep=sleeper), 0)
            sleeper.assert_not_called()
            manifest = json.loads((Path(directory) / "dry-cool.manifest.json").read_text())
            self.assertEqual(len(manifest["cooldowns"]), 7)
            for cooldown in manifest["cooldowns"]:
                self.assertFalse(cooldown["applied"])
                self.assertEqual(cooldown["elapsed_seconds"], 0.0)
                self.assertEqual(cooldown["requested_seconds"], 2.5)


class BaselineRetryTests(unittest.TestCase):
    def _args(self, directory, batch_id="retry", scenarios="A", *extra):
        return run_matrix.parse_args(
            live_args(directory, batch_id, "gitops", scenarios, "1", *extra)
        )

    def test_baseline_failure_retries_with_new_id_and_preserved_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            args = self._args(directory)
            sleeper = mock.Mock()
            runner, calls = fake_runner(statuses=["baseline_failure", "observed"])
            self.assertEqual(run_quiet(args, run_one=runner, sleep=sleeper), 0)
            self.assertEqual(len(calls), 2)
            base_id, retry_id = calls
            self.assertEqual(retry_id, base_id + "-retry1")
            self.assertEqual(
                json.loads((out / (base_id + ".jsonl")).read_text())["status"], "baseline_failure"
            )
            self.assertEqual(
                json.loads((out / (retry_id + ".jsonl")).read_text())["status"], "observed"
            )

            manifest = json.loads((out / "retry.manifest.json").read_text())
            entry = manifest["runs"][0]
            self.assertEqual(manifest["state"], "complete")
            self.assertEqual(entry["status"], "observed")
            self.assertEqual(
                [attempt["run_id"] for attempt in entry["attempts"]], [base_id, retry_id]
            )
            self.assertEqual(entry["attempts"][0]["status"], "baseline_failure")
            self.assertEqual(entry["attempts"][1]["status"], "observed")
            self.assertIsNone(entry["attempts"][0]["retry_of"])
            self.assertEqual(entry["attempts"][1]["retry_of"], base_id)
            self.assertEqual(entry["attempts"][0]["row_path"], str(out / (base_id + ".jsonl")))
            self.assertEqual(manifest["counts"]["by_status"], {"observed": 1})
            self.assertEqual(len(manifest["cooldowns"]), 1)
            self.assertEqual(manifest["cooldowns"][0]["after_run_id"], base_id)
            self.assertEqual(manifest["cooldowns"][0]["next_run_id"], retry_id)
            sleeper.assert_called_once_with(60.0)

            rows = [
                json.loads(line) for line in (out / "retry.rows.jsonl").read_text().splitlines()
            ]
            self.assertEqual([row["run_id"] for row in rows], [base_id, retry_id])
            self.assertEqual([row["batch_attempt"] for row in rows], [0, 1])
            self.assertEqual([row["batch_retry_of"] for row in rows], [None, base_id])
            summary = json.loads((out / "retry.summary.json").read_text())
            self.assertEqual(summary["analysis_rows"], 1)
            self.assertEqual(summary["recorded"], 1)

    def test_injection_recovery_cleanup_and_restore_failures_are_not_retried(self):
        cases = (
            ("invalid_injection", "ok", "restored", "invalid_injection"),
            ("recovery_failure", "ok", "restored", "recovery_failure"),
            ("instrumentation_failure", "ok", "restored", "instrumentation_failure"),
            ("observed", "failed", "restored", "cleanup_failure"),
            ("observed", "ok", "failed", "arm_restore_failure"),
            ("baseline_failure", "failed", "restored", "baseline_failure"),
            ("baseline_failure", "ok", "failed", "baseline_failure"),
        )
        for status, cleanup, restore, reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                args = self._args(directory, "no-retry")
                runner, calls = fake_runner(statuses=[status], cleanup=cleanup, restore=restore)
                self.assertEqual(run_quiet(args, run_one=runner), 1)
                self.assertEqual(len(calls), 1)
                manifest = json.loads((Path(directory) / "no-retry.manifest.json").read_text())
                entry = manifest["runs"][0]
                self.assertEqual(manifest["state"], "stopped")
                self.assertEqual(entry["stop_reason"], reason)
                self.assertEqual(len(entry["attempts"]), 1)
                self.assertEqual(entry["attempts"][0]["run_id"], calls[0])

    def test_resume_during_retry_cooldown_continues_the_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            args = self._args(directory, "retry-cooldown")
            runner, calls = fake_runner(statuses=["baseline_failure"])

            def interrupted(seconds):
                raise RuntimeError("interrupted cooldown")

            with self.assertRaises(RuntimeError):
                run_quiet(args, run_one=runner, sleep=interrupted)
            manifest = json.loads((out / "retry-cooldown.manifest.json").read_text())
            self.assertEqual(manifest["runs"][0]["status"], "retrying")
            self.assertEqual(len(manifest["runs"][0]["attempts"]), 1)

            resume_args = run_matrix.parse_args(
                live_args(directory, "retry-cooldown", "gitops", "A", "1", "--resume")
            )
            second_runner, second_calls = fake_runner()
            self.assertEqual(run_quiet(resume_args, run_one=second_runner), 0)
            self.assertEqual(second_calls, [calls[0] + "-retry1"])
            manifest = json.loads((out / "retry-cooldown.manifest.json").read_text())
            self.assertEqual(manifest["runs"][0]["status"], "observed")
            self.assertEqual(
                [attempt["status"] for attempt in manifest["runs"][0]["attempts"]],
                ["baseline_failure", "observed"],
            )

    def test_baseline_failure_with_injection_or_mutation_is_not_retried(self):
        cases = (
            {"injection": {"accepted": True}},
            {"t0_utc": "2026-10-27T00:00:00+00:00"},
            {"mutations_executed": 1},
        )
        for override in cases:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory:
                args = self._args(directory, "tainted")

                def mutate(row, override=override):
                    row.update(override)

                runner, calls = fake_runner(statuses=["baseline_failure"], mutate=mutate)
                self.assertEqual(run_quiet(args, run_one=runner), 1)
                self.assertEqual(len(calls), 1)
                manifest = json.loads((Path(directory) / "tainted.manifest.json").read_text())
                self.assertEqual(len(manifest["runs"][0]["attempts"]), 1)
                self.assertEqual(manifest["state"], "stopped")

    def test_resume_refuses_a_retry_slot_that_already_has_output(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            args = self._args(directory, "retry-slot")
            runner, calls = fake_runner(statuses=["baseline_failure"])

            def interrupted(seconds):
                raise RuntimeError("interrupted cooldown")

            with self.assertRaises(RuntimeError):
                run_quiet(args, run_one=runner, sleep=interrupted)
            (out / (calls[0] + "-retry1.jsonl")).write_text("{}\n")
            resume_args = run_matrix.parse_args(
                live_args(directory, "retry-slot", "gitops", "A", "1", "--resume")
            )
            with self.assertRaises(run_matrix.BatchSafetyError):
                run_quiet(resume_args, run_one=fake_runner()[0])

    def test_failed_retry_stops_the_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self._args(directory, "retry-fail", "AB")
            runner, calls = fake_runner(statuses=["baseline_failure", "baseline_failure"])
            self.assertEqual(run_quiet(args, run_one=runner), 1)
            self.assertEqual(len(calls), 2)
            base_id, retry_id = calls
            self.assertEqual(retry_id, base_id + "-retry1")
            manifest = json.loads((Path(directory) / "retry-fail.manifest.json").read_text())
            self.assertEqual(manifest["state"], "stopped")
            self.assertEqual(manifest["stop_reason"], "baseline_failure")
            self.assertEqual(manifest["stop_run_id"], retry_id)
            self.assertEqual(manifest["runs"][0]["status"], "baseline_failure")
            self.assertEqual(manifest["runs"][1]["status"], "pending")
            self.assertEqual(len(manifest["runs"][0]["attempts"]), 2)

    def test_zero_baseline_retries_stops_on_the_first_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self._args(directory, "no-retry-zero", "A", "--baseline-retries", "0")
            runner, calls = fake_runner(statuses=["baseline_failure"])
            self.assertEqual(run_quiet(args, run_one=runner), 1)
            self.assertEqual(len(calls), 1)
            manifest = json.loads((Path(directory) / "no-retry-zero.manifest.json").read_text())
            self.assertEqual(manifest["state"], "stopped")
            self.assertEqual(manifest["stop_run_id"], calls[0])
            self.assertEqual(len(manifest["runs"][0]["attempts"]), 1)

    def test_resume_keeps_the_failed_attempt_ledger_and_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            args = self._args(directory, "retry-resume", "AB")
            runner, calls = fake_runner(statuses=["baseline_failure", "baseline_failure"])
            self.assertEqual(run_quiet(args, run_one=runner), 1)
            base_id, retry_id = calls
            resume_args = run_matrix.parse_args(
                live_args(directory, "retry-resume", "gitops", "AB", "1", "--resume")
            )
            second_runner, second_calls = fake_runner()
            self.assertEqual(run_quiet(resume_args, run_one=second_runner), 1)
            self.assertEqual(len(second_calls), 1)
            self.assertNotIn(second_calls[0], calls)
            manifest = json.loads((out / "retry-resume.manifest.json").read_text())
            self.assertEqual(manifest["state"], "stopped")
            self.assertEqual(manifest["stop_reason"], "baseline_failure")
            self.assertEqual(manifest["stop_run_id"], retry_id)
            self.assertEqual(manifest["runs"][0]["status"], "baseline_failure")
            self.assertEqual(
                [attempt["run_id"] for attempt in manifest["runs"][0]["attempts"]],
                [base_id, retry_id],
            )
            self.assertEqual(manifest["runs"][1]["status"], "observed")
            self.assertTrue((out / (base_id + ".jsonl")).exists())
            self.assertTrue((out / (retry_id + ".jsonl")).exists())


class AnalysisOutputTests(unittest.TestCase):
    def test_rows_map_to_summarize_and_csv_without_losing_arm(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(
                live_args(
                    directory, "analysis", "gitops imperative", "B", "15", "--production-like"
                )
            )
            runner, _calls = fake_runner()
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
                {"observed": 20, "right_censored": 0, "unobserved_before_stop": 0},
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "analysis/summarize.py"),
                    "--in",
                    str(out / "analysis.analysis.jsonl"),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(len(payload["groups"]), 2)
            self.assertEqual({group["env"] for group in payload["groups"]}, {"manual", "gitops"})
            self.assertEqual(sum(group["runs"] for group in payload["groups"]), 30)

            import csv

            with (out / "analysis.csv").open(newline="") as source:
                csv_rows = list(csv.DictReader(source))
            self.assertEqual(len(csv_rows), 30)
            self.assertEqual({row["env"] for row in csv_rows}, {"manual", "gitops"})
            self.assertTrue(all(row["skenario"] == "B" for row in csv_rows))

    def test_summary_counts_censoring_and_exclusions(self):
        with tempfile.TemporaryDirectory() as directory:

            def mutate(row):
                row["status"] = "right_censored"
                row["stop_reason"] = "timeout"
                row["recovery_seconds"] = None
                row["recovery_status"] = "right_censored"
                row["t_r_mono"] = None
                row["t_r_first_mono"] = None
                row["t_r_confirmed_mono"] = None
                row["recovery_confirmation"] = "none"
                row["window_end_mono"] = 130.0

            args = run_matrix.parse_args(
                live_args(directory, "censor", "gitops imperative", "B", "1")
            )
            runner, _calls = fake_runner(mutate=mutate)
            self.assertEqual(run_quiet(args, run_one=runner), 0)
            summary = json.loads((Path(directory) / "censor.summary.json").read_text())
            self.assertEqual(summary["exclusions"], [])
            self.assertEqual(
                summary["censoring"]["R2"]["recovery"],
                {"observed": 0, "right_censored": 2, "unobserved_before_stop": 0},
            )
            self.assertEqual(summary["phases"]["R2"]["observed"], 0)
            self.assertEqual(summary["phases"]["R2"]["right_censored"], 2)


class TokenSafetyTests(unittest.TestCase):
    def test_token_never_appears_in_logs_or_batch_artifacts(self):
        token = "tok-super-secret-123"
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(os.environ, {"INVENIO_TOKEN": token}),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            args = run_matrix.parse_args(
                live_args(directory, "secret", "gitops imperative", "A", "1", "--production-like")
            )
            self.assertEqual(run_quiet(args, run_one=fake_runner()[0]), 0)
            texts = [stdout.getvalue(), stderr.getvalue()]
            texts.extend(path.read_text() for path in Path(directory).iterdir() if path.is_file())
            for text in texts:
                self.assertNotIn(token, text)

    def test_runner_exception_is_redacted_and_stops_the_batch(self):
        token = "tok-super-secret-456"
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(os.environ, {"INVENIO_TOKEN": token}),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):

            def runner(args, item, run_id):
                raise RuntimeError("failed with " + token)

            args = run_matrix.parse_args(
                live_args(directory, "boom", "gitops imperative", "A", "1")
            )
            self.assertEqual(run_quiet(args, run_one=runner), 1)
            manifest = json.loads((Path(directory) / "boom.manifest.json").read_text())
            self.assertEqual(manifest["state"], "stopped")
            self.assertNotIn(token, (Path(directory) / "boom.manifest.json").read_text())
            texts = [stdout.getvalue(), stderr.getvalue()]
            texts.extend(path.read_text() for path in Path(directory).iterdir() if path.is_file())
            for text in texts:
                self.assertNotIn(token, text)


class RunMatrixEdgeTests(unittest.TestCase):
    def _item(self):
        return {"index": 0, "arm": "gitops", "scenario": "A", "rep": 1, "phase": "R2"}

    def test_argument_parsers_cover_ranges_and_rejections(self):
        self.assertEqual(run_matrix._as_list("gitops", "arms"), ["gitops"])
        with self.assertRaises(ValueError):
            run_matrix._as_list([" "], "arms")
        with self.assertRaises(ValueError):
            run_matrix.parse_arms("bogus")
        self.assertEqual(run_matrix.parse_scenarios("b-d"), ["B", "C", "D"])
        with self.assertRaises(ValueError):
            run_matrix.parse_scenarios("D-B")
        with self.assertRaises(ValueError):
            run_matrix.parse_scenarios("Q")
        with self.assertRaises(ValueError):
            run_matrix.build_plan(["gitops"], ["A"], 0, 1)

    def test_read_last_jsonl_returns_none_for_blank_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blank.jsonl"
            path.write_text("\n")
            self.assertIsNone(run_matrix._read_last_jsonl(path))

    def test_parse_args_rejects_every_invalid_bound(self):
        cases = (
            ["--reps", "0"],
            ["--cooldown-seconds", "-1"],
            ["--cooldown-seconds", "nan"],
            ["--baseline-retries", "-1"],
            ["--batch-id", "bad id"],
            ["--source-revision", "short"],
            ["--render-sha256", "short"],
            ["--production-like"],
            ["--arms", "bogus"],
            ["--scenarios", "Q"],
        )
        for case in cases:
            with (
                self.subTest(case=case),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                run_matrix.parse_args(case)

    def test_validate_batch_args_rejects_missing_live_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(live_args(directory, "safety", "gitops", "A", "1"))
            mutations = (
                ("confirm_single_stack", False, "--live requires"),
                ("namespace_explicit", False, "--namespace must be explicit"),
                ("app_explicit", False, "--app must be explicit"),
                ("render_sha256", None, "--render-sha256 is required"),
                ("source_revision", None, "--source-revision is required"),
                ("render_file", None, "--render-file is required"),
                ("render_file", "https://example/render.json", "local file"),
            )
            for attribute, value, message in mutations:
                current = copy.deepcopy(args)
                setattr(current, attribute, value)
                with (
                    self.subTest(attribute=attribute),
                    self.assertRaisesRegex(run_matrix.BatchSafetyError, message),
                ):
                    run_matrix.validate_batch_args(current)

    def test_new_batch_rejects_long_ids_and_existing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            long_args = argparse.Namespace(out=directory, baseline_retries=15)
            plan = run_matrix.build_plan(["gitops"], ["A"], 1, 1)
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "longer than 63"):
                run_matrix._ensure_new_batch(
                    long_args, plan, "x" * 60, {"manifest": Path(directory) / "m"}
                )
            args = run_matrix.parse_args(full_args(directory, "exists", "gitops", "A", "1"))
            plan = run_matrix.build_plan(args.arms, args.scenarios, args.reps, args.seed)
            run_id = run_matrix.run_id_for("exists", plan["runs"][0])
            write_row(directory, run_id, make_row(plan["runs"][0]))
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "refusing to overwrite"):
                run_matrix._ensure_new_batch(
                    args, plan, "exists", {"manifest": Path(directory) / "m"}
                )
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "refusing to overwrite"):
                run_matrix._ensure_run_slot(args, run_id)

    def _tiny_batch(self, directory, batch_id="tiny", scenarios="A"):
        args = run_matrix.parse_args(live_args(directory, batch_id, "gitops", scenarios, "1"))
        self.assertEqual(run_quiet(args, run_one=fake_runner()[0]), 0)
        paths = run_matrix._batch_paths(args.out, batch_id)
        manifest = json.loads(paths["manifest"].read_text())
        plan = run_matrix.build_plan(args.arms, args.scenarios, args.reps, args.seed)
        return args, plan, batch_id, paths, manifest

    def test_resume_rejects_malformed_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            args, plan, batch_id, paths, manifest = self._tiny_batch(directory)
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "existing manifest"):
                run_matrix._validate_resume(
                    args, plan, batch_id, {"manifest": Path(directory) / "missing.json"}
                )
            paths["manifest"].write_text("{bad")
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "invalid batch manifest"):
                run_matrix._validate_resume(args, plan, batch_id, paths)
            paths["manifest"].write_text("[]")
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "not an object"):
                run_matrix._validate_resume(args, plan, batch_id, paths)
            cases = (
                (lambda value: value.pop("timing_convention"), "predates"),
                (lambda value: value.pop("counts"), "missing counts"),
                (lambda value: value.update(seed=999), "seed does not match"),
                (lambda value: value.update(state="weird"), "invalid batch manifest state"),
                (lambda value: value["runs"].pop(), "does not match the plan"),
            )
            for mutate, message in cases:
                bad = copy.deepcopy(manifest)
                mutate(bad)
                paths["manifest"].write_text(json.dumps(bad))
                with (
                    self.subTest(message=message),
                    self.assertRaisesRegex(run_matrix.BatchSafetyError, message),
                ):
                    run_matrix._validate_resume(args, plan, batch_id, paths)

    def test_resume_rejects_each_manifest_identity_violation(self):
        with tempfile.TemporaryDirectory() as directory:
            args, plan, batch_id, paths, manifest = self._tiny_batch(directory)

            def check(mutate, message):
                bad = copy.deepcopy(manifest)
                mutate(bad)
                paths["manifest"].write_text(json.dumps(bad))
                with self.assertRaisesRegex(run_matrix.BatchSafetyError, message):
                    run_matrix._validate_resume(args, plan, batch_id, paths)

            def entry(value):
                return value["runs"][0]

            check(lambda value: entry(value).update(index=9), "does not match the plan")
            check(lambda value: entry(value).update(run_id="other"), "identity mismatch")
            check(lambda value: entry(value).update(status="weird"), "unknown status")
            check(lambda value: entry(value).update(attempts="bad"), "no attempt ledger")
            check(
                lambda value: entry(value)["attempts"][0].update(attempt=3),
                "invalid attempt ledger",
            )
            check(
                lambda value: entry(value)["attempts"][0].update(run_id="other"),
                "unexpected retry identity",
            )
            check(
                lambda value: entry(value)["attempts"][0].update(retry_of="other"),
                "invalid retry relationship",
            )
            check(lambda value: entry(value).update(row_path="missing"), "missing evidence")
            check(
                lambda value: entry(value).update(status="observed", attempts=[]),
                "no attempts but is not pending",
            )
            check(
                lambda value: entry(value).update(status="failure"),
                "does not match its last attempt",
            )
            check(
                lambda value: (
                    entry(value).update(status="retrying"),
                    entry(value)["attempts"][0].update(status="observed"),
                ),
                "retrying without a retryable baseline failure",
            )

    def test_resume_rejects_duplicate_identity_across_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(live_args(directory, "dupe", "gitops", "A", "1"))
            item = {"index": 0, "arm": "gitops", "scenario": "A", "rep": 1, "phase": "R2"}
            plan = {
                "arm_order": ["gitops"],
                "scenario_order": ["A"],
                "runs": [dict(item), dict(item, index=1)],
            }
            manifest = run_matrix._new_manifest(args, plan, "dupe")
            run_id = run_matrix.run_id_for("dupe", item)
            for entry in manifest["runs"]:
                entry["attempts"] = [
                    {"attempt": 0, "run_id": run_id, "retry_of": None, "status": "pending"}
                ]
            manifest["state"] = "running"
            paths = run_matrix._batch_paths(args.out, "dupe")
            paths["manifest"].write_text(json.dumps(manifest))
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "duplicate run identity"):
                run_matrix._validate_resume(args, plan, "dupe", paths)

    def test_resume_rejects_missing_rows_and_pending_output(self):
        with tempfile.TemporaryDirectory() as directory:
            args, plan, batch_id, paths, manifest = self._tiny_batch(directory, "rows")
            row_path = run_matrix._row_path(args.out, run_matrix.final_run_id(manifest["runs"][0]))
            manifest["runs"][0]["row_path"] = None
            manifest["runs"][0]["attempts"][0]["row_path"] = None
            row_path.unlink()
            paths["manifest"].write_text(json.dumps(manifest))
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "missing its preserved row"):
                run_matrix._validate_resume(args, plan, batch_id, paths)
            manifest["runs"][0].update(status="pending", attempts=[])
            paths["manifest"].write_text(json.dumps(manifest))
            write_row(args.out, manifest["runs"][0]["run_id"], make_row(plan["runs"][0]))
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "already has output"):
                run_matrix._validate_resume(args, plan, batch_id, paths)

    def test_resume_rejects_complete_with_pending_and_stopped_without_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            args, plan, batch_id, paths, manifest = self._tiny_batch(directory, "state")
            row_path = run_matrix._row_path(args.out, run_matrix.final_run_id(manifest["runs"][0]))
            manifest["runs"][0].update(status="pending", attempts=[], row_path=None)
            row_path.unlink()
            manifest["state"] = "complete"
            paths["manifest"].write_text(json.dumps(manifest))
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "still has pending"):
                run_matrix._validate_resume(args, plan, batch_id, paths)
            manifest["state"] = "stopped"
            manifest["stop_reason"] = None
            paths["manifest"].write_text(json.dumps(manifest))
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "no stop reason"):
                run_matrix._validate_resume(args, plan, batch_id, paths)

    def test_validate_attempt_rejects_invalid_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(full_args(directory, "attempt", "gitops", "A", "1"))
            item = {"arm": "gitops", "scenario": "A", "rep": 1}
            run_id = "attempt-gitops-A-r01"
            base = make_row(item)
            base["run_id"] = run_id
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "unknown status"):
                run_matrix._validate_attempt(args, item, run_id, {"status": "weird"})
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "missing evidence"):
                run_matrix._validate_attempt(
                    args, item, run_id, {"status": "observed", "row_path": "missing"}
                )
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "preserved row"):
                run_matrix._validate_attempt(args, item, run_id, {"status": "observed"})
            write_row(directory, run_id, dict(base))
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "identity/status"):
                run_matrix._validate_attempt(args, item, run_id, {"status": "failure"})
            Path(directory, run_id + ".jsonl").write_text("{bad")
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "unreadable row"):
                run_matrix._validate_attempt(args, item, run_id, {"status": "observed"})
            Path(directory, run_id + ".jsonl").write_text("[1]\n")
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "invalid row"):
                run_matrix._validate_attempt(args, item, run_id, {"status": "observed"})
            write_row(directory, run_id, make_row(item, status="pending"))
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "already has output"):
                run_matrix._validate_attempt(args, item, run_id, {"status": "pending"})

    def test_rebuild_rows_skips_pending_and_missing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(full_args(directory, "rebuild", "gitops", "A", "1"))
            manifest = {
                "runs": [
                    {
                        "index": 0,
                        "arm": "gitops",
                        "scenario": "A",
                        "rep": 1,
                        "phase": "R2",
                        "run_id": "rebuild-gitops-A-r01",
                        "attempts": [
                            {"attempt": 0, "run_id": "rebuild-gitops-A-r01", "status": "pending"},
                            {"attempt": 1, "run_id": "missing-row", "status": "observed"},
                        ],
                    }
                ]
            }
            self.assertEqual(run_matrix._rebuild_rows(args, manifest, "rebuild"), [])
            write_row(directory, "rebuild-gitops-A-r01", make_row(manifest["runs"][0]))
            manifest["runs"][0]["attempts"][0]["status"] = "observed"
            rows = run_matrix._rebuild_rows(args, manifest, "rebuild")
            self.assertEqual(len(rows), 1)

    def test_resolve_batch_id_handles_resume_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            args = run_matrix.parse_args(full_args(directory, "named", "gitops", "A", "1"))
            plan = run_matrix.build_plan(args.arms, args.scenarios, args.reps, args.seed)
            self.assertEqual(run_matrix._resolve_batch_id(args, plan), "named")
            unnamed = run_matrix.parse_args(full_args(directory, "named", "gitops", "A", "1"))
            unnamed.batch_id = None
            self.assertEqual(
                run_matrix._resolve_batch_id(unnamed, plan), run_matrix.default_batch_id(unnamed)
            )
            args.resume = True
            args.batch_id = None
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "zero or multiple manifests"):
                run_matrix._resolve_batch_id(args, plan)
            default = run_matrix.default_batch_id(args)
            (out / (default + ".manifest.json")).write_text("{}")
            self.assertEqual(run_matrix._resolve_batch_id(args, plan), default)
            (out / "other.manifest.json").write_text("{}")
            (out / (default + ".manifest.json")).unlink()
            self.assertEqual(run_matrix._resolve_batch_id(args, plan), "other")
            long_args = argparse.Namespace(
                out=directory, batch_id="x" * 60, resume=False, baseline_retries=0
            )
            with self.assertRaisesRegex(run_matrix.BatchSafetyError, "longer than 63"):
                run_matrix._resolve_batch_id(long_args, plan)

    def test_timing_problem_reports_each_invalid_shape(self):
        def row(**overrides):
            value = make_row(self._item())
            value.update(overrides)
            return value

        cases = (
            (lambda value: value.pop("t0_mono"), "incomplete_timing_bounds"),
            (lambda value: value.update(censor_seconds=0), "invalid_censor_seconds"),
            (lambda value: value.update(t_a_mono=99.0), "invalid_timing_bounds"),
            (lambda value: value.update(injection_seconds=9.0), "invalid_timing_bounds"),
            (lambda value: value.update(stop_reason="timeout"), "incomplete_timing_bounds"),
            (
                lambda value: value.update(status="right_censored", recovery_status="observed"),
                "incomplete_timing_bounds",
            ),
            (
                lambda value: value.update(
                    status="right_censored",
                    recovery_status="right_censored",
                    stop_reason="recovery",
                ),
                "window_not_completed",
            ),
            (
                lambda value: value.update(
                    status="right_censored",
                    recovery_status="right_censored",
                    stop_reason="timeout",
                    window_end_mono=120.0,
                ),
                "window_not_completed",
            ),
            (lambda value: value.update(t_d_mono=None), "invalid_detection_observation"),
            (
                lambda value: value.update(detection_status="right_censored"),
                "invalid_detection_observation",
            ),
            (lambda value: value.update(t_r_first_mono=200.0), "invalid_recovery_observation"),
            (lambda value: value.update(t_r_first_seconds=9.0), "invalid_recovery_observation"),
            (lambda value: value.update(t_r_confirmed_mono=200.0), "invalid_recovery_observation"),
            (
                lambda value: value.update(t_r_confirmed_seconds=9.0),
                "invalid_recovery_observation",
            ),
            (
                lambda value: value.update(t_r_mono=104.0, recovery_seconds=4.0),
                "incomplete_timing_bounds",
            ),
            (
                lambda value: value.update(
                    status="right_censored",
                    recovery_status="right_censored",
                    stop_reason="timeout",
                    t_r_mono=102.0,
                    t_r_confirmed_mono=None,
                    recovery_confirmation="none",
                ),
                "invalid_recovery_observation",
            ),
            (
                lambda value: value.update(
                    status="right_censored",
                    recovery_status="right_censored",
                    stop_reason="timeout",
                    t_r_mono=None,
                    recovery_seconds=None,
                ),
                "invalid_recovery_observation",
            ),
            (
                lambda value: value.update(t_e_store_mono=101.6),
                None,
            ),
            (lambda value: value.update(t_e_store_mono="bad"), "invalid_evidence_store"),
            (
                lambda value: value.update(t_e_store_mono=101.6, evidence_store_seconds=9.0),
                "invalid_evidence_store",
            ),
        )
        for index, (mutate, expected) in enumerate(cases):
            value = row()
            mutate(value)
            with self.subTest(index=index, expected=expected):
                self.assertEqual(run_matrix._timing_problem(value), expected)
        self.assertIsNone(run_matrix._timing_problem(row()))

    def test_analysis_problem_reports_each_invalid_shape(self):
        def row(**overrides):
            value = make_row(self._item())
            value.update(overrides)
            return value

        cases = (
            (lambda value: value.update(status="dry_run"), "status:dry_run"),
            (lambda value: value.update(cleanup_status="failed"), "cleanup_failure"),
            (lambda value: value.update(arm_restore_status="failed"), "arm_restore_failure"),
            (lambda value: value.update(batch_stop_reason="halt"), "batch_stop:halt"),
            (lambda value: value.update(error="boom"), "row_error"),
            (lambda value: value.update(postcondition=None), "postcondition_not_verified"),
            (lambda value: value.update(synthetic=True), "synthetic"),
            (lambda value: value.pop("timing_convention"), "missing_timing_convention"),
            (
                lambda value: value.update(timing_convention="other"),
                "unsupported_timing_convention",
            ),
            (lambda value: value.update(window_completed=False), "window_not_completed"),
            (lambda value: value.update(t_a_mono=99.0), "invalid_timing_bounds"),
            (lambda value: value.update(scenario="Z"), "invalid_scenario"),
            (
                lambda value: value.update(analysis_group="visibility_boundary"),
                "invalid_analysis_group",
            ),
            (lambda value: value.update(source_revision="short"), "invalid_source_revision"),
            (lambda value: value.update(render_sha256="short"), "invalid_render_sha256"),
            (
                lambda value: value.update(
                    status="right_censored",
                    recovery_status="right_censored",
                    stop_reason="timeout",
                    detection_seconds=None,
                    detection_status="unobserved_before_stop",
                    t_d_mono=None,
                    recovery_seconds=None,
                    t_r_mono=None,
                    t_r_first_mono=None,
                    t_r_confirmed_mono=None,
                    recovery_confirmation="none",
                ),
                "invalid_detection_observation",
            ),
        )
        for mutate, expected in cases:
            value = row()
            mutate(value)
            with self.subTest(expected=expected):
                self.assertEqual(run_matrix._analysis_problem(value), expected)
        self.assertIsNone(run_matrix._analysis_problem(row()))

    def test_run_one_forwards_optional_identity_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(live_args(directory, "one", "gitops", "A", "1"))
            self.assertFalse(hasattr(args, "for_test_only"))
            item = self._item()
            run_id = "one-gitops-A-r01"
            write_row(directory, run_id, make_row(item))
            with mock.patch.object(run_matrix.harness, "main", return_value=0) as main:
                code, row, error = run_matrix._run_one(args, item, run_id)
            self.assertEqual((code, error), (0, None))
            self.assertEqual(row["run_id"], run_id)
            forwarded = main.call_args[0][0]
            for flag in ("--source-revision", "--render-sha256", "--render-file", "--live"):
                self.assertIn(flag, forwarded)

    def test_classify_covers_each_terminal_shape(self):
        live = argparse.Namespace(live=True)
        dry = argparse.Namespace(live=False)
        cases = (
            (live, 0, None, "boom", ("failure", "runner_exception")),
            (live, 0, None, None, ("refused", "missing_row")),
            (live, 0, {"status": "weird"}, None, ("failure", "unknown_status")),
            (live, 0, {"status": "dry_run"}, None, ("dry_run", "unexpected_dry_run")),
            (dry, 0, {"status": "observed"}, None, ("observed", "unexpected_live_row")),
            (
                live,
                0,
                {"status": "observed", "cleanup_status": "failed"},
                None,
                ("observed", "cleanup_failure"),
            ),
            (
                live,
                0,
                {"status": "observed", "arm_restore_status": "failed"},
                None,
                ("observed", "arm_restore_failure"),
            ),
            (
                live,
                0,
                {"status": "baseline_failure"},
                None,
                ("baseline_failure", "baseline_failure"),
            ),
            (live, 1, {"status": "observed"}, None, ("observed", "nonzero_exit")),
        )
        for args, code, row, error, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(run_matrix._classify(args, code, row, error), expected)
        self.assertFalse(run_matrix._baseline_retryable("baseline_failure", None))
        censored = run_matrix._censoring([{"batch_phase": "R2", "detection_status": "weird"}])
        self.assertEqual(censored["R2"]["detection"]["observed"], 0)

    def test_run_batch_stops_on_output_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            args = run_matrix.parse_args(full_args(directory, "conflict", "gitops", "A", "1"))
            with (
                mock.patch.object(
                    run_matrix,
                    "_ensure_run_slot",
                    side_effect=run_matrix.BatchSafetyError("conflict"),
                ),
                self.assertRaises(run_matrix.BatchSafetyError),
            ):
                run_quiet(args, run_one=fake_runner()[0])

    def test_run_batch_records_non_object_and_missing_row_outputs(self):
        for runner, expected in (
            (lambda args, item, run_id: (0, "not-a-row", None), "non-object row"),
            (lambda args, item, run_id: (0, make_row(item), None), "row file missing"),
        ):
            with tempfile.TemporaryDirectory() as directory:
                args = run_matrix.parse_args(live_args(directory, "shape", "gitops", "A", "1"))
                self.assertEqual(run_quiet(args, run_one=runner), 1)
                manifest = json.loads((Path(directory) / "shape.manifest.json").read_text())
                self.assertIn(expected, manifest["runs"][0]["error"])

    def test_run_batch_pops_a_pending_attempt_on_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            args, _plan, _batch_id, paths, manifest = self._tiny_batch(directory, "pop")
            entry = manifest["runs"][0]
            manifest["state"] = "running"
            entry["status"] = "running"
            entry["row_path"] = None
            entry["attempts"][0]["row_path"] = None
            entry["attempts"][0]["status"] = "running"
            run_matrix._row_path(args.out, run_matrix.final_run_id(entry)).unlink()
            paths["manifest"].write_text(json.dumps(manifest))
            resume = run_matrix.parse_args(
                live_args(directory, "pop", "gitops", "A", "1", "--resume")
            )
            self.assertEqual(run_quiet(resume, run_one=fake_runner()[0]), 0)

    def test_main_reports_batch_errors(self):
        with redirect_stderr(io.StringIO()):
            with mock.patch.object(run_matrix, "run_batch", side_effect=run_matrix.BatchError("x")):
                self.assertEqual(run_matrix.main([]), 1)
            with mock.patch.object(
                run_matrix, "run_batch", side_effect=run_matrix.BatchSafetyError("x")
            ):
                self.assertEqual(run_matrix.main([]), 2)


if __name__ == "__main__":
    unittest.main()
