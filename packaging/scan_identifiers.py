#!/usr/bin/env python3
"""Scan files for research-participant identifiers before a build or a publish.

The identifier list is built at run time from local data and never stored or
printed: the PatientInformation / DeviceInformation blocks and session dates of
every Percept export under the data folders, plus the patient folder names.
Hits print as ``path:line: category`` only.

Text files and BrainSenser's own code inside a frozen app (``main`` and
``src.*`` read out of PyInstaller's archive) fail the scan. Third-party
binaries are only searched for long tokens and only warn, because short
tokens turn up in them by chance.

Run it with the build venv's Python so frozen apps can be read:

    python packaging/scan_identifiers.py TARGET [TARGET ...] [--data DIR ...]

TARGET is a folder, a .app, a .zip or a single file. Exit 1 on any failing hit.
"""
import argparse
import json
import marshal
import re
import sys
import tempfile
import unicodedata
import zipfile
from datetime import date
from pathlib import Path

DEFAULT_DATA = [Path.home() / ".brainsense_data",
                Path.home() / "Library" / "Application Support" / "BrainSenser"]
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".csv", ".qss", ".spec", ".sh",
                 ".yml", ".yaml", ".toml", ".ini", ".cfg", ".cff", ".svg", ".html",
                 ".xml", ".plist", ".bat", ".ps1", ".rst", ".in"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "htmlcov"}
NAME_KEYS = ("PatientFirstName", "PatientLastName")
DATE_KEYS = ("PatientDateOfBirth", "ImplantDate")
ID_KEYS = ("PatientId", "NeurostimulatorSerialNumber")
SESSION_KEYS = ("SessionDate", "SessionEndDate", "DeviceDateTime")
# Placeholders and the paper's public pseudonyms are not identifiers.
GENERIC = {"", "unknown", "n/a", "na", "none", "null", "test", "test1", "test2", "test3",
           "patient", "pt1", "pt2", "pt3", "patient1", "patient2", "patient3"}
MIN_TOKEN = {"name": 3, "id": 4, "serial": 4, "folder": 3}
LONG_TOKEN = 6   # third-party binaries: only tokens at least this long, warn only
SHOW = False     # --show


def fold(text):
    """Case- and accent-insensitive form for name matching."""
    norm = unicodedata.normalize("NFKD", text)
    return "".join(c for c in norm if not unicodedata.combining(c)).casefold()


def parse_day(value):
    """The calendar day of an ISO (Percept) or US-style date string."""
    if not isinstance(value, str):
        return None
    iso = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", value)
    us = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", value)
    try:
        if iso:
            return date(*map(int, iso.groups()))
        if us:
            month, day, year = map(int, us.groups())
            return date(year, month, day)
    except ValueError:
        pass
    return None


def day_patterns(day):
    """The ways a date is commonly written, as one regex."""
    y, m, d = day.year, day.month, day.day
    forms = {f"{y:04d}-{m:02d}-{d:02d}", f"{y:04d}/{m:02d}/{d:02d}", f"{y:04d}{m:02d}{d:02d}",
             f"{m:02d}/{d:02d}/{y:04d}", f"{m}/{d}/{y:04d}", f"{d:02d}/{m:02d}/{y:04d}",
             f"{m:02d}{d:02d}{y:04d}", f"{d:02d}.{m:02d}.{y:04d}",
             f"{day:%b} {d}, {y}", f"{day:%B} {d}, {y}", f"{d} {day:%b} {y}", f"{d} {day:%B} {y}"}
    return "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))


def walk_json(obj, found, depth=0):
    if depth > 6:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                walk_json(value, found, depth + 1)
            elif isinstance(value, str):
                found.setdefault(key, set()).add(value.strip())
    elif isinstance(obj, list):
        for item in obj:
            walk_json(item, found, depth + 1)


