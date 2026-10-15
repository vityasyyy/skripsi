import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ANALYSIS = Path(__file__).resolve().parents[1]
ANALYZER = ANALYSIS / "analyze.py"
sys.path.insert(0, str(ANALYSIS))
import analyze


def run_record(**changes):
    record = {
        "schema_version": 2,
        "run_id": "fixture-s1-manual-A-1",
        "phase": "fixture",
        "subject": "s1",
        "env": "manual",
        "scenario": "A",
        "rep": 1,
        "status": "complete",
        "reason": None,
        "started_at_utc": "2026-10-15T12:00:00Z",
        "t0_mono_s": 100.0,
        "ta_mono_s": 104.0,
        "td_mono_s": 102.5,
        "te_mono_s": 103.0,
        "tr_mono_s": 105.0,
        "timeout_s": 30.0,
        "poll_interval_s": 0.1,
        "detection_status": "observed",
        "evidence_status": "observed",
        "recovery_status": "observed",
        "r1_baseline_pct": 100.0,
        "r1_post_pct": 80.0,
        "r1_recovered_pct": 100.0,
        "healthy_baseline": True,
        "healthy_final": True,
        "evidence": [
            {
                "resource": "Deployment/exp-web",
                "field_paths": ["spec.replicas"],
                "source": "inventory-comparison",
                "observed_at_mono_s": 103.0,
            }
        ],
    }
    record.update(changes)
    return record


def formal_comparison_record(env, rep, detection_s, evidence_s, recovery_s):
    t0 = 100.0
    te = t0 + evidence_s
    return run_record(
        run_id=f"synthetic-formal-{env}-{rep}",
        phase="formal",
        subject="synthetic-policy-test-subject",
        env=env,
        rep=rep,
        t0_mono_s=t0,
        ta_mono_s=t0 + 0.1,
        td_mono_s=t0 + detection_s,
        te_mono_s=te,
        tr_mono_s=t0 + recovery_s,
        r1_recovered_pct=100.0,
        evidence=[
            {
                "resource": "Deployment/test",
                "field_paths": ["spec.replicas"],
                "source": "synthetic-test-observer",
                "observed_at_mono_s": te,
            }
        ],
    )


def approved_policy(runs, family):
    return {
        "policy_id": "SYNTHETIC-TEST-ONLY",
        "approved": True,
        "approval_reference": "synthetic test input only",
        "prespecified": True,
        "independence_confirmed": True,
        "independence_basis": "hand-authored CLI test records only",
        "collection_run_ids": [run["run_id"] for run in runs],
        "holm_family": family,
    }


