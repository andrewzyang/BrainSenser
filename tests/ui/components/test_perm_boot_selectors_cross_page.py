"""Cross-page contract tests for the Bootstrap/Permutation selector pair.

The three analysis pages that expose a bootstrap + permutation selector pair —
Snapshots 5 Hz Band, Timeline LFP Threshold, Timeline Peri-Event — must present
that pair *uniformly*:

  1. **Same values selectable** — every page offers the identical perm menu and
     the identical boot menu (the shared single source of truth in
     ``base_grouping_panel``).
  2. **Bootstrap on top of Permutations** — the Bootstrap (CI) row sits above
     the Permutations (p) row in the control column.
  3. **Exact labels** — the rows read "Bootstrap (CI):" and "Permutations (p):".

A fourth, non-negotiable invariant guards the science: unifying the *menu* must
NOT change any page's manuscript-locked DEFAULT selection (which is what an
out-of-the-box Compare reproduces). Each page keeps its own default.

The PSD page is intentionally excluded — it has no perm/boot selector (only
upstream-computed bootstrap CIs), so it is not part of this contract.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from src.ui.components.base_grouping_panel import (
    BOOTSTRAP_LABEL,
    BOOTSTRAP_OPTION_LABELS,
    PERMUTATION_LABEL,
    PERMUTATION_OPTION_LABELS,
)
from src.ui.views.snapshots_5hz_band.components.grouping_panel import (
    Snapshots5HzBandGroupingPanel,
)
from src.ui.views.timeline_lfp_threshold.components.grouping_panel import (
    TimelineLfpThresholdGroupingPanel,
)
from src.ui.views.timeline_peri_event.components.grouping_panel import (
    TimelinePeriEventGroupingPanel,
)


PERM_BOOT_PANELS = [
    Snapshots5HzBandGroupingPanel,
    TimelineLfpThresholdGroupingPanel,
    TimelinePeriEventGroupingPanel,
]

# The DEFAULT selection each page must keep after the menu is unified. These are
# the manuscript-locked values; changing them would change the published
# analysis an out-of-the-box Compare reproduces. Keyed by class name.
EXPECTED_DEFAULTS = {
    "Snapshots5HzBandGroupingPanel": (10_000, 2_000),     # (n_perm, n_boot)
    "TimelineLfpThresholdGroupingPanel": (1_000, 2_000),
    "TimelinePeriEventGroupingPanel": (10_000, 5_000),
}


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(params=PERM_BOOT_PANELS, ids=lambda c: c.__name__)
def panel(qapp, request):
    widget = request.param()
    yield widget
    widget.deleteLater()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _combo_texts(combo) -> list:
    return [combo.itemText(i) for i in range(combo.count())]


def _row_index_of(vbox, label) -> int:
    """Index of the sub-layout (row) within ``vbox`` that holds ``label``.

    The perm/boot/window rows are QHBoxLayouts added to the control column's
    QVBoxLayout; each holds its title QLabel. Comparing row indices is a
    layout-level (geometry-free, show()-free) way to assert vertical order.
    """
    for i in range(vbox.count()):
        sub = vbox.itemAt(i).layout()
        if sub is None:
            continue
        for j in range(sub.count()):
            if sub.itemAt(j).widget() is label:
                return i
    return -1


# --------------------------------------------------------------------------
# 1. Same values selectable (per page, then cross-page)
# --------------------------------------------------------------------------

def test_perm_menu_matches_shared_source(panel):
    assert _combo_texts(panel.n_perm_combo) == list(PERMUTATION_OPTION_LABELS)


def test_boot_menu_matches_shared_source(panel):
    assert _combo_texts(panel.n_boot_combo) == list(BOOTSTRAP_OPTION_LABELS)


def test_all_pages_share_identical_menus(qapp):
    """The whole point of the unification: construct all three pages and assert
    their perm menus are byte-identical, and likewise their boot menus."""
    panels = [cls() for cls in PERM_BOOT_PANELS]
    try:
        perm_menus = {_tuple(_combo_texts(p.n_perm_combo)) for p in panels}
        boot_menus = {_tuple(_combo_texts(p.n_boot_combo)) for p in panels}
        assert len(perm_menus) == 1, f"perm menus diverge: {perm_menus}"
        assert len(boot_menus) == 1, f"boot menus diverge: {boot_menus}"
    finally:
        for p in panels:
            p.deleteLater()


def _tuple(seq) -> tuple:
    return tuple(seq)


# --------------------------------------------------------------------------
# 2. Bootstrap row sits ABOVE the Permutations row
# --------------------------------------------------------------------------

def test_bootstrap_row_is_above_permutation_row(panel):
    assert panel._boot_label.parent() is panel._perm_label.parent(), (
        "boot/perm labels must live in the same control column"
    )
    vbox = panel._boot_label.parent().layout()
    boot_idx = _row_index_of(vbox, panel._boot_label)
    perm_idx = _row_index_of(vbox, panel._perm_label)
    assert boot_idx >= 0 and perm_idx >= 0, "both rows must be found in the column"
    assert boot_idx < perm_idx, (
        f"Bootstrap row (index {boot_idx}) must sit above Permutations row "
        f"(index {perm_idx})"
    )


# --------------------------------------------------------------------------
# 3. Exact label text
# --------------------------------------------------------------------------

def test_label_constants_are_exactly_specified():
    assert BOOTSTRAP_LABEL == "Bootstrap (CI):"
    assert PERMUTATION_LABEL == "Permutations (p):"


def test_boot_label_text(panel):
    assert panel._boot_label.text() == "Bootstrap (CI):"


def test_perm_label_text(panel):
    assert panel._perm_label.text() == "Permutations (p):"


# --------------------------------------------------------------------------
# 4. Science guard — the per-page DEFAULT selection is unchanged
# --------------------------------------------------------------------------

def test_default_selection_is_preserved(panel):
    expected_perm, expected_boot = EXPECTED_DEFAULTS[type(panel).__name__]
    assert panel.selected_n_perm() == expected_perm
    assert panel.selected_n_boot() == expected_boot
