"""Data safety for the responsive harness and ``tools/responsive_sweep.py``.

The harness drives the real ``MainWindow`` in child processes, so it carries
its own guarantees on top of the suite's isolation:

* :func:`never_open_paths` — the real data roots, the real preferences stores,
  the Percept-format fixtures ``tests/fixtures/sample_brainsense_*.json``
  (synthetic now; older checkouts hold real exports) and the data folders of this checkout
  and of the main checkout it belongs to;
* :func:`install_open_guard` — an audit hook that makes a child process refuse
  to open, list, copy, move, delete or connect to anything on that list;
* :func:`check_child_environment` / :func:`assert_inside` — every resolved path
  of a child lies in its throwaway sandbox;
* :func:`fingerprint` — ``stat()`` (never open or list) of the real user state
  and the export fixtures, taken before and after a run, so a change fails the run.
"""

import glob
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Folders of a checkout that hold patient-derived data the app never needs.
_CHECKOUT_DATA = ("raw_data", ".brainsense_data", "results", "research")
_EXPORT_FIXTURES = "tests/fixtures/sample_brainsense_*.json"
_CHECKOUT_DATA_GLOBS = ("*.csv", _EXPORT_FIXTURES)
# Files the app writes inside its data root; stat()ed so an in-place write shows.
_DATA_ROOT_FILES = ("app_metadata.db", "app_metadata.db-wal", "app_metadata.db-shm",
                    "config.json", "patients")

# Audit events whose path arguments the guard checks, and which arguments are paths.
_GUARDED_EVENTS = {
    "open": (0,), "os.listdir": (0,), "os.scandir": (0,), "os.mkdir": (0,), "os.remove": (0,),
    "os.rmdir": (0,), "os.rename": (0, 1), "os.truncate": (0,), "os.utime": (0,),
    "shutil.copyfile": (0, 1), "shutil.copytree": (0, 1), "shutil.rmtree": (0,),
    "sqlite3.connect": (0,), "glob.glob": (0,),
}


def real_home() -> Path:
    """The user's home even when ``HOME`` points at a sandbox."""
    try:
        import pwd
    except ImportError:  # Windows: the harness never redirects USERPROFILE
        return Path(os.environ.get("USERPROFILE", Path.home()))
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def main_checkout(repo: Path) -> Path:
    """The main checkout of ``repo`` (``repo`` itself unless it is a git worktree)."""
    dot_git = repo / ".git"
    if dot_git.is_file():  # "gitdir: <main>/.git/worktrees/<name>"
        gitdir = repo / dot_git.read_text().split(":", 1)[1].strip()
        return gitdir.resolve().parents[2]
    return repo


def _data_roots() -> list:
    """The real app data roots: development and the frozen macOS app."""
    home = real_home()
    return [home / ".brainsense_data", home / "Library" / "Application Support" / "BrainSenser"]


def _settings_stores() -> list:
    """QSettings("BrainSense", "iEEG-App") native stores (EffectSizePreference)."""
    home = real_home()
    return [home / "Library" / "Preferences" / "com.brainsense.iEEG-App.plist",
            home / ".config" / "BrainSense" / "iEEG-App.conf"]


def _checkouts(repo: Path) -> list:
    return list(dict.fromkeys((repo, main_checkout(repo))))


def never_open_paths(repo: Path = REPO_ROOT) -> tuple:
    """Every path the harness must never open: real data, real settings, export fixtures."""
    paths = _data_roots() + _settings_stores()
    for checkout in _checkouts(repo):
        paths += [checkout / name for name in _CHECKOUT_DATA]
        for pattern in _CHECKOUT_DATA_GLOBS:
            paths += sorted(Path(p) for p in glob.glob(str(checkout / pattern)))
    return tuple(paths)


def _normalized(path) -> str:
    """Symlink-free absolute path; case-folded where the file system ignores case."""
    resolved = os.path.realpath(os.fsdecode(path))
    return resolved.lower() if sys.platform in ("darwin", "win32") else resolved


def _within(candidate: str, roots: tuple) -> bool:
    return any(candidate == root or candidate.startswith(root.rstrip(os.sep) + os.sep)
               for root in roots)


def is_protected(path, repo: Path = REPO_ROOT) -> bool:
    return _within(_normalized(path), tuple(_normalized(p) for p in never_open_paths(repo)))


def install_open_guard(protected=None) -> None:
    """Make this process refuse any file operation on ``protected`` (by default
    :func:`never_open_paths`). Audit hooks cannot be removed, so this is for
    harness child processes only."""
    roots = tuple(_normalized(p) for p in (never_open_paths() if protected is None else protected))

    def guard(event, args):
        positions = _GUARDED_EVENTS.get(event)
        if positions is None:
            return
        for i in positions:
            arg = args[i] if i < len(args) else None
            if isinstance(arg, (str, bytes, os.PathLike)) and _within(_normalized(arg), roots):
                raise PermissionError(f"responsive harness: refusing {event} on protected "
                                      f"path {arg}")

    sys.addaudithook(guard)


def assert_inside(path, root: Path, what: str) -> None:
    resolved = Path(os.path.realpath(path))
    if not resolved.is_relative_to(Path(os.path.realpath(root))):
        raise AssertionError(f"isolation violated: {what} = {resolved} is outside {root}")


def check_sandbox_location(sandbox: Path, repo: Path = REPO_ROOT) -> None:
    """A sandbox or output folder must lie outside every checkout and protected path."""
    resolved = Path(os.path.realpath(sandbox))
    for checkout in (repo, main_checkout(repo)):
        if resolved.is_relative_to(Path(os.path.realpath(checkout))):
            raise AssertionError(f"refusing to write inside the checkout {checkout}: {sandbox}")
    if is_protected(resolved, repo):
        raise AssertionError(f"refusing to write inside protected data: {sandbox}")


def check_child_environment(sandbox: Path) -> None:
    """HOME, BRAINSENSER_DATA_DIR and the cwd lie in the sandbox; MPLCONFIGDIR is
    set and outside the real home (so no user matplotlibrc applies)."""
    for var in ("HOME", "BRAINSENSER_DATA_DIR", "MPLCONFIGDIR"):
        if not os.environ.get(var):
            raise AssertionError(f"isolation violated: {var} is not set")
    for var in ("HOME", "BRAINSENSER_DATA_DIR"):
        assert_inside(os.environ[var], sandbox, var)
    assert_inside(os.getcwd(), sandbox, "cwd")
    if Path(os.path.realpath(os.environ["MPLCONFIGDIR"])).is_relative_to(
            Path(os.path.realpath(real_home()))):
        raise AssertionError(f"isolation violated: MPLCONFIGDIR {os.environ['MPLCONFIGDIR']} "
                             "is inside the real home")


def fingerprint(repo: Path = REPO_ROOT) -> dict:
    """``(mtime_ns, size)`` (None if absent) of the real data roots and the files the
    app writes in them, the real settings stores and the export fixtures; ``stat()``
    only. Checkout data folders are left to the open guard: other work changes them."""
    paths = [root / name for root in _data_roots() for name in ("", *_DATA_ROOT_FILES)]
    paths += _settings_stores()
    for checkout in _checkouts(repo):
        paths += sorted(Path(p) for p in glob.glob(str(checkout / _EXPORT_FIXTURES)))
    out = {}
    for path in paths:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            out[str(path)] = None
        else:
            out[str(path)] = [st.st_mtime_ns, st.st_size]
    return out


def changed_paths(before: dict, after: dict) -> list:
    return sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
