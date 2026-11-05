"""The responsive matrix on the real MainWindow (plan §3.2; M0.5).

Every screen profile runs in its own offscreen Qt process (see ``runner``); each
cell — profile × viewport × page × empty/populated — is checked against I1–I6,
or I10 after a screen move. Today's failing cells are the M0 baseline in
``known_sweep_failures.txt`` (see ``ratchet``). Profile-level tests cover the
exports (I9), widget re-creation and arrangement (I7, I7b) and interface sizes
(I8, I8b). Synthetic data only.
"""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.ui.responsive import invariants, runner
from tests.ui.responsive.profiles import COMMON_SIZES, PROFILES, STATES, all_cells, cell_id

pytestmark = [pytest.mark.responsive, pytest.mark.slow, pytest.mark.qt_subprocess]

CELLS = all_cells()
# I7: the analysis pages' ROW minimum with a page host's scrollbar, ~550 px; at
# the common sizes the aspect decides for any value from 480 to 640.
ROW_MIN_WIDTH = 560
# I8: one fresh process per interface size, on the user's screen.
INTERFACE_SIZES = (100, 125, 150, 200)
INTERFACE_SIZE_PROFILE = "mac_air15"


def _profile_result(sweep, profile: str) -> dict:
    result = sweep[profile]
    assert "error" not in result, result["error"]
    return result


def _describe(cell: dict, invariant_ids) -> str:
    lines = []
    for invariant in invariant_ids:
        found = cell["violations"][invariant]
        lines += [f"{invariant} {v['path']}: {v['detail']}" for v in found[:10]]
        lines += [f"{invariant} … {len(found) - 10} more"] if len(found) > 10 else []
    return "\n".join(lines)


@pytest.mark.parametrize("cell", CELLS, ids=[cell_id(*c) for c in CELLS])
def test_cell(sweep, sweep_ratchet, cell):
    """I1–I6 (I10 after a screen move) hold in the cell, or fail as listed."""
    profile, viewport, page, state = cell
    measured = _profile_result(sweep, profile)["index"].get((viewport, page, state))
    assert measured is not None, f"cell not measured: {sweep[profile]['errors']}"
    failing = [k for k, v in measured["violations"].items() if v]
    unlisted = sweep_ratchet.check(cell_id(*cell), failing)
    assert not unlisted, _describe(measured, unlisted)
    if failing:
        pytest.xfail(f"known sweep failure ({', '.join(failing)}); see {sweep_ratchet.source}")


@pytest.mark.parametrize("profile", PROFILES)
def test_profile_ran(sweep, profile):
    """The child emulated the declared screens and measured every cell."""
    result = _profile_result(sweep, profile)
    assert not result["errors"], "\n".join(result["errors"])


@pytest.mark.parametrize("fmt", ["png", "pdf", "svg"])
def test_exports_identical(sweep, fmt):
    """I9: a plot's export is byte-identical across windows, screens and DPRs."""
    digests = defaultdict(dict)
    for profile, result in sweep.items():
        for viewport, files in result.get("exports", {}).items():
            for name, digest in files.items():
                plot, ext = name.rsplit(".", 1)
                if ext == fmt:
                    digests[(plot, ext)][f"{profile}/{viewport}"] = digest
    assert digests, "no exports were recorded"
    assert not invariants.check_exports_identical(digests)


@pytest.mark.parametrize("profile", PROFILES)
def test_no_widget_recreation(sweep, profile):
    """I7: resizing and switching pages never re-creates widgets."""
    result = _profile_result(sweep, profile)
    found = []
    for state in STATES:
        counts = {f"{c['viewport']}/{c['page']}": c["widgets"]
                  for c in result["cells"] if c["state"] == state}
        found += invariants.check_widget_count(counts, f"{profile}/{state}")
    assert not found, found


@pytest.mark.parametrize("profile", PROFILES)
def test_arrangement_at_common_sizes(sweep, profile):
    """I7: the grouping panel arranges as plan §3.1 assigns to each common size,
    which is what the layout policy gives it."""
    history = _profile_result(sweep, profile)["history"]
    found = []
    for (width, height), arrangement in COMMON_SIZES.items():
        assert invariants.policy_arrangement((width, height), ROW_MIN_WIDTH) == arrangement
        observed = history[f"{width}x{height}"][0]
        found += invariants.check_arrangement(observed, {"panel": arrangement},
                                              f"{width}×{height}")
    assert not found, found


@pytest.mark.parametrize("profile", PROFILES)
def test_arrangement_without_history(sweep, profile):
    """I7b: within ±8 px of each common size the class facts are the same,
    whether the window arrived there from a small or a large size."""
    found = invariants.check_history_free(_profile_result(sweep, profile)["history"], profile)
    assert not found, found


@pytest.fixture(scope="module")
def interface_sizes(tmp_path_factory) -> dict:
    """``{percent: result}``: one fresh process per interface size, started as after
    the restart that applies it: the size saved for the user's screen in the
    preferences, the environment composed by the production policy (M4.2)."""
    scale = invariants.scale_policy()
    screen = PROFILES[INTERFACE_SIZE_PROFILE].primary.name
    out = tmp_path_factory.mktemp("interface_sizes")
    with ThreadPoolExecutor(max_workers=len(INTERFACE_SIZES)) as pool:
        futures = {}
        for percent in INTERFACE_SIZES:
            steps = {screen: scale.ZOOM_LADDER.index(percent)}
            futures[percent] = pool.submit(
                runner.run_profile, INTERFACE_SIZE_PROFILE, out, label=f"_{percent}",
                ladder=True, env=scale.compose_scale_env(steps, {}, launch_display=screen),
                zoom_steps=steps)
        return {percent: future.result() for percent, future in futures.items()}


@pytest.mark.parametrize("percent", INTERFACE_SIZES)
def test_interface_size_cells(interface_sizes, percent):
    """I8: every cell holds I1–I6 at each interface size, which is the size chosen
    for the screen (no restart pending)."""
    result = interface_sizes[percent]
    assert "error" not in result, result["error"]
    assert not result["errors"], "\n".join(result["errors"])
    assert result["interface_size"] == {"active": percent, "chosen": percent}
    failing = [f"{c['viewport']}/{c['page']}/{c['state']} {k}"
               for c in result["cells"] for k, v in c["violations"].items() if v]
    assert not failing, failing


def test_interface_size_ladder(interface_sizes):
    """I8b: stepping up the interface size never shrinks a font; control heights
    step down at most once."""
    levels = [(percent, {path: tuple(m) for path, m in interface_sizes[percent]["ladder"].items()})
              for percent in INTERFACE_SIZES]
    found = invariants.check_ladder(levels, INTERFACE_SIZE_PROFILE)
    assert not found, found
