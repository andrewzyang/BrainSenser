#!/usr/bin/env python3
"""Generate THIRD_PARTY_NOTICES.txt for the BrainSenser binaries.

The .dmg/.exe bundle third-party software whose licenses (LGPL, BSD, MIT, ...)
require their notices to ship with binary copies: the Python interpreter, the
runtime dependency closure of requirements.txt, and PyInstaller's bootloader and
run-time hooks. This copies every license file they ship, adds the licenses of
the icon fonts QtAwesome bundles and of the software CPython incorporates, and
appends the GNU LGPL/GPL texts that the Qt (PySide6) wheels omit. The texts that
no installed package ships are vendored in packaging/licenses/, so this runs
offline.

Run it with the same Python environment PyInstaller builds from, so the list
matches what gets bundled. Rerun whenever requirements.txt or the build Python
changes, and on each OS you build for (Windows wheels bundle different native
libraries).

Usage:
    python packaging/generate_third_party_notices.py
"""
from __future__ import annotations

import ctypes
import importlib.metadata as metadata
import platform
import re
import sys
import sysconfig
from pathlib import Path

# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
OUT = ROOT / "THIRD_PARTY_NOTICES.txt"
LICENSES_DIR = ROOT / "packaging" / "licenses"   # vendored verbatim, so this runs offline

GNU_TEXTS = {                                    # from gnu.org/licenses
    "GNU Lesser General Public License v2.1": LICENSES_DIR / "LGPL-2.1.txt",
    "GNU Lesser General Public License v3.0": LICENSES_DIR / "LGPL-3.0.txt",
    "GNU General Public License v3.0": LICENSES_DIR / "GPL-3.0.txt",
}
# CPython's LICENSE.txt holds only the PSF terms; the licenses of the software it
# incorporates (OpenSSL, expat, libmpdec, ...) are in its docs, Doc/license.rst
PYTHON_INCORPORATED = "Python-{}-incorporated-software.txt"
# Third-party code inside Qt's own libraries (PCRE2, FreeType, ...), which the
# PySide6 wheels don't list; made by packaging/vendor_qt_attributions.py
QT_THIRD_PARTY = "Qt-{}-third-party.txt"
# Build tools that embed parts of themselves in the app, with what to say about it
BUILD_TOOLS = {
    "pyinstaller": "Its bootloader (GPL-2.0-or-later WITH Bootloader-exception, which allows\n"
                   "shipping it inside any application) and its run-time hooks (Apache-2.0)\n"
                   "are part of the application; see COPYING.txt below.\n",
}
QT_PACKAGES = ("pyside6", "shiboken6")      # prefixes: PySide6-Addons, -Pdf, ...
LICENSE_FILE = re.compile(r"LICEN[CS]E|COPYING|NOTICE", re.IGNORECASE)
CODE_SUFFIXES = (".py", ".pyc", ".pyi", ".so", ".dylib", ".dll", ".pyd")
AVUTIL = re.compile(r"^(lib)?avutil\b.*\.(dylib|dll)$|^libavutil\.so")
NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
MARKDOWN_LINK = re.compile(r"\[([^]]+)\]\(([^)]+)\)")
# The QtAwesome note says these full texts are in the file (via matplotlib,
# packaging, PyInstaller); fail rather than ship a false pointer.
REQUIRED_TEXTS = {"SIL OFL 1.1": "SIL OPEN FONT LICENSE Version 1.1",
                  "Apache 2.0": "Version 2.0, January 2004"}
RULE = "=" * 79

HEADER = """\
Third-party software notices for BrainSenser
{rule}

BrainSenser itself is released under the MIT License (see LICENSE).

The downloadable BrainSenser application bundles the third-party software
listed below. Each component remains under its own license.

LGPL-licensed components
- Qt and Qt for Python (PySide6, shiboken6) {qt_version}, used under the GNU
  Lesser General Public License v3.0. Source code:
  https://download.qt.io/official_releases/QtForPython/ and
  https://download.qt.io/official_releases/qt/
  The third-party code inside Qt's libraries (PCRE2, FreeType, HarfBuzz, libpng,
  libjpeg-turbo, libtiff, libwebp and others) is listed with its licenses in the
  "Third-party components inside Qt" section below.
{ffmpeg}{quadmath}
These libraries are dynamically linked. You can replace them with modified
versions in the application's library folder (BrainSenser.app/Contents/
Frameworks on macOS; the _internal folder on Windows). The full texts of the
GNU LGPL v2.1, GNU LGPL v3.0 and GNU GPL v3.0 are at the end of this file.
"""

