"""Checks for the C-r02 sensitivity script's frozen-output guard."""

from __future__ import annotations

import importlib.util
import tempfile
import types
import unittest
from pathlib import Path


def _load_module() -> types.ModuleType:
    path = Path(__file__).with_name("c_r02_sensitivity.py")
    spec = importlib.util.spec_from_file_location("c_r02_sensitivity", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


if __name__ == "__main__":
    unittest.main()
