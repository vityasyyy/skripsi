"""Checks for the C-r02 sensitivity script's frozen-output guard."""

from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


def _load_module() -> types.ModuleType:
    path = Path(__file__).with_name("c_r02_sensitivity.py")
    spec = importlib.util.spec_from_file_location("c_r02_sensitivity", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DefaultsTest(unittest.TestCase):
    def test_defaults_are_repo_relative_not_home_based(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(Path, "home", return_value=Path(tmp)),
        ):
            module = _load_module()
        repo = Path(module.__file__ or __file__).resolve().parents[2]
        expected = {
            "_DEFAULT_BATCH_DIR": repo / "experiments" / "formal-20261029",
            "_DEFAULT_ANALYSIS_JSON": (
                repo / "experiments" / "analysis-formal-20261029" / "live_analysis.json"
            ),
        }
        for name, path in expected.items():
            with self.subTest(name=name):
                default = getattr(module, name)
                self.assertTrue(default.is_absolute())
                self.assertEqual(default, path)
                self.assertNotIn(Path(tmp), default.parents)
        self.assertEqual(module._REPO_ROOT, repo)


class FrozenOutputGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def _assert_rejected(self, out: Path, batch: Path, analysis: Path) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.module.main(
                [
                    "--batch-dir",
                    str(batch),
                    "--analysis-json",
                    str(analysis / "live_analysis.json"),
                    "--out",
                    str(out),
                ]
            )
        self.assertIn("frozen", str(raised.exception).lower())

    def test_rejects_output_inside_batch_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch = root / "batch"
            analysis = root / "analysis"
            batch.mkdir()
            analysis.mkdir()
            self._assert_rejected(batch / "sensitivity.json", batch, analysis)

    def test_rejects_output_inside_analysis_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch = root / "batch"
            analysis = root / "analysis"
            batch.mkdir()
            analysis.mkdir()
            self._assert_rejected(analysis / "sensitivity.json", batch, analysis)

    def test_accepts_output_outside_frozen_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch = root / "batch"
            analysis = root / "analysis"
            out = root / "out"
            batch.mkdir()
            analysis.mkdir()
            out.mkdir()
            self.assertIsNone(
                self.module._reject_frozen_output(
                    out / "sensitivity.json", batch, analysis / "live_analysis.json"
                )
            )


class SensitivityMainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def write_dataset(self, root: Path, rows: int = 207, raw: int = 211) -> tuple[Path, Path, Path]:
        batch = root / "batch"
        analysis_dir = root / "analysis"
        batch.mkdir(parents=True)
        analysis_dir.mkdir(parents=True)
        analysis_rows: list[dict] = [
            {
                "run_id": f"analysis-{index}",
                "scenario": "B",
                "batch_phase": "R2",
            }
            for index in range(rows)
        ]
        raw_rows: list[dict] = [
            {
                "run_id": f"raw-{index}",
                "scenario": "B",
                "batch_phase": "R2",
            }
            for index in range(raw)
        ]
        raw_rows[0] = {
            "run_id": "formal-20261029-gitops-C-r02",
            "scenario": "C",
            "batch_phase": "R2",
            "status": "observed",
            "recovery_status": "observed",
            "detection_seconds": 2.0,
            "evidence_seconds": 3.0,
            "recovery_seconds": 4.0,
            "r1_baseline": 100.0,
            "r1_first": 90.0,
            "r1_last": 100.0,
        }
        (batch / "formal-20261029.analysis.jsonl").write_text(
            "\n".join(json.dumps(row) for row in analysis_rows) + "\n"
        )
        (batch / "formal-20261029.rows.jsonl").write_text(
            "\n".join(json.dumps(row) for row in raw_rows) + "\n"
        )
        primary = {
            "efficacy": [
                {
                    "scenario": scenario,
                    "metric": metric,
                    "test": {"p_value": 0.5},
                }
                for scenario in "BDE"
                for metric in ("detection", "evidence", "recovery")
            ]
        }
        analysis_json = analysis_dir / "live_analysis.json"
        analysis_json.write_text(json.dumps(primary))
        return batch, analysis_json, Path(self.module.__file__ or __file__)

    def analyzer(self) -> types.SimpleNamespace:
        def comparison(c_rows: list, scenario: str, metric: str, bootstrap: int, seed: int) -> dict:
            return {
                "test": {
                    "n_manual": 3,
                    "n_gitops": 3,
                    "statistic": 1.0,
                    "p_value": 0.25,
                },
                "pairing": {"method": "paired", "reason": "complete_paired_blocks"},
                "effect": {
                    "cliffs_delta": 1.0,
                    "cliffs_delta_ci": [0.5, 1.0],
                    "median_paired_difference": 1.0,
                },
            }

        return types.SimpleNamespace(
            METRICS=("detection", "evidence", "recovery"),
            _comparison=comparison,
            holm_adjust=lambda values, size: [min(1.0, value * 2) for value in values],
        )

    def run_main(self, argv: list[str]) -> int:
        with mock.patch.object(self.module, "_load_analyzer", return_value=self.analyzer()):
            return self.module.main(argv)

    def test_load_jsonl_reports_invalid_and_non_object_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            invalid = root / "invalid.jsonl"
            invalid.write_text("{bad\n")
            with self.assertRaises(SystemExit):
                self.module._load_jsonl(invalid)
            non_object = root / "non-object.jsonl"
            non_object.write_text("[1]\n")
            with self.assertRaises(SystemExit):
                self.module._load_jsonl(non_object)
            valid = root / "valid.jsonl"
            valid.write_text('\n{"run_id": "x"}\n')
            self.assertEqual(self.module._load_jsonl(valid), [{"run_id": "x"}])

    def test_load_analyzer_loads_the_frozen_module(self) -> None:
        module = self.module._load_analyzer(
            Path(self.module.__file__ or __file__).with_name("c_r02_sensitivity.py")
        )
        self.assertTrue(callable(module.main))
        with (
            mock.patch.object(
                self.module.importlib.util, "spec_from_file_location", return_value=None
            ),
            self.assertRaises(SystemExit),
        ):
            self.module._load_analyzer(Path("analyzer.py"))
        with (
            mock.patch.object(
                self.module.importlib.util,
                "spec_from_file_location",
                return_value=types.SimpleNamespace(loader=None),
            ),
            self.assertRaises(SystemExit),
        ):
            self.module._load_analyzer(Path("analyzer.py"))

    def test_main_prints_or_writes_the_sensitivity_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch, analysis_json, analyzer = self.dataset(root)
            stdout = io.StringIO()
            argv = [
                "--batch-dir",
                str(batch),
                "--analysis-json",
                str(analysis_json),
                "--analyzer",
                str(analyzer),
                "--bootstrap",
                "100",
                "--seed",
                "7",
            ]
            with (
                mock.patch.object(self.module, "_load_analyzer", return_value=self.analyzer()),
                redirect_stdout(stdout),
            ):
                self.assertEqual(self.module.main(argv), 0)
            self.assertIn("sensitivity_c", stdout.getvalue())
            out = root / "out.json"
            argv.extend(["--out", str(out)])
            with (
                mock.patch.object(self.module, "_load_analyzer", return_value=self.analyzer()),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(self.module.main(argv), 0)
            self.assertIn("sensitivity_c", out.read_text())

    def dataset(self, root: Path) -> tuple[Path, Path, Path]:
        return self.write_dataset(root)

    def test_main_rejects_unexpected_counts_and_c_r02_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch, analysis_json, analyzer = self.write_dataset(root, rows=206)
            argv = [
                "--batch-dir",
                str(batch),
                "--analysis-json",
                str(analysis_json),
                "--analyzer",
                str(analyzer),
            ]
            with self.assertRaises(SystemExit):
                self.run_main(argv)
            batch, analysis_json, analyzer = self.write_dataset(root / "second", rows=207)
            raw_path = batch / "formal-20261029.rows.jsonl"
            raw = [json.loads(line) for line in raw_path.read_text().splitlines()]
            raw = [row for row in raw if row["run_id"] != "formal-20261029-gitops-C-r02"]
            raw_path.write_text("\n".join(json.dumps(row) for row in raw) + "\n")
            argv = [
                "--batch-dir",
                str(batch),
                "--analysis-json",
                str(analysis_json),
                "--analyzer",
                str(analyzer),
            ]
            with self.assertRaises(SystemExit):
                self.run_main(argv)
            batch, analysis_json, analyzer = self.write_dataset(root / "third", rows=207)
            raw_path = batch / "formal-20261029.rows.jsonl"
            raw = [json.loads(line) for line in raw_path.read_text().splitlines()]
            raw = [row for row in raw if row["run_id"] != "formal-20261029-gitops-C-r02"]
            raw.append(
                {
                    "run_id": "formal-20261029-gitops-C-r02",
                    "scenario": "C",
                    "batch_phase": "R2",
                    "status": "right_censored",
                    "recovery_status": "right_censored",
                }
            )
            raw_path.write_text("\n".join(json.dumps(row) for row in raw) + "\n")
            argv = [
                "--batch-dir",
                str(batch),
                "--analysis-json",
                str(analysis_json),
                "--analyzer",
                str(analyzer),
            ]
            with self.assertRaises(SystemExit):
                self.run_main(argv)
            for mutate in (self.remove_c_r02, self.duplicate_c_r02):
                batch, analysis_json, analyzer = self.write_dataset(
                    root / mutate.__name__, rows=207
                )
                mutate(batch / "formal-20261029.rows.jsonl")
                argv = [
                    "--batch-dir",
                    str(batch),
                    "--analysis-json",
                    str(analysis_json),
                    "--analyzer",
                    str(analyzer),
                ]
                with self.assertRaises(SystemExit):
                    self.run_main(argv)

    def remove_c_r02(self, path: Path) -> None:
        raw = [json.loads(line) for line in path.read_text().splitlines()]
        for row in raw:
            if row["run_id"] == "formal-20261029-gitops-C-r02":
                row["run_id"] = "displaced"
        path.write_text("\n".join(json.dumps(row) for row in raw) + "\n")

    def duplicate_c_r02(self, path: Path) -> None:
        raw = [json.loads(line) for line in path.read_text().splitlines()]
        raw[1]["run_id"] = "formal-20261029-gitops-C-r02"
        path.write_text("\n".join(json.dumps(row) for row in raw) + "\n")

    def test_reject_frozen_output_accepts_none(self) -> None:
        self.assertIsNone(self.module._reject_frozen_output(None, Path("a"), Path("b")))


if __name__ == "__main__":
    unittest.main()