FFMPEG = """\
- FFmpeg {version} libraries (libavcodec, libavformat, libavutil,
  libswresample, libswscale), shipped with PySide6 for Qt Multimedia, used
  under the GNU Lesser General Public License v2.1 or later. Their source code
  (ffmpeg-{version}.tar.xz) and build configuration are published next to the
  BrainSenser downloads on each GitHub release page; the source is also at
  https://ffmpeg.org/releases/.
"""

QUADMATH = """\
- libquadmath (part of GCC), shipped with {owner}, used under the GNU Lesser
  General Public License v2.1 or later. Source code:
  https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=libquadmath
"""


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def runtime_distributions() -> list[metadata.Distribution]:
    """Installed distributions reachable from requirements.txt, skipping extras."""
    pending = [m.group(1) for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
               if (m := NAME.match(line.split("#")[0]))]
    found: dict[str, metadata.Distribution] = {}
    while pending:
        name = canonical(pending.pop())
        if name in found:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue                      # platform-specific, not installed here
        found[name] = dist
        for requirement in dist.requires or []:
            spec, _, marker = requirement.partition(";")
            if "extra" not in marker and (m := NAME.match(spec)):
                pending.append(m.group(1))
    return sorted(found.values(), key=lambda d: canonical(d.metadata["Name"]))


def license_summary(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    if meta.get("License-Expression"):
        return meta["License-Expression"]
    field = (meta.get("License") or "").strip()
    if field and "\n" not in field and len(field) < 120:
        return field                      # some packages put the full text here
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or []
                   if c.startswith("License ::")]
    return ", ".join(classifiers) or "see license text below"


def license_texts(dist: metadata.Distribution) -> list[tuple[str, str]]:
    """(path, text) of every license-like file the distribution ships."""
    texts, seen = [], set()
    for file in dist.files or []:
        if not LICENSE_FILE.search(file.name) or file.name.endswith(CODE_SUFFIXES):
            continue
        path = Path(file.locate())
        try:
            if path.stat().st_size > 1_000_000:
                continue
            text = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if text and text not in seen:
            seen.add(text)
            texts.append((str(file), text))
    return texts


def python_license() -> list[tuple[str, str]]:
    """(label, text) for the interpreter PyInstaller bundles: its LICENSE.txt (the
    PSF terms) and the licenses of the software CPython incorporates."""
    minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    incorporated = LICENSES_DIR / PYTHON_INCORPORATED.format(minor)
    if not incorporated.is_file():
        sys.exit(f"Missing {incorporated}: copy the 'Licenses and Acknowledgements for "
                 f"Incorporated Software' section of Python {minor}'s Doc/license.rst there.")
    for path in (Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",   # macOS, Linux
                 Path(sys.base_prefix) / "LICENSE.txt"):                # Windows
        if path.is_file():
            return [("LICENSE.txt", path.read_text(encoding="utf-8").strip()),
                    (f"Doc/license.rst of Python {minor}",
                     incorporated.read_text(encoding="utf-8").strip())]
    sys.exit("Python's LICENSE.txt was not found; is this a full Python install?")


def qt_third_party() -> str:
    """The licenses of the third-party code inside the Qt we ship, vendored for
    this PySide6's minor version."""
    version = metadata.version("PySide6")
    minor = ".".join(version.split(".")[:2])
    path = LICENSES_DIR / QT_THIRD_PARTY.format(minor)
    if not path.is_file():
        sys.exit(f"Missing {path}: run packaging/vendor_qt_attributions.py {version} (online).")
    return path.read_text(encoding="utf-8").strip()


