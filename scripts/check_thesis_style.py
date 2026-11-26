#!/usr/bin/env python3
"""Report-only style audit for the thesis body.

The audit never fails a build. It prints counts and ``file:line`` locations for
banned claim phrases, term drift, R1/R2/RQ labels, Latin abbreviations in
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
    *sorted((ROOT / "content/skripsi/diagrams").glob("*.tex")),
]
ALLOW_MARKER = "style-allow: proposal-history"

BANNED = [
    ("menolak hipotesis nol", re.compile(r"menolak\s+hipotesis\s+nol", re.IGNORECASE)),
    ("dua belas", re.compile(r"\bdua\s+belas\b", re.IGNORECASE)),
    ("kedua mode mencapai", re.compile(r"kedua\s+mode\s+mencapai", re.IGNORECASE)),
]
UNQUALIFIED_FASTER = re.compile(r"gitops\s+lebih\s+cepat", re.IGNORECASE)
NEGATED_FASTER = re.compile(r"(bukan|tidak)\s+bahwa\s+gitops\s+lebih\s+cepat", re.IGNORECASE)
QUALIFIERS = ("sinyal yang teramati", "selang pengamatan", "di bawah selang")

TERM_DRIFT = [
    ("manual", re.compile(r"\bmanual\b", re.IGNORECASE)),
    ("prosedur imperatif terotomasi", re.compile(r"terotomasi", re.IGNORECASE)),
    ("mode manual", re.compile(r"mode\s+manual", re.IGNORECASE)),
    ("R1/R2/RQ label", re.compile(r"\b(?:R1|R2|RQ)\b")),
    ("cadence", re.compile(r"\bcadence\b", re.IGNORECASE)),
    ("arm", re.compile(r"\barm\b", re.IGNORECASE)),
    ("batch", re.compile(r"\bbatch\b", re.IGNORECASE)),
    ("run", re.compile(r"\brun\b", re.IGNORECASE)),
    ("seed", re.compile(r"\bseed\b", re.IGNORECASE)),
    ("pembakuan", re.compile(r"pembakuan", re.IGNORECASE)),
    ("pembekuan", re.compile(r"pembekuan", re.IGNORECASE)),
    ("penyensoran", re.compile(r"penyensoran", re.IGNORECASE)),
    ("pengoperasionalan", re.compile(r"pengoperasionalan", re.IGNORECASE)),
    ("validitas manipulasi", re.compile(r"validitas\s+manipulasi", re.IGNORECASE)),
    ("postcondition", re.compile(r"postcondition", re.IGNORECASE)),
    ("guardrail", re.compile(r"guardrail", re.IGNORECASE)),
    ("status live", re.compile(r"status\s+live", re.IGNORECASE)),
    ("state live", re.compile(r"state\s+live", re.IGNORECASE)),
    ("state aktual", re.compile(r"state\s+aktual", re.IGNORECASE)),
]
LATIN = re.compile(r"\b(e\.g\.|i\.e\.|etc\.)")
DOUBLE_SPACE = re.compile(r" {2,}")
TERSEBUT = re.compile(r"\btersebut\b", re.IGNORECASE)
RUN_ID = re.compile(r"\b[A-Z]-r\d{2}\b")
TEXTTT = re.compile(r"\\texttt\{[^{}]*\}")
PATH = re.compile(r"\\(?:path|url|seqsplit)\{[^{}]*\}")


def _strip_inline_code(line: str) -> str:
    previous = None
    current = line
    while previous != current:
        previous = current
        current = TEXTTT.sub("", current)
        current = PATH.sub("", current)
    return current


def _iter_lines(path: Path):
    try:
        text = path.read_text()
    except OSError as error:
        print(f"WARN: cannot read {path}: {error}", file=sys.stderr)
        return
    in_listing = False
    for number, line in enumerate(text.splitlines(), 1):
        if "\\begin{lstlisting}" in line:
            in_listing = True
            continue
        if "\\end{lstlisting}" in line:
            in_listing = False
            continue
        if in_listing:
            continue
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
    latin: list[tuple[Path, int, str]] = []
    double_spaces: list[tuple[Path, int, str]] = []
    tersebut = 0
    for path in FILES:
        for number, line in _iter_lines(path):
            if ALLOW_MARKER in line:
                continue
            if line.lstrip().startswith("%") or "keywords=" in line:
                continue
            body = _strip_inline_code(line).lstrip()
            raw_body = line.lstrip()
            if RUN_ID.search(line) and path.name != "lampiran-a.tex":
                drift.append((path, number, f"raw run identifier -> {line.strip()[:100]}"))
            for label, pattern in BANNED:
                if pattern.search(body):
                    banned.append((path, number, f"{label} -> {line.strip()[:100]}"))
            if (
                UNQUALIFIED_FASTER.search(body)
                and not NEGATED_FASTER.search(body)
                and not any(qualifier in body.lower() for qualifier in QUALIFIERS)
            ):
                banned.append((path, number, f"GitOps lebih cepat tanpa kualifikasi -> {line.strip()[:80]}"))
            for label, pattern in TERM_DRIFT:
                if pattern.search(body):
                    drift.append((path, number, f"{label} -> {line.strip()[:100]}"))
            if LATIN.search(body):
                latin.append((path, number, line.strip()[:100]))
            if (
                "&" not in raw_body
                and not raw_body.startswith("\\")
                and DOUBLE_SPACE.search(raw_body)
            ):
                double_spaces.append((path, number, repr(raw_body[:100])))
            tersebut += len(TERSEBUT.findall(body))
    total = 0
    total += _report("Banned phrases", banned)
    total += _report("Term drift", drift)
    total += _report("Latin abbreviations in prose", latin)
    total += _report("Prose double spaces", double_spaces)
    print(f"'tersebut' occurrences: {tersebut}")
    print(f"Total findings: {total}")
    print("Report-only: inspect the locations above; the build result is unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
