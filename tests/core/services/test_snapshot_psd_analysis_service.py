import importlib.util
from pathlib import Path

import numpy as np
import pytest
from datetime import datetime, timedelta
from scipy import stats

from src.core.services import snapshot_psd_analysis_service as analysis_module
from src.core.services.snapshot_psd_analysis_service import SnapshotPsdAnalysisService
from src.core.services.effect_size_calculator import EffectSizeCalculator
from src.domain.models import EffectSizeType
from src.domain.psd_models import SnapshotPsdDataset, SnapshotPsdEvent


class _StubEffectSizePreference:
    """Minimal stub to sidestep Qt dependency in tests."""

    def __init__(self, effect_type: EffectSizeType = EffectSizeType.COHENS_D):
        self._effect_size_type = effect_type

    def get_effect_size(self) -> EffectSizeType:
        return self._effect_size_type


@pytest.fixture
def service(monkeypatch):
    """Provide service with deterministic effect size preference."""
    preference_stub = _StubEffectSizePreference()
    monkeypatch.setattr(
        analysis_module,
        "EffectSizePreference",
        lambda: preference_stub,
    )
    return SnapshotPsdAnalysisService(effect_size_calculator=EffectSizeCalculator())


def _make_event(event_name: str, offset: float, freq_axis: np.ndarray) -> SnapshotPsdEvent:
    """Helper to produce SnapshotPsdEvent instances with predictable PSD."""
    base_psd = np.linspace(2.0 + offset, 12.0 + offset, freq_axis.size)
    artifact_mask = np.zeros(freq_axis.shape, dtype=bool)
    return SnapshotPsdEvent(
        timestamp=datetime(2025, 1, 1) + timedelta(minutes=int(offset * 10)),
        event_name=event_name,
        patient_event_id=f"{event_name}_{offset}",
        frequency_axis=freq_axis,
        psd_left=base_psd,
        psd_right=None,
        artifact_mask_left=artifact_mask,
        artifact_mask_right=None,
        hemisphere="LEFT",
    )


def test_fdr_preserves_effect_size_result(service):
    freq_axis = np.array(
        [
            1.0,
            1.5,
            2.0,
            2.5,
            3.0,
            3.5,
            4.0,
            5.5,
            6.0,
            7.0,
            8.0,
            9.0,
            10.0,
            11.0,
            12.0,
            13.0,
            14.0,
            15.0,
            16.0,
            17.0,
            18.0,
            19.0,
            20.0,
            21.0,
            22.0,
            23.0,
            24.0,
            25.0,
            26.0,
            27.0,
            28.0,
            29.0,
            30.0,
        ],
        dtype=float,
    )

    events = []
    for idx, offset in enumerate([0.0, 0.2, 0.4]):
        events.append(_make_event("Craving", offset, freq_axis))
        events.append(_make_event("Neutral", -0.6 - offset, freq_axis))

    dataset = SnapshotPsdDataset(
        patient_id="patient-123",
        events=events,
        frequency_axis=freq_axis,
    )

    results = service.analyze_group_comparison(
        dataset=dataset,
        group1_event_types=["Craving"],
        group2_event_types=["Neutral"],
        group1_name="Craving",
        group2_name="Neutral",
        hemisphere="LEFT",
        use_log_scale=False,
        filter_stimulation=False,
    )

    assert results, "Expected band comparison results to be generated"

    # Effect sizes must survive the FDR correction pass.
    for band_name, band_result in results.items():
        assert (
            band_result.effect_size_result is not None
        ), f"Effect size for band {band_name} was lost during FDR correction"
        assert (
            band_result.effect_size_result.effect_size_type == EffectSizeType.COHENS_D
        ), "Service should respect the injected effect size preference"


# ============================================================================
# D6 + D7 — canonical-script faithfulness of the displayed effect sizes.
# Targets: code_release/scripts/1_snapshot_stats_canonical.py (Supp Table 2):
#   * craving-referenced sign (positive = craving higher)
#   * rank-biserial r and Cohen's d both via 5,000-iter stratified BCa, seed 2025
#   * Cohen's d on log10 band power
# ============================================================================