def qtawesome_fonts(dist: metadata.Distribution) -> str:
    """QtAwesome bundles icon fonts but ships only its own MIT license file; the
    fonts' licenses are stated in its README (the package description)."""
    fonts = sorted(f.name for f in dist.files or [] if f.name.endswith((".ttf", ".otf")))
    readme = dist.metadata.get_payload() or dist.metadata.get("Description") or ""
    match = re.search(r"^## License\n(.*?)^## ", readme, re.MULTILINE | re.DOTALL)
    if not match:
        sys.exit("QtAwesome's README has no '## License' section; update qtawesome_fonts().")
    statement = MARKDOWN_LINK.sub(
        lambda m: f"{m[1]} ({m[2]})" if "://" in m[2] else m[1], match[1]).strip()
    return (f"Icon fonts bundled with QtAwesome: {', '.join(fonts)}.\n\n"
            f"Their licenses, from QtAwesome's README:\n\n{statement}\n\n"
            "The full SIL Open Font License 1.1 and Apache License 2.0 texts appear\n"
            "elsewhere in this file.\n")


def ffmpeg_build(dists: list[metadata.Distribution]) -> dict[str, str] | None:
    """Version, license and configure line of the FFmpeg that PySide6 bundles,
    read from its libavutil; None if no FFmpeg is bundled."""
    for dist in dists:
        for file in dist.files or []:
            if AVUTIL.match(file.name):
                lib = ctypes.CDLL(str(file.locate()))
                info = {}
                for key, symbol in (("version", "av_version_info"),
                                    ("license", "avutil_license"),
                                    ("configuration", "avutil_configuration")):
                    function = getattr(lib, symbol)
                    function.restype = ctypes.c_char_p
                    info[key] = function().decode()
                return info
    return None


def main() -> None:
    dists = runtime_distributions()
    if not any(canonical(d.metadata["Name"]) == "pyside6" for d in dists):
        sys.exit("PySide6 is not installed here; run this with the build environment's Python.")
    try:
        tools = [metadata.distribution(name) for name in BUILD_TOOLS]
    except metadata.PackageNotFoundError:
        sys.exit("PyInstaller is not installed here; run this with the build environment's Python.")
    gnu = {title: path.read_text(encoding="utf-8").strip() for title, path in GNU_TEXTS.items()}

    ffmpeg = ffmpeg_build(dists)
    quadmath = next((d.metadata["Name"] for d in dists for f in d.files or []
                     if f.name.startswith("libquadmath")), None)
    parts = [HEADER.format(rule=RULE, qt_version=metadata.version("PySide6"),
                           ffmpeg=FFMPEG.format(**ffmpeg) if ffmpeg else "",
                           quadmath=QUADMATH.format(owner=quadmath) if quadmath else "")]
    parts.append(f"{RULE}\nPython {platform.python_version()}\nLicense: PSF-2.0\n{RULE}\n")
    for label, text in python_license():
        parts.append(f"--- {label} ---\n{text}\n")
    unlicensed = []
    for dist in dists + tools:
        name = dist.metadata["Name"]
        parts.append(f"{RULE}\n{name} {dist.version}\nLicense: {license_summary(dist)}\n{RULE}\n")
        if dist in tools:
            parts.append(BUILD_TOOLS[canonical(name)])
        texts = license_texts(dist)
        for path, text in texts:
            parts.append(f"--- {path} ---\n{text}\n")
        if canonical(name) == "qtawesome":
            parts.append(qtawesome_fonts(dist))
        if not texts:
            if canonical(name).startswith(QT_PACKAGES):
                parts.append("Used under the GNU LGPL v3.0; full text at the end of this file.\n")
            else:
                unlicensed.append(name)
                parts.append("(This package ships no license file; its license is named above.)\n")
    parts.append(f"{RULE}\nThird-party components inside Qt {metadata.version('PySide6')}\n{RULE}\n"
                 f"{qt_third_party()}\n")
    for title, text in gnu.items():
        parts.append(f"{RULE}\n{title} (full text)\n{RULE}\n{text}\n")

    notices = "\n".join(parts)
    missing = [name for name, marker in REQUIRED_TEXTS.items() if marker not in notices]
    if missing:
        sys.exit(f"The QtAwesome note points to a full {', '.join(missing)} text that is no "
                 "longer in the notices; vendor it in packaging/licenses/ and append it.")
    OUT.write_text(notices, encoding="utf-8")
    print(f"Wrote {OUT} (Python {platform.python_version()}, {len(dists)} packages, "
          f"PyInstaller, FFmpeg {ffmpeg['version'] if ffmpeg else 'not found'})")
    if unlicensed:
        print("No license file shipped by: " + ", ".join(unlicensed))


if __name__ == "__main__":
    main()
