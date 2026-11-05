"""
Tests for DualHemisphereAucWidget (matplotlib manuscript-aesthetic version).

Covers instantiation, clear/empty state, no-data messages, marker counts
(parametrized over N), greyscale audit, the standalone (no scripts/results
imports) invariant, annotation content, and PNG export.

Author: iEEG BrainSense Development Team
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from src.core.services.snapshot_ml_analysis_service import AucProfileResult
from src.ui.views.snapshots_5hz_band.components.dual_hemisphere_auc_widget import (
    DualHemisphereAucWidget,
    NO_DATA_TEXT,
    PLACEHOLDER_TEXT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_result(n: int, hemi: str = "L") -> AucProfileResult:
    """Build a synthetic AucProfileResult with N candidate bands."""
    centers = np.linspace(7.0, 35.0, n)
    half = (centers[1] - centers[0]) / 2.0
    edges = np.column_stack([centers - half, centers + half])
    auc = np.linspace(0.5, 0.7, n)
    ci_lo = auc - 0.05
    ci_hi = auc + 0.05
    return AucProfileResult(
        hemisphere=hemi,
        band_centers_hz=centers,
        band_edges_hz=edges,
        per_band_auc=auc,
        per_band_ci_lo=ci_lo,
        per_band_ci_hi=ci_hi,
        modal_band_idx=n // 2,
        pipeline_loo_auc=0.65,
        pipeline_loo_ci_lo=0.55,
        pipeline_loo_ci_hi=0.75,
        fwer_p=0.04,
        n_craving=8,
        n_non_craving=9,
        n_perm=200,
        n_boot=200,
    )


def _axes(w: DualHemisphereAucWidget):
    """Return (left_ax, right_ax) from the widget's figure."""
    axes = w._mpl.figure.axes
    assert len(axes) == 2, f"Expected 2 panels, got {len(axes)}"
    return axes[0], axes[1]


def _marker_point_count(ax) -> int:
    """Sum data points across every marker-bearing Line2D in the axis.

    The per-band curve is one ``Line2D`` with ``marker='o'`` and N points; the
    modal-band triangle is a second ``Line2D`` with ``marker='v'`` and 1 point.
    The two ``axhline`` reference lines are markerless and excluded.
    """
    total = 0
    for line in ax.lines:
        marker = line.get_marker()
        if marker in (None, "None", "", " "):
            continue
        total += len(line.get_xdata())
    return total


def _has_message(ax) -> bool:
    return any(NO_DATA_TEXT in t.get_text() for t in ax.texts)


def _has_placeholder(ax) -> bool:
    return any(PLACEHOLDER_TEXT in t.get_text() for t in ax.texts)


# ---------------------------------------------------------------------------
# 1. Widget instantiates with a 2-panel matplotlib figure
# ---------------------------------------------------------------------------


def test_widget_instantiates(qtbot):
    w = DualHemisphereAucWidget()
    qtbot.addWidget(w)
    assert w is not None
    assert w._mpl is not None
    left_ax, right_ax = _axes(w)
    assert left_ax is not None
    assert right_ax is not None


# ---------------------------------------------------------------------------
# 2. clear() → centered placeholder, no plot (no axes / reference lines)
# ---------------------------------------------------------------------------


def test_clear_shows_placeholder_no_plot(qtbot):
    w = DualHemisphereAucWidget()
    qtbot.addWidget(w)
    w.clear()

    for ax in _axes(w):
        # Pre-analysis empty state shows the standardized placeholder and NO
        # plot — not even the chance/target reference lines (the former bug).
        assert len(ax.lines) == 0, (
            f"clear() should draw no plot lines (incl. reference lines), got "
            f"{len(ax.lines)}"
        )
        # No curve / modal markers, no CI fill.
        assert _marker_point_count(ax) == 0
        assert len(ax.collections) == 0
        # Axes hidden (ticks cleared).
        assert len(ax.get_xticks()) == 0
        assert len(ax.get_yticks()) == 0
        # The standardized "Click compare to run analysis" placeholder is shown,
        # not the post-analysis "no data" message.
        assert _has_placeholder(ax)
        assert not _has_message(ax)


# ---------------------------------------------------------------------------
# 3. set_results(None, None) → no-data message on BOTH panels
# ---------------------------------------------------------------------------


def test_set_results_none_none_shows_message_on_both_panels(qtbot):
    w = DualHemisphereAucWidget()
    qtbot.addWidget(w)
    w.set_results(None, None)

    left_ax, right_ax = _axes(w)
    assert _has_message(left_ax)
    assert _has_message(right_ax)
    # Reference lines still present; no curve drawn.
    for ax in (left_ax, right_ax):
        assert len(ax.lines) == 2
        assert _marker_point_count(ax) == 0


# ---------------------------------------------------------------------------
# 4. set_results(left, None) → message only on the right panel
# ---------------------------------------------------------------------------


def test_set_results_left_only_message_only_right(qtbot):
    w = DualHemisphereAucWidget()
    qtbot.addWidget(w)
    w.set_results(_build_result(10, "L"), None)

    left_ax, right_ax = _axes(w)
    assert not _has_message(left_ax)
    assert _marker_point_count(left_ax) > 0      # curve drawn on the left
    assert _has_message(right_ax)
    assert _marker_point_count(right_ax) == 0     # no curve on the right


