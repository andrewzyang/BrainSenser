#!/usr/bin/env python3
"""
Responsive sweep: the real BrainSenser window across screen profiles and window
sizes, before/after any layout change.

A port of ``notes/responsive_ui_v2_audit/harness/sweep.py`` onto the responsive
test harness (``tests/ui/responsive``): the same child runner, plan §3.2
invariant detectors, screen profiles, synthetic data and data-safety guards as
the pytest matrix, plus contact sheets.

Usage:
    python tools/responsive_sweep.py --out DIR                        # every profile
    python tools/responsive_sweep.py --out DIR --profiles mac_air15,win150 --cell-png
    python tools/responsive_sweep.py --out NEW --compare BASELINE     # sweep, then diff
    python tools/responsive_sweep.py --out NEW --compare BASELINE --no-run
    python tools/responsive_sweep.py --out DIR --platform cocoa       # native macOS, hidden window

DIR must lie outside the checkout. It receives profiles/<profile>.json (every
cell's violations), summary.json, matrix.md, failing_cells.txt (the format of
tests/ui/responsive/known_sweep_failures.txt, to re-baseline it), sheets/*.png
(one contact sheet per profile, page and state), cells/ with --cell-png, logs/
and isolation.json (the real-data fingerprint before and after).

Exits 0 when done, 1 when --compare finds regressions, 2 when a profile fails to
run, 3 when protected real data changed during the run.
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.ui.responsive import _safety, runner  # noqa: E402
from tests.ui.responsive.profiles import PAGES, PROFILES, all_cells, cell_id  # noqa: E402

RATCHET_HEADER = """\
# Sweep-cell ratchet: one profile/viewport/page/state/invariant per line that
# fails on a clean tree (see tests/ui/responsive/ratchet.py). Regenerate with
#   python tools/responsive_sweep.py --out <dir outside the checkout>
# and copy <dir>/failing_cells.txt over this file.
"""


def load_results(run_dir: Path) -> dict:
    return {path.stem: json.loads(path.read_text())
            for path in sorted((run_dir / "profiles").glob("*.json"))}


def failing_entries(results: dict) -> list:
    """``profile/viewport/page/state/invariant`` for every failing cell invariant,
    in matrix order."""
    order = {cell: i for i, cell in enumerate(all_cells())}
    entries = []
    for profile, result in results.items():
        for cell in result.get("cells", []):
            key = (profile, cell["viewport"], cell["page"], cell["state"])
            entries += [(order.get(key, len(order)), f"{cell_id(*key)}/{invariant}")
                        for invariant, found in sorted(cell["violations"].items()) if found]
    return [entry for _, entry in sorted(entries)]


def write_summary(results: dict, out: Path) -> None:
    rows = [{"profile": profile, "viewport": c["viewport"], "page": c["page"], "state": c["state"],
             "window": c["window"], "failing": {k: len(v) for k, v in c["violations"].items() if v}}
            for profile, result in results.items() for c in result.get("cells", [])]
    (out / "summary.json").write_text(json.dumps(rows, indent=1))
    (out / "failing_cells.txt").write_text(RATCHET_HEADER + "".join(
        f"{entry}\n" for entry in failing_entries(results)))
    lines = ["# Responsive sweep", "", "Failing invariants per cell (OK = all hold).", ""]
    for profile, result in results.items():
        if "error" in result:
            lines += [f"## {profile}: {result['error']}", ""]
            continue
        for state in ("empty", "populated"):
            cells = [c for c in result["cells"] if c["state"] == state]
            lines += [f"## {profile} — {state}", "",
                      "| viewport | window | " + " | ".join(PAGES) + " |",
                      "|---" * (len(PAGES) + 2) + "|"]
            for viewport in dict.fromkeys(c["viewport"] for c in cells):
                by_page = {c["page"]: c for c in cells if c["viewport"] == viewport}
                window = "×".join(map(str, next(iter(by_page.values()))["window"]))
                marks = [" ".join(k for k, v in by_page[p]["violations"].items() if v) or "OK"
                         if p in by_page else "—" for p in PAGES]
                lines.append(f"| {viewport} | {window} | " + " | ".join(marks) + " |")
            lines.append("")
    (out / "matrix.md").write_text("\n".join(lines))


def print_overview(results: dict) -> None:
    for profile, result in results.items():
        if "error" in result:
            print(f"  {profile:16} ERROR {result['error']}")
            continue
        counts = Counter(k for c in result["cells"] for k, v in c["violations"].items() if v)
        cells = len(result["cells"])
        failing = sum(1 for c in result["cells"] if any(c["violations"].values()))
        by_number = sorted(counts.items(), key=lambda kv: int(kv[0][1:]))
        detail = ", ".join(f"{k} {n}" for k, n in by_number)
        print(f"  {profile:16} {failing:3}/{cells} cells failing ({detail or 'none'}); "
              f"{result['wall_s']} s")


def compare(baseline: Path, current: Path) -> int:
    """Print fixed and regressed cell invariants of ``current`` against ``baseline``
    (cells both runs measured); return the number of regressions."""
    def index(results):
        cells = {(p, c["viewport"], c["page"], c["state"]): c
                 for p, r in results.items() for c in r.get("cells", [])}
        failing = {f"{cell_id(*k)}/{inv}"
                   for k, c in cells.items() for inv, v in c["violations"].items() if v}
        return cells, failing

    base_cells, base_failing = index(load_results(baseline))
    cur_cells, cur_failing = index(load_results(current))
    shared = {cell_id(*k) for k in base_cells.keys() & cur_cells.keys()}
    fixed = sorted(e for e in base_failing - cur_failing if e.rsplit("/", 1)[0] in shared)
    regressed = sorted(e for e in cur_failing - base_failing if e.rsplit("/", 1)[0] in shared)
    for entry in regressed:
        print(f"regressed  {entry}")
    for entry in fixed:
        print(f"fixed      {entry}")
    print(f"{len(fixed)} fixed, {len(regressed)} regressed across {len(shared)} shared cells "
          f"({len(base_cells.keys() ^ cur_cells.keys())} cells in one run only)")
    return len(regressed)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path, help="run folder, outside the checkout")
    parser.add_argument("--profiles", default=",".join(PROFILES),
                        help=f"comma-separated, from: {', '.join(PROFILES)}")
    parser.add_argument("--platform", choices=("offscreen", "cocoa"), default="offscreen",
                        help="cocoa: the real display, with a hidden window (macOS only)")
    parser.add_argument("--cell-png", action="store_true", help="also save every cell's screenshot")
    parser.add_argument("--compare", type=Path, metavar="BASELINE",
                        help="diff against an earlier run")
    parser.add_argument("--no-run", action="store_true", help="with --compare: diff --out as it is")
    parser.add_argument("--jobs", type=int, help="profiles run in parallel (default: all)")
    parser.add_argument("--timeout", type=int, default=900, help="seconds per profile")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    _safety.check_sandbox_location(out)
    if args.no_run and not args.compare:
        parser.error("--no-run needs --compare")

    if not args.no_run:
        names = [runner.NATIVE] if args.platform == "cocoa" else args.profiles.split(",")
        unknown = [n for n in names if n not in PROFILES and args.platform == "offscreen"]
        if unknown:
            parser.error(f"unknown profiles: {', '.join(unknown)}")
        if any((out / "profiles").glob("*.json")):
            parser.error(f"{out} already holds a run; pick a fresh --out")
        out.mkdir(parents=True, exist_ok=True)
        print(f"[sweep] {len(names)} profiles -> {out}")
        started, before = time.monotonic(), _safety.fingerprint()
        results = runner.run_profiles(names, out, jobs=args.jobs, platform=args.platform,
                                      sheets=True, cell_png=args.cell_png, timeout=args.timeout)
        after = _safety.fingerprint()
        changed = _safety.changed_paths(before, after)
        (out / "isolation.json").write_text(json.dumps(
            {"before": before, "after": after, "changed": changed, "sandbox": str(out / "sandbox"),
             "elapsed_s": round(time.monotonic() - started, 1)}, indent=1))
        write_summary(results, out)
        print_overview(results)
        print(f"[sweep] {time.monotonic() - started:.0f} s; matrix: {out / 'matrix.md'}")
        if changed:
            print(f"!!! protected real data changed during the run: {changed}")
            return 3
        if any("error" in r for r in results.values()):
            return 2
        print(f"[sweep] real-data fingerprint unchanged ({len(before)} protected paths)")
    if args.compare:
        return 1 if compare(args.compare.resolve(), out) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