def build_dictionary(data_dirs, extra_exports):
    found, folders = {}, set()
    exports = list(extra_exports)
    for root in data_dirs:
        if not root.is_dir():
            continue
        exports += [p for p in root.rglob("*.json") if p.stat().st_size < 400_000_000]
        for patient_dir in root.glob("patients/*"):
            if patient_dir.is_dir():
                folders.add(patient_dir.name)
    n_exports = 0
    for path in exports:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or "PatientInformation" not in data:
            continue
        n_exports += 1
        walk_json(data.get("PatientInformation"), found)
        walk_json(data.get("DeviceInformation"), found)
        for key in SESSION_KEYS:
            if isinstance(data.get(key), str):
                found.setdefault(key, set()).add(data[key])
    tokens = []   # (category, compiled regex, usable in binaries)
    for key in NAME_KEYS:
        for value in found.get(key, ()):
            if len(value) >= MIN_TOKEN["name"] and fold(value) not in GENERIC:
                tokens.append(("name", re.compile(rf"(?<![^\W\d_]){re.escape(fold(value))}(?![^\W\d_])"),
                               len(value) >= LONG_TOKEN))
    for key, cat in (("PatientId", "id"), ("NeurostimulatorSerialNumber", "serial")):
        for value in found.get(key, ()):
            if len(value) >= MIN_TOKEN[cat] and fold(value) not in GENERIC:
                tokens.append((cat, re.compile(re.escape(fold(value))), len(value) >= LONG_TOKEN))
    for value in folders:
        if len(value) >= MIN_TOKEN["folder"] and fold(value) not in GENERIC:
            tokens.append(("patient-folder", re.compile(rf"(?<![^\W\d_]){re.escape(fold(value))}(?![^\W\d_])"),
                           len(value) >= LONG_TOKEN))
    for key, cat in (("PatientDateOfBirth", "dob"), ("ImplantDate", "implant-date")):
        for day in filter(None, map(parse_day, found.get(key, ()))):
            tokens.append((cat, re.compile(rf"(?<!\d)(?:{day_patterns(day)})(?!\d)", re.I), False))
    sessions = {parse_day(v) for key in SESSION_KEYS for v in found.get(key, ())} - {None}
    for day in sessions:
        tokens.append(("session-date", re.compile(rf"(?<!\d)(?:{day_patterns(day)})(?!\d)", re.I), False))
    initials = set()
    for first in found.get("PatientFirstName", ()):
        for last in found.get("PatientLastName", ()):
            if first and last:
                initials.add((first[0] + last[0]).upper())
    for value in initials:   # only as a quoted literal or dict key, e.g. 'XY' or "XY":
        tokens.append(("initials", re.compile(rf"""(?<![\w])["']{re.escape(value)}["']"""), False))
    counts = {}
    for cat, _, _ in tokens:
        counts[cat] = counts.get(cat, 0) + 1
    print(f"dictionary: {n_exports} exports; " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if not n_exports:
        sys.exit("No Percept exports found; refusing to report a clean scan.")
    return tokens


FOLDED_CATEGORIES = ("name", "id", "serial", "patient-folder")


def masked(line, tokens):
    """The line, lower-cased, with every identifier replaced by «category»."""
    out = fold(line)
    for cat, regex, _ in tokens:
        out = regex.sub(f"«{cat}»", out) if cat in FOLDED_CATEGORIES else out
    for cat, regex, _ in tokens:
        out = regex.sub(f"«{cat}»", out) if cat not in FOLDED_CATEGORIES else out
    return out.strip()


def scan_text(label, text, tokens, hits, show=False):
    folded = fold(text)
    lines = text.splitlines()
    for cat, regex, _ in tokens:
        target = folded if cat in FOLDED_CATEGORIES else text
        for match in regex.finditer(target):
            line = target.count("\n", 0, match.start()) + 1
            context = masked(lines[line - 1], tokens)[:160] if show and line <= len(lines) else ""
            hits.append((label, line, cat, True, context))


def binary_patterns(tokens):
    """One combined regex per category, long tokens only."""
    grouped = {}
    for cat, regex, long_enough in tokens:
        if long_enough:
            grouped.setdefault(cat, []).append(regex.pattern)
    return [(cat, re.compile("|".join(patterns))) for cat, patterns in grouped.items()]


def scan_binary(label, blob, patterns, hits):
    text = blob.lower().decode("latin-1")
    for cat, regex in patterns:
        if regex.search(text):
            hits.append((label, 0, cat, False, ""))


def code_strings(code):
    for const in code.co_consts:
        if isinstance(const, str):
            yield const
        elif hasattr(const, "co_consts"):
            yield from code_strings(const)


def scan_frozen(exe, root, tokens, hits):
    """BrainSenser's own modules inside PyInstaller's archive. Returns the
    number of modules read, so a scan that finds no code can't pass as clean."""
    try:
        from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
    except ImportError:
        sys.exit("PyInstaller isn't installed in this Python; run with the build venv.")
    carchive = CArchiveReader(str(exe))
    n_modules = 0
    for name in carchive.toc:
        if not name.startswith("PYZ"):
            continue
        with tempfile.NamedTemporaryFile(suffix=".pyz", delete=False) as tmp:
            tmp.write(carchive.extract(name))
        pyz = ZlibArchiveReader(tmp.name)
        for module in pyz.toc:
            if module != "main" and module != "src" and not module.startswith("src."):
                continue
            code = pyz.extract(module)
            if isinstance(code, bytes):
                code = marshal.loads(code)
            if code is None:          # a namespace package: no code of its own
                continue
            text = "\n".join(code_strings(code))
            scan_text(f"{exe.relative_to(root)}::{module}", text, tokens, hits)
            n_modules += 1
        Path(tmp.name).unlink()
    return n_modules


# Inside a built app, only these are ours; everything else there is third-party
# code (warn on long tokens only, since short ones turn up in it by chance).
OWN_IN_BUNDLE = ("assets/", "src/ui/style.qss", "LICENSE", "THIRD_PARTY_NOTICES.txt", "Info.plist")


def bundle_relative(path):
    """The path inside a PyInstaller bundle's data folder, or None outside one."""
    parts = path.parts
    if "_internal" in parts:                                   # Windows onedir
        return "/".join(parts[parts.index("_internal") + 1:])
    for i, part in enumerate(parts):                           # macOS .app
        if part.endswith(".app") and parts[i + 1:i + 2] == ("Contents",):
            rest = parts[i + 2:]
            if rest[:1] in (("Resources",), ("Frameworks",)):
                rest = rest[1:]
            return "/".join(rest)
    return None


def is_frozen_exe(path):
    if path.suffix.lower() == ".exe":
        return True
    return path.parent.name == "MacOS" and path.parent.parent.name == "Contents"


def scan_path(target, tokens, patterns, hits):
    if target.is_file() and target.suffix == ".zip":
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(target) as archive:
                archive.extractall(tmp)
            scan_path(Path(tmp), tokens, patterns, hits)
        return
    files = [target] if target.is_file() else [
        p for p in sorted(target.rglob("*"))
        if p.is_file() and not p.is_symlink() and not SKIP_DIRS.intersection(p.parts)]
    root = Path.cwd() if target.is_relative_to(Path.cwd()) else (
        target.parent if target.is_file() else target)
    for path in files:
        label = str(path.relative_to(root))
        if is_frozen_exe(path):
            n_modules = scan_frozen(path, root, tokens, hits)
            print(f"{label}: read {n_modules} BrainSenser modules from the frozen archive")
            if not n_modules:
                hits.append((label, 0, "no-app-code-found", True, ""))
            continue
        blob = path.read_bytes()
        inside = bundle_relative(path)
        if inside is not None and not inside.startswith(OWN_IN_BUNDLE):
            scan_binary(label, blob, patterns, hits)
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or not path.suffix:
            try:
                scan_text(label, blob.decode("utf-8"), tokens, hits, SHOW)
                continue
            except UnicodeDecodeError:
                pass
        scan_binary(label, blob, patterns, hits)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("targets", nargs="+", type=Path)
    parser.add_argument("--data", nargs="*", type=Path, default=DEFAULT_DATA,
                        help="folders holding Percept exports and patient folders")
    parser.add_argument("--exports", nargs="*", type=Path, default=[],
                        help="extra Percept export files (e.g. old real fixtures)")
    parser.add_argument("--show", action="store_true",
                        help="print each hit's line, lower-cased, with identifiers masked")
    args = parser.parse_args()
    global SHOW
    SHOW = args.show
    tokens = build_dictionary(args.data, args.exports)
    patterns = binary_patterns(tokens)
    hits = []
    for target in args.targets:
        scan_path(target.resolve(), tokens, patterns, hits)
    failing = sorted({(l, n, c, ctx) for l, n, c, fail, ctx in hits if fail})
    warnings = sorted({(l, c) for l, n, c, fail, _ in hits if not fail})
    for label, line, cat, context in failing:
        print(f"{label}:{line}: {cat}" + (f"  | {context}" if context else ""))
    for label, cat in warnings:
        print(f"warning (binary): {label}: {cat}")
    print(f"{len(failing)} failing hit(s), {len(warnings)} binary warning(s)")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
