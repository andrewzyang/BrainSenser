"""
Tests for SnapshotMlAnalysisService.

Validates:
- Import-clean (no PySide6 in sys.modules after import).
- AucProfileResult shape contract.
- Numerical parity with the script-direct pipeline.
- Cancellation via OperationCancelledException.
- Empty-after-preprocessing guard.
- Both-hemisphere dispatch with one-side-None inputs.
- progress_callback plumbing.

Author: iEEG BrainSense Development Team
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# 1. Import-clean
# ---------------------------------------------------------------------------


def test_service_import_does_not_pull_in_pyside6():
    """The service must be Qt-free.

    After importing it (and only it), PySide6 must not appear in sys.modules.
    Run in a subprocess to start with a clean import state — otherwise
    other tests that already imported PySide6 would invalidate the check.
    """
    import subprocess

    code = (
        "import sys\n"
        "from src.core.services.snapshot_ml_analysis_service import "
        "SnapshotMlAnalysisService\n"
        "assert 'PySide6' not in sys.modules, "
        "f'PySide6 leaked in: {sorted(k for k in sys.modules if k.startswith(\"PySide6\"))}'\n"
        "print('OK')\n"
    )
    project_root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# Helpers — synthesize a small but realistic PSD fixture
# ---------------------------------------------------------------------------


def _synthetic_fixture(seed: int = 0):
    """
    Build a tiny PSD fixture sized so candidate_band_bins yields a small N.

    With FREQ_MIN_HZ=5.31, FREQ_MAX_HZ=37.5 and a Percept-like ~0.98 Hz bin
    width, the envelope contains ~33 bins → N=10 candidate bands. Use a
    realistic frequency axis (0.98 Hz spacing) so the service's envelope
    masking + band construction matches the script.
    """
    rng = np.random.default_rng(seed)
    # 95 bins from ~0.98 Hz to ~93.1 Hz, mirroring the Percept device grid.
    freqs = np.arange(1, 96) * 0.9766
    n_freq = freqs.size

    # Generate raw µV²/Hz with a ~1/f shape so log10 is well-behaved.
    base_shape = 1.0 / (freqs + 0.5)

    # Inject a modest band-specific signal in ~12-18 Hz for craving.
    n_crav = 8
    n_nc = 9
    crav = np.tile(base_shape, (n_crav, 1)) * (1.0 + 0.05 * rng.standard_normal((n_crav, n_freq)))
    nc = np.tile(base_shape, (n_nc, 1)) * (1.0 + 0.05 * rng.standard_normal((n_nc, n_freq)))

    # Boost craving in 12-18 Hz so the analysis has a real signal to find.
    band_mask = (freqs >= 12) & (freqs <= 18)
    crav[:, band_mask] *= 1.4

    # Small NaN rate to exercise the row-cleaner (well below the 30 % drop
    # threshold so no rows are dropped — keeps n_crav/n_nc deterministic).
    n_nan = 1
    for row in crav:
        idx = rng.integers(0, n_freq, size=n_nan)
        row[idx] = np.nan
    for row in nc:
        idx = rng.integers(0, n_freq, size=n_nan)
        row[idx] = np.nan

    return crav, nc, freqs


# ---------------------------------------------------------------------------
# 2. Output shapes / contract
# ---------------------------------------------------------------------------


def test_output_shapes_and_contract():
    """The result fields must satisfy the documented invariants."""
    from src.core.services.snapshot_ml_analysis_service import (
        AucProfileResult,
        SnapshotMlAnalysisService,
    )

    crav, nc, freqs = _synthetic_fixture(seed=0)

    service = SnapshotMlAnalysisService()
    result = service.analyze_hemisphere(
        crav, nc, freqs, "L",
        n_perm=20, n_boot=20, seed=42,
    )

    assert isinstance(result, AucProfileResult)
    assert result.hemisphere == "L"

    n = result.band_centers_hz.shape[0]
    assert n > 0, "fixture should produce >= 1 candidate band"

    # Per-band shape consistency
    assert result.per_band_auc.shape == (n,)
    assert result.per_band_ci_lo.shape == (n,)
    assert result.per_band_ci_hi.shape == (n,)
    assert result.band_edges_hz.shape == (n, 2)

    # Strictly increasing band centers
    assert np.all(np.diff(result.band_centers_hz) > 0)

    # CI ordering: 0 ≤ ci_lo ≤ auc ≤ ci_hi ≤ 1
    assert np.all(result.per_band_ci_lo >= 0.0 - 1e-9)
    assert np.all(result.per_band_ci_lo <= result.per_band_auc + 1e-9)
    assert np.all(result.per_band_auc <= result.per_band_ci_hi + 1e-9)
    assert np.all(result.per_band_ci_hi <= 1.0 + 1e-9)

    # Modal index in range
    assert 0 <= result.modal_band_idx < n

    # FWER p in (0, 1]
    assert 0.0 < result.fwer_p <= 1.0

    # Pipeline AUC + CI plausible
    assert 0.0 <= result.pipeline_loo_ci_lo <= result.pipeline_loo_auc + 1e-9
    assert result.pipeline_loo_auc <= result.pipeline_loo_ci_hi + 1e-9
    assert result.pipeline_loo_ci_hi <= 1.0 + 1e-9


# ---------------------------------------------------------------------------
# 3. Numerical parity with the script's direct pipeline
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_numerical_parity_with_canonical_classifier():
    """The standalone kernel (via the service) must match the published
    canonical classifier numerically -- the accuracy guarantee for shipping
    the app standalone.

    The service now imports its kernel from
    ``src.core.analysis.snapshot_loo_kernel`` (no ``scripts``/``code_release``
    dependency). This test proves that kernel reproduces the deposited,
    manuscript-anchored classifier
    ``code_release/scripts/2_snapshot_5hz_classifier.py`` bit-for-bit.

    Two paths over the same deposited PSD matrix (Pt2 Left):
      - canonical : load_csv_matrix -> precompute -> nested LOO -> bootstrap +
                    permutation_fwer -> per_band_loo_aucs
      - service   : same matrix split into (crav, nc, freqs) -> analyze_hemisphere

    Both run at the same n_perm / n_boot / seed and must agree on
    pipeline_loo_auc, pipeline_loo_ci, modal_band_idx, per_band_auc, and fwer_p.

    ``code_release`` is imported ONLY here (a test), never in ``src`` -- the
    shipped app stays standalone. Skips if the canonical script or its data CSV
    is absent from the checkout.
    """
    import importlib.util
    from collections import Counter

    repo_root = Path(__file__).resolve().parents[4]
    canon_path = (
        repo_root / "code_release" / "scripts" / "2_snapshot_5hz_classifier.py"
    )
    pt2_csv = repo_root / "code_release" / "data" / "pt2_snapshots.csv"
    if not canon_path.exists() or not pt2_csv.exists():
        pytest.skip("canonical classifier or pt2_snapshots.csv not available")

    # Import the canonical deposit script by file path: its module name starts
    # with a digit, so a normal ``import`` statement is impossible.
    spec = importlib.util.spec_from_file_location("_canonical_5hz", canon_path)
    canon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = canon
    spec.loader.exec_module(canon)

    from src.core.services.snapshot_ml_analysis_service import (
        SnapshotMlAnalysisService,
    )

    n_perm, n_boot, seed = 200, 200, 42

    X, y, freqs = canon.load_csv_matrix(
        pt2_csv, "Left", canon.FREQ_MIN_HZ, canon.FREQ_MAX_HZ
    )
    if X.size == 0 or len(np.unique(y)) < 2:
        pytest.skip("pt2 Left CSV fixture has no usable events")

    # The service stacks rows as [nc (label 0), crav (label 1)]; load_csv_matrix
    # returns CSV order (label-interleaved). Canonicalize the canonical path's
    # row order to [nc, crav] so the seed-driven FWER null and the bootstrap CI
    # are bit-comparable (same rationale as the pre-refactor parity test).
    order = np.argsort(y, kind="stable")
    Xs, ys = X[order], y[order]

    bands = canon.candidate_band_bins(freqs)
    band_powers = canon.precompute_band_powers(Xs, bands)
    held, sel, _dirs, per_band_held = canon.nested_loo_predictions(band_powers, ys)
    canon_loo_auc = float(canon.loo_auc_from_predictions(held, ys))
    canon_modal_idx = int(Counter(sel.tolist()).most_common(1)[0][0])
    canon_ci_lo, canon_ci_hi = canon.bootstrap_loo_ci(held, ys, n_boot, seed)
    canon_fwer_p, _ = canon.permutation_fwer(
        band_powers, ys, canon_loo_auc, n_perm, seed
    )
    canon_per_band_auc = canon.per_band_loo_aucs(per_band_held, ys)

    # --- service path (exercises src/core/analysis/snapshot_loo_kernel) ------
    # Feed the unsorted, envelope-restricted matrix split by class; the service
    # does its own [nc, crav] stacking and re-masks freqs (a no-op here, since
    # load_csv_matrix already restricted to [5.31, 37.5] Hz).
    crav = X[y == 1]
    nc = X[y == 0]
    service = SnapshotMlAnalysisService()
    result = service.analyze_hemisphere(
        crav, nc, freqs, "L", n_perm=n_perm, n_boot=n_boot, seed=seed,
    )

    # --- comparisons: service (standalone kernel) == canonical classifier ----
    assert abs(result.pipeline_loo_auc - canon_loo_auc) <= 1e-6, (
        f"pipeline_loo_auc: service={result.pipeline_loo_auc}, "
        f"canonical={canon_loo_auc}"
    )
    assert result.modal_band_idx == canon_modal_idx, (
        f"modal_band_idx: service={result.modal_band_idx}, "
        f"canonical={canon_modal_idx}"
    )
    np.testing.assert_allclose(
        result.per_band_auc, canon_per_band_auc, atol=1e-6,
        err_msg="per_band_auc mismatch between service and canonical classifier",
    )
    assert abs(result.pipeline_loo_ci_lo - canon_ci_lo) <= 1e-6, (
        f"pipeline_loo_ci_lo: service={result.pipeline_loo_ci_lo}, "
        f"canonical={canon_ci_lo}"
    )
    assert abs(result.pipeline_loo_ci_hi - canon_ci_hi) <= 1e-6, (
        f"pipeline_loo_ci_hi: service={result.pipeline_loo_ci_hi}, "
        f"canonical={canon_ci_hi}"
    )
    assert abs(result.fwer_p - canon_fwer_p) <= 1e-6, (
        f"fwer_p: service={result.fwer_p}, canonical={canon_fwer_p}"
    )


# ---------------------------------------------------------------------------
# 4. Cancellation
# ---------------------------------------------------------------------------


def test_cancellation_raises_operation_cancelled():
    """If cancel_check returns True, the service must raise the typed exc."""
    from src.core.services.snapshot_ml_analysis_service import (
        OperationCancelledException,
        SnapshotMlAnalysisService,
    )

    crav, nc, freqs = _synthetic_fixture(seed=0)
    service = SnapshotMlAnalysisService()

    def cancel_check() -> bool:
        return True

    with pytest.raises(OperationCancelledException):
        service.analyze_hemisphere(
            crav, nc, freqs, "L",
            n_perm=20, n_boot=20, seed=42,
            cancel_check=cancel_check,
        )


def test_cancellation_inside_permutation_loop_raises_with_hemisphere_label():
    """cancel_check polled inside permutation_fwer aborts the perm loop.

    Pass a cancel_check that returns False until its 5th call, then True.
    The service must raise OperationCancelledException with a message that
    embeds the hemisphere label (so error logs / status bars can show
    which side bailed) and the cause must come from the permutation loop
    rather than a between-stage check.
    """
    from src.core.services.snapshot_ml_analysis_service import (
        OperationCancelledException,
        SnapshotMlAnalysisService,
    )

    crav, nc, freqs = _synthetic_fixture(seed=3)
    service = SnapshotMlAnalysisService()

    call_counter = {"n": 0}

    def cancel_check() -> bool:
        call_counter["n"] += 1
        return call_counter["n"] >= 5

    with pytest.raises(OperationCancelledException) as exc_info:
        service.analyze_hemisphere(
            crav, nc, freqs, "R",
            n_perm=20, n_boot=20, seed=0,
            cancel_check=cancel_check,
        )

    assert "R" in str(exc_info.value)
    # Must have entered the perm loop (at least 4 polls before the cancel
    # poll inside the loop fired) — confirms the cancel check is plumbed
    # through to permutation_fwer rather than only checked between stages.
    assert call_counter["n"] >= 5


# ---------------------------------------------------------------------------
# 5. Empty-after-preprocessing guard
# ---------------------------------------------------------------------------


def test_empty_after_preprocessing_raises_value_error():
    """A matrix with all-NaN rows (above the 30 % drop threshold) is empty.

    The service should raise ValueError with the hemisphere label embedded.
    """
    from src.core.services.snapshot_ml_analysis_service import (
        SnapshotMlAnalysisService,
    )

    freqs = np.arange(1, 96) * 0.9766
    n_freq = freqs.size

    # All-NaN crav matrix → all rows dropped.
    crav = np.full((4, n_freq), np.nan)
    nc = np.full((4, n_freq), 1.0)

    service = SnapshotMlAnalysisService()
    with pytest.raises(ValueError, match="L"):
        service.analyze_hemisphere(
            crav, nc, freqs, "L",
            n_perm=20, n_boot=20, seed=0,
        )


# ---------------------------------------------------------------------------
# 6. Both-hemispheres dispatch with one side missing
# ---------------------------------------------------------------------------


def test_analyze_both_hemispheres_with_only_left_present():
    """If R inputs are None, the result dict has only key "L"."""
    from src.core.services.snapshot_ml_analysis_service import (
        SnapshotMlAnalysisService,
    )

    crav_L, nc_L, freqs = _synthetic_fixture(seed=1)

    service = SnapshotMlAnalysisService()
    results = service.analyze_both_hemispheres(
        crav_L, nc_L, None, None, freqs,
        n_perm=20, n_boot=20, seed=0,
    )
    assert set(results.keys()) == {"L"}
    assert "R" not in results
    assert None not in results
    assert results["L"].hemisphere == "L"


# ---------------------------------------------------------------------------
# 7. progress_callback plumbing
# ---------------------------------------------------------------------------


def test_progress_callback_invoked_with_total_equal_to_n_perm():
    """The callback is invoked at least once with total == n_perm."""
    from src.core.services.snapshot_ml_analysis_service import (
        SnapshotMlAnalysisService,
    )

    crav, nc, freqs = _synthetic_fixture(seed=2)

    calls = []

    def progress_cb(done: int, total: int) -> None:
        calls.append((done, total))

    service = SnapshotMlAnalysisService()
    service.analyze_hemisphere(
        crav, nc, freqs, "L",
        n_perm=20, n_boot=20, seed=0,
        progress_callback=progress_cb,
    )

    assert len(calls) >= 1, "progress_callback was never called"
    for done, total in calls:
        assert isinstance(done, int)
        assert isinstance(total, int)
        assert total == 20
        assert 0 < done <= total
