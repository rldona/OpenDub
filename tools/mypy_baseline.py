"""mypy may not grow: fail on any error not in mypy-baseline.txt, and say which listed ones are gone.

    uv run python tools/mypy_baseline.py           # the CI check
    uv run python tools/mypy_baseline.py --update  # after fixing some: write the shorter list

Errors are compared without their line numbers, so code moving around doesn't count as new.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parents[1]
BASELINE = ROOT / "mypy-baseline.txt"


def errors() -> Counter[str]:
    out = subprocess.run([sys.executable, "-m", "mypy", "--no-error-summary"], cwd=ROOT,
                         capture_output=True, text=True).stdout
    return Counter(re.sub(r"^([^:]+):\d+(:\d+)?:", r"\1:", line) for line in out.splitlines() if ": error:" in line)


def main() -> int:
    now = errors()
    if "--update" in sys.argv:
        BASELINE.write_text("".join(f"{e}\n" for e in sorted(now.elements())))
        print(f"{sum(now.values())} errors in {BASELINE.name}")
        return 0
    listed = Counter(BASELINE.read_text().splitlines())
    new, gone = now - listed, listed - now
    for e in sorted(new.elements()):
        print(f"new: {e}")
    if gone:
        print(f"{sum(gone.values())} listed error(s) are fixed: run with --update to take them off the list")
    print(f"mypy: {sum(now.values())} errors, {sum(listed.values())} listed, {sum(new.values())} new")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
