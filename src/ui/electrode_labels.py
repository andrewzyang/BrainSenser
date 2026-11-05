"""Single source of truth for electrode display names in progress popups.

Maps a hemisphere's *run-order index* (0 = first analyzed, 1 = second) onto the
user-facing electrode label shown in the shared ``MlProgressDialog`` during a
"Compare" run. The mapping matches the convention already used by the result
panels — Left → "Electrode 1", Right → "Electrode 2" (see e.g.
``snapshots_psd/components/dual_hemisphere_psd_widget._PANEL_TITLE`` and
``snapshots_5hz_band/components/dual_hemisphere_auc_widget.HEADER_LEFT``) — so
the popup and the panels it precedes always agree.

This is display-only: workers continue to key data, dict entries, service calls,
and ``partial_*`` emits off their domain hemisphere tokens ("L"/"R",
"LEFT"/"RIGHT", "Left"/"Right"). Only the label string passed to
``progress.emit(..., label)`` is built from these names.
"""

from __future__ import annotations

ELECTRODE_LABELS = ("Electrode 1", "Electrode 2")  # index 0 = Left, 1 = Right

# Side token (any casing) → anatomical index. Mirrors the panel convention
# Left → "Electrode 1", Right → "Electrode 2".
_SIDE_INDEX = {"L": 0, "LEFT": 0, "R": 1, "RIGHT": 1}


def electrode_label(index: int) -> str:
    """Return the electrode display name for an *anatomical* side index.

    ``0 → "Electrode 1"`` (Left), ``1 → "Electrode 2"`` (Right). Out-of-range
    indices fall back to ``f"Electrode {index + 1}"`` so the popup degrades
    gracefully rather than raising on an unexpected hemisphere count.

    Pass the anatomical side index, NOT a run-order position — for a unilateral
    implant the sole hemisphere still runs at run-order 0 yet must keep its
    anatomical label (a right-only patient → "Electrode 2"). Workers that
    iterate hemispheres in fixed ``(Left, Right)`` order may pass their loop
    index directly; those with variable run order should use
    :func:`electrode_label_for_hemisphere`.
    """
    if 0 <= index < len(ELECTRODE_LABELS):
        return ELECTRODE_LABELS[index]
    return f"Electrode {index + 1}"


def electrode_label_for_hemisphere(hemi: str) -> str:
    """Return the electrode display name for a hemisphere side token.

    Accepts any casing of ``"L"/"LEFT"`` → "Electrode 1" and
    ``"R"/"RIGHT"`` → "Electrode 2". Robust against run order (a right-only
    patient maps to "Electrode 2" regardless of being analyzed first); unknown
    tokens echo back unchanged so an unexpected value is visible rather than
    silently mislabeled.
    """
    index = _SIDE_INDEX.get(hemi.strip().upper())
    return ELECTRODE_LABELS[index] if index is not None else hemi
