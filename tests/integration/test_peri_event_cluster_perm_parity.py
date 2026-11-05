"""Bit-for-bit parity: app peri-event cluster-perm engine vs the manuscript reference.

Acceptance test for the goal "make the app's Peri-Event cluster-permutation
analysis statistically bit-for-bit identical to the reference script". It
feeds the SAME ``(lfps, y)`` to the app engine
(``src.core.analysis.peri_event_cluster_perm``) and to the reference script's
functions and asserts every downstream statistic matches.

Reference (source of truth):
    ``code_release/scripts/3_timeline_stats_cluster_permutation.py``

Only the EVENT GROUPING / LABEL SOURCE is permitted to differ between the app
and the reference; everything from a labeled ``(lfps, y)`` onward must be
identical, so this test builds a shared ``(lfps, y)`` from the canonical CSVs
via the engine's ``get_data`` and compares the statistical functions directly.

Tolerance: arrays / point estimates to atol=1e-9; integer counts and bin
indices exact. (Empirically the diff is exactly 0.0 — both sides run identical
code under identical seeds.) Equivalence is exact at any matched ``n_perm``, so
a small ``n_perm`` is used for speed.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

# Force single-threaded BLAS before the heavy permutation loop to avoid
# oversubscription wedging the test (see the lfp_threshold test-thread note).
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

# ── Locate the two implementations ──────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REF_PATH = (
    _PROJECT_ROOT / "code_release" / "scripts"
    / "3_timeline_stats_cluster_permutation.py"
)
_DATA = _PROJECT_ROOT / "code_release" / "data"

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.core.analysis import peri_event_cluster_perm as engine  # noqa: E402


# (patient, hemisphere) -> (snapshots_csv, timeline_csv)
_CSVS = {
    ("pt1", "left"):  (_DATA / "pt1_snapshots.csv", _DATA / "pt1_timeline.csv"),
    ("pt2", "left"):  (_DATA / "pt2_snapshots.csv", _DATA / "pt2_timeline.csv"),
    ("pt2", "right"): (_DATA / "pt2_snapshots.csv", _DATA / "pt2_timeline.csv"),
}
_PANELS = [("pt1", "left"), ("pt2", "left"), ("pt2", "right")]

# Same skip guard as the other CSV-driven parity tests: nothing to compare
# against if the reference script or canonical CSVs are absent.
_MISSING = not (
    _REF_PATH.exists()
    and all(p.exists() for pair in _CSVS.values() for p in pair)
)
pytestmark = pytest.mark.skipif(
    _MISSING, reason="manuscript reference script or canonical CSVs not available",
)

SEED = 42
N_PERM = 300  # equivalence is exact at any matched n_perm; headline uses 10000


def _load_reference():
    """Import the reference script by path (its filename starts with a digit,
    so it is not importable as a normal module name)."""
    spec = importlib.util.spec_from_file_location(
        "ref_peri_event_cluster_perm", _REF_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ref():
    return _load_reference()


def _xy(ref, pid, hemi):
    """Build a shared (lfps, y) from the canonical CSVs via the engine."""
    snap_csv, tl_csv = _CSVS[(pid, hemi)]
    snaps = ref.load_snapshots_csv(snap_csv)
    ts, val = ref.load_timeline_csv(tl_csv, hemi)
    lfps, y, *_ = engine.get_data(snaps, ts, val, hemi)
    return lfps, y


# ── 1. Locked constants ─────────────────────────────────────────────────────
def test_constants_match(ref):
    assert engine.WINDOW_MINUTES == ref.WINDOW_MINUTES == 50
    assert engine.OFFSET_BINS == ref.OFFSET_BINS
    assert engine.BIN_TOLERANCE == ref.BIN_TOLERANCE == 5
    assert engine.MIN_INTER_EVENT_MINUTES == ref.MIN_INTER_EVENT_MINUTES == 60
    assert engine.MIN_PER_CLASS == ref.MIN_PER_CLASS == 3
    assert engine.CLUSTER_FORMING_Z == ref.CLUSTER_FORMING_Z
    assert engine.RANDOM_STATE == ref.RANDOM_STATE == SEED


# ── 2. get_data: matrix, labels, drop counts, raw count, span ───────────────
@pytest.mark.parametrize("pid,hemi", _PANELS)
def test_get_data_matches_reference(ref, pid, hemi):
    snap_csv, tl_csv = _CSVS[(pid, hemi)]
    snaps = ref.load_snapshots_csv(snap_csv)
    ts, val = ref.load_timeline_csv(tl_csv, hemi)
    e_lfps, e_y, e_drop, e_raw, e_span = engine.get_data(snaps, ts, val, hemi)
    r_lfps, r_y, r_drop, r_raw, r_span = ref.get_data(snaps, ts, val, hemi)
    # assert_allclose treats NaN==NaN as equal (equal_nan default True).
    np.testing.assert_allclose(e_lfps, r_lfps, rtol=0.0, atol=1e-9)
    np.testing.assert_array_equal(e_y, r_y)
    assert e_drop == r_drop
    assert e_raw == r_raw
    np.testing.assert_allclose(e_span, r_span, rtol=0.0, atol=1e-9)


# ── 3. usable_mask + per-bin |z| ────────────────────────────────────────────
@pytest.mark.parametrize("pid,hemi", _PANELS)
def test_usable_mask_and_abs_z_match(ref, pid, hemi):
    lfps, y = _xy(ref, pid, hemi)
    e_mask = engine.compute_usable_mask(lfps, y)
    r_mask = ref.compute_usable_mask(lfps, y)
    np.testing.assert_array_equal(e_mask, r_mask)
    np.testing.assert_allclose(
        engine.per_bin_abs_z(lfps, y, usable_mask=e_mask),
        ref.per_bin_abs_z(lfps, y, usable_mask=r_mask),
        rtol=0.0, atol=1e-9,
    )


# ── 4. cluster permutation test: obs_z, null, mask, clusters ────────────────
@pytest.mark.parametrize("pid,hemi", _PANELS)
def test_cluster_perm_matches_reference(ref, pid, hemi):
    lfps, y = _xy(ref, pid, hemi)
    e = engine.cluster_perm_test(lfps, y, n_perm=N_PERM, seed=SEED)
    r = ref.cluster_perm_test(lfps, y, n_perm=N_PERM, seed=SEED)
    np.testing.assert_allclose(e["obs_z"], r["obs_z"], rtol=0.0, atol=1e-9)
    np.testing.assert_allclose(e["null_max"], r["null_max"], rtol=0.0, atol=1e-9)
    np.testing.assert_array_equal(e["usable_mask"], r["usable_mask"])
    assert len(e["clusters"]) == len(r["clusters"])
    for ce, cr in zip(e["clusters"], r["clusters"]):
        assert ce["start_idx"] == cr["start_idx"]
        assert ce["end_idx"] == cr["end_idx"]
        assert ce["start_bin"] == cr["start_bin"]
        assert ce["end_bin"] == cr["end_bin"]
        np.testing.assert_allclose(ce["mass"], cr["mass"], rtol=0.0, atol=1e-9)
        np.testing.assert_allclose(ce["p"], cr["p"], rtol=0.0, atol=1e-9)


# ── 5. progress / cancel hooks do not perturb the result ────────────────────
def test_progress_callback_does_not_change_result(ref):
    """The GUI worker drives cluster_perm_test with a progress_callback; the
    extra hook must not alter any statistic vs the no-callback reference."""
    lfps, y = _xy(ref, "pt2", "left")
    seen = []
    e = engine.cluster_perm_test(
        lfps, y, n_perm=N_PERM, seed=SEED,
        progress_callback=lambda done, total: seen.append((done, total)),
    )
    r = ref.cluster_perm_test(lfps, y, n_perm=N_PERM, seed=SEED)
    np.testing.assert_allclose(e["null_max"], r["null_max"], rtol=0.0, atol=1e-9)
    assert seen and seen[-1] == (N_PERM, N_PERM)


def test_cancel_check_raises():
    """cancel_check tripping mid-loop raises PeriEventCancelled."""
    lfps = np.random.RandomState(0).normal(size=(11, 30))
    y = np.array([1] * 15 + [0] * 15)
    with pytest.raises(engine.PeriEventCancelled):
        engine.cluster_perm_test(
            lfps, y, n_perm=N_PERM, seed=SEED, cancel_check=lambda: True,
        )