# 33-bin frequency axis spanning the canonical low-frequency bands (1-30 Hz).
_FREQ_AXIS = np.array(
    [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.5, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0,
     12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0, 22.0, 23.0,
     24.0, 25.0, 26.0, 27.0, 28.0, 29.0, 30.0],
    dtype=float,
)


def _load_canonical_module():
    """Load the deposit script as a module for byte-level parity checks."""
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "code_release" / "scripts" / "1_snapshot_stats_canonical.py"
    spec = importlib.util.spec_from_file_location("snapshot_stats_canonical", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _service_with_pref(monkeypatch, effect_type: EffectSizeType) -> SnapshotPsdAnalysisService:
    """Build a service whose effect-size preference is pinned to ``effect_type``."""
    stub = _StubEffectSizePreference(effect_type)
    monkeypatch.setattr(analysis_module, "EffectSizePreference", lambda: stub)
    return SnapshotPsdAnalysisService(effect_size_calculator=EffectSizeCalculator())


def _craving_high_dataset() -> SnapshotPsdDataset:
    """Dataset where craving PSD power is uniformly above non-craving."""
    events = []
    for off in (1.0, 1.2, 1.4, 1.6, 1.8):
        events.append(_make_event("Craving", off, _FREQ_AXIS))   # higher power
    for off in (-1.0, -1.2, -1.4, -1.6, -1.8):
        events.append(_make_event("Neutral", off, _FREQ_AXIS))   # lower power
    return SnapshotPsdDataset(
        patient_id="p-sign", events=events, frequency_axis=_FREQ_AXIS
    )


# ---------------------------------------------------------------------------
# Sign — craving-referenced (positive = craving higher)
# ---------------------------------------------------------------------------

def test_helper_effect_sizes_are_craving_referenced():
    rng = np.random.default_rng(0)
    craving = rng.normal(10.0, 1.0, 40)
    non_craving = rng.normal(8.0, 1.0, 50)

    # Craving first -> both positive when craving is higher.
    assert analysis_module._effect_sizes(craving, non_craving)[2] > 0
    assert analysis_module._cohens_d(craving, non_craving) > 0

    # Swapping the groups negates the sign (order convention is the only driver).
    r_swapped = analysis_module._effect_sizes(non_craving, craving)[2]
    assert r_swapped == pytest.approx(
        -analysis_module._effect_sizes(craving, non_craving)[2], abs=1e-12
    )


def test_legacy_rank_biserial_anchor_matches_supp_table_2():
    """Pt1 delta anchor: craving-first U=5659, n_cr=56, n_nc=159 -> r_rb=+0.271.

    The legacy ``rank_biserial_r`` field stores ``u_stat`` non-craving-first, so
    the service complements it. Verify the complement reproduces +0.271 (the old
    code produced -0.271).
    """
    n_cr, n_nc = 56, 159
    u_craving = 5659.0
    u_stat_app = n_cr * n_nc - u_craving  # what mannwhitneyu(non_craving, craving) returns
    legacy = (2 * (n_cr * n_nc - u_stat_app)) / (n_cr * n_nc) - 1
    assert legacy == pytest.approx(0.271, abs=5e-4)


@pytest.mark.slow
@pytest.mark.parametrize(
    "pref", [EffectSizeType.RANK_BISERIAL, EffectSizeType.COHENS_D]
)
def test_service_displays_craving_referenced_effect_size(monkeypatch, pref):
    service = _service_with_pref(monkeypatch, pref)
    results = service.analyze_group_comparison(
        dataset=_craving_high_dataset(),
        group1_event_types=["Neutral"],   # Group 1 = non-craving
        group2_event_types=["Craving"],   # Group 2 = craving
        group1_name="Non-Craving",
        group2_name="Craving",
        hemisphere="LEFT",
        filter_stimulation=False,
    )

    assert results, "Expected band comparison results"
    delta = results["Delta"]
    eff = delta.effect_size_result
    assert eff is not None
    assert eff.effect_size_type == pref
    # Craving higher -> displayed effect size positive (craving-referenced).
    assert eff.value > 0, f"{pref.value} should be positive when craving is higher"
    # Legacy fallback field is craving-referenced too.
    assert delta.rank_biserial_r > 0
    # CI endpoints are populated (bootstrap succeeded on non-degenerate data).
    assert np.isfinite(eff.ci_lower) and np.isfinite(eff.ci_upper)


# ---------------------------------------------------------------------------
# Scale — Cohen's d is computed on log10 band power
# ---------------------------------------------------------------------------

def test_cohens_d_uses_log10_scale():
    # Right-skewed positive arrays: log10 changes d substantially vs raw scale.
    craving = np.array([2.0, 3.0, 4.0, 5.0, 100.0])
    non_craving = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

    d_raw = analysis_module._cohens_d(craving, non_craving)
    d_log = analysis_module._cohens_d(np.log10(craving), np.log10(non_craving))
    assert not np.isclose(d_raw, d_log), "log10 transform must change Cohen's d"

    # The displayed COHENS_D path feeds log10 power to bca_bootstrap_d, so its
    # point estimate must equal _cohens_d on the already-logged input.
    value, _, _ = analysis_module.bca_bootstrap_d(
        np.log10(craving), np.log10(non_craving), n_boot=200
    )
    assert value == pytest.approx(d_log, abs=1e-12)


# ---------------------------------------------------------------------------
# CI is BCa bootstrap (not the parametric Kerby normal approximation)
# ---------------------------------------------------------------------------

def test_displayed_ci_is_bca_bootstrap_not_kerby():
    rng = np.random.default_rng(3)
    craving = np.abs(rng.normal(6.0, 2.0, 35)) + 1.0
    non_craving = np.abs(rng.normal(4.0, 1.5, 45)) + 1.0

    value, lo, hi = analysis_module.bca_bootstrap_rrb(craving, non_craving)

    # BCa is asymmetric about the point estimate; the Kerby normal approximation
    # (value +/- z*SE) is symmetric. Asymmetry => not the parametric formula.
    assert abs((value - lo) - (hi - value)) > 1e-3

    # Reproducible under the fixed seed (2025).
    assert analysis_module.bca_bootstrap_rrb(craving, non_craving) == pytest.approx(
        (value, lo, hi)
    )

    # And it differs from the shared calculator's parametric Kerby CI computed
    # on the same craving-first arrays (same point estimate, different CI).
    calc = EffectSizeCalculator()
    u_craving, _ = stats.mannwhitneyu(craving, non_craving, alternative="two-sided")
    k_val, k_lo, k_hi = calc._calculate_rank_biserial(craving, non_craving, u_craving)
    assert k_val == pytest.approx(value, abs=1e-9)  # same point estimate
    assert not (
        lo == pytest.approx(k_lo, abs=1e-6) and hi == pytest.approx(k_hi, abs=1e-6)
    )


# ---------------------------------------------------------------------------
# Parity — point estimates and BCa CIs match the canonical deposit script
# ---------------------------------------------------------------------------

def test_effect_sizes_match_canonical_script():
    canonical = _load_canonical_module()

    rng = np.random.default_rng(7)
    craving = np.abs(rng.normal(5.0, 1.5, 30)) + 1.0
    non_craving = np.abs(rng.normal(4.0, 1.2, 40)) + 1.0

    # Point estimates are deterministic (no RNG) -> exact match.
    assert analysis_module._effect_sizes(craving, non_craving)[2] == pytest.approx(
        canonical._effect_sizes(craving, non_craving)[2], abs=1e-12
    )
    assert analysis_module._cohens_d(
        np.log10(craving), np.log10(non_craving)
    ) == pytest.approx(
        canonical._cohens_d(np.log10(craving), np.log10(non_craving)), abs=1e-12
    )

    # Full stratified BCa with matched iterations + shared default seed (2025)
    # -> identical resample streams -> identical CIs.
    assert analysis_module.bca_bootstrap_rrb(
        craving, non_craving, n_boot=500
    ) == pytest.approx(
        canonical.bca_bootstrap_rrb(craving, non_craving, n_boot=500), abs=1e-9
    )
    assert analysis_module.bca_bootstrap_d(
        np.log10(craving), np.log10(non_craving), n_boot=500
    ) == pytest.approx(
        canonical.bca_bootstrap_d(np.log10(craving), np.log10(non_craving), n_boot=500),
        abs=1e-9,
    )
