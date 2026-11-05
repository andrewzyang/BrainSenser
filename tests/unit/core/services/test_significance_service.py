"""
Unit tests for SignificanceService

Tests business logic for determining when to show significance indicators
based on p-values and q-values.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-15
"""

import pytest
from src.core.services.significance_service import SignificanceService
from src.domain.significance_info import SignificanceType


class TestSignificanceService:
    """Test suite for SignificanceService"""

    def test_service_initialization(self):
        """Test that service initializes with default threshold"""
        service = SignificanceService()
        assert service.significance_threshold == 0.05

    def test_service_custom_threshold(self):
        """Test service initialization with custom threshold"""
        service = SignificanceService(significance_threshold=0.01)
        assert service.significance_threshold == 0.01

    def test_set_threshold_valid(self):
        """Test setting a valid threshold"""
        service = SignificanceService()
        service.set_significance_threshold(0.01)
        assert service.significance_threshold == 0.01

    def test_set_threshold_invalid(self):
        """Test that invalid thresholds raise ValueError"""
        service = SignificanceService()

        with pytest.raises(ValueError):
            service.set_significance_threshold(0.0)

        with pytest.raises(ValueError):
            service.set_significance_threshold(1.0)

        with pytest.raises(ValueError):
            service.set_significance_threshold(-0.05)

        with pytest.raises(ValueError):
            service.set_significance_threshold(1.5)

    def test_evaluate_significance_corrected_significant(self):
        """Test: corrected q-value < 0.05 → show indicator for q"""
        service = SignificanceService()

        # Case: p < 0.05, q < 0.05 (both significant, correction applied)
        sig_info = service.evaluate_significance(p_value=0.02, q_value=0.03)

        assert sig_info.p_value == 0.02
        assert sig_info.q_value == 0.03
        assert sig_info.has_correction is True
        assert sig_info.q_is_significant is True
        assert sig_info.show_indicator_for_q is True
        assert sig_info.show_indicator_for_p is False  # Priority to corrected
        assert sig_info.significance_type == SignificanceType.CORRECTED

    def test_evaluate_significance_uncorrected_significant(self):
        """Test: no correction, p < 0.05 → show indicator for p"""
        service = SignificanceService()

        # Case: No correction applied (q_value is None)
        sig_info = service.evaluate_significance(p_value=0.03, q_value=None)

        assert sig_info.p_value == 0.03
        assert sig_info.q_value is None
        assert sig_info.has_correction is False
        assert sig_info.p_is_significant is True
        assert sig_info.show_indicator_for_p is True
        assert sig_info.show_indicator_for_q is False
        assert sig_info.significance_type == SignificanceType.UNCORRECTED

    def test_evaluate_significance_no_correction_applied(self):
        """Test: q-value equals p-value → treated as no correction"""
        service = SignificanceService()

        # Case: q_value equals p_value (no correction actually applied)
        sig_info = service.evaluate_significance(p_value=0.03, q_value=0.03)

        assert sig_info.p_value == 0.03
        assert sig_info.q_value == 0.03
        assert sig_info.has_correction is False  # Should detect no real correction
        assert sig_info.p_is_significant is True
        assert sig_info.show_indicator_for_p is True
        assert sig_info.show_indicator_for_q is False
        assert sig_info.significance_type == SignificanceType.UNCORRECTED

    def test_evaluate_significance_not_significant(self):
        """Test: both p and q >= 0.05 → no indicator"""
        service = SignificanceService()

        # Case: Neither significant
        sig_info = service.evaluate_significance(p_value=0.12, q_value=0.25)

        assert sig_info.p_is_significant is False
        assert sig_info.q_is_significant is False
        assert sig_info.show_indicator_for_p is False
        assert sig_info.show_indicator_for_q is False
        assert sig_info.significance_type == SignificanceType.NONE

    def test_evaluate_significance_p_significant_q_not(self):
        """Test: p < 0.05 but q >= 0.05 after correction → no indicator"""
        service = SignificanceService()

        # Case: p significant, but q not significant after correction
        sig_info = service.evaluate_significance(p_value=0.03, q_value=0.08)

        assert sig_info.p_is_significant is True
        assert sig_info.q_is_significant is False
        assert sig_info.has_correction is True
        assert sig_info.show_indicator_for_p is False  # Correction applied, use q
        assert sig_info.show_indicator_for_q is False  # q not significant
        assert sig_info.significance_type == SignificanceType.NONE

    def test_should_show_indicator_for_p(self):
        """Test helper method for p-value indicator"""
        service = SignificanceService()

        # Should show for p when no correction
        assert service.should_show_indicator_for_p(p_value=0.03, q_value=None) is True

        # Should NOT show for p when correction applied
        assert service.should_show_indicator_for_p(p_value=0.03, q_value=0.04) is False

        # Should NOT show for p when not significant
        assert service.should_show_indicator_for_p(p_value=0.10, q_value=None) is False

    def test_should_show_indicator_for_q(self):
        """Test helper method for q-value indicator"""
        service = SignificanceService()

        # Should show for q when correction applied and significant
        assert service.should_show_indicator_for_q(p_value=0.03, q_value=0.04) is True

        # Should NOT show for q when no correction
        assert service.should_show_indicator_for_q(p_value=0.03, q_value=None) is False

        # Should NOT show for q when not significant
        assert service.should_show_indicator_for_q(p_value=0.03, q_value=0.10) is False

    def test_edge_case_boundary_values(self):
        """Test boundary values (exactly 0.05)"""
        service = SignificanceService()

        # p = 0.05 (exactly at threshold)
        sig_info = service.evaluate_significance(p_value=0.05, q_value=None)
        assert sig_info.p_is_significant is False  # Should be >= 0.05
        assert sig_info.show_indicator_for_p is False

        # q = 0.05 (exactly at threshold)
        sig_info = service.evaluate_significance(p_value=0.01, q_value=0.05)
        assert sig_info.q_is_significant is False
        assert sig_info.show_indicator_for_q is False

        # p = 0.049999 (just below threshold)
        sig_info = service.evaluate_significance(p_value=0.049999, q_value=None)
        assert sig_info.p_is_significant is True
        assert sig_info.show_indicator_for_p is True

    def test_custom_threshold_affects_evaluation(self):
        """Test that custom thresholds work correctly"""
        service = SignificanceService(significance_threshold=0.01)

        # p=0.02 should NOT be significant with 0.01 threshold
        sig_info = service.evaluate_significance(p_value=0.02, q_value=None)
        assert sig_info.p_is_significant is False
        assert sig_info.show_indicator_for_p is False

        # p=0.005 should be significant with 0.01 threshold
        sig_info = service.evaluate_significance(p_value=0.005, q_value=None)
        assert sig_info.p_is_significant is True
        assert sig_info.show_indicator_for_p is True

    def test_floating_point_precision(self):
        """Test that small floating point differences are handled"""
        service = SignificanceService()

        # Very small difference (should be treated as no correction)
        sig_info = service.evaluate_significance(
            p_value=0.03,
            q_value=0.03 + 1e-11  # Within floating point tolerance
        )
        assert sig_info.has_correction is False

        # Larger difference (should be treated as correction applied)
        sig_info = service.evaluate_significance(
            p_value=0.03,
            q_value=0.03 + 1e-9  # Beyond floating point tolerance
        )
        assert sig_info.has_correction is True
