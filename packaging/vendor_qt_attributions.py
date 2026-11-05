#!/usr/bin/env python3
"""Vendor the licence notices of the third-party code inside the Qt we ship.

PySide6's wheels carry no licence files, yet Qt's libraries contain third-party
code (PCRE2, FreeType, HarfBuzz, libpng, libjpeg-turbo, libtiff, libwebp, ...)
whose BSD/MIT-style licences ask for their notices in binary distributions. Qt
describes each component in a qt_attribution.json file in its source tree. This
reads those files for the given Qt version from Qt's GitHub mirrors and writes
packaging/licenses/Qt-<major.minor>-third-party.txt, which
generate_third_party_notices.py appends.

MODULES are the Qt source repositories of what the bundle ships after the
spec's slimming (QtCore/Gui/Widgets/Network/DBus/OpenGL/PrintSupport and their
plugins come from qtbase). Rerun it, online, whenever PySide6 moves to a new
minor version; the notices generator refuses to run until the file exists.

Usage:
    python packaging/vendor_qt_attributions.py 6.9.2
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "packaging" / "licenses"
MODULES = ("qtbase", "qtsvg", "qtimageformats", "qtmultimedia")
# Attributions for code that never reaches the shipped libraries.
SKIP_PREFIXES = ("tests/", "examples/", "util/", "doc/", "coin/", "cmake/",
                 "src/testlib/", "src/testinternal/", "src/tools/", "src/android/",
                 "src/plugins/platforms/wasm/", "src/plugins/platforms/android/",
                 "src/plugins/platforms/xcb/", "src/plugins/platforms/eglfs/",
                 "src/3rdparty/wasm/", "src/3rdparty/xcb/", "src/3rdparty/gradle/",
                 "src/3rdparty/android/")
RULE = "-" * 79


def fetch(url):
    """curl, because python.org's macOS Python has no CA certificates."""
    result = subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location", url],
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"{url}: {result.stderr.strip()}")
    return result.stdout


def tree(module, tag):
    data = json.loads(fetch(f"https://api.github.com/repos/qt/{module}/git/trees/{tag}?recursive=1"))
    if data.get("truncated"):
        sys.exit(f"GitHub truncated the file list of {module}; can't be sure every attribution was found.")
    return [entry["path"] for entry in data["tree"] if entry["type"] == "blob"]


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    version = sys.argv[1]
    tag = f"v{version}"
    minor = ".".join(version.split(".")[:2])
    sections, seen = [], set()
    for module in MODULES:
        paths = tree(module, tag)
        raw = f"https://raw.githubusercontent.com/qt/{module}/{tag}/"
        attribution_files = sorted(p for p in paths if p.endswith("qt_attribution.json")
                                   and not p.startswith(SKIP_PREFIXES))
        for path in attribution_files:
            folder = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
            # strict=False: some of Qt's files have raw tabs/newlines inside strings
            for entry in as_list(json.loads(fetch(raw + path), strict=False)):
                if not isinstance(entry, dict) or "Name" not in entry:
                    continue
                key = (entry.get("Name"), entry.get("Version"), entry.get("LicenseId"))
                if key in seen:
                    continue
                seen.add(key)
                copyright = "\n".join(as_list(entry.get("Copyright")))
                if not copyright and entry.get("CopyrightFile"):
                    copyright = fetch(raw + folder + entry["CopyrightFile"]).strip()
                texts = []
                for name in as_list(entry.get("LicenseFile")) + as_list(entry.get("LicenseFiles")):
                    texts.append(fetch(raw + folder + name).strip())
                if not texts:      # by SPDX id: LICENSE.<id>.txt beside the file, or LICENSES/<id>.txt
                    expression = str(entry.get("LicenseId", "")).replace("(", " ").replace(")", " ")
                    for spdx in expression.split():
                        if spdx in ("AND", "OR", "WITH"):
                            continue
                        for candidate in (f"{folder}LICENSE.{spdx}.txt", f"LICENSES/{spdx}.txt"):
                            if candidate in paths:
                                texts.append(fetch(raw + candidate).strip())
                                break
                if not texts:
                    sys.exit(f"No licence text for {entry['Name']} ({module}/{path}); "
                             "extend this script before shipping.")
                header = f"{entry['Name']}" + (f" {entry['Version']}" if entry.get("Version") else "")
                sections.append(
                    f"{RULE}\n{header}\n"
                    f"In: Qt {module} ({entry.get('QtUsage', '').strip() or 'see Qt documentation'})\n"
                    f"License: {entry.get('License', '')} ({entry.get('LicenseId', '')})\n"
                    + (f"{copyright}\n" if copyright else "")
                    + f"{RULE}\n" + "\n\n".join(texts) + "\n")
    intro = (f"Third-party components inside Qt {version} ({', '.join(MODULES)}), from Qt's\n"
             "qt_attribution.json files. Some apply only on certain platforms.\n\n")
    out = OUT_DIR / f"Qt-{minor}-third-party.txt"
    out.write_text(intro + "\n".join(sections), encoding="utf-8")
    print(f"Wrote {out} ({len(sections)} components)")


if __name__ == "__main__":
    main()
