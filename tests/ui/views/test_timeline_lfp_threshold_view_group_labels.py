"""Tests for the Timeline → LFP Threshold group-label format helper.

Pins the contract used by :func:`_format_group_label` in
``src/ui/views/timeline_lfp_threshold/timeline_lfp_threshold_view.py``: the user's selected
event names render into the violin x-tick label so the plot is
self-describing for arbitrary group selections (e.g. ``"Happy"`` vs
``"Neutral"`` instead of the generic ``"Group 1"`` / ``"Group 2"``).
"""

from __future__ import annotations

import pytest

from src.ui.views.timeline_lfp_threshold.timeline_lfp_threshold_view import _format_group_label


class TestFormatGroupLabel:
    def test_empty_returns_default(self):
        assert _format_group_label([], "Group 1") == "Group 1"
        assert _format_group_label([], "Group 2") == "Group 2"

    def test_single_name_returns_name(self):
        assert _format_group_label(["Happy"], "Group 1") == "Happy"
        assert _format_group_label(["Drinking/Craving"], "Group 2") == \
            "Drinking/Craving"

    def test_two_names_joined_with_plus(self):
        assert _format_group_label(["Happy", "Neutral"], "Group 1") == \
            "Happy + Neutral"
        assert _format_group_label(
            ["Drinking", "Drinking/Craving"], "Group 2"
        ) == "Drinking + Drinking/Craving"

    def test_three_names_truncated_with_count(self):
        assert _format_group_label(
            ["Craving", "Drinking", "Drinking/Craving"], "Group 1"
        ) == "Craving (+2 more)"

    def test_many_names_truncated_with_count(self):
        names = ["Anxious", "Sad", "Depressed", "Happy", "Neutral"]
        assert _format_group_label(names, "Group 1") == "Anxious (+4 more)"

    def test_none_input_returns_default(self):
        # Defensive: ``if not names`` accepts None and falls through to
        # the default placeholder rather than crashing.
        assert _format_group_label(None, "Group 1") == "Group 1"  # type: ignore[arg-type]
