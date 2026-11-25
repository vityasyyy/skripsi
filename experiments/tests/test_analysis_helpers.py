"""Tests for the public shared analysis helpers."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

import core  # noqa: E402
import data  # noqa: E402
import formatting  # noqa: E402
import stats  # noqa: E402


class FormattingHelpersTest(unittest.TestCase):
    def test_public_formatters_match_the_latex_output(self):
        self.assertEqual(formatting.tex_escape("a&b_c%"), r"a\&b\_c\%")
        self.assertEqual(formatting.format_num(1.5), "1,500")
        self.assertEqual(formatting.format_num(None), "--")
        self.assertEqual(formatting.format_p(0.0001), "$<0{,}001$")
        self.assertEqual(formatting.format_p(None), "--")
        self.assertEqual(formatting.format_interval(1.5, None), "1,500")
        self.assertEqual(
            formatting.format_interval(1.5, [1.0, 2.0]),
            "1,500 [1,000; 2,000]",
        )


class DataHelpersTest(unittest.TestCase):
    def test_load_jsonl_accepts_objects_and_reports_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / "valid.jsonl"
            valid.write_text('{"run_id": "a"}\n\n{"run_id": "b"}\n')
            self.assertEqual(data.load_jsonl(valid), [{"run_id": "a"}, {"run_id": "b"}])
            missing = root / "missing.jsonl"
            self.assertRaises(core.LiveAnalysisError, data.load_jsonl, missing)
            invalid = root / "invalid.jsonl"
            invalid.write_text("{not-json}\n")
            self.assertRaises(core.LiveAnalysisError, data.load_jsonl, invalid)
            scalar = root / "scalar.jsonl"
            scalar.write_text("[1, 2]\n")
            self.assertRaises(core.LiveAnalysisError, data.load_jsonl, scalar)
            empty = root / "empty.jsonl"
            empty.write_text("\n\n")
            self.assertRaises(core.LiveAnalysisError, data.load_jsonl, empty)


class StatsHelpersTest(unittest.TestCase):
    def test_percentile_interpolates_and_handles_empty(self):
        self.assertIsNone(stats.percentile([], 0.5))
        self.assertEqual(stats.percentile([3], 0.5), 3)
        self.assertEqual(stats.percentile([0, 10], 0.5), 5.0)


if __name__ == "__main__":
    unittest.main()
