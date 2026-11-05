"""Self-tests for the known-failures gate (tests/_plugins/known_failures.py)."""

import sys

import pytest

pytest_plugins = ["pytester"]

PLUGIN = "tests._plugins.known_failures"

SUITE = """
    import pytest

    @pytest.fixture
    def broken():
        raise RuntimeError("setup fails")

    def test_passes():
        pass

    def test_fails():
        assert False

    def test_errors(broken):
        pass

    class TestGroup:
        def test_method_fails(self):
            assert False

    @pytest.mark.parametrize("value", [1, 2])
    def test_param(value):
        assert value == 1
"""

# Every failure in SUITE: a call failure, a setup error, a method, a parameter.
ALL_FAILURES = """
# A full-line comment.
test_suite.py::test_fails   # a trailing comment
test_suite.py::test_errors

test_suite.py::TestGroup::test_method_fails
test_suite.py::test_param[2]
"""


@pytest.fixture
def suite(pytester, monkeypatch):
    """A pytester dir (its own rootdir) holding SUITE; inner runs load builtins + the gate."""
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    pytester.makeini("[pytest]")
    pytester.makepyfile(test_suite=SUITE)
    return pytester


def run_gate(pytester, listing, *args):
    pytester.path.joinpath("known.txt").write_text(listing, encoding="utf-8")
    return pytester.runpytest("-p", PLUGIN, "--known-failures=known.txt", "-rx", *args)


def test_gate_is_loaded_by_the_root_conftest(request):
    # Via pytest_plugins in tests/conftest.py, so overriding addopts can't drop it.
    assert request.config.pluginmanager.has_plugin(PLUGIN)


def test_listed_failures_and_errors_become_xfail(suite):
    result = run_gate(suite, ALL_FAILURES)

    result.assert_outcomes(passed=2, xfailed=4)
    assert result.ret == pytest.ExitCode.OK
    out = result.stdout.str()
    assert "known failures: known.txt (4 known, 0 tolerated)" in out
    assert "XFAIL test_suite.py::test_errors - known failure (see known.txt)" in out
    assert "XFAIL test_suite.py::TestGroup::test_method_fails - known failure" in out
    assert "XFAIL test_suite.py::test_param[2] - known failure" in out


def test_unlisted_failures_fail_the_run(suite):
    result = run_gate(suite, "test_suite.py::test_fails\n")

    result.assert_outcomes(passed=2, xfailed=1, failed=2, errors=1)
    assert result.ret == pytest.ExitCode.TESTS_FAILED


def test_listed_pass_is_reported_fixed_without_failing(suite):
    result = run_gate(suite, ALL_FAILURES + "test_suite.py::test_passes\n")

    result.assert_outcomes(passed=2, xfailed=4)
    assert result.ret == pytest.ExitCode.OK
    result.stdout.fnmatch_lines([
        "*= known failures =*",
        "FIXED — delete this line from known.txt: test_suite.py::test_passes",
    ])


def test_tolerated_entries_neither_fail_nor_report_fixed(suite):
    listing = (
        "test_suite.py::test_errors\n"
        "test_suite.py::TestGroup::test_method_fails\n"
        "test_suite.py::test_param[2]\n"
        "[tolerated]\n"
        "test_suite.py::test_fails\n"
        "test_suite.py::test_passes\n"
    )
    result = run_gate(suite, listing)

    result.assert_outcomes(passed=2, xfailed=4)
    assert result.ret == pytest.ExitCode.OK
    out = result.stdout.str()
    assert "(3 known, 2 tolerated)" in out
    assert "XFAIL test_suite.py::test_fails - tolerated flaky test (see known.txt)" in out
    assert "FIXED" not in out


def test_stale_entries_are_reported(suite):
    listing = ALL_FAILURES + "test_suite.py::test_renamed\nmissing_test.py::test_gone\n"
    result = run_gate(suite, listing)

    assert result.ret == pytest.ExitCode.OK
    out = result.stdout.str()
    assert "stale entry in known.txt (not collected): test_suite.py::test_renamed" in out
    assert "stale entry in known.txt (file not found): missing_test.py::test_gone" in out


@pytest.mark.parametrize(
    "narrowing",
    [
        ["-k", "test_passes"],
        ["--deselect", "test_suite.py::test_fails"],
        ["test_suite.py::test_passes"],
    ],
    ids=["keyword", "deselect", "node-id"],
)
def test_partial_runs_report_nothing_stale(suite, narrowing):
    result = run_gate(suite, ALL_FAILURES, *narrowing)

    assert "stale entry" not in result.stdout.str()


def test_last_failed_runs_report_nothing_stale(suite):
    run_gate(suite, "")  # nothing listed: every failure lands in the --lf cache
    result = run_gate(suite, "test_suite.py::test_passes\n", "--lf")

    assert "stale entry" not in result.stdout.str()


def test_no_known_failures_shows_raw_results(suite):
    result = run_gate(suite, ALL_FAILURES, "--no-known-failures")

    result.assert_outcomes(passed=2, failed=3, errors=1)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(["known failures: off"])


def test_default_lists_are_the_shared_and_platform_files(suite):
    lists = suite.mkdir("tests")
    lists.joinpath("known_failures.txt").write_text("test_suite.py::test_fails\n", encoding="utf-8")
    lists.joinpath(f"known_failures.{sys.platform}.txt").write_text(
        "test_suite.py::test_errors\n", encoding="utf-8"
    )
    result = suite.runpytest("-p", PLUGIN, "-rx")

    result.assert_outcomes(passed=2, xfailed=2, failed=2)
    out = result.stdout.str()
    assert (
        f"known failures: tests/known_failures.txt, tests/known_failures.{sys.platform}.txt"
        " (2 known, 0 tolerated)" in out
    )
    assert "known failure (see tests/known_failures.txt)" in out
    assert f"known failure (see tests/known_failures.{sys.platform}.txt)" in out


@pytest.mark.parametrize(
    "listing, message",
    [
        ("[flaky]\n", "known.txt:1: unknown section [flaky]"),
        ("test_suite.py\n", "known.txt:1: not a test node ID: test_suite.py"),
        (
            "test_suite.py::test_fails\n[tolerated]\ntest_suite.py::test_fails\n",
            "known.txt:3: duplicate entry: test_suite.py::test_fails",
        ),
    ],
    ids=["unknown-section", "not-a-node-id", "duplicate"],
)
def test_malformed_list_is_a_usage_error(suite, listing, message):
    result = run_gate(suite, listing)

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert message in result.stderr.str()


def test_missing_list_is_a_usage_error(suite):
    result = suite.runpytest("-p", PLUGIN, "--known-failures=absent.txt")

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "--known-failures: no such file" in result.stderr.str()
