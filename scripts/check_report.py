#!/usr/bin/env python3
"""check_report.py — refuse to ship a broken report.

weekly.py once crashed midway (KeyError in best_transfer) and, because the workflow piped it to
`tee`, the run still "succeeded" and committed a 3-line stub that would have been emailed as the
pre-deadline report. This is the guard: the workflow calls it between generating the report and
emailing it, so a truncated report fails the run loudly instead of arriving on your phone as
three useless lines.

Usage:  python scripts/check_report.py report_latest.txt
Exit 0 = report is complete. Exit 1 = truncated/broken, with a diagnosis.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Sections every complete report contains, once per team block.
REQUIRED = ["DECISIONS", "MODEL UPDATES THIS WEEK", "CHIP EVALUATION", "TRANSFER DECISION",
            "CAPTAIN", "STARTING XI", "PROJECTED WEEKLY POINTS"]
MIN_CHARS = 1500          # a real two-team report is ~6-8k; the crash stub was ~200
EXPECTED_TEAMS = 2        # weekly.py reports the AI team and the human team


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "report_latest.txt")
    if not path.exists():
        print(f"FAIL: {path} does not exist — weekly.py produced no report at all.")
        return 1
    text = path.read_text(encoding="utf-8", errors="replace")

    problems = []
    if len(text) < MIN_CHARS:
        problems.append(f"only {len(text)} chars (expected >{MIN_CHARS}) — weekly.py probably crashed early")
    missing = [s for s in REQUIRED if s not in text]
    if missing:
        problems.append(f"missing sections: {', '.join(missing)}")
    n_teams = text.count(" DECISIONS")
    if n_teams < EXPECTED_TEAMS:
        problems.append(f"found {n_teams} team block(s), expected {EXPECTED_TEAMS} "
                        f"— a later report() call likely raised")
    if "Traceback (most recent call last)" in text:
        problems.append("a Python traceback was captured in the report body")

    if problems:
        print(f"FAIL: {path} is not a complete report.")
        for p in problems:
            print(f"  - {p}")
        print("\n--- first 400 chars ---")
        print(text[:400])
        return 1

    print(f"OK: {path} looks complete — {len(text)} chars, {n_teams} team blocks, all sections present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