class AnalyzeV2CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "reports"

    def tearDown(self):
        self.tmp.cleanup()

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, allow_nan=True), encoding="utf-8")
        return path

    def invoke(self, source, *options):
        return subprocess.run(
            [
                sys.executable,
                str(ANALYZER),
                "--in",
                str(source),
                "--out",
                str(self.out),
                *options,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def invoke_fixture(self, source):
        return self.invoke(source, "--schema-version", "2", "--phase", "fixture")

    def test_fixture_report_derives_elapsed_time_from_monotonic_events(self):
        source = self.write_json(self.root / "run.json", run_record())

        result = self.invoke_fixture(source)

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.out / "analysis-v2.json").read_text(encoding="utf-8"))
        self.assertEqual(report["label"], "SYNTHETIC FIXTURE — NOT EMPIRICAL")
        group = report["groups"][0]
        self.assertEqual(group["events"]["detection"]["observed_duration_s"]["median"], 2.5)
        self.assertEqual(group["events"]["recovery"]["observed_duration_s"]["median"], 5.0)
        self.assertEqual(group["r1_percent"]["r1_post_pct"]["median"], 80.0)
        self.assertEqual(group["health"]["healthy_final"]["true"], 1)
        self.assertNotIn("t0_mono_s", json.dumps(report))
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["analysis-v2.json"])

    def test_stored_deviation_evidence_may_precede_detection_signal(self):
        record = run_record(
            td_mono_s=103.5,
            te_mono_s=102.0,
            evidence=[
                {
                    "resource": "Deployment/exp-web",
                    "field_paths": ["spec.replicas"],
                    "source": "independent-oracle",
                    "observed_at_mono_s": 102.0,
                }
            ],
        )
        source = self.write_json(self.root / "run.json", record)

        result = self.invoke_fixture(source)

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.out / "analysis-v2.json").read_text(encoding="utf-8"))
        group = report["groups"][0]
        self.assertEqual(group["events"]["evidence"]["observed_duration_s"]["median"], 2.0)
        self.assertEqual(group["events"]["detection"]["observed_duration_s"]["median"], 3.5)

    def test_restoration_can_be_observed_when_detection_and_evidence_are_censored(self):
        record = run_record(
            status="timeout",
            td_mono_s=None,
            te_mono_s=None,
            tr_mono_s=105.0,
            detection_status="right_censored",
            evidence_status="right_censored",
            recovery_status="observed",
            evidence=[],
        )
        source = self.write_json(self.root / "run.json", record)

        result = self.invoke_fixture(source)

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.out / "analysis-v2.json").read_text(encoding="utf-8"))
        group = report["groups"][0]
        self.assertEqual(group["events"]["detection"]["status_counts"]["right_censored"], 1)
        self.assertEqual(group["events"]["evidence"]["status_counts"]["right_censored"], 1)
        self.assertEqual(group["events"]["recovery"]["observed_duration_s"]["median"], 5.0)

    def test_observed_restoration_requires_full_r1_recovery(self):
        source = self.write_json(self.root / "run.json", run_record(r1_recovered_pct=99.0))

        result = self.invoke_fixture(source)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("r1_recovered_pct=100", result.stderr.lower())
        self.assertFalse(self.out.exists())

    def test_report_retains_failures_censor_counts_and_separates_scenario_f(self):
        complete = run_record()
        timeout = run_record(
            run_id="fixture-s1-manual-A-2",
            rep=2,
            status="timeout",
            ta_mono_s=200.1,
            t0_mono_s=200.0,
            td_mono_s=None,
            te_mono_s=None,
            tr_mono_s=None,
            detection_status="right_censored",
            evidence_status="right_censored",
            recovery_status="right_censored",
            evidence=[],
        )
        failed = run_record(
            run_id="fixture-s1-gitops-A-1",
            env="gitops",
            status="injection_failed",
            t0_mono_s=300.0,
            ta_mono_s=None,
            td_mono_s=None,
            te_mono_s=None,
            tr_mono_s=None,
            detection_status="not_evaluable",
            evidence_status="not_evaluable",
            recovery_status="not_evaluable",
            r1_post_pct=None,
            r1_recovered_pct=None,
            healthy_final=None,
            evidence=[],
        )
        boundary = run_record(
            run_id="fixture-s2-manual-F-1",
            subject="s2",
            scenario="F",
            t0_mono_s=400.0,
            ta_mono_s=400.1,
            td_mono_s=401.0,
            te_mono_s=401.5,
            tr_mono_s=None,
            recovery_status="not_evaluable",
            r1_baseline_pct=None,
            r1_post_pct=None,
            r1_recovered_pct=None,
            evidence=[
                {
                    "resource": "ConfigMap/visible",
                    "field_paths": ["data.mode"],
                    "source": "inventory-comparison",
                    "observed_at_mono_s": 401.5,
                }
            ],
        )
        source = self.root / "runs"
        self.write_json(source / "one.json", complete)
        self.write_json(source / "two.json", timeout)
        self.write_json(source / "three.json", failed)
        self.write_json(source / "four.json", boundary)

        result = self.invoke_fixture(source)

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.out / "analysis-v2.json").read_text(encoding="utf-8"))
        managed = next(group for group in report["groups"] if group["env"] == "manual")
        self.assertEqual(managed["run_status_counts"]["complete"], 1)
        self.assertEqual(managed["run_status_counts"]["timeout"], 1)
        self.assertEqual(managed["events"]["detection"]["status_counts"]["right_censored"], 1)
        self.assertEqual(managed["events"]["detection"]["observed_duration_s"]["n"], 1)
        self.assertTrue(all(group["scenario"] != "F" for group in report["groups"]))
        failed_group = next(group for group in report["groups"] if group["env"] == "gitops")
        self.assertEqual(failed_group["run_status_counts"]["injection_failed"], 1)
        self.assertEqual(report["visibility_boundary"][0]["scenario"], "F")
        self.assertEqual(
            report["visibility_boundary"][0]["events"]["recovery"]["status_counts"]["not_evaluable"],
            1,
        )
        self.assertEqual(
            report["visibility_boundary"][0]["events"]["recovery"]["observed_duration_s"]["n"],
            0,
        )

    def test_formal_mode_rejects_reserved_fixture_subject_before_writing(self):
        source = self.write_json(self.root / "run.json", run_record(phase="formal"))

        result = self.invoke(source, "--schema-version", "2", "--phase", "formal")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reserved", result.stderr.lower())
        self.assertFalse(self.out.exists())

    def test_formal_mode_accepts_future_subject_without_claiming_authorization(self):
        source = self.write_json(
            self.root / "run.json",
            run_record(phase="formal", subject="future-subject"),
        )

        runs = analyze.load_v2_runs(source, "formal")

        self.assertEqual(runs[0]["subject"], "future-subject")
        self.assertFalse(self.out.exists())

    def test_mixed_phase_directory_fails_before_writing(self):
        source = self.root / "runs"
        self.write_json(source / "one.json", run_record())
        self.write_json(source / "two.json", run_record(run_id="pilot-2", phase="pilot", rep=2))

        result = self.invoke_fixture(source)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mixed phase", result.stderr.lower())
        self.assertFalse(self.out.exists())

    def test_invalid_null_and_nonfinite_timestamps_fail_before_writing(self):
        cases = [
            ("observed event without timestamp", {"td_mono_s": None}),
            ("boolean monotonic timestamp", {"td_mono_s": True}),
            ("nonfinite monotonic timestamp", {"td_mono_s": float("nan")}),
            ("negative elapsed event", {"td_mono_s": 99.0}),
        ]
        for name, changes in cases:
            with self.subTest(name=name):
                self.out = self.root / name.replace(" ", "-")
                source = self.write_json(self.root / f"{name.replace(' ', '-')}.json", run_record(**changes))

                result = self.invoke_fixture(source)

                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(
                    "timestamp" in result.stderr.lower() or "non-finite" in result.stderr.lower(),
                    result.stderr,
                )
                self.assertFalse(self.out.exists())

    def test_directory_input_does_not_recursively_consume_evidence_json(self):
        source = self.root / "runs"
        self.write_json(source / "run.json", run_record())
        self.write_json(source / "evidence" / "details.json", {"private": "not a run summary"})

        result = self.invoke_fixture(source)

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.out / "analysis-v2.json").read_text(encoding="utf-8"))
        self.assertEqual(report["run_count"], 1)

    def test_unstructured_evidence_payload_is_rejected(self):
        record = run_record()
        record["evidence"][0]["field_value"] = "must not enter reports"
        source = self.write_json(self.root / "run.json", record)

        result = self.invoke_fixture(source)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sanitized provenance", result.stderr.lower())
        self.assertFalse(self.out.exists())

    def test_status_and_measurement_schema_must_be_consistent(self):
        cases = [
            ("correction failure cannot claim recovery", {"status": "correction_failed"}, "status=correction_failed"),
            ("R1 is a percent", {"r1_post_pct": 100.01}, "[0, 100]"),
            ("subject is nonempty", {"subject": "  "}, "nonempty string"),
            ("unknown schema keys are rejected", {"raw_payload": {}}, "schema fields mismatch"),
        ]
        for name, changes, error_text in cases:
            with self.subTest(name=name):
                self.out = self.root / name.replace(" ", "-")
                source = self.write_json(
                    self.root / f"{name.replace(' ', '-')}.json",
                    run_record(**changes),
                )

                result = self.invoke_fixture(source)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error_text, result.stderr.lower())
                self.assertFalse(self.out.exists())

    def test_duplicate_replicates_fail_before_writing(self):
        source = self.root / "runs"
        first = run_record()
        second = run_record(run_id="different-run-id")
        self.write_json(source / "one.json", first)
        self.write_json(source / "two.json", second)

        result = self.invoke_fixture(source)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate", result.stderr.lower())
        self.assertFalse(self.out.exists())

    def test_duplicate_run_ids_fail_before_writing(self):
        source = self.root / "runs"
        self.write_json(source / "one.json", run_record())
        self.write_json(source / "two.json", run_record(rep=2))

        result = self.invoke_fixture(source)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate run_id", result.stderr.lower())
        self.assertFalse(self.out.exists())

    def test_existing_v2_report_is_never_overwritten(self):
        source = self.write_json(self.root / "run.json", run_record())
        self.out.mkdir()
        target = self.out / "analysis-v2.json"
        target.write_text("preserve me", encoding="utf-8")

        result = self.invoke_fixture(source)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "preserve me")
        self.assertIn("already exists", result.stderr.lower())

    def test_fixture_mode_refuses_exploratory_comparisons(self):
        source = self.write_json(self.root / "run.json", run_record())

        result = self.invoke(
            source,
            "--schema-version",
            "2",
            "--phase",
            "fixture",
            "--exploratory-comparisons",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("formal", result.stderr.lower())
        self.assertFalse(self.out.exists())

    def test_cli_requires_an_explicit_input_mode(self):
        result = self.invoke(self.root / "not-read.csv")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("select --schema-version 2", result.stderr)

        result = self.invoke(
            self.root / "not-read.json",
            "--schema-version",
            "2",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires an explicit --phase", result.stderr)

        result = self.invoke(
            self.root / "not-read.json",
            "--schema-version",
            "2",
            "--phase",
            "formal",
            "--exploratory-comparisons",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("require an approved --policy", result.stderr)

    def test_legacy_csv_outputs_are_marked_synthetic(self):
        source = self.root / "legacy.csv"
        source.write_text(
            "subject,env,skenario,rep,t0,td,trci,t2,r1_t0,r1_t1,r1_t2,kubectl_cmds,notes\n"
            "s1,manual,A,1,1,2,3,4,1,0.8,1,4,mock\n"
            "s1,gitops,A,1,1,1.5,2,3,1,0.7,1,1,mock\n",
            encoding="utf-8",
        )

        result = self.invoke(source, "--legacy-synthetic-csv")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SYNTHETIC LEGACY CSV — NOT EMPIRICAL", result.stdout)
        self.assertIn("SYNTHETIC LEGACY CSV — NOT EMPIRICAL", (self.out / "descriptives.tex").read_text())
        self.assertIn(b"SYNTHETIC MOCK DATA", (self.out / "boxplot_td_A.png").read_bytes())

    def test_holm_adjustment_matches_hand_calculation(self):
        adjust = getattr(analyze, "holm_adjust", None)
        self.assertTrue(callable(adjust), "v2 comparisons need a Holm step-down adjustment")

        self.assertEqual(adjust([0.01, 0.04, 0.03]), [0.03, 0.06, 0.06])

    def test_unapproved_comparison_policy_is_refused(self):
        run = run_record()
        policy = {
            "policy_id": "unapproved-test",
            "approved": False,
            "approval_reference": "",
            "prespecified": True,
            "independence_confirmed": True,
            "independence_basis": "test only",
            "collection_run_ids": [run["run_id"]],
            "holm_family": [{"subject": "s1", "scenario": "A", "metric": "detection"}],
        }
        path = self.write_json(self.root / "policy.json", policy)

        with self.assertRaisesRegex(ValueError, "not approved"):
            analyze._load_comparison_policy(path, [run])

    def test_approved_comparison_policy_reports_hand_checked_effect_and_holm_p(self):
        runs = [
            formal_comparison_record("manual", 1, 5, 6, 9),
            formal_comparison_record("manual", 2, 6, 7, 10),
            formal_comparison_record("gitops", 1, 2, 3, 4),
            formal_comparison_record("gitops", 2, 3, 4, 5),
        ]
        source = self.root / "formal-test-records"
        for index, run in enumerate(runs):
            self.write_json(source / f"run-{index}.json", run)
        family = [
            {"subject": "synthetic-policy-test-subject", "scenario": "A", "metric": "detection"},
            {"subject": "synthetic-policy-test-subject", "scenario": "A", "metric": "recovery"},
        ]
        policy_path = self.write_json(self.root / "approved-test-policy.json", approved_policy(runs, family))

        result = self.invoke(
            source,
            "--schema-version",
            "2",
            "--phase",
            "formal",
            "--exploratory-comparisons",
            "--policy",
            str(policy_path),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.out / "analysis-v2.json").read_text(encoding="utf-8"))
        self.assertIn("AUTHORIZATION NOT VERIFIED", report["label"])
        comparisons = report["exploratory_comparisons"]["tests"]
        self.assertEqual(len(comparisons), 2)
        for test in comparisons:
            self.assertAlmostEqual(test["u_two_sided"], 4.0)
            self.assertAlmostEqual(test["p_two_sided"], 1 / 3)
            self.assertAlmostEqual(test["p_holm"], 2 / 3)
            self.assertAlmostEqual(test["cliffs_delta_manual_minus_gitops"], 1.0)
            self.assertGreaterEqual(test["p_holm"], test["p_two_sided"])

    def test_comparison_policy_rejects_censored_cell_without_partial_report(self):
        runs = [
            formal_comparison_record("manual", 1, 5, 6, 9),
            formal_comparison_record("manual", 2, 6, 7, 10),
            formal_comparison_record("gitops", 1, 2, 3, 4),
            formal_comparison_record("gitops", 2, 3, 4, 5),
        ]
        runs[1].update(
            status="timeout",
            td_mono_s=None,
            te_mono_s=None,
            detection_status="right_censored",
            evidence_status="right_censored",
            evidence=[],
        )
        source = self.root / "formal-test-records"
        for index, run in enumerate(runs):
            self.write_json(source / f"run-{index}.json", run)
        policy = approved_policy(
            runs,
            [{"subject": "synthetic-policy-test-subject", "scenario": "A", "metric": "detection"}],
        )
        policy_path = self.write_json(self.root / "approved-test-policy.json", policy)

        result = self.invoke(
            source,
            "--schema-version",
            "2",
            "--phase",
            "formal",
            "--exploratory-comparisons",
            "--policy",
            str(policy_path),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("complete observed runs", result.stderr.lower())
        self.assertFalse(self.out.exists())

    def test_comparison_policy_rejects_f_and_r1_without_partial_report(self):
        runs = [
            formal_comparison_record("manual", 1, 5, 6, 9),
            formal_comparison_record("gitops", 1, 2, 3, 4),
        ]
        source = self.root / "formal-test-records"
        for index, run in enumerate(runs):
            self.write_json(source / f"run-{index}.json", run)
        forbidden = (
            {"subject": "synthetic-policy-test-subject", "scenario": "F", "metric": "detection"},
            {"subject": "synthetic-policy-test-subject", "scenario": "A", "metric": "r1_recovered_pct"},
        )
        for index, family_item in enumerate(forbidden):
            with self.subTest(family_item=family_item):
                self.out = self.root / f"reports-{index}"
                policy_path = self.write_json(
                    self.root / f"policy-{index}.json",
                    approved_policy(runs, [family_item]),
                )

                result = self.invoke(
                    source,
                    "--schema-version",
                    "2",
                    "--phase",
                    "formal",
                    "--exploratory-comparisons",
                    "--policy",
                    str(policy_path),
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("non-f scenarios", result.stderr.lower())
                self.assertFalse(self.out.exists())

    def test_cliffs_delta_direction_is_manual_minus_gitops(self):
        self.assertEqual(analyze.cliff_delta([1.0, 2.0], [3.0, 4.0]), -1.0)

    def test_producer_partial_endpoints_remain_independently_reportable(self):
        cases = [
            {"status": "injection_failed", "td_mono_s": None, "te_mono_s": None,
             "tr_mono_s": None, "detection_status": "not_evaluable",
             "evidence_status": "not_evaluable", "recovery_status": "not_evaluable"},
            {"status": "instrumentation_failed", "td_mono_s": None, "te_mono_s": None,
             "detection_status": "right_censored", "evidence_status": "not_evaluable"},
            {"status": "correction_failed", "te_mono_s": None, "tr_mono_s": None,
             "evidence_status": "not_evaluable", "recovery_status": "not_evaluable"},
            {"status": "complete", "scenario": "F", "td_mono_s": None,
             "te_mono_s": None, "tr_mono_s": None, "detection_status": "right_censored",
             "evidence_status": "not_evaluable", "recovery_status": "not_evaluable"},
        ]
        for index, changes in enumerate(cases):
            with self.subTest(status=changes["status"]):
                record = run_record(evidence=[], **changes)
                source = self.write_json(self.root / f"partial-{index}.json", record)
                runs = analyze.load_v2_runs(source, "fixture")
                self.assertEqual(runs[0]["status"], changes["status"])


if __name__ == "__main__":
    unittest.main()
