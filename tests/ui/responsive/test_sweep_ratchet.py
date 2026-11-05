"""The sweep-cell ratchet behind the responsive matrix."""

from tests.ui.responsive.ratchet import SweepRatchet

CELL = "mac_air15/1280x769/snapshots_canonical_bands/populated"


def _ratchet(tmp_path, *lines):
    path = tmp_path / "known_sweep_failures.txt"
    path.write_text("# header comment\n\n" + "\n".join(lines) + "\n")
    return SweepRatchet(path)


def test_listed_failures_are_known_and_unlisted_ones_are_returned(tmp_path):
    ratchet = _ratchet(tmp_path, f"{CELL}/I5", f"{CELL}/I4  # list h-scroll")
    assert ratchet.check(CELL, ["I4", "I5"]) == []
    assert ratchet.check(CELL, ["I1", "I4", "I5"]) == ["I1"]
    assert ratchet.fixed == []


def test_listed_invariants_that_hold_are_reported_fixed(tmp_path):
    ratchet = _ratchet(tmp_path, f"{CELL}/I5", f"{CELL}/I6")
    assert ratchet.check(CELL, ["I5"]) == []
    assert ratchet.fixed == [f"{CELL}/I6"]


def test_entries_outside_the_matrix_are_stale(tmp_path):
    ratchet = _ratchet(tmp_path, f"{CELL}/I5", "mac_air15/999x999/data_management/empty/I1",
                       f"{CELL}/I10")  # I10 is measured only after a screen move
    assert ratchet.stale() == [f"{CELL}/I10", "mac_air15/999x999/data_management/empty/I1"]


def test_the_checked_in_list_has_no_stale_entries():
    assert SweepRatchet().stale() == []
