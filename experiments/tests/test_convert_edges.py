"""Edge coverage for the archival CSV bridge; no cluster or network access."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "live"
sys.path.insert(0, str(LIVE))

import convert  # noqa: E402


class ConvertEdgesTest(unittest.TestCase):
    def test_numbers_keep_integer_float_and_fallback_forms(self):
        self.assertEqual(convert._number(None), "")
        self.assertEqual(convert._number(7), "7")
        self.assertEqual(convert._number(2.5), "2.5")
        self.assertEqual(convert._number(True), "True")

    def test_notes_include_dry_run_and_sanitized_error(self):
        notes = convert._notes(
            {
                "status": "dry_run",
                "dry_run": True,
                "error": "bad;value",
                "detection_controller": None,
            }
        )
        self.assertIn("dry_run_no_cluster_access", notes)
        self.assertIn("error=bad,value", notes)

    def test_row_maps_imperative_env_and_missing_values(self):
        row = convert.row_to_csv({"arm": "imperative", "scenario": "B", "rep": 3})
        self.assertEqual(row["env"], "manual")
        self.assertEqual(row["t0"], "")
        self.assertEqual(row["subject"], "invenio-live")

    def test_row_keeps_explicit_env_and_float_values(self):
        row = convert.row_to_csv(
            {"env": "gitops", "scenario": "A", "rep": 1, "injection_seconds": 0.25}
        )
        self.assertEqual(row["env"], "gitops")
        self.assertEqual(row["t0"], "0.25")

    def test_write_csv_creates_parent_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "rows.csv"
            convert.write_csv([{"arm": "imperative", "scenario": "C", "rep": 2}], target)
            with target.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["env"], "manual")

    def test_main_writes_csv_from_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rows.jsonl"
            target = Path(directory) / "rows.csv"
            source.write_text(json.dumps({"arm": "gitops", "scenario": "D", "rep": 1}) + "\n")
            self.assertEqual(convert.main(["--in", str(source), "--out", str(target)]), 0)
            self.assertTrue(target.exists())

    def test_main_rejects_empty_or_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rows.jsonl"
            target = Path(directory) / "rows.csv"
            for text in ("", "{not-json}\n"):
                source.write_text(text)
                self.assertEqual(convert.main(["--in", str(source), "--out", str(target)]), 1)
            self.assertEqual(
                convert.main(["--in", str(Path(directory) / "missing"), "--out", str(target)]),
                1,
            )


if __name__ == "__main__":
    unittest.main()
