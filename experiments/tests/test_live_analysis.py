import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "live"))

import analyze_live  # noqa: E402
import run_matrix  # noqa: E402


REVISION = "a" * 40
RENDER = "b" * 64
BATCH = "synthetic-batch"


def observation(value, censor=10.0):
    if value is None:
        return None, "right_censored"
    return float(value), "observed"


def make_row(scenario, arm, rep, *, detection=2.0, evidence=3.0,
             recovery=5.0, censor=10.0, batch_id=BATCH, **overrides):
    env = "manual" if arm == "imperative" else "gitops"
    row = {
        "schema_version": 2,
        "run_id": f"{batch_id}-{arm}-{scenario}-r{rep:02d}",
        "batch_id": batch_id,
        "batch_phase": "R2" if rep <= 10 else "R1",
        "batch_mode": "live",
        "scenario": scenario,
        "arm": arm,
        "env": env,
        "rep": rep,
        "analysis_group": ("hpa_control" if scenario == "A" else
                           "visibility_boundary" if scenario == "F" else
                           "managed_drift"),
        "efficacy_eligible": scenario not in ("A", "F"),
        "synthetic": False,
        "status": "observed" if recovery is not None else "right_censored",
        "censor_seconds": censor,
        "r1_baseline": 100.0,
        "r1_first": 100.0,
        "r1_last": 100.0,
        "source_revision": REVISION,
        "render_sha256": RENDER,
        "formal_execution_approved": True,
        "stack_isolated": False,
        "r3_status": "not_measured",
    }
    for metric, value in (("detection", detection), ("evidence", evidence),
                          ("recovery", recovery)):
        row[metric + "_seconds"], row[metric + "_status"] = observation(
            value, censor)
    row.update(overrides)
    return row


def paired_batch(scenario="B", reps=range(1, 11), offset=2.0):
    rows = []
    for rep in reps:
        rows.append(make_row(scenario, "imperative", rep,
                             detection=2.0 + offset + rep / 10,
                             evidence=3.0 + offset + rep / 10,
                             recovery=5.0 + offset + rep / 10))
        rows.append(make_row(scenario, "gitops", rep,
                             detection=2.0 + rep / 100,
                             evidence=3.0 + rep / 100,
                             recovery=5.0 + rep / 100))
    return rows


def retry_row(scenario="C", arm="imperative", rep=4, attempt=1,
              *, batch_id=BATCH, **overrides):
    base_id = f"{batch_id}-{arm}-{scenario}-r{rep:02d}"
    identity = {
        "run_id": base_id if attempt == 0 else f"{base_id}-retry{attempt}",
        "batch_attempt": attempt,
        "batch_retry_of": None if attempt == 0 else base_id,
    }
    identity.update(overrides)
    return make_row(scenario, arm, rep, batch_id=batch_id, **identity)


def harness_row(scenario, arm, rep, *, status="observed", detection=2.0,
                evidence=3.0, recovery=5.0, censor=10.0, **overrides):
    row = {
        "schema_version": 2,
        "run_id": None,
        "synthetic": False,
        "formal_execution_approved": False,
        "timing_convention": analyze_live.TIMING_CONVENTION,
        "env": arm,
        "arm": arm,
        "scenario": scenario,
        "rep": rep,
        "analysis_group": ("hpa_control" if scenario == "A" else
                           "visibility_boundary" if scenario == "F" else
                           "managed_drift"),
        "efficacy_eligible": scenario not in ("A", "F"),
        "status": status,
        "censor_seconds": censor,
        "r1_baseline": 100.0,
        "r1_first": 100.0,
        "r1_last": 100.0,
        "source_revision": REVISION,
        "render_sha256": RENDER,
        "cleanup_status": "ok",
        "arm_restore_status": "restored",
        "mutations_executed": 0 if status == "baseline_failure" else 1,
        "postcondition": {"verified": True},
        "t0_utc": None,
    }
    for metric, value in (("detection", detection), ("evidence", evidence),
                          ("recovery", recovery)):
        if status == "baseline_failure":
            row[metric + "_seconds"] = None
            row[metric + "_status"] = "not_observed"
        else:
            row[metric + "_seconds"], row[metric + "_status"] = observation(
                value, censor)
    row.update(overrides)
    return row


class RunnerArguments:
    live = True
    production_like = True


def runner_view(batch_id, statuses, *, arm="gitops", scenario="C", rep=4,
                metrics=None):
    """Build rows with run_matrix.annotate_row, then its real analysis view."""
    base_id = f"{batch_id}-{arm}-{scenario}-r{rep:02d}"
    entry = {
        "index": 0,
        "arm": arm,
        "scenario": scenario,
        "rep": rep,
        "phase": "R2" if rep <= 10 else "R1",
        "run_id": base_id,
        "status": statuses[-1],
        "stop_reason": None,
        "attempts": [],
    }
    rows = []
    for number, status in enumerate(statuses):
        run_id = base_id if number == 0 else f"{base_id}-retry{number}"
        attempt = {
            "attempt": number,
            "run_id": run_id,
            "retry_of": base_id if number else None,
            "status": status,
        }
        entry["attempts"].append(attempt)
        payload = dict((metrics or {}).get(number, {}))
        row = harness_row(scenario, arm, rep, status=status, **payload)
        row["run_id"] = run_id
        rows.append(run_matrix.annotate_row(
            row, entry, RunnerArguments(), batch_id, attempt))
    analysis_rows, exclusions = run_matrix._analysis_view(
        {"runs": [entry]}, rows)
    return analysis_rows, rows, exclusions


