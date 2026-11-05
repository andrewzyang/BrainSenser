"""Session fixtures of the responsive matrix: the parallel sweep and its ratchet
(see ``ratchet`` for the meaning of ``known_sweep_failures.txt``)."""

from pathlib import Path

import pytest

from tests.ui.responsive import _safety, runner
from tests.ui.responsive.profiles import PROFILES
from tests.ui.responsive.ratchet import SweepRatchet

HERE = Path(__file__).resolve().parent
_RATCHET = pytest.StashKey[SweepRatchet]()


@pytest.fixture(scope="session")
def sweep_ratchet(request) -> SweepRatchet:
    ratchet = SweepRatchet()
    request.config.stash[_RATCHET] = ratchet
    return ratchet


@pytest.fixture(scope="session")
def sweep(request, tmp_path_factory) -> dict:
    """``{profile: result}`` for every profile the session's matrix tests name
    (all of them if none does), run in parallel; the real-data fingerprint must
    not change meanwhile."""
    wanted = set()
    for item in request.session.items:
        params = getattr(getattr(item, "callspec", None), "params", {})
        if Path(item.path).is_relative_to(HERE):
            wanted.update(v for v in (params.get("profile"), params.get("cell", (None,))[0]) if v)
    before = _safety.fingerprint()
    out = tmp_path_factory.mktemp("responsive_sweep")
    results = runner.run_profiles(sorted(wanted) or PROFILES, out)
    changed = _safety.changed_paths(before, _safety.fingerprint())
    if changed:
        pytest.fail(f"protected real data changed during the sweep: {changed}")
    for result in results.values():
        result["index"] = {(c["viewport"], c["page"], c["state"]): c
                           for c in result.get("cells", [])}
    return results


def pytest_terminal_summary(terminalreporter):
    ratchet = terminalreporter.config.stash.get(_RATCHET, None)
    if ratchet is None:
        return
    lines = [f"FIXED — delete this line from {ratchet.source}: {e}" for e in ratchet.fixed]
    lines += [f"stale entry in {ratchet.source} (not in the matrix): {e}" for e in ratchet.stale()]
    if lines:
        terminalreporter.write_sep("=", "responsive sweep ratchet", yellow=True)
        for line in lines:
            terminalreporter.write_line(line)
