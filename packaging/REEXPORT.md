# Re-exporting the BrainSenser `.dmg` installers

How the two macOS installers are built, so you can rebuild them after
changing the app. (The Windows zip is built by `.github/workflows/release.yml`.) This is the **authoritative, verified** procedure.

All commands assume your shell is at the **repo root**:

```bash
cd BrainSenser        # your clone of this repository
```

---

## What gets produced

PyInstaller freezes the app **for one CPU architecture per build** and cannot
cross-compile, so each installer is a separate build:

| File in `application_exports/` | Arch | How | For |
|---|---|---|---|
| `BrainSenser-<ver>-silicon.dmg` | arm64  | native        | Apple Silicon (M-series) |
| `BrainSenser-<ver>-intel.dmg` | x86_64 | via Rosetta 2 | Intel Macs |

The `.dmg` is a frozen snapshot — **any change to `main.py`, `src/`, or
`assets/` requires a full rebuild + re-package** (you can't hand-edit files
inside the bundle; PyInstaller compiles them into an embedded archive).

> **Naming:** the two shipped builds are named by **architecture** —
> `-silicon` (arm64) and `-intel` (x86_64). (`-silicon` was previously called
> `-slim`; it is the slimmed arm64 build.)
>
> **Why they're slimmed:** the spec ships only the Qt modules the app uses
> (Core, Gui, Widgets, Svg, PrintSupport, Multimedia and what they link). It
> leaves out QtWebEngine (Chromium), QtPdf, the QML stack and the GPL-only
> modules that QML's plugins used to drag in (Charts, Virtual Keyboard, …);
> shipping those would break the LGPL-only terms in THIRD_PARTY_NOTICES.txt.
> An arm64 app is ≈ 300 MB.

---

## Prerequisites (one-time per machine)

- **Xcode Command Line Tools** — `xcode-select -p` should print a path
  (needed because `dependency_injector` compiles from source on x86_64).
- **Rosetta 2** (only for the Intel build) — verify with:
  ```bash
  arch -x86_64 uname -m        # must print: x86_64
  ```
  If missing: `softwareupdate --install-rosetta --agree-to-license`
- **The python.org universal2 framework Python** at `/usr/local/bin/python3`,
  used for both builds (must have an x86_64 slice — `file /usr/local/bin/python3`
  should list `x86_64`). Not Anaconda's Python: builds from it bundled GNU
  readline (GPL-3) along with Anaconda's own OpenSSL and other libraries.

---

## One-time: create the two clean build venvs

> ⚠️ **Build in a clean venv that contains ONLY `requirements.txt`.** Do **not**
> build with the Anaconda base interpreter directly — PyInstaller would vacuum
> in ~670 packages and balloon the app to ~2.3 GB. A `venv` is isolated from the
> base env's site-packages, which is the whole point.

> These live in `/tmp`, which macOS may clear on reboot. If a build step says
> the venv python is missing, just re-run the matching block below.

```bash
# ── arm64 build venv (native) ──────────────────────────────────────────────
/usr/local/bin/python3 -m venv /tmp/bs_build_venv
/tmp/bs_build_venv/bin/python -m pip install --upgrade pip
/tmp/bs_build_venv/bin/python -m pip install -r packaging/requirements-build.txt

# ── x86_64 (Intel) build venv (Rosetta; framework python's x86_64 slice) ────
arch -x86_64 /usr/local/bin/python3 -m venv /tmp/bs_build_venv_x86
arch -x86_64 /tmp/bs_build_venv_x86/bin/python -m pip install --upgrade pip
arch -x86_64 /tmp/bs_build_venv_x86/bin/python -m pip install -r packaging/requirements-build.txt
```

Sanity check (optional):
```bash
/tmp/bs_build_venv/bin/python -c "import platform;print('arm venv ->',platform.machine())"          # arm64
arch -x86_64 /tmp/bs_build_venv_x86/bin/python -c "import platform;print('x86 venv ->',platform.machine())"  # x86_64
```

---

## Re-export procedure

Do the two builds **sequentially** — both write to `dist/`, so finish and copy
one before starting the other. `create_dmg.sh` always emits
`dist/BrainSenser-<ver>.dmg`; you rename it on copy.

