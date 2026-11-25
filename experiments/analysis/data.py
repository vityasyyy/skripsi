"""Public JSONL loading shared by the live analyzer and its thesis view."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__:
    from . import core as _core
else:  # direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import core as _core  # type: ignore[no-redef]

LiveAnalysisError = _core.LiveAnalysisError


def load_jsonl(path: str | Path) -> list[dict]:
    """Load a non-empty JSONL file of JSON objects; raise on any violation."""
    rows = []
    try:
        text = Path(path).read_text()
    except (OSError, UnicodeError) as error:
        raise LiveAnalysisError(f"cannot read {path}: {error}") from error
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise LiveAnalysisError(f"invalid JSON on line {number}") from error
        if not isinstance(row, dict):
            raise LiveAnalysisError(f"line {number} is not a JSON object")
        rows.append(row)
    if not rows:
        raise LiveAnalysisError("empty JSONL input")
    return rows


__all__ = ["load_jsonl"]
