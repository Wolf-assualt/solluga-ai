"""
scripts/generate_readme_charts.py — Build the README charts from REAL repo data.

  * docs/assets/tests-per-module.png  — pytest test count per test file
                                         (from `pytest --collect-only`)
  * docs/assets/loc-by-package.png    — non-blank lines of code per package

Usage:
    python -m pip install -r requirements-dev.txt
    python scripts/generate_readme_charts.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "docs", "assets")

BRAND = "#6366f1"   # dashboard --brand-500
INK = "#1e293b"
MUTED = "#64748b"
GRID = "#e2e6ef"


def collect_tests() -> Counter:
    env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1"}
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True,
    ).stdout
    counts: Counter = Counter()
    for line in out.splitlines():
        if "::" in line:
            counts[os.path.basename(line.split("::", 1)[0])] += 1
    return counts


def count_loc() -> dict[str, int]:
    groups = {
        "core/  (business logic)": ("core", (".py",)),
        "bot/   (Telegram)": ("bot", (".py",)),
        "web/   (FastAPI app)": ("web", (".py",)),
        "web/templates (Jinja2)": ("web/templates", (".html",)),
        "data/  (schema + seeds)": ("data", (".py", ".sql")),
        "tests/": ("tests", (".py",)),
        "scripts/": ("scripts", (".py",)),
    }
    result: dict[str, int] = {}
    for label, (folder, exts) in groups.items():
        total = 0
        base = os.path.join(ROOT, folder)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "templates") or folder.endswith("templates")]
            for fn in filenames:
                if fn.endswith(exts):
                    with open(os.path.join(dirpath, fn), encoding="utf-8", errors="ignore") as f:
                        total += sum(1 for ln in f if ln.strip())
        result[label] = total
    return result


def hbar(data: dict[str, int], title: str, xlabel: str, filename: str) -> None:
    items = sorted(data.items(), key=lambda kv: kv[1])
    labels = [k for k, _ in items]
    values = [v for _, v in items]

    fig, ax = plt.subplots(figsize=(8, 0.42 * len(items) + 1.4), dpi=160)
    bars = ax.barh(labels, values, color=BRAND, height=0.62)
    ax.bar_label(bars, padding=4, color=INK, fontsize=9)
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=INK, pad=12)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.tick_params(colors=INK, labelsize=9, length=0)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.set_xlim(0, max(values) * 1.12)
    fig.text(0.99, 0.01, f"Generated from the repo on {date.today().isoformat()}",
             ha="right", va="bottom", fontsize=7, color=MUTED)
    fig.tight_layout()
    path = os.path.join(OUT_DIR, filename)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(f"  📊 {os.path.relpath(path, ROOT)}")


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    tests = collect_tests()
    hbar(dict(tests), f"Automated tests per module  ({sum(tests.values())} total)",
         "pytest test cases", "tests-per-module.png")
    loc = count_loc()
    hbar(loc, f"Codebase size by package  ({sum(loc.values()):,} non-blank lines)",
         "non-blank lines", "loc-by-package.png")


if __name__ == "__main__":
    main()
