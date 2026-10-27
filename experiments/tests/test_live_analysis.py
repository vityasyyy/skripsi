import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

import analyze_live  # noqa: E402


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


class LiveAnalysisTest(unittest.TestCase):
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
        raw.append({
            "run_id": "failed-run", "batch_id": BATCH, "batch_mode": "live",
            "scenario": "C", "arm": "imperative", "rep": 3,
            "status": "invalid_injection", "cleanup_status": "ok",
            "arm_restore_status": "restored", "synthetic": False,
            "error": "token=supersecretvalue",
        })
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


if __name__ == "__main__":
    unittest.main()
