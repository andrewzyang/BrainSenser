"""The sweep-cell ratchet: known failing cell invariants of the responsive matrix.

``known_sweep_failures.txt`` holds one ``profile/viewport/page/state/invariant``
entry per line for every cell invariant that fails on a clean tree:

- a listed invariant that still fails turns its cell into an xfail;
- a listed invariant that now holds gets a "FIXED — delete this line" note in
  the terminal summary (it does not fail the run);
- an unlisted failure fails the cell;
- an entry that names no cell invariant of the matrix is reported as stale.

``tools/responsive_sweep.py`` writes the same entries for a whole run
(``failing_cells.txt``); that is how the list is regenerated.
"""

import os
import re
from collections import defaultdict
from pathlib import Path

from tests.ui.responsive.profiles import all_cells, cell_id, cell_invariants

KNOWN_SWEEP_FAILURES = Path(__file__).with_name("known_sweep_failures.txt")
_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMMENT = re.compile(r"(^|\s)#.*$")


class SweepRatchet:
    """The listed failing cell invariants, and what this session found fixed."""

    def __init__(self, path: Path = KNOWN_SWEEP_FAILURES):
        try:
            self.source = Path(os.path.relpath(path, _REPO_ROOT)).as_posix()
        except ValueError:  # Windows: path and repo on different drives
            self.source = Path(path).as_posix()
        self.entries = set()
        self._by_cell = defaultdict(set)
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = _COMMENT.sub("", line).strip()
            if entry:
                self.entries.add(entry)
                cell, invariant = entry.rsplit("/", 1)
                self._by_cell[cell].add(invariant)
        self.fixed = []

    def check(self, cell: str, failing) -> list:
        """Record listed invariants of ``cell`` that hold now; return the unlisted failures."""
        known = self._by_cell.get(cell, set())
        self.fixed += [f"{cell}/{inv}" for inv in sorted(known - set(failing))]
        return sorted(set(failing) - known)

    def stale(self) -> list:
        """Entries that name no cell invariant of the current matrix."""
        valid = {f"{cell_id(*cell)}/{inv}"
                 for cell in all_cells() for inv in cell_invariants(cell[1])}
        return sorted(self.entries - valid)