def entry(result, scenario, metric):
    for item in result["efficacy"]:
        if item["scenario"] == scenario and item["metric"] == metric:
            return item
    raise AssertionError(f"missing efficacy entry {scenario}/{metric}")


def survival(result, scenario, arm, metric):
    for item in result["survival"]:
        if (item["scenario"], item["arm"], item["metric"]) == (
                scenario, arm, metric):
            return item
    raise AssertionError(f"missing survival entry {scenario}/{arm}/{metric}")


def completed_row(scenario, arm, rep, *, detection=2.0, evidence=3.0,
                  recovery=5.0, detection_status=None, evidence_status=None,
                  stop_reason=None, convention=analyze_live.TIMING_CONVENTION,
                  **overrides):
    row = make_row(scenario, arm, rep, detection=detection,
                   evidence=evidence, recovery=recovery, **overrides)
    row["timing_convention"] = convention
    if detection is None:
        row["detection_status"] = detection_status or "unobserved_before_stop"
    if evidence is None:
        row["evidence_status"] = evidence_status or "unobserved_before_stop"
    row["stop_reason"] = stop_reason or (
        "recovery" if recovery is not None else "timeout")
    row["t0_mono"] = 100.0
    row["t_a_mono"] = 100.1
    row["t_d_mono"] = None if detection is None else 100.0 + detection
    row["t_e_mono"] = None if evidence is None else 100.0 + evidence
    row["t_r_mono"] = None if recovery is None else 100.0 + recovery
    row["t_r_first_mono"] = row["t_r_mono"]
    row["t_r_confirmed_mono"] = (
        None if recovery is None else 100.0 + recovery + 1.0)
    row["t_e_store_mono"] = (
        None if evidence is None else 100.0 + evidence + 0.1)
    return row