### Step 0 — version, identifier scan

If releasing a new version, edit **both** so the dmg name + Info.plist match:
- `src/ui/app_bootstrap.py` → `app.setApplicationVersion("X.Y.Z")`
- `packaging/brainsenser.spec` → `VERSION = 'X.Y.Z'` (`create_dmg.sh` reads it)

Replace `1.0.0` below with your version. Then scan everything that goes into
the app for participant identifiers (docstrings ship inside it); it must
report 0 failing hits:

```bash
/tmp/bs_build_venv/bin/python packaging/scan_identifiers.py main.py src assets
```

The build itself stops if a GPL-only Qt module (Charts, Virtual Keyboard, …)
or QtTest ends up in the bundle (`_MUST_NOT_SHIP` in the spec).

### A. Apple Silicon (arm64) — "silicon"

```bash
rm -rf build dist
/tmp/bs_build_venv/bin/python packaging/generate_third_party_notices.py   # notices for what this venv bundles
/tmp/bs_build_venv/bin/python -m PyInstaller packaging/brainsenser.spec --clean --noconfirm
PATH="/tmp/bs_build_venv/bin:$PATH" ./packaging/create_dmg.sh
mkdir -p application_exports
cp dist/BrainSenser-1.0.0.dmg application_exports/BrainSenser-1.0.0-silicon.dmg
```

### B. Intel (x86_64) — via Rosetta