# ---------------------------------------------------------------------------
# 5. set_results(left, right) → both panels populated, no message
# ---------------------------------------------------------------------------


def test_set_results_both_populated_no_message(qtbot):
    w = DualHemisphereAucWidget()
    qtbot.addWidget(w)
    w.set_results(_build_result(10, "L"), _build_result(10, "R"))

    for ax in _axes(w):
        assert not _has_message(ax)
        assert _marker_point_count(ax) > 0
        # CI band present.
        assert len(ax.collections) >= 1


# ---------------------------------------------------------------------------
# 6. Number of markers == len(band_centers_hz) + 1 modal, parametrized
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [10, 18])
def test_marker_count_matches_band_centers(qtbot, n):
    """No 10-hardcodes — the curve has exactly N markers + 1 modal marker."""
    w = DualHemisphereAucWidget()
    qtbot.addWidget(w)

    w.set_results(_build_result(n, "L"), None)

    left_ax, _ = _axes(w)
    # N curve points + 1 modal-band triangle.
    assert _marker_point_count(left_ax) == n + 1, (
        f"Expected {n} curve markers + 1 modal marker = {n + 1}, got "
        f"{_marker_point_count(left_ax)}"
    )


# ---------------------------------------------------------------------------
# 7. Greyscale audit — no chromatic literals in the widget's color set
# ---------------------------------------------------------------------------


def test_greyscale_audit_color_constants_only_greyscale(qtbot):
    """Each declared color constant must be greyscale or pure white/black."""
    from src.ui.views.snapshots_5hz_band.components import (
        dual_hemisphere_auc_widget as mod,
    )

    color_attrs = [
        "COLOR_PLOT_BG",
        "COLOR_AXIS",
        "COLOR_CURVE",
        "COLOR_MODAL_FILL",
        "COLOR_MODAL_OUTLINE",
        "COLOR_CI_FILL",
        "COLOR_REF",
    ]

    allowed = {
        "#000000",
        "#ffffff",
        "#bfbfbf",
        "#8a8a8a",
    }

    for attr in color_attrs:
        val = getattr(mod, attr)
        assert isinstance(val, str), f"{attr} should be a string color, got {val!r}"
        assert val.lower() in allowed, (
            f"{attr}={val!r} is not in the allowed greyscale set {allowed}; "
            f"the AUC widget must keep the manuscript greyscale aesthetic."
        )

    # Scan the source for the project's chromatic palette tokens (jade, rose):
    # their absence is the load-bearing audit.
    src_path = Path(mod.__file__)
    text = src_path.read_text()
    forbidden = ["#2BA495", "#8DD4CA", "#D97F86", "#AC4E8D", "#5B7FC7"]
    for token in forbidden:
        if re.search(re.escape(token), text, re.IGNORECASE):
            raise AssertionError(
                f"Forbidden chromatic token {token!r} appears in "
                f"dual_hemisphere_auc_widget.py — widget must be greyscale."
            )


# ---------------------------------------------------------------------------
# 8. Standalone invariant — no scripts/ or results/ imports in the widget
# ---------------------------------------------------------------------------


def test_no_external_script_imports():
    """The widget must be self-contained: zero imports from scripts/ or
    results/. The manuscript styling is ported inline, never imported."""
    from src.ui.views.snapshots_5hz_band.components import (
        dual_hemisphere_auc_widget as mod,
    )

    text = Path(mod.__file__).read_text()
    offenders = re.findall(
        r"^[ \t]*(?:from|import)[ \t]+(scripts|results)\b", text, re.MULTILINE
    )
    assert not offenders, (
        f"Widget imports from {set(offenders)} — it must be standalone "
        f"(no scripts/ or results/ imports)."
    )


# ---------------------------------------------------------------------------
# 9. export_png → produces a non-empty PNG file (headless savefig)
# ---------------------------------------------------------------------------


def test_export_png_creates_non_empty_file(qtbot, tmp_path):
    w = DualHemisphereAucWidget()
    qtbot.addWidget(w)
    w.set_results(_build_result(10, "L"), _build_result(10, "R"))

    out_path = tmp_path / "auc_export.png"
    ok = w.export_png(str(out_path))

    assert ok is True
    assert out_path.exists()
    assert out_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# 10. Annotation includes the pipeline-AUC 95% CI
# ---------------------------------------------------------------------------


def test_annotation_includes_pipeline_auc_ci(qtbot):
    """The per-panel annotation must include the pipeline-AUC 95% CI."""
    w = DualHemisphereAucWidget()
    qtbot.addWidget(w)

    sample = _build_result(10, "L")
    w.set_results(sample, sample)

    expected_ci = (
        f"[{sample.pipeline_loo_ci_lo:.3f}, {sample.pipeline_loo_ci_hi:.3f}]"
    )

    for ax in _axes(w):
        texts = " ".join(t.get_text() for t in ax.texts)
        assert expected_ci in texts, (
            f"Annotation text {texts!r} is missing the pipeline-AUC CI "
            f"substring {expected_ci!r}."
        )
