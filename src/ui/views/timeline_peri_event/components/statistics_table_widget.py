"""Per-cluster results table for the Timeline → Peri-Event page.

Population helpers for the :class:`BaseGroupingPanel` statistics table: one
row per (hemisphere, cluster), with a fallback row when a hemisphere has no
supra-threshold clusters or is insufficient. Kept as pure functions
operating on the panel's ``QTableWidget`` so the grouping panel owns the
widget (and Copy Table reads it) while the cluster-row formatting lives in
one testable place.

Side mapping is display-only: **Left → "Electrode 1"**, **Right → "Electrode 2"**
(matching the plot panel titles); data access stays hemisphere-named.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

from src.ui.utils.tooltips import wrap_tooltip


CLUSTER_HEADERS = [
    "Electrode",       # 0
    "Cluster (min)",   # 1
    "Bins",            # 2
    "Mass (Σ|z|)",     # 3
    "p (perm.)",       # 4
]

_SIDE_LABEL = {"Left": "Electrode 1", "Right": "Electrode 2"}


def _fmt_p(p: float, n_perm: int) -> str:
    floor = 1.0 / (n_perm + 1)
    if p <= floor + 1e-12:
        return f"< {floor:.4f}"
    if p < 0.001:
        return "< 0.001"
    if p < 0.01:
        return f"= {p:.4f}"
    return f"= {p:.3f}"


def _item(text: str, *, bold: bool = False, align=Qt.AlignCenter) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setTextAlignment(align)
    if bold:
        f = QFont(it.font())
        f.setBold(True)
        it.setFont(f)
    return it


def populate_cluster_rows(table: QTableWidget, results: Optional[dict]) -> int:
    """Fill ``table`` with one row per (hemisphere, cluster). Returns the
    number of hemispheres that produced a full result (for footer logic)."""
    from src.core.services.timeline_peri_event_service import (
        InsufficientPeriEvent,
        PeriEventResult,
    )

    results = results or {}
    # Build a flat list of (side_label, row_kind, payload) first so we can
    # size the table once.
    plan: List[Tuple[str, str, object]] = []
    valid_hemis = 0
    for hemi in ("Left", "Right"):
        side = _SIDE_LABEL[hemi]
        res = results.get(hemi)
        if isinstance(res, PeriEventResult):
            valid_hemis += 1
            if res.clusters:
                for cl in res.clusters:
                    plan.append((side, "cluster", (cl, res.n_perm)))
            else:
                plan.append((side, "none", None))
        elif isinstance(res, InsufficientPeriEvent):
            plan.append((side, "insufficient", res.reason))
        else:
            plan.append((side, "empty", None))

    table.clearSpans()
    table.setRowCount(len(plan))
    for row, (side, kind, payload) in enumerate(plan):
        table.setItem(row, 0, _item(side))
        if kind == "cluster":
            cl, n_perm = payload
            n_bins = int(cl["end_idx"] - cl["start_idx"] + 1)
            sig = cl["p"] <= 0.05
            table.setItem(row, 1, _item(f"{cl['start_bin']:+d} to {cl['end_bin']:+d}"))
            table.setItem(row, 2, _item(str(n_bins)))
            table.setItem(row, 3, _item(f"{cl['mass']:.2f}"))
            table.setItem(row, 4, _item(_fmt_p(cl["p"], n_perm), bold=sig))
        elif kind == "none":
            table.setItem(row, 1, _item("no clusters"))
            for col in (2, 3, 4):
                table.setItem(row, col, _item("—"))
        elif kind == "insufficient":
            msg = _item(f"insufficient: {payload}", align=Qt.AlignVCenter | Qt.AlignLeft)
            # The span is only as wide as its columns, so a long reason is
            # elided; the tooltip has it in full.
            msg.setToolTip(wrap_tooltip(msg.text()))
            table.setItem(row, 1, msg)
            table.setSpan(row, 1, 1, 4)
        else:  # empty
            for col in (1, 2, 3, 4):
                table.setItem(row, col, _item("—"))

    return valid_hemis