Everything runs under `arch -x86_64` so PyInstaller produces an x86_64 binary
(`target_arch=None` in the spec → it follows the interpreter's arch).

```bash
rm -rf build dist
arch -x86_64 /tmp/bs_build_venv_x86/bin/python packaging/generate_third_party_notices.py
arch -x86_64 /tmp/bs_build_venv_x86/bin/python -m PyInstaller packaging/brainsenser.spec --clean --noconfirm
PATH="/tmp/bs_build_venv_x86/bin:$PATH" ./packaging/create_dmg.sh
cp dist/BrainSenser-1.0.0.dmg application_exports/BrainSenser-1.0.0-intel.dmg
```

Each build takes ~5 min (arm64) / ~15 min (Intel, emulated). They run fine in
the background.

### C. FFmpeg source (ships next to the dmgs)

The FFmpeg inside PySide6 is LGPL-2.1, which asks for its source to be offered
wherever the dmgs are, and `THIRD_PARTY_NOTICES.txt` says it is on the release
page. One copy covers both dmgs:

```bash
/tmp/bs_build_venv/bin/python packaging/fetch_ffmpeg_source.py application_exports
```

---

## Verify each build

```bash
# Architecture of the freshly built app (before you rename/copy the dmg)
lipo -archs dist/BrainSenser.app/Contents/MacOS/BrainSenser     # arm64  OR  x86_64

# No patient data and no Chromium got bundled (both must be 0)
find dist/BrainSenser.app \( -name '*.db' -o -name 'app_metadata*' \) | wc -l
find dist/BrainSenser.app -iname '*webengine*' | wc -l

# No GNU readline (GPL-3) or ncurses got bundled (must be 0)
find dist/BrainSenser.app \( -iname '*readline*' -o -iname '*ncurses*' \) | wc -l

# No binary needs a newer macOS than Info.plist promises (must print 14.0 or lower)
find dist/BrainSenser.app -type f \( -name '*.so' -o -name '*.dylib' -o -perm -111 \) \
  -exec otool -l {} \; 2>/dev/null | awk '/minos/ {print $2}' | sort -V | tail -1

# The ad-hoc signature holds together (an unsigned download then gets
# "Open Anyway" rather than "damaged")
codesign --verify --deep --strict dist/BrainSenser.app && echo "signature ok"

# No participant identifiers in the app's own code (must report 0 failing hits)
/tmp/bs_build_venv/bin/python packaging/scan_identifiers.py dist/BrainSenser.app

# dmg integrity (run on the file in application_exports/)
hdiutil verify application_exports/BrainSenser-1.0.0-silicon.dmg
```

**Optional launch smoke-test** (catches runtime/import problems the file checks
miss). Run the binary, wait, then grep the log — *don't* judge by "is it still
running" (a modal error dialog keeps the process alive):

```bash
# arm64: run directly.   Intel: prefix the app line with  arch -x86_64
# Throwaway home and data dir: the test never touches your real data
# (~/Library/Application Support/BrainSenser) or your saved window settings.
# Run the binary itself; `open` would drop these variables.
T="$(mktemp -d)"
HOME="$T" CFFIXED_USER_HOME="$T" BRAINSENSER_DATA_DIR="$T/data" \
  dist/BrainSenser.app/Contents/MacOS/BrainSenser > "$T/stdout.log" 2>&1 &
APP_PID=$!
sleep 40        # arm64: ~30s is enough. Intel under Rosetta: use 75s (first run rebuilds the font cache).
kill -9 "$APP_PID"   # only this test's process, not a copy you have open
find "$T" -name '*.log' -exec cat {} + > "$T.log"   # outside $T, so find can't read its own output
grep -nE "Application started|Resolved writable app data dir" "$T.log"   # success markers
grep -niE "Traceback|ModuleNotFoundError|OSError|CRITICAL" "$T.log" || echo "clean"
rm -rf "$T" "$T.log"
```

A good run logs `DI Container initialized` → `All services initialized` →
`Loaded N active patients` → `Application started`, with no traceback.

> First launch is slow (~20–30 s) because matplotlib builds a font cache once;
> that's normal, not a hang.

---

## Gotchas / notes

- **Clean venv, not base** — see the warning above. This is the #1 way the build
  goes wrong.
- **Intel is verified under Rosetta on this Mac**, which strongly predicts native
  Intel behavior, but the only 100% confirmation is launching on a real Intel Mac.
- **`configparser`** is in the spec's `hiddenimports` — required because the
  Cython `dependency_injector` imports it invisibly to PyInstaller. Don't remove it.
- **Multiprocessing must stay frozen-safe** — the LFP-threshold page's
  permutation test uses `joblib.Parallel`. A frozen app MUST (1) call
  `multiprocessing.freeze_support()` at the top of `main.py`'s
  `if __name__ == "__main__"` block, and (2) force `n_jobs=1` when `sys.frozen`
  (the guard in `timeline_mean20_core.py`). Without BOTH, clicking **Compare**
  spawns child processes that re-launch the GUI (a storm of windows) and the
  workers die with `TerminatedWorkerError`. Dev runs (from `src`) are unaffected
  and stay multi-core. Don't remove either guard.
- **Data lives outside the bundle** at `~/Library/Application Support/BrainSenser`
  (set by `default_app_data_dir()` in `src/core/path_resolver.py`). This is why
  the app runs from a read-only `.dmg`/`/Applications`, **and why updating the app
  never wipes a user's data** — they just drag the new `.app` over the old one.
- **Unsigned** — recipients clear Gatekeeper once
  (`xattr -dr com.apple.quarantine /Applications/BrainSenser.app`). See
  `application_exports/HOW_TO_OPEN.txt`.
- **Detach leftover installer volumes between runs** — `create_dmg.sh` (and
  double-clicking a dmg to test) can leave `/Volumes/BrainSenser Installer`
  mounted — sometimes several (`… 1`, `… 2`) and occasionally held open by an
  orphaned loky `resource_tracker` from a prior crashed run. Clear them before
  re-running create_dmg so the volume name is free:
  ```bash
  pkill -9 -f "BrainSenser.app/Contents/MacOS/BrainSenser" 2>/dev/null
  ls -d /Volumes/BrainSenser* 2>/dev/null | while read -r v; do hdiutil detach -force "$v"; done
  ```
- **zsh tip** — `for v in /Volumes/Glob*` aborts when nothing matches; use
  `ls -d /Volumes/BrainSenser* 2>/dev/null | while read -r v; do …; done`.

---

## Updating a recipient

Send the matching dmg → they drag the new `BrainSenser.app` onto `/Applications`
(replace), then `xattr -dr com.apple.quarantine /Applications/BrainSenser.app`.
Their imported data persists (it's in `~/Library/Application Support/BrainSenser`).
