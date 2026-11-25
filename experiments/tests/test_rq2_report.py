"""Tests for the thesis-facing RQ timing view over the frozen analyzer."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

import analyze_live  # noqa: E402
import rq2_report  # noqa: E402

REVISION = "a" * 40
RENDER = "b" * 64
BATCH = "rq2-fixture"


def make_row(scenario, arm, rep, *, detection=2.0, evidence=3.0, recovery=5.0, **overrides):
    env = "manual" if arm == "imperative" else "gitops"
    row = {
        "schema_version": 2,
        "run_id": f"{BATCH}-{arm}-{scenario}-r{rep:02d}",
        "batch_id": BATCH,
        "batch_phase": "R2" if rep <= 10 else "R1",
        "batch_mode": "live",
        "scenario": scenario,
        "arm": arm,
        "env": env,
        "rep": rep,
        "analysis_group": (
            "hpa_control"
            if scenario == "A"
            else "visibility_boundary"
            if scenario == "F"
            else "managed_drift"
        ),
        "efficacy_eligible": scenario not in ("A", "F"),
        "synthetic": False,
        "status": "observed",
        "censor_seconds": 20.0,
        "r1_baseline": 100.0,
        "r1_first": 75.0,
        "r1_last": 100.0,
        "source_revision": REVISION,
        "render_sha256": RENDER,
        "formal_execution_approved": True,
        "stack_isolated": False,
        "r3_status": "not_measured",
    }
    for metric, value in (("detection", detection), ("evidence", evidence), ("recovery", recovery)):
        row[metric + "_seconds"] = value
        row[metric + "_status"] = "observed" if value is not None else "right_censored"
    row.update(overrides)
    if row["recovery_seconds"] is None:
        row["status"] = "right_censored"
    return row


def matrix():
    rows = []
    for rep in range(1, 11):
        rows.append(
            make_row(
                "B",
                "imperative",
                rep,
                detection=5.0 + rep / 2,
                evidence=6.0 + rep / 2,
                recovery=8.0 + rep,
            )
        )
        rows.append(
            make_row(
                "B",
                "gitops",
                rep,
                detection=2.0 + rep / 10,
                evidence=3.0 + rep / 10,
                recovery=5.0 + rep / 10,
            )
        )
    for rep in range(1, 5):
        rows.append(
            make_row(
                "C",
                "imperative",
                rep,
                detection=4.0 + (rep % 2) / 10,
                evidence=5.0,
                recovery=6.0,
            )
        )
        rows.append(
            make_row(
                "C",
                "gitops",
                rep,
                detection=4.0 + ((rep + 1) % 2) / 10,
                evidence=5.0,
                recovery=6.0,
            )
        )
    completeness = {
        "imperative": [100.0, 75.0, 50.0, 25.0, None],
        "gitops": [100.0, 100.0, 100.0, 100.0, 60.0],
    }
    for arm, values in completeness.items():
        for offset, value in enumerate(values):
            rows.append(
                make_row(
                    "B",
                    arm,
                    11 + offset,
                    r1_last=value,
                    detection=None,
                    evidence=None,
                    recovery=None,
                )
            )
            rows[-1]["detection_status"] = "unobserved_before_stop"
            rows[-1]["evidence_status"] = "unobserved_before_stop"
            rows[-1]["recovery_seconds"] = 4.0
            rows[-1]["recovery_status"] = "observed"
            rows[-1]["status"] = "observed"
            rows[-1]["stop_reason"] = "recovery"
    for rep in range(1, 5):
        rows.append(
            make_row(
                "D",
                "imperative",
                rep,
                detection=5.0 + rep / 10,
                evidence=6.0 + rep / 10,
                recovery=8.0 + rep / 10,
            )
        )
        rows.append(
            make_row(
                "D",
                "gitops",
                rep,
                detection=2.0 + rep / 10,
                evidence=3.0 + rep / 10,
                recovery=None if rep == 1 else 5.0 + rep / 10,
            )
        )
    rows.append(make_row("E", "imperative", 1, detection=5.0, evidence=6.0, recovery=7.0))
    rows[-1]["detection_seconds"] = None
    rows[-1]["detection_status"] = "unobserved_before_stop"
    rows[-1]["evidence_seconds"] = None
    rows[-1]["evidence_status"] = "unobserved_before_stop"
    rows[-1]["stop_reason"] = "recovery"
    rows.append(make_row("G", "gitops", 1, detection=2.0, evidence=3.0, recovery=None, censor=10.0))
    return rows


def analyze(rows, raw_rows=None):
    return analyze_live.analyze(rows, raw_rows, bootstrap=100, seed=11, alpha=0.05)


def write_inputs(directory, rows):
    analysis_path = Path(directory) / "fixture.analysis.jsonl"
    rows_path = Path(directory) / "fixture.rows.jsonl"
    payload = "\n".join(json.dumps(row) for row in rows) + "\n"
    analysis_path.write_text(payload)
    rows_path.write_text(payload)
    return analysis_path, rows_path


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = rq2_report.main(argv)
    return code, out.getvalue(), err.getvalue()


class Rq2ViewTests(unittest.TestCase):
    def test_view_matches_analyzer_for_selected_fields(self):
        rows = matrix()
        result = analyze(rows)
        view = rq2_report.build_view(result, rows)
        self.assertEqual(
            set(view),
            set(rq2_report.RQ_FIELDS)
            | {"schema_version", "view", "recovery_completeness", "repair", "source"},
        )
        for key in ("batch", "exclusions", "efficacy", "families"):
            self.assertEqual(view[key], result[key])
        for key in ("overview", "survival"):
            self.assertEqual(len(view[key]), len(result[key]))
            for produced, source in zip(view[key], result[key]):
                self.assertEqual(produced["legacy_env"], source["arm"])
                self.assertEqual(
                    produced["arm"],
                    "imperative" if source["arm"] == "manual" else "gitops",
                )
                stripped = {
                    name: value
                    for name, value in produced.items()
                    if name not in ("arm", "legacy_env")
                }
                self.assertEqual({**stripped, "arm": source["arm"]}, source)
        self.assertNotIn("r1", view)

    def test_repair_seconds_only_when_both_observed(self):
        entries = rq2_report.repair_entries(matrix())
        by_key = {(item["scenario"], item["arm"]): item for item in entries}
        imperative_b = by_key[("B", "imperative")]
        self.assertEqual(imperative_b["n"], 10)
        self.assertAlmostEqual(imperative_b["median"], 5.75)
        self.assertLessEqual(imperative_b["iqr"][0], imperative_b["median"])
        self.assertGreaterEqual(imperative_b["iqr"][1], imperative_b["median"])
        self.assertAlmostEqual(imperative_b["min"], 3.5)
        self.assertAlmostEqual(imperative_b["max"], 8.0)
        self.assertEqual((imperative_b["censored"], imperative_b["missing"]), (0, 0))
        gitops_d = by_key[("D", "gitops")]
        self.assertEqual(gitops_d["n"], 3)
        self.assertEqual(gitops_d["censored"], 1)
        self.assertIsNotNone(gitops_d["median"])
        self.assertEqual(by_key[("E", "imperative")]["missing"], 1)
        self.assertEqual(by_key[("G", "gitops")]["n"], 0)
        self.assertIsNone(by_key[("G", "gitops")]["iqr"])

    def test_recovery_completeness_counts_levels(self):
        entries = rq2_report.recovery_completeness(matrix())
        by_key = {(item["scenario"], item["arm"]): item for item in entries}
        imperative = by_key[("B", "imperative")]
        self.assertEqual(imperative["counts"], {"100": 1, "75": 1, "50": 1, "25": 1})
        self.assertEqual(imperative["missing"], 1)
        self.assertEqual(imperative["other"], 0)
        self.assertEqual(imperative["rows"], 5)
        gitops = by_key[("B", "gitops")]
        self.assertEqual(gitops["counts"]["100"], 4)
        self.assertEqual(gitops["other"], 1)


class Rq2MainTests(unittest.TestCase):
    def test_writes_rq_tables_without_an_r1_comparison(self):
        rows = matrix()
        with tempfile.TemporaryDirectory() as directory:
            analysis_path, rows_path = write_inputs(directory, rows)
            out = Path(directory) / "out"
            code, stdout, stderr = run_main(
                [
                    "--in",
                    str(analysis_path),
                    "--rows",
                    str(rows_path),
                    "--out",
                    str(out),
                    "--bootstrap",
                    "100",
                    "--seed",
                    "11",
                ]
            )
            self.assertEqual(code, 0, stderr)
            self.assertIn("OK:", stdout)
            names = sorted(path.name for path in out.iterdir())
            self.assertEqual(
                names,
                [
                    "recovery_completeness.tex",
                    "rq2_analysis.json",
                    "rq2_effects.tex",
                    "rq2_overview.tex",
                    "rq2_repair.tex",
                    "rq2_survival.tex",
                    "rq2_tests.tex",
                ],
            )
            self.assertFalse(any("r1" in name for name in names))
            payload = json.loads((out / "rq2_analysis.json").read_text())
            self.assertNotIn("r1", payload)
            self.assertEqual(payload["source"]["frozen_check"], "disabled")
            self.assertEqual(payload["overview"][0]["arm"], "imperative")
            self.assertEqual(payload["overview"][0]["legacy_env"], "manual")
            tests_tex = (out / "rq2_tests.tex").read_text()
            self.assertNotIn("menolak", tests_tex)
            self.assertNotIn("tolak", tests_tex)
            self.assertIn("p < \\alpha", tests_tex)
            repair_tex = (out / "rq2_repair.tex").read_text()
            self.assertIn("Imperatif", repair_tex)
            self.assertIn("GitOps", repair_tex)

    def test_without_rows_exclusions_are_not_counted(self):
        rows = matrix()
        with tempfile.TemporaryDirectory() as directory:
            analysis_path, _ = write_inputs(directory, rows)
            out = Path(directory) / "out"
            code, _, stderr = run_main(
                ["--in", str(analysis_path), "--out", str(out), "--bootstrap", "100"]
            )
            self.assertEqual(code, 0, stderr)
            payload = json.loads((out / "rq2_analysis.json").read_text())
            self.assertIsNone(payload["exclusions"]["count"])
            self.assertIn("tidak dihitung", (out / "rq2_overview.tex").read_text())

    def test_check_frozen_match_and_mismatch(self):
        rows = matrix()
        with tempfile.TemporaryDirectory() as directory:
            analysis_path, rows_path = write_inputs(directory, rows)
            frozen = Path(directory) / "live_analysis.json"
            frozen.write_text(json.dumps(analyze(rows, raw_rows=rows)))
            base = [
                "--in",
                str(analysis_path),
                "--rows",
                str(rows_path),
                "--bootstrap",
                "100",
                "--seed",
                "11",
                "--check-frozen",
                "--frozen",
                str(frozen),
            ]
            code, stdout, stderr = run_main([*base, "--out", str(Path(directory) / "ok")])
            self.assertEqual(code, 0, stderr)
            self.assertIn("frozen: match", stdout)
            payload = json.loads((Path(directory) / "ok" / "rq2_analysis.json").read_text())
            self.assertEqual(payload["source"]["frozen_check"], "match")

            corrupted = analyze(rows, raw_rows=rows)
            corrupted["batch"]["analysis_rows"] += 1
            frozen.write_text(json.dumps(corrupted))
            code, _, stderr = run_main([*base, "--out", str(Path(directory) / "bad")])
            self.assertEqual(code, 1)
            self.assertIn("frozen mismatch: batch", stderr)

    def test_check_frozen_without_the_file_is_pending(self):
        rows = matrix()
        with tempfile.TemporaryDirectory() as directory:
            analysis_path, rows_path = write_inputs(directory, rows)
            out = Path(directory) / "out"
            code, _, stderr = run_main(
                [
                    "--in",
                    str(analysis_path),
                    "--rows",
                    str(rows_path),
                    "--out",
                    str(out),
                    "--bootstrap",
                    "100",
                    "--check-frozen",
                    "--frozen",
                    str(Path(directory) / "absent.json"),
                ]
            )
            self.assertEqual(code, 2)
            self.assertIn("PENDING", stderr)
            payload = json.loads((out / "rq2_analysis.json").read_text())
            self.assertEqual(payload["source"]["frozen_check"], "pending")

    def test_frozen_file_must_be_an_object(self):
        rows = matrix()
        with tempfile.TemporaryDirectory() as directory:
            analysis_path, rows_path = write_inputs(directory, rows)
            frozen = Path(directory) / "live_analysis.json"
            frozen.write_text("[]")
            code, _, stderr = run_main(
                [
                    "--in",
                    str(analysis_path),
                    "--rows",
                    str(rows_path),
                    "--out",
                    str(Path(directory) / "out"),
                    "--bootstrap",
                    "100",
                    "--check-frozen",
                    "--frozen",
                    str(frozen),
                ]
            )
            self.assertEqual(code, 1)
            self.assertIn("must be a JSON object", stderr)

    def test_invalid_input_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _, stderr = run_main(
                [
                    "--in",
                    str(Path(directory) / "absent.jsonl"),
                    "--out",
                    str(Path(directory) / "out"),
                ]
            )
            self.assertEqual(code, 1)
            self.assertIn("Invalid RQ2 view", stderr)

    def test_package_import_uses_relative_modules(self):
        root = str(ROOT.parent)
        sys.path.insert(0, root)
        try:
            from experiments.analysis import rq2_report as package_report

            self.assertTrue(callable(package_report.main))
            self.assertEqual(package_report.RQ_FIELDS, rq2_report.RQ_FIELDS)
        finally:
            sys.path.remove(root)


if __name__ == "__main__":
    unittest.main()