class LiveAnalysisTest(unittest.TestCase):
    def test_timing_convention_matches_the_runner_contract(self):
        self.assertEqual(analyze_live.TIMING_CONVENTION,
                         run_matrix.TIMING_CONVENTION)

    def test_complete_pairs_use_wilcoxon_signed_rank(self):
        result = analyze_live.analyze(paired_batch(), bootstrap=200, seed=7)
        item = entry(result, "B", "detection")
        self.assertEqual(item["pairing"]["method"], "paired")
        self.assertEqual(item["analysis_set"], "paired_complete_blocks")
        self.assertEqual(item["test"]["name"], "wilcoxon_signed_rank")
        self.assertEqual(item["test"]["n_pairs"], 10)
        self.assertEqual(item["test"]["n_nonzero"], 10)
        self.assertLess(item["test"]["p_value"], 0.01)
        self.assertGreater(item["effect"]["median_paired_difference"], 0.0)
        self.assertGreater(item["effect"]["cliffs_delta"], 0.9)

    def test_small_complete_pair_block_stays_paired(self):
        result = analyze_live.analyze(paired_batch(reps=range(1, 5)),
                                      bootstrap=100, seed=7)
        item = entry(result, "B", "detection")
        self.assertEqual(item["pairing"]["method"], "paired")
        self.assertEqual(item["test"]["n_pairs"], 4)

    def test_censored_pair_falls_back_to_exploratory_mann_whitney(self):
        rows = paired_batch()
        rows = [row for row in rows
                if not (row["arm"] == "gitops" and row["scenario"] == "B"
                        and row["rep"] == 5)]
        rows.append(make_row("B", "gitops", 5, recovery=None))
        result = analyze_live.analyze(rows, bootstrap=200, seed=7)
        item = entry(result, "B", "recovery")
        self.assertEqual(item["pairing"]["method"], "unpaired")
        self.assertIn("censored", item["pairing"]["reason"])
        self.assertEqual(item["analysis_set"], "observed_values_only")
        self.assertIn("censoring is not adjusted", item["note"])
        self.assertEqual(item["test"]["name"], "mann_whitney_u")
        self.assertEqual(item["test"]["n_manual"], 10)
        self.assertEqual(item["test"]["n_gitops"], 9)
        censored = survival(result, "B", "gitops", "recovery")
        self.assertEqual(censored["events"], 9)
        self.assertEqual(censored["censored"], 1)
        self.assertIsNotNone(censored["median_seconds"])
        self.assertLess(censored["median_seconds"], 10.0)
        # Detection pairs are still complete and stay paired.
        self.assertEqual(entry(result, "B", "detection")["pairing"]["method"],
                         "paired")

    def test_kaplan_meier_and_rmst_never_impute_censored_as_zero(self):
        curve = analyze_live.kaplan_meier([1.0, 2.0], [4.0], horizon=4.0)
        self.assertAlmostEqual(curve["rmst_seconds"], 1 + 2 / 3 + 2 / 3)
        self.assertEqual(curve["events"], 2)
        self.assertEqual(curve["censored"], 1)
        self.assertEqual(curve["median_seconds"], 2.0)
        self.assertTrue(curve["median_reached"])

        all_censored = analyze_live.kaplan_meier([], [5.0, 5.0], horizon=5.0)
        self.assertEqual(all_censored["events"], 0)
        self.assertEqual(all_censored["censored"], 2)
        self.assertIsNone(all_censored["median_seconds"])
        self.assertFalse(all_censored["median_reached"])
        self.assertAlmostEqual(all_censored["rmst_seconds"], 5.0)

        rows = []
        for rep in range(1, 6):
            rows.append(make_row("A", "imperative", rep, recovery=float(rep)))
        for rep in (1, 3, 4, 5):
            rows.append(make_row("A", "gitops", rep, recovery=float(rep)))
        rows.append(make_row("A", "gitops", 2, recovery=None))
        result = analyze_live.analyze(rows, bootstrap=100, seed=7)
        item = survival(result, "A", "gitops", "recovery")
        self.assertEqual(item["censored"], 1)
        self.assertEqual(item["events"], 4)
        self.assertAlmostEqual(item["rmst_seconds"], 4.6)

    def test_control_boundary_and_g_are_outside_efficacy(self):
        rows = []
        for scenario in ("A", "B", "F", "G"):
            rows.extend(paired_batch(scenario=scenario, reps=range(1, 6)))
        result = analyze_live.analyze(rows, bootstrap=100, seed=7)
        self.assertEqual({item["scenario"] for item in result["efficacy"]}
                         & {"A", "F", "G"}, set())
        self.assertIn("B", {item["scenario"] for item in result["efficacy"]})
        populations = {item["scenario"]: item["population"]
                       for item in result["survival"]}
        self.assertEqual(populations["A"], "hpa_control")
        self.assertEqual(populations["F"], "visibility_boundary")
        self.assertEqual(populations["G"], "descriptive_non_argo")
        self.assertIn("G", result["batch"]["efficacy_ineligible"])
        self.assertIn("A", result["batch"]["efficacy_ineligible"])
        self.assertIn("F", result["batch"]["efficacy_ineligible"])
        self.assertEqual(
            result["batch"]["analysis_group_by_scenario"]["G"],
            "managed_drift")
        self.assertEqual(
            result["batch"]["population_by_scenario"]["G"],
            "descriptive_non_argo")
        self.assertIn("R3: not measured", result["r3"]["statement"])

    def test_holm_adjustment_uses_predeclared_family(self):
        self.assertEqual(
            analyze_live.holm_adjust([0.01, 0.02, 0.03, 0.04], 4),
            [0.04, 0.06, 0.06, 0.06])
        self.assertEqual(
            analyze_live.holm_adjust([0.01, 0.02, 0.03, 0.04], 12)[0], 0.12)
        result = analyze_live.analyze(paired_batch(), bootstrap=100, seed=7)
        family = result["families"][0]
        self.assertEqual(family["predeclared_size"], 12)
        self.assertEqual(family["id"], "r2_efficacy_managed_drift")
        self.assertIn("12", result["method"]["holm_family"])
        for item in result["efficacy"]:
            if item["test"]["p_value"] is None:
                self.assertIsNone(item["holm_adjusted_p"])
                continue
            self.assertGreaterEqual(item["holm_adjusted_p"],
                                    item["test"]["p_value"])
            self.assertIsInstance(item["reject_holm"], bool)

    def test_bootstrap_is_deterministic_for_a_fixed_seed(self):
        first = analyze_live.analyze(paired_batch(), bootstrap=300, seed=123)
        second = analyze_live.analyze(paired_batch(), bootstrap=300, seed=123)
        self.assertEqual(first["efficacy"], second["efficacy"])

    def test_invalid_schema_fails_closed(self):
        cases = {}

        missing = paired_batch(reps=range(1, 2))
        del missing[0]["detection_seconds"]
        cases["missing_field"] = missing

        observed_none = paired_batch(reps=range(1, 2))
        observed_none[0]["detection_seconds"] = None
        cases["observed_without_value"] = observed_none

        censored_zero = paired_batch(reps=range(1, 2))
        censored_zero.append(make_row("B", "gitops", 2))
        censored_zero[-1]["detection_status"] = "right_censored"
        censored_zero[-1]["detection_seconds"] = 0.0
        cases["censored_as_zero"] = censored_zero

        unobserved = paired_batch(reps=range(1, 2))
        unobserved[0]["detection_status"] = "unobserved_before_stop"
        cases["unobserved_before_stop"] = unobserved

        duplicate = paired_batch(reps=range(1, 2))
        duplicate.append(dict(duplicate[0], run_id="duplicate-run"))
        cases["duplicate_block"] = duplicate

        wrong_env = paired_batch(reps=range(1, 2))
        wrong_env[0]["env"] = "gitops"
        cases["wrong_env_mapping"] = wrong_env

        dry_run = paired_batch(reps=range(1, 2))
        dry_run[0]["batch_mode"] = "dry_run"
        cases["dry_run"] = dry_run

        bad_phase = paired_batch(reps=range(1, 2))
        bad_phase[0]["batch_phase"] = "R1"
        cases["phase_mismatch"] = bad_phase

        bad_rep = paired_batch(reps=range(1, 2))
        bad_rep[0]["rep"] = 16
        cases["rep_out_of_range"] = bad_rep

        synthetic = paired_batch(reps=range(1, 2))
        synthetic[0]["synthetic"] = True
        cases["synthetic"] = synthetic

        bad_revision = paired_batch(reps=range(1, 2))
        bad_revision[0]["source_revision"] = "not-a-revision"
        cases["bad_revision"] = bad_revision

        mixed_batches = paired_batch(reps=range(1, 2))
        mixed_batches[1]["batch_id"] = "other-batch"
        mixed_batches[1]["run_id"] = "other-batch-gitops-B-r01"
        cases["mixed_batches"] = mixed_batches

        mismatched_identity = paired_batch(reps=range(1, 2))
        mismatched_identity[0]["run_id"] = "wrong-run-id"
        cases["run_id_mismatch"] = mismatched_identity

        for label, rows in cases.items():
            with self.subTest(label):
                with self.assertRaises(analyze_live.LiveAnalysisError):
                    analyze_live.analyze(rows, bootstrap=100, seed=1)

    def test_r1_descriptives_report_missing_values(self):
        rows = paired_batch(reps=range(11, 13))
        rows[1]["r1_first"] = None
        rows[1]["r1_last"] = 90.0
        result = analyze_live.analyze(rows, bootstrap=100, seed=1)
        group = next(item for item in result["r1"]
                     if item["scenario"] == "B" and item["arm"] == "gitops"
                     and item["phase"] == "R1")
        self.assertEqual(group["rows"], 2)
        self.assertEqual(group["first"]["missing"], 1)
        self.assertEqual(group["last"]["missing"], 0)
        self.assertAlmostEqual(group["last"]["median"], 95.0)

    def test_exclusions_are_minimal_and_outputs_never_echo_raw_values(self):
        rows = paired_batch(reps=range(1, 2))
        raw = [dict(row) for row in rows]
        raw.append(make_row(
            "C", "imperative", 3, status="invalid_injection",
            cleanup_status="ok", arm_restore_status="restored",
            error="token=supersecretvalue"))
        result = analyze_live.analyze(rows, raw_rows=raw, bootstrap=100, seed=1)
        self.assertEqual(result["exclusions"]["count"], 1)
        self.assertEqual(result["exclusions"]["by_reason"],
                         {"status_not_analyzable": 1})
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.analyze(rows, raw_rows=raw[-1:], bootstrap=100, seed=1)
        serialized = json.dumps(result)
        self.assertNotIn("supersecretvalue", serialized)
        self.assertNotIn("supersecretvalue", json.dumps(
            result["exclusions"]))

        with tempfile.TemporaryDirectory() as directory:
            paths = analyze_live.write_outputs(result, Path(directory))
            overview = Path(paths["overview"]).read_text()
            survival_tex = Path(paths["survival"]).read_text()
            self.assertIn("R3: not measured", overview)
            self.assertIn("Eksklusi", overview)
            self.assertIn("Tersensor", survival_tex)
            for path in paths.values():
                self.assertNotIn("supersecretvalue", Path(path).read_text())

    def test_excluded_counts_normalize_the_imperative_arm(self):
        rows = paired_batch(reps=range(1, 3))
        raw = [dict(row) for row in rows]
        raw.append(make_row("B", "imperative", 3,
                            status="instrumentation_failure"))
        result = analyze_live.analyze(
            rows, raw_rows=raw, bootstrap=100, seed=1)
        overview = next(item for item in result["overview"]
                        if item["scenario"] == "B" and item["arm"] == "manual")
        self.assertEqual(overview["metrics"]["detection"]["excluded"], 1)
        curve = survival(result, "B", "manual", "detection")
        self.assertEqual(curve["excluded_runs"], 1)

    def test_mixed_censor_limits_are_administratively_censored(self):
        rows = []
        for rep in range(1, 6):
            rows.append(make_row("B", "imperative", rep, detection=5.0,
                                 censor=20.0 if rep != 2 else 10.0))
            rows.append(make_row("B", "gitops", rep, detection=3.0,
                                 censor=20.0))
        rows[0]["detection_seconds"] = 15.0
        result = analyze_live.analyze(rows, bootstrap=100, seed=1)
        item = survival(result, "B", "manual", "detection")
        self.assertEqual(item["censor_limits_seconds"], [10.0, 20.0])
        self.assertEqual(item["horizon_seconds"], 10.0)
        self.assertEqual(item["events"], 4)
        self.assertEqual(item["censored"], 1)
        self.assertEqual(item["administratively_censored"], 1)

    def test_all_censored_horizon_is_finite(self):
        rows = [make_row("B", "gitops", rep, detection=None, evidence=None,
                         recovery=None, censor=30.0)
                for rep in range(1, 6)]
        result = analyze_live.analyze(rows, bootstrap=100, seed=1)
        item = survival(result, "B", "gitops", "recovery")
        self.assertEqual(item["censored"], 5)
        self.assertIsNone(item["median_seconds"])
        self.assertAlmostEqual(item["rmst_seconds"], 30.0)
        self.assertAlmostEqual(item["horizon_seconds"], 30.0)
        self.assertTrue(math.isfinite(item["rmst_seconds"]))


    def test_cli_writes_json_and_latex_tables(self):
        rows = paired_batch(reps=range(1, 3))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "batch.analysis.jsonl"
            source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            output = Path(directory) / "out"
            result = subprocess.run(
                [sys.executable, str(ROOT / "analysis/analyze_live.py"),
                 "--in", str(source), "--out", str(output),
                 "--bootstrap", "100", "--seed", "1"],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("OK:", result.stdout)
            for name in ("live_analysis.json", "live_overview.tex",
                         "live_exclusions.tex", "live_r1.tex",
                         "live_survival.tex", "live_tests.tex",
                         "live_effects.tex"):
                self.assertTrue((output / name).is_file(), name)
            self.assertNotIn("secret", result.stdout + result.stderr)


    def test_missing_detection_at_confirmed_early_recovery_is_not_censored(self):
        rows = []
        for rep in range(1, 6):
            rows.append(completed_row("B", "imperative", rep,
                                      detection=None, evidence=None))
            rows.append(completed_row("B", "gitops", rep,
                                      detection=None, evidence=None,
                                      recovery=5.1))
        result = analyze_live.analyze(
            rows, raw_rows=[dict(row) for row in rows],
            bootstrap=100, seed=1)
        item = entry(result, "B", "detection")
        self.assertEqual(item["pairing"]["method"], "unpaired")
        self.assertEqual(item["pairing"]["reason"], "missing_blocks")
        self.assertEqual(item["pairing"]["missing_blocks"], 5)
        self.assertEqual(item["endpoints"]["manual"]["missing"], 5)
        self.assertEqual(item["endpoints"]["gitops"]["missing"], 5)
        self.assertEqual(item["test"]["name"], "not_estimable")
        self.assertIsNone(item["test"]["p_value"])
        self.assertIn("Missing endpoints", item["note"])
        curve = survival(result, "B", "manual", "detection")
        self.assertEqual(curve["missing"], 5)
        self.assertEqual(curve["censored"], 0)
        self.assertEqual(curve["n"], 0)
        self.assertFalse(curve["estimable"])
        self.assertIsNone(curve["rmst_seconds"])
        self.assertIn("not estimable", curve["note"])
        self.assertNotIn("all observations censored", curve["note"])
        recovery = entry(result, "B", "recovery")
        self.assertEqual(recovery["test"]["name"], "wilcoxon_signed_rank")
        self.assertEqual(result["batch"]["timing_convention"],
                         analyze_live.TIMING_CONVENTION)

    def test_missing_metric_without_early_stop_provenance_is_rejected(self):
        for override in ({"stop_reason": "timeout"},
                         {"recovery_status": "right_censored"},
                         {"status": "right_censored"}):
            with self.subTest(override=override):
                row = completed_row("B", "gitops", 1, detection=None)
                row.update(override)
                with self.assertRaises(analyze_live.LiveAnalysisError):
                    analyze_live.validate_rows([row])

    def test_mixed_and_unknown_timing_conventions_fail_closed(self):
        rows = [completed_row("B", "gitops", 1),
                make_row("B", "imperative", 1)]
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.validate_rows(rows)
        unknown = completed_row("B", "gitops", 1,
                                convention="legacy-observation-v0")
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.validate_rows([unknown])

    def test_raw_and_analysis_timing_markers_must_agree(self):
        rows = [completed_row("B", "gitops", 1)]
        raw = [dict(rows[0])]
        del raw[0]["timing_convention"]
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.analyze(rows, raw_rows=raw, bootstrap=100, seed=1)
        raw = [dict(rows[0])]
        raw[0]["timing_convention"] = "legacy-observation-v0"
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.analyze(rows, raw_rows=raw, bootstrap=100, seed=1)
        excluded = completed_row("B", "gitops", 2)
        excluded["status"] = "invalid_injection"
        excluded["timing_convention"] = "legacy-observation-v0"
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.analyze(rows, raw_rows=[dict(rows[0]), excluded],
                                 bootstrap=100, seed=1)
        raw = [dict(rows[0])]
        raw[0]["t_d_mono"] = 101.0
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.analyze(rows, raw_rows=raw, bootstrap=100, seed=1)

    def test_tampered_timing_bounds_fail_closed(self):
        cases = (
            {"t_d_mono": 101.0},
            {"t_r_mono": 111.0},
            {"t_r_confirmed_mono": 104.0},
            {"t_a_mono": 99.0},
        )
        for override in cases:
            with self.subTest(override=override):
                row = completed_row("B", "gitops", 1)
                row.update(override)
                with self.assertRaises(analyze_live.LiveAnalysisError):
                    analyze_live.validate_rows([row])

    def test_survival_table_reports_missing_and_excluded_endpoints(self):
        rows = [completed_row("B", "gitops", rep, detection=None)
                for rep in range(1, 4)]
        result = analyze_live.analyze(rows, bootstrap=100, seed=1)
        with tempfile.TemporaryDirectory() as directory:
            paths = analyze_live.write_outputs(result, Path(directory))
            survival_tex = Path(paths["survival"]).read_text()
            self.assertIn("Hilang", survival_tex)
            self.assertIn("Eksklusi", survival_tex)
            self.assertIn("Tidak terestimasi", survival_tex)


class RetryIdentityTest(unittest.TestCase):
    def test_issue_example_retry_identity_is_accepted(self):
        meta = analyze_live.validate_rows([
            retry_row(scenario="C", arm="imperative", rep=14,
                      batch_id="formal-20261027c")])
        self.assertEqual(meta["analysis_rows"], 1)

    def test_base_and_explicit_retry_metadata_are_accepted(self):
        legacy = make_row("C", "imperative", 3)
        explicit = retry_row(scenario="C", arm="gitops", rep=3, attempt=0)
        retry = retry_row(scenario="C", arm="gitops", rep=3, attempt=2)
        self.assertEqual(
            analyze_live.validate_rows([legacy])["analysis_rows"], 1)
        self.assertEqual(
            analyze_live.validate_rows([explicit])["analysis_rows"], 1)
        result = analyze_live.analyze([retry], bootstrap=100, seed=1)
        self.assertEqual(result["batch"]["analysis_rows"], 1)

    def test_censored_retry_is_accepted_as_one_censored_observation(self):
        rows = [retry_row(scenario="C", arm="gitops", rep=4, recovery=None)]
        result = analyze_live.analyze(rows, bootstrap=100, seed=1)
        item = survival(result, "C", "gitops", "recovery")
        self.assertEqual(item["censored"], 1)
        self.assertEqual(item["events"], 0)
        self.assertIsNone(item["median_seconds"])

    def test_runner_retry_flows_through_analysis_view_into_analyzer(self):
        analysis_rows, raw_rows, _ = runner_view(
            "formal-20261027c", ["baseline_failure", "observed"])
        self.assertEqual(
            [row["run_id"] for row in analysis_rows],
            ["formal-20261027c-gitops-C-r04-retry1"])
        result = analyze_live.analyze(
            analysis_rows, raw_rows=raw_rows, bootstrap=100, seed=1)
        self.assertEqual(result["batch"]["analysis_rows"], 1)
        self.assertEqual(result["exclusions"]["count"], 1)
        self.assertEqual(result["exclusions"]["by_reason"],
                         {"status_not_analyzable": 1})
        self.assertEqual(
            sum(item["rows"] for item in result["overview"]), 1)
        self.assertEqual(
            result["exclusions"]["rows"][0]["run_id"],
            "formal-20261027c-gitops-C-r04")

    def test_runner_censored_retry_stays_censored(self):
        analysis_rows, raw_rows, _ = runner_view(
            "formal-20261027c", ["baseline_failure", "right_censored"],
            metrics={1: {"recovery": None}})
        result = analyze_live.analyze(
            analysis_rows, raw_rows=raw_rows, bootstrap=100, seed=1)
        self.assertEqual(result["batch"]["analysis_rows"], 1)
        item = survival(result, "C", "gitops", "recovery")
        self.assertEqual(item["censored"], 1)

    def test_retry_without_metadata_is_rejected(self):
        missing = retry_row()
        del missing["batch_attempt"]
        del missing["batch_retry_of"]
        partial = retry_row()
        del partial["batch_retry_of"]
        for label, row in (("missing", missing), ("partial", partial)):
            with self.subTest(label):
                with self.assertRaises(analyze_live.LiveAnalysisError):
                    analyze_live.validate_rows([row])

    def test_ambiguous_attempt_values_are_rejected(self):
        values = (True, False, 1.0, -1, "1", None, [], {})
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(analyze_live.LiveAnalysisError):
                    analyze_live.validate_rows(
                        [retry_row(batch_attempt=value)])

    def test_mismatched_retry_parent_is_rejected(self):
        row = retry_row()
        row["batch_retry_of"] = "other-batch-gitops-C-r04"
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.validate_rows([row])

    def test_inconsistent_retry_suffix_is_rejected(self):
        row = retry_row(attempt=1)
        row["batch_attempt"] = 2
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.validate_rows([row])

    def test_malformed_retry_suffix_is_rejected(self):
        base_id = f"{BATCH}-imperative-C-r04"
        for suffix in ("-retry0", "-retry01", "-retry", "-retryx",
                       "-retry1x", "-retry-1"):
            with self.subTest(suffix):
                with self.assertRaises(analyze_live.LiveAnalysisError):
                    analyze_live.validate_rows([
                        retry_row(run_id=base_id + suffix)])

    def test_base_id_with_retry_metadata_is_rejected(self):
        base_id = f"{BATCH}-imperative-C-r04"
        cases = (
            {"run_id": base_id, "batch_attempt": 1,
             "batch_retry_of": base_id},
            {"run_id": base_id, "batch_attempt": 0,
             "batch_retry_of": base_id},
        )
        for overrides in cases:
            with self.subTest(overrides):
                with self.assertRaises(analyze_live.LiveAnalysisError):
                    analyze_live.validate_rows([retry_row(**overrides)])

    def test_base_identity_fields_must_match_the_run_id(self):
        cases = (
            ("arm", "gitops"),
            ("scenario", "D"),
            ("rep", 5),
        )
        for field, value in cases:
            with self.subTest(field=field):
                row = retry_row()
                row[field] = value
                if field == "arm":
                    row["env"] = value
                with self.assertRaises(analyze_live.LiveAnalysisError):
                    analyze_live.validate_rows([row])

    def test_duplicate_statistical_cell_rejects_base_plus_retry(self):
        rows = [retry_row(attempt=0), retry_row(attempt=1)]
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.validate_rows(rows)
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.analyze(rows, bootstrap=100, seed=1)

    def test_raw_rows_reject_inconsistent_identity(self):
        analysis_rows, raw_rows, _ = runner_view(
            "formal-20261027c", ["observed"])
        raw_rows[0]["rep"] = 5
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.analyze(
                analysis_rows, raw_rows=raw_rows, bootstrap=100, seed=1)

    def test_raw_rows_reject_duplicate_run_ids(self):
        analysis_rows, raw_rows, _ = runner_view(
            "formal-20261027c", ["observed"])
        raw = raw_rows + [dict(raw_rows[0])]
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.analyze(
                analysis_rows, raw_rows=raw, bootstrap=100, seed=1)

    def test_raw_retry_requires_attempt_metadata(self):
        analysis_rows, raw_rows, _ = runner_view(
            "formal-20261027c", ["baseline_failure", "observed"])
        for row in raw_rows:
            del row["batch_attempt"]
            del row["batch_retry_of"]
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.analyze(
                analysis_rows, raw_rows=raw_rows, bootstrap=100, seed=1)

    def test_raw_retry_chain_requires_predecessor(self):
        analysis_rows, raw_rows, _ = runner_view(
            "formal-20261027c", ["baseline_failure", "observed"])
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.analyze(
                analysis_rows, raw_rows=raw_rows[-1:], bootstrap=100, seed=1)

    def test_raw_retry_chain_rejects_successful_predecessor(self):
        analysis_rows, raw_rows, _ = runner_view(
            "formal-20261027c", ["observed", "observed"])
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.analyze(
                analysis_rows, raw_rows=raw_rows, bootstrap=100, seed=1)

    def test_raw_retry_chain_rejects_non_retryable_baseline(self):
        analysis_rows, raw_rows, _ = runner_view(
            "formal-20261027c", ["baseline_failure", "observed"])
        raw_rows[0]["mutations_executed"] = 1
        with self.assertRaises(analyze_live.LiveAnalysisError):
            analyze_live.analyze(
                analysis_rows, raw_rows=raw_rows, bootstrap=100, seed=1)

    def test_legacy_unsuffixed_rows_without_metadata_keep_working(self):
        rows = paired_batch(reps=range(1, 3))
        raw_rows = [dict(row) for row in rows]
        result = analyze_live.analyze(
            rows, raw_rows=raw_rows, bootstrap=100, seed=1)
        self.assertEqual(result["batch"]["analysis_rows"], 4)
        self.assertEqual(result["exclusions"]["count"], 0)

    def test_cli_reads_analysis_and_raw_retry_inputs_together(self):
        analysis_rows, raw_rows, _ = runner_view(
            "formal-20261027c", ["baseline_failure", "observed"])
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "batch.analysis.jsonl"
            raw = Path(directory) / "batch.rows.jsonl"
            output = Path(directory) / "out"
            source.write_text("\n".join(
                json.dumps(row) for row in analysis_rows) + "\n")
            raw.write_text("\n".join(
                json.dumps(row) for row in raw_rows) + "\n")
            result = subprocess.run(
                [sys.executable, str(ROOT / "analysis/analyze_live.py"),
                 "--in", str(source), "--rows", str(raw),
                 "--out", str(output), "--bootstrap", "100", "--seed", "1"],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(
                (output / "live_analysis.json").read_text())
            self.assertEqual(report["batch"]["analysis_rows"], 1)
            self.assertEqual(report["exclusions"]["count"], 1)


class RawAnalysisConsistencyTest(unittest.TestCase):
    def test_matching_raw_row_accepts_normalized_env(self):
        analysis_rows, raw_rows, _ = runner_view(
            "review-batch", ["observed"], arm="imperative")
        self.assertEqual(raw_rows[0]["env"], "imperative")
        self.assertEqual(analysis_rows[0]["env"], "manual")
        result = analyze_live.analyze(
            analysis_rows, raw_rows=raw_rows, bootstrap=100, seed=1)
        self.assertEqual(result["batch"]["analysis_rows"], 1)

    def test_matching_raw_row_must_agree_on_protocol_and_metrics(self):
        cases = (
            ("source_revision", "c" * 40),
            ("render_sha256", "d" * 64),
            ("batch_phase", "R1"),
            ("recovery_seconds", 9.0),
            ("r1_last", 90.0),
        )
        for field, value in cases:
            with self.subTest(field=field):
                analysis_rows, raw_rows, _ = runner_view(
                    "review-batch", ["observed"])
                raw_rows[0][field] = value
                with self.assertRaises(analyze_live.LiveAnalysisError):
                    analyze_live.analyze(
                        analysis_rows, raw_rows=raw_rows, bootstrap=100,
                        seed=1)

    def test_matching_raw_row_must_not_carry_failed_eligibility(self):
        cases = (
            {"cleanup_status": "failed"},
            {"arm_restore_status": "failed"},
            {"postcondition": {"verified": False}},
            {"synthetic": True},
            {"error": "preserved failure"},
            {"batch_stop_reason": "cleanup_failure"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                analysis_rows, raw_rows, _ = runner_view(
                    "review-batch", ["observed"])
                raw_rows[0].update(overrides)
                with self.assertRaises(analyze_live.LiveAnalysisError):
                    analyze_live.analyze(
                        analysis_rows, raw_rows=raw_rows, bootstrap=100,
                        seed=1)

    def test_analyzed_row_must_not_carry_failed_eligibility(self):
        cases = (
            {"cleanup_status": "failed"},
            {"arm_restore_status": "failed"},
            {"postcondition": {"verified": False}},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                analysis_rows, raw_rows, _ = runner_view(
                    "review-batch", ["observed"])
                analysis_rows[0].update(overrides)
                with self.assertRaises(analyze_live.LiveAnalysisError):
                    analyze_live.analyze(
                        analysis_rows, raw_rows=raw_rows, bootstrap=100,
                        seed=1)

    def test_runner_row_with_missing_detection_survives_into_analysis(self):
        payload = {
            "stop_reason": "recovery",
            "detection_seconds": None,
            "detection_status": "unobserved_before_stop",
            "evidence_seconds": None,
            "evidence_status": "unobserved_before_stop",
            "recovery_seconds": 5.0,
            "recovery_status": "observed",
        }
        analysis_rows, raw_rows, _ = runner_view(
            "review-batch", ["observed"], metrics={0: payload})
        self.assertEqual(analysis_rows[0]["timing_convention"],
                         analyze_live.TIMING_CONVENTION)
        result = analyze_live.analyze(
            analysis_rows, raw_rows=raw_rows, bootstrap=100, seed=1)
        self.assertEqual(result["batch"]["analysis_rows"], 1)
        item = entry(result, "C", "detection")
        self.assertEqual(item["endpoints"]["gitops"]["missing"], 1)
        self.assertEqual(item["pairing"]["reason"], "unmatched_arm_blocks")
        curve = survival(result, "C", "gitops", "detection")
        self.assertFalse(curve["estimable"])
        self.assertEqual(curve["censored"], 0)
        self.assertIsNone(curve["rmst_seconds"])

    def test_runner_rows_preserve_missing_endpoints_end_to_end(self):
        analysis_rows, raw_rows = [], []
        payload = {
            "stop_reason": "recovery",
            "detection_seconds": None,
            "detection_status": "unobserved_before_stop",
            "evidence_seconds": None,
            "evidence_status": "unobserved_before_stop",
            "recovery_seconds": 5.0,
            "recovery_status": "observed",
        }
        for arm in ("imperative", "gitops"):
            for rep in range(1, 6):
                selected, raw, _ = runner_view(
                    "review-batch", ["observed"], arm=arm, rep=rep,
                    metrics={0: payload})
                analysis_rows.extend(selected)
                raw_rows.extend(raw)
        result = analyze_live.analyze(
            analysis_rows, raw_rows=raw_rows, bootstrap=100, seed=1)
        item = entry(result, "C", "detection")
        self.assertEqual(item["pairing"]["reason"], "missing_blocks")
        self.assertEqual(item["pairing"]["missing_blocks"], 5)
        self.assertEqual(item["endpoints"]["manual"]["missing"], 5)
        self.assertEqual(item["endpoints"]["gitops"]["missing"], 5)
        self.assertIsNone(item["test"]["p_value"])
        for arm in ("manual", "gitops"):
            curve = survival(result, "C", arm, "detection")
            self.assertEqual(curve["missing"], 5)
            self.assertEqual(curve["censored"], 0)
            self.assertFalse(curve["estimable"])
            self.assertIsNone(curve["rmst_seconds"])
        recovery = entry(result, "C", "recovery")
        self.assertEqual(recovery["test"]["name"], "wilcoxon_signed_rank")
        self.assertEqual(result["batch"]["analysis_rows"], 10)

    def test_missing_legacy_eligibility_fields_remain_compatible(self):
        analysis_rows, raw_rows, _ = runner_view(
            "review-batch", ["observed"])
        for field in ("cleanup_status", "arm_restore_status",
                      "postcondition"):
            raw_rows[0].pop(field, None)
        result = analyze_live.analyze(
            analysis_rows, raw_rows=raw_rows, bootstrap=100, seed=1)
        self.assertEqual(result["batch"]["analysis_rows"], 1)

    def test_invalid_raw_env_mapping_is_rejected(self):
        for value in ("gitops", []):
            with self.subTest(value=value):
                analysis_rows, raw_rows, _ = runner_view(
                    "review-batch", ["observed"], arm="imperative")
                raw_rows[0]["env"] = value
                with self.assertRaises(analyze_live.LiveAnalysisError):
                    analyze_live.analyze(
                        analysis_rows, raw_rows=raw_rows, bootstrap=100,
                        seed=1)


if __name__ == "__main__":
    unittest.main()
