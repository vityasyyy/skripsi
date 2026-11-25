#!/usr/bin/env python3
"""Report-only style audit for the thesis body and the defense deck.

The audit never fails a build. It prints counts and ``file:line`` locations for
banned claim phrases, term drift, RQ/R1 label collisions, Latin abbreviations in
Indonesian prose, and double spaces. See ``docs/thesis-style.md`` for the rules.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "content/skripsi/main.tex",
    *sorted((ROOT / "content/skripsi/chapters").glob("*.tex")),
    *sorted((ROOT / "content/skripsi/lampiran").glob("*.tex")),
    ROOT / "presentation/skripsi/contents/slides.tex",
]
ALLOW_MARKER = "style-allow: proposal-history"

BANNED = [
    ("menolak hipotesis nol", re.compile(r"menolak\s+hipotesis\s+nol", re.IGNORECASE)),
    ("dua belas", re.compile(r"\bdua\s+belas\b", re.IGNORECASE)),
    ("kedua mode mencapai", re.compile(r"kedua\s+mode\s+mencapai", re.IGNORECASE)),
]
UNQUALIFIED_FASTER = re.compile(r"gitops\s+lebih\s+cepat", re.IGNORECASE)
QUALIFIERS = ("sinyal yang teramati", "cadence", "di bawah cadence")

TERM_DRIFT = [
    ("manual", re.compile(r"\bmanual\b", re.IGNORECASE)),
    ("prosedur imperatif terotomasi", re.compile(r"terotomasi", re.IGNORECASE)),
    ("mode manual", re.compile(r"mode\s+manual", re.IGNORECASE)),
    ("RQ label", re.compile(r"\bRQ[12]\b")),
    ("R2 timing label", re.compile(r"\bR2\b")),
]
R1_COLLISION = re.compile(
    r"\bR1\b[^.]{0,60}\b(lebih|uji|menolak|hipotesis|keunggulan)\b", re.IGNORECASE
)
LATIN = re.compile(r"\b(e\.g\.|i\.e\.|etc\.)")
DOUBLE_SPACE = re.compile(r" {2,}")
TERSEBUT = re.compile(r"\btersebut\b", re.IGNORECASE)


def _iter_lines(path: Path):
    try:
        text = path.read_text()
    except OSError as error:
        print(f"WARN: cannot read {path}: {error}", file=sys.stderr)
        return
    for number, line in enumerate(text.splitlines(), 1):
        yield number, line


def _report(title: str, hits: list[tuple[Path, int, str]]) -> int:
    print(f"{title}: {len(hits)}")
    for path, number, detail in hits:
        print(f"  {path.relative_to(ROOT)}:{number}: {detail}")
    return len(hits)


def main() -> int:
    print("Thesis style audit (report-only; never fails the build)")
    print(f"Files: {len(FILES)}")
    banned: list[tuple[Path, int, str]] = []
    drift: list[tuple[Path, int, str]] = []
    collisions: list[tuple[Path, int, str]] = []
    latin: list[tuple[Path, int, str]] = []
    double_spaces: list[tuple[Path, int, str]] = []
    tersebut = 0
    for path in FILES:
        for number, line in _iter_lines(path):
            if ALLOW_MARKER in line:
                continue
            for label, pattern in BANNED:
                if pattern.search(line):
                    banned.append((path, number, f"{label} -> {line.strip()[:100]}"))
            if UNQUALIFIED_FASTER.search(line) and not any(
                qualifier in line.lower() for qualifier in QUALIFIERS
            ):
                banned.append((path, number, f"GitOps lebih cepat tanpa kualifikasi -> {line.strip()[:80]}"))
            for label, pattern in TERM_DRIFT:
                if pattern.search(line):
                    if label == "R2 timing label" and "\\nomenclature" in line:
                        continue
                    drift.append((path, number, f"{label} -> {line.strip()[:100]}"))
            if R1_COLLISION.search(line):
                collisions.append((path, number, line.strip()[:100]))
            if LATIN.search(line):
                latin.append((path, number, line.strip()[:100]))
            body = line.lstrip()
            if not body.startswith("%") and DOUBLE_SPACE.search(body):
                double_spaces.append((path, number, repr(body[:100])))
            tersebut += len(TERSEBUT.findall(line))
    total = 0
    total += _report("Banned phrases", banned)
    total += _report("Term drift", drift)
    total += _report("RQ/R1 collisions", collisions)
    total += _report("Latin abbreviations in prose", latin)
    total += _report("Prose double spaces", double_spaces)
    print(f"'tersebut' occurrences: {tersebut}")
    print(f"Total findings: {total}")
    print("Report-only: inspect the locations above; the build result is unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
