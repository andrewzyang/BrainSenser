"""
Unit tests for SignificanceInfo domain model

Tests the immutable domain model for significance state.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-15
"""

import pytest
from src.domain.significance_info import SignificanceInfo, SignificanceType


class TestSignificanceInfo:
    """Test suite for SignificanceInfo domain model"""

    def test_immutable_dataclass(self):
        """Test that SignificanceInfo is immutable (frozen)"""
        info = SignificanceInfo(p_value=0.03, q_value=0.05)

        with pytest.raises(Exception):  # FrozenInstanceError
            info.p_value = 0.01

    def test_p_is_significant_true(self):
        """Test p_is_significant property when p < threshold"""
        info = SignificanceInfo(p_value=0.03, q_value=None)
        assert info.p_is_significant is True

    def test_p_is_significant_false(self):
        """Test p_is_significant property when p >= threshold"""
        info = SignificanceInfo(p_value=0.10, q_value=None)
        assert info.p_is_significant is False

    def test_q_is_significant_true(self):
        """Test q_is_significant property when q < threshold"""
        info = SignificanceInfo(p_value=0.01, q_value=0.03)
        assert info.q_is_significant is True

    def test_q_is_significant_false_not_significant(self):
        """Test q_is_significant property when q >= threshold"""
        info = SignificanceInfo(p_value=0.01, q_value=0.10)
        assert info.q_is_significant is False

    def test_q_is_significant_false_none(self):
        """Test q_is_significant property when q is None"""
        info = SignificanceInfo(p_value=0.01, q_value=None)
        assert info.q_is_significant is False

    def test_has_correction_true(self):
        """Test has_correction property when q differs from p"""
        info = SignificanceInfo(p_value=0.02, q_value=0.05)
        assert info.has_correction is True

    def test_has_correction_false_none(self):
        """Test has_correction property when q is None"""
        info = SignificanceInfo(p_value=0.02, q_value=None)
        assert info.has_correction is False

    def test_has_correction_false_equal(self):
        """Test has_correction property when q equals p"""
        info = SignificanceInfo(p_value=0.03, q_value=0.03)
        assert info.has_correction is False

    def test_has_correction_floating_point_tolerance(self):
        """Test that small floating point differences are ignored"""
        # Within tolerance
        info = SignificanceInfo(p_value=0.03, q_value=0.03 + 1e-11)
        assert info.has_correction is False

        # Beyond tolerance
        info = SignificanceInfo(p_value=0.03, q_value=0.03 + 1e-9)
        assert info.has_correction is True

    def test_show_indicator_for_p_no_correction_significant(self):
        """Test: no correction + p significant → show p indicator"""
        info = SignificanceInfo(p_value=0.03, q_value=None)
        assert info.show_indicator_for_p is True
        assert info.show_indicator_for_q is False

    def test_show_indicator_for_p_no_correction_not_significant(self):
        """Test: no correction + p not significant → no indicator"""
        info = SignificanceInfo(p_value=0.10, q_value=None)
        assert info.show_indicator_for_p is False
        assert info.show_indicator_for_q is False

    def test_show_indicator_for_q_correction_significant(self):
        """Test: correction + q significant → show q indicator"""
        info = SignificanceInfo(p_value=0.02, q_value=0.03)
        assert info.show_indicator_for_q is True
        assert info.show_indicator_for_p is False  # Priority to q

    def test_show_indicator_for_q_correction_not_significant(self):
        """Test: correction + q not significant → no indicator"""
        info = SignificanceInfo(p_value=0.02, q_value=0.08)
        assert info.show_indicator_for_q is False
        assert info.show_indicator_for_p is False

    def test_show_indicator_priority_to_corrected(self):
        """Test: when both p and q significant, priority goes to q"""
        info = SignificanceInfo(p_value=0.01, q_value=0.02)
        assert info.show_indicator_for_q is True
        assert info.show_indicator_for_p is False  # q has priority

    def test_significance_type_none(self):
        """Test significance_type when not significant"""
        info = SignificanceInfo(p_value=0.10, q_value=0.15)
        assert info.significance_type == SignificanceType.NONE

    def test_significance_type_uncorrected(self):
        """Test significance_type when only p significant"""
        info = SignificanceInfo(p_value=0.03, q_value=None)
        assert info.significance_type == SignificanceType.UNCORRECTED

    def test_significance_type_corrected(self):
        """Test significance_type when q significant"""
        info = SignificanceInfo(p_value=0.02, q_value=0.03)
        assert info.significance_type == SignificanceType.CORRECTED

    def test_get_display_value_for_p(self):
        """Test get_display_value_for_p returns value when indicator shown"""
        # Should return value when indicator shown
        info = SignificanceInfo(p_value=0.03, q_value=None)
        assert info.get_display_value_for_p() == 0.03

        # Should return None when indicator not shown
        info = SignificanceInfo(p_value=0.03, q_value=0.04)
        assert info.get_display_value_for_p() is None

        # Should return None when not significant
        info = SignificanceInfo(p_value=0.10, q_value=None)
        assert info.get_display_value_for_p() is None

    def test_get_display_value_for_q(self):
        """Test get_display_value_for_q returns value when indicator shown"""
        # Should return value when indicator shown
        info = SignificanceInfo(p_value=0.02, q_value=0.03)
        assert info.get_display_value_for_q() == 0.03

        # Should return None when no correction
        info = SignificanceInfo(p_value=0.03, q_value=None)
        assert info.get_display_value_for_q() is None

        # Should return None when not significant
        info = SignificanceInfo(p_value=0.02, q_value=0.10)
        assert info.get_display_value_for_q() is None

    def test_custom_threshold(self):
        """Test that custom threshold affects all properties"""
        # Custom threshold 0.01
        info = SignificanceInfo(p_value=0.02, q_value=None, significance_threshold=0.01)

        assert info.p_is_significant is False  # 0.02 >= 0.01
        assert info.show_indicator_for_p is False

        # With 0.01 threshold and p=0.005
        info = SignificanceInfo(p_value=0.005, q_value=None, significance_threshold=0.01)
        assert info.p_is_significant is True
        assert info.show_indicator_for_p is True

    def test_edge_case_all_zeros(self):
        """Test edge case with p=0"""
        info = SignificanceInfo(p_value=0.0, q_value=None)
        assert info.p_is_significant is True
        assert info.show_indicator_for_p is True

    def test_edge_case_p_exactly_threshold(self):
        """Test boundary value p = 0.05"""
        info = SignificanceInfo(p_value=0.05, q_value=None)
        assert info.p_is_significant is False  # Should be <, not <=
        assert info.show_indicator_for_p is False

    def test_edge_case_q_exactly_threshold(self):
        """Test boundary value q = 0.05"""
        info = SignificanceInfo(p_value=0.01, q_value=0.05)
        assert info.q_is_significant is False  # Should be <, not <=
        assert info.show_indicator_for_q is False

    def test_real_world_scenario_fdr_correction(self):
        """Test realistic FDR correction scenario"""
        # Scenario: 5 tests, one passes after FDR
        # Test 1: p=0.001, q=0.005 (passes FDR)
        info1 = SignificanceInfo(p_value=0.001, q_value=0.005)
        assert info1.show_indicator_for_q is True
        assert info1.significance_type == SignificanceType.CORRECTED

        # Test 2: p=0.03, q=0.08 (fails FDR)
        info2 = SignificanceInfo(p_value=0.03, q_value=0.08)
        assert info2.show_indicator_for_q is False
        assert info2.show_indicator_for_p is False
        assert info2.significance_type == SignificanceType.NONE

    def test_real_world_scenario_no_correction(self):
        """Test realistic scenario with no multiple comparison correction"""
        # Single comparison, p < 0.05
        info = SignificanceInfo(p_value=0.023, q_value=None)
        assert info.show_indicator_for_p is True
        assert info.significance_type == SignificanceType.UNCORRECTED

    def test_real_world_scenario_correction_equals_p(self):
        """Test scenario where q-value equals p-value (single test)"""
        # When only 1 test is run, FDR correction doesn't change p-value
        info = SignificanceInfo(p_value=0.023, q_value=0.023)
        assert info.has_correction is False  # Treated as no correction
        assert info.show_indicator_for_p is True
        assert info.significance_type == SignificanceType.UNCORRECTED
