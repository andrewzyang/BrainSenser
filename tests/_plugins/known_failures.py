"""Known-failures gate: the suite's ratchet for failures that predate a change.

``tests/known_failures.txt`` (plus ``tests/known_failures.<sys.platform>.txt``
when present) lists the exact node IDs that fail on a clean tree. With the gate
on (the default):

- a listed test that fails or errors is reported as xfail;
- a listed test that passes gets a "FIXED — delete this line" entry in the
  terminal summary; it does not fail the run;
- an unlisted failure fails the run as usual;
- an entry the run did not collect although it collected the entry's file, or
  whose file no longer exists, gets a "stale entry" line;
- entries under a ``[tolerated]`` header are flaky: either outcome is fine and
  they are never reported FIXED.

``--known-failures=PATH`` (repeatable) replaces the default lists, and
``--no-known-failures`` shows the raw results. ``tests/conftest.py`` loads this
plugin through ``pytest_plugins``, so it stays active when ``addopts`` is
overridden (``-o addopts=...``).
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

GATE_NAME = "known-failures-gate"
DEFAULT_LIST = "tests/known_failures.txt"

_SECTIONS = {"[known]": False, "[tolerated]": True}
# "#" starts a comment at the start of a line or after whitespace, so a "#"
# inside a parametrized ID such as test_x[a#b] survives.
_COMMENT = re.compile(r"(^|\s)#.*$")


@dataclass(frozen=True)
class _Entry:
    source: str  # the list file, relative to the rootdir
    tolerated: bool


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("known failures")
    group.addoption(
        "--known-failures",
        action="append",
        metavar="PATH",
        help=f"known-failures list to gate on (repeatable; default: {DEFAULT_LIST} "
        "plus tests/known_failures.<sys.platform>.txt if present)",
    )
    group.addoption(
        "--no-known-failures",
        action="store_true",
        help="disable the known-failures gate and show raw results",
    )


def pytest_configure(config: pytest.Config) -> None:
    if not config.getoption("no_known_failures"):
        config.pluginmanager.register(KnownFailuresGate(config), GATE_NAME)


def pytest_report_header(config: pytest.Config) -> str:
    gate = config.pluginmanager.get_plugin(GATE_NAME)
    return gate.header() if gate is not None else "known failures: off"


class KnownFailuresGate:
    """Turns listed failures into xfails and reports fixed and stale entries."""

    def __init__(self, config: pytest.Config) -> None:
        self._config = config
        self._sources: list[str] = []
        self._entries: dict[str, _Entry] = {}
        for path in _list_paths(config):
            source = _relative(path, config.rootpath)
            self._sources.append(source)
            _parse(path, source, self._entries)
        self._collected: set[str] = set()
        self._failed: set[str] = set()
        self._passed: set[str] = set()

    def header(self) -> str:
        tolerated = sum(entry.tolerated for entry in self._entries.values())
        lists = ", ".join(self._sources) or "no list found"
        return (
            f"known failures: {lists} "
            f"({len(self._entries) - tolerated} known, {tolerated} tolerated)"
        )

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        # Before -k/-m/--deselect drop anything: a deselected test is not stale.
        self._collected.update(item.nodeid for item in items)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_makereport(
        self, item: pytest.Item, call: pytest.CallInfo[None]
    ) -> Generator[None, pytest.TestReport, pytest.TestReport]:
        report = yield
        if report.failed:
            self._failed.add(report.nodeid)
            entry = self._entries.get(report.nodeid)
            if entry is not None:
                kind = "tolerated flaky test" if entry.tolerated else "known failure"
                report.outcome = "skipped"
                report.wasxfail = f"{kind} (see {entry.source})"
        elif report.passed and call.when == "call":
            self._passed.add(report.nodeid)
        return report

    def pytest_terminal_summary(self, terminalreporter) -> None:
        lines = [*self._fixed(), *self._stale()]
        if lines:
            terminalreporter.write_sep("=", "known failures", yellow=True)
            for line in lines:
                terminalreporter.write_line(line)

    def _fixed(self) -> Iterator[str]:
        for nodeid, entry in self._entries.items():
            if not entry.tolerated and nodeid in self._passed and nodeid not in self._failed:
                yield f"FIXED — delete this line from {entry.source}: {nodeid}"

    def _stale(self) -> Iterator[str]:
        complete = self._completely_collected_files()
        for nodeid, entry in self._entries.items():
            file = nodeid.split("::", 1)[0]
            if not (self._config.rootpath / file).is_file():
                yield f"stale entry in {entry.source} (file not found): {nodeid}"
            elif file in complete and nodeid not in self._collected:
                yield f"stale entry in {entry.source} (not collected): {nodeid}"

    def _completely_collected_files(self) -> set[str]:
        """Files this run collected in full: not narrowed to node IDs or by --lf."""
        if self._config.getoption("lf", False):
            return set()
        files = {nodeid.split("::", 1)[0] for nodeid in self._collected}
        for arg in self._config.args:
            path, separator, _ = arg.partition("::")
            if separator:
                files.discard(
                    _relative(self._config.invocation_params.dir / path, self._config.rootpath)
                )
        return files


def _list_paths(config: pytest.Config) -> list[Path]:
    given = config.getoption("known_failures")
    if given:
        paths = [config.invocation_params.dir / path for path in given]
        for path in paths:
            if not path.is_file():
                raise pytest.UsageError(f"--known-failures: no such file: {path}")
        return paths
    default = config.rootpath / DEFAULT_LIST
    per_platform = default.with_name(f"{default.stem}.{sys.platform}{default.suffix}")
    return [path for path in (default, per_platform) if path.is_file()]


def _parse(path: Path, source: str, entries: dict[str, _Entry]) -> None:
    tolerated = False
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = _COMMENT.sub("", raw).strip()
        where = f"{source}:{lineno}"
        if not line:
            continue
        if line.startswith("["):
            if line not in _SECTIONS:
                raise pytest.UsageError(
                    f"{where}: unknown section {line} (expected [known] or [tolerated])"
                )
            tolerated = _SECTIONS[line]
        elif "::" not in line:
            raise pytest.UsageError(f"{where}: not a test node ID: {line}")
        elif line in entries:
            raise pytest.UsageError(f"{where}: duplicate entry: {line}")
        else:
            entries[line] = _Entry(source, tolerated)


def _relative(path: Path, root: Path) -> str:
    """``path`` relative to ``root`` in node-ID form, or absolute outside it."""
    path = Path(os.path.abspath(path))
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
