#!/usr/bin/env python3
"""Download the FFmpeg source that matches the libraries PySide6 bundles.

FFmpeg is LGPL-2.1-or-later, which asks that its source be offered from the same
place as the binaries, and THIRD_PARTY_NOTICES.txt says it is on each GitHub
release page. Upload both files this writes next to the .dmg/.zip:
    ffmpeg-<version>.tar.xz      the release the bundled libraries were built from
    ffmpeg-<version>-build.txt   version, license and configure line, read from the
                                 bundled libavutil itself

Qt builds FFmpeg from the unmodified upstream source: Qt 6.9.2 (PySide6 6.9.2)
takes the n7.1.1 tag of github.com/FFmpeg/FFmpeg, and 6.12.0 did the same for
its version (see coin/provisioning/common/unix/ffmpeg-installation-utils.sh and
windows/install-ffmpeg.ps1 in qt5.git); recheck that when upgrading PySide6. Downloads use curl, because python.org's macOS
Python has no CA certificates until "Install Certificates.command" is run.

Run it with the build environment's Python, like generate_third_party_notices.py.

Usage:
    python packaging/fetch_ffmpeg_source.py [OUT_DIR]      # default: dist/
"""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import subprocess
import sys
from pathlib import Path

from generate_third_party_notices import ROOT, ffmpeg_build, runtime_distributions

# ---------------------------------------------------------------------------
RELEASES = "https://ffmpeg.org/releases/"
QT_SCRIPTS = "https://github.com/qt/qt5/tree/v{qt}/coin/provisioning/common"

BUILD_INFO = """\
FFmpeg {version}, as bundled with BrainSenser (via PySide6 {qt} / Qt Multimedia)

License: {license}
Source:  {tarball} (SHA-256 {sha256}), from {releases}
Built by The Qt Company with the scripts in
{scripts}
configured with:

{configuration}
"""


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"
    ffmpeg = ffmpeg_build(runtime_distributions())
    if ffmpeg is None:
        sys.exit("The PySide6 installed here bundles no FFmpeg; nothing to fetch.")
    out.mkdir(parents=True, exist_ok=True)
    tarball = out / f"ffmpeg-{ffmpeg['version']}.tar.xz"
    subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
                    "--output", str(tarball), RELEASES + tarball.name], check=True)
    qt = metadata.version("PySide6")
    info = BUILD_INFO.format(**ffmpeg, qt=qt, tarball=tarball.name, releases=RELEASES,
                             sha256=hashlib.sha256(tarball.read_bytes()).hexdigest(),
                             scripts=QT_SCRIPTS.format(qt=qt))
    (out / f"ffmpeg-{ffmpeg['version']}-build.txt").write_text(info, encoding="utf-8")
    print(f"Wrote {tarball} and its build notes; upload both with the release.")


if __name__ == "__main__":
    main()
