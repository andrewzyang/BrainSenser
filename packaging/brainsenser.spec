# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spec File for BrainSenser Application
=================================================

This spec file configures PyInstaller to build a macOS .app bundle for the
BrainSenser iEEG data analysis application.

Usage:
    pyinstaller packaging/brainsenser.spec

Output:
    dist/BrainSenser.app - Standalone macOS application bundle

Requirements:
    - Python 3.9+
    - PyInstaller 5.0+
    - All dependencies from requirements.txt

Created: 2025-10-25
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

# ============================================================================
# Configuration Variables
# ============================================================================

APP_NAME = 'BrainSenser'
BUNDLE_IDENTIFIER = 'com.davidson-lab.brainsenser'
VERSION = '1.0.0'  # also src/ui/app_bootstrap.py (setApplicationVersion)
COPYRIGHT = 'Copyright (c) 2025-2026 The BrainSenser Authors. MIT License.'

# Path configuration
spec_root = Path(SPECPATH)
project_root = spec_root.parent
main_script = str(project_root / 'main.py')

# ============================================================================
# Collect Hidden Imports
# ============================================================================

# Core dependencies that need explicit inclusion
hiddenimports = [
    # PySide6 modules
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtSvg',
    'PySide6.QtPrintSupport',
    'qtawesome',

    # Scientific computing
    'numpy',
    'numpy.core',
    'numpy.core._methods',
    'numpy.core._dtype_ctypes',
    'scipy',
    'scipy.stats',
    'scipy.signal',
    'scipy.interpolate',
    'scipy.optimize',
    'pandas',
    'pandas.core',
    'pandas.io.formats.style',

    # Visualization
    'matplotlib',
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_qtagg',
    'matplotlib.figure',
    'matplotlib.pyplot',

    # Machine learning (vendored threshold pipeline)
    'sklearn',
    'sklearn.metrics',
    'sklearn.preprocessing',
    'joblib',

    # Utilities
    'pytz',
    'PIL',
    'PIL.Image',
    'PIL.ImageQt',

    # Dependency injection
    'dependency_injector',
    'dependency_injector.containers',
    'dependency_injector.providers',
    # dependency_injector is Cython-compiled; its Configuration.from_ini() imports
    # configparser from inside the .so, invisible to PyInstaller static analysis.
    'configparser',

    # Application modules
    'src.core',
    'src.domain',
    'src.infrastructure',
    'src.ui',
    'src.utils',
]

# Automatically collect all submodules from critical packages. Not PySide6:
# collecting all of it pulled in Qt's QML stack, whose plugins drag along Qt 3D,
# Charts, Virtual Keyboard, PDF and other modules the app never uses (several
# are GPL-only). The Qt modules the app imports are found by analysis and the
# hidden imports above. Test packages are skipped everywhere.
def _not_tests(name):
    return '.tests' not in name and not name.endswith('.conftest')


auto_collect_packages = [
    'numpy',
    'scipy',
    'pandas',
    'matplotlib',
    'sklearn',
    'joblib',
    'qtawesome',
    'dependency_injector',
]

for package in auto_collect_packages:
    try:
        hiddenimports.extend(collect_submodules(package, filter=_not_tests))
    except Exception as e:
        print(f"Warning: Could not collect submodules for {package}: {e}")

# ============================================================================
# Collect Data Files
# ============================================================================

datas = []

# Add stylesheet
qss_file = project_root / 'src' / 'ui' / 'style.qss'
if qss_file.exists():
    datas.append((str(qss_file), 'src/ui'))

# Add assets directory (logo, etc.)
assets_dir = project_root / 'assets'
if assets_dir.exists():
    datas.append((str(assets_dir), 'assets'))

# License + third-party notices (required to ship with the binaries; regenerate
# the notices with packaging/generate_third_party_notices.py). No exists() guard:
# a missing file must fail the build, not ship silently without notices.
for license_file in ('LICENSE', 'THIRD_PARTY_NOTICES.txt'):
    datas.append((str(project_root / license_file), '.'))

# Collect data files from packages that need them
for package in ['matplotlib', 'scipy', 'sklearn', 'pandas', 'qtawesome', 'joblib']:
    try:
        pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package, filter_submodules=_not_tests)
        datas.extend(pkg_datas)
        hiddenimports.extend(pkg_hiddenimports)
    except Exception as e:
        print(f"Warning: Could not collect data for {package}: {e}")

# ============================================================================
# Binary Files Collection
# ============================================================================

binaries = []

# Collect binaries from scientific packages (may include native libs)
for package in ['numpy', 'scipy', 'sklearn', 'matplotlib']:
    try:
        pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package, filter_submodules=_not_tests)
        binaries.extend(pkg_binaries)
    except Exception as e:
        print(f"Warning: Could not collect binaries for {package}: {e}")

# ============================================================================
# Exclusions
# ============================================================================

# Exclude test files, development tools, and unnecessary packages
excludes = [
    # Testing frameworks
    'pytest',
    'pytest_cov',
    'pytest_qt',
    'pytest_mock',
    '_pytest',

    # Development tools
    'pylint',
    'mypy',
    'black',
    'isort',
    'flake8',
    'ipython',
    'ipdb',
    'IPython',

    # Jupyter and notebooks
    'jupyter',
    'jupyterlab',
    'ipykernel',
    'notebook',
    'nbconvert',
    'nbformat',

    # Unused GUI frameworks
    'tkinter',
    'PyQt5',
    'PyQt6',

    # Terminal-only modules a GUI never uses. They drag in GNU readline (GPL-3,
    # linked by Anaconda's Python) and ncurses (whose license isn't in the notices).
    'readline', 'curses', '_curses',

    # Documentation tools
    'sphinx',
    'docutils',

    # Other development tools
    'setuptools',
    'wheel',
    'pip',
    # NOTE: do NOT exclude 'distutils' — on Python 3.12+ it is gone from the
    # stdlib and PyInstaller's distutils hook aliases setuptools._distutils onto
    # it; excluding it makes that alias crash the analysis (ValueError).

    # Research-only analysis libs (used by scripts/results/research, NOT the app)
    'seaborn',
    'statsmodels',
    'pyqtgraph',
    'EntropyHub',
    'specparam',
    'fooof',

    # ── Unused PySide6/Qt modules (SLIM build) ──────────────────────────────
    # App imports only QtCore/QtGui/QtWidgets/QtSvg/QtPrintSupport/QtMultimedia
    # (+QtMultimediaWidgets). PyInstaller still keeps any framework a RETAINED
    # module actually links (binary-dep scan), so excluding these wrappers is
    # safe. The QtQuick/QtQml stack is excluded too: the splash video plays in a
    # QVideoWidget, which doesn't need QML, and QML's plugins pull in the modules
    # below. QtWebEngine and QtPdf are also force-dropped from binaries below.
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
    'PySide6.QtWebChannel', 'PySide6.QtWebSockets', 'PySide6.QtWebView',
    'PySide6.QtHttpServer', 'PySide6.QtNetworkAuth',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput', 'PySide6.Qt3DLogic',
    'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras', 'PySide6.QtQuick3D',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs', 'PySide6.QtGraphsWidgets',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
    'PySide6.QtDesigner', 'PySide6.QtUiTools', 'PySide6.QtHelp', 'PySide6.QtTest',
    'PySide6.QtSql', 'PySide6.QtLocation', 'PySide6.QtPositioning', 'PySide6.QtSensors',
    'PySide6.QtSerialPort', 'PySide6.QtSerialBus', 'PySide6.QtBluetooth', 'PySide6.QtNfc',
    'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtStateMachine',
    'PySide6.QtTextToSpeech', 'PySide6.QtSpatialAudio', 'PySide6.QtCanvasPainter',
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickControls2', 'PySide6.QtQuickWidgets',
    'PySide6.QtQuickTest', 'PySide6.QtAsyncio', 'PySide6.QtExampleIcons',
    'PySide6.QtDBus', 'PySide6.QtConcurrent', 'PySide6.QtXml',
]

# ============================================================================
# Analysis
# ============================================================================

a = Analysis(
    [main_script],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

# ============================================================================
# Remove Duplicate and Unwanted Files
# ============================================================================

# Remove test files that might have slipped through
a.datas = [x for x in a.datas if not any([
    'test' in x[0].lower(),
    'pytest' in x[0].lower(),
    '__pycache__' in x[0],
    '.pyc' in x[0],
])]

# Remove duplicate entries
a.datas = list({x[0]: x for x in a.datas}.values())
a.binaries = list({x[0]: x for x in a.binaries}.values())

# SLIM build: force-drop QtWebEngine (Chromium, ~287 MB), QtPdf (PDFium, via the
# PDF image-format plugin) and Qt Virtual Keyboard (GPL-only, via its input-
# context plugin, which also drags in QtQuick); the app has no web view, PDF
# import or on-screen keyboard, and nothing it uses links them. On Windows, also
# drop opengl32sw.dll (Mesa's software OpenGL, not used by a widgets app). Other
# unused Qt modules are handled by `excludes` above (which preserves real binary deps).
_SLIM_DROP = ('QtWebEngine', 'Qt6WebEngine', 'QtPdf', 'Qt6Pdf', 'libqpdf', 'qpdf.dll',
              'VirtualKeyboard', 'virtualkeyboard', 'opengl32sw.dll',
              # Left behind by the keyboard plugin; nothing the app ships links
              # them (checked with otool -L on the macOS bundle).
              'QtQuick', 'Qt6Quick', 'QtQml', 'Qt6Qml', 'QtConcurrent', 'Qt6Concurrent')
a.binaries = [x for x in a.binaries if not any(s in x[0] for s in _SLIM_DROP)]
a.datas = [x for x in a.datas if not any(s in x[0] for s in _SLIM_DROP)]

# Qt modules that must not ship: GPL-only in open-source Qt (so not covered by
# the LGPL terms in THIRD_PARTY_NOTICES.txt), or QtTest, whose stripped bundle
# breaks the ad-hoc code signature. Fail the build if one sneaks back in.
_MUST_NOT_SHIP = ('QtCharts', 'Qt6Charts', 'QtDataVisualization', 'Qt6DataVisualization',
                  'QtGraphs', 'Qt6Graphs', 'QtVirtualKeyboard', 'Qt6VirtualKeyboard',
                  'QtQuick3D', 'Qt6Quick3D', 'QtQuickTimeline', 'Qt6QuickTimeline',
                  'QtShaderTools', 'Qt6ShaderTools', 'QtTest', 'Qt6Test')
_shipped = sorted({x[0] for x in a.binaries + a.datas
                   if any(s in x[0] for s in _MUST_NOT_SHIP)})
if _shipped:
    raise SystemExit('Unwanted Qt modules in the bundle:\n  ' + '\n  '.join(_shipped[:20]))

# ============================================================================
# PYZ (Python Archive)
# ============================================================================

pyz = PYZ(
    a.pure,
    a.zipped_data,
)

# ============================================================================
# EXE (Executable)
# ============================================================================

exe = EXE(
    pyz,
    a.scripts,
    # Python's UTF-8 mode: text files default to UTF-8 on Windows too (its
    # default there is the ANSI code page), so Percept exports, settings and
    # the stylesheet read the same on every platform.
    [('X utf8', None, 'OPTION')],
    exclude_binaries=True,
    name=APP_NAME,
    # The Windows exe's icon (Pillow converts the PNG); the macOS icon is BUNDLE's.
    icon=str(project_root / 'assets' / 'brainsenser_app_icon.png') if sys.platform == 'win32' else None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-packed exes trip antivirus heuristics; size isn't worth it
    console=False,  # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,  # TODO: Add code signing identity for distribution
    entitlements_file=None,  # TODO: Add entitlements.plist if needed
)

# ============================================================================
# COLLECT (Collect Files for Bundle)
# ============================================================================

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

# ============================================================================
# BUNDLE (macOS .app Bundle)
# ============================================================================

app = BUNDLE(
    coll,
    name=f'{APP_NAME}.app',
    icon=str(project_root / 'assets' / 'brainsenser_app_icon.icns'),
    bundle_identifier=BUNDLE_IDENTIFIER,
    version=VERSION,
    info_plist={
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': APP_NAME,
        'CFBundleIdentifier': BUNDLE_IDENTIFIER,
        'CFBundleVersion': VERSION,
        'CFBundleShortVersionString': VERSION,
        'CFBundlePackageType': 'APPL',
        'CFBundleSignature': '????',
        'NSHumanReadableCopyright': COPYRIGHT,
        'NSHighResolutionCapable': True,
        # Qt 6.9 alone would run on macOS 12, but the numpy/scipy wheels pip
        # installs on current macOS are built for macOS 14 (REEXPORT.md checks
        # every bundled binary's minimum against this value).
        'LSMinimumSystemVersion': '14.0',
        # Light appearance (D20): the sidebar and top bar paint no background of
        # their own; configure_application also forces Qt's light colour scheme.
        'NSRequiresAquaSystemAppearance': True,
        'NSPrincipalClass': 'NSApplication',

        # Application category
        'LSApplicationCategoryType': 'public.app-category.medical',

        # File associations (if needed for opening data files)
        # 'CFBundleDocumentTypes': [
        #     {
        #         'CFBundleTypeName': 'JSON File',
        #         'CFBundleTypeRole': 'Viewer',
        #         'LSItemContentTypes': ['public.json'],
        #         'LSHandlerRank': 'Default',
        #     }
        # ],

        # Permissions (uncomment if needed)
        # 'NSDesktopFolderUsageDescription': 'BrainSenser needs access to save exported data.',
        # 'NSDocumentsFolderUsageDescription': 'BrainSenser needs access to read patient data files.',
    },
)

# ============================================================================
# Build Instructions
# ============================================================================

"""
To build the application:

1. Install PyInstaller:
   pip install pyinstaller

2. Run PyInstaller with this spec file:
   pyinstaller packaging/brainsenser.spec

3. The .app bundle will be created in:
   dist/BrainSenser.app

4. Test the application:
   open dist/BrainSenser.app

5. For distribution:
   - Create an .icns icon file and update the 'icon' parameter above
   - Add code signing certificate (codesign_identity)
   - Add entitlements.plist if needed for specific macOS permissions
   - Consider notarization for macOS Gatekeeper
   - Package as DMG for distribution:
     hdiutil create -volname "BrainSenser" -srcfolder dist/BrainSenser.app \
             -ov -format UDZO dist/BrainSenser.dmg

Build Options:
- Clean build: rm -rf build dist && pyinstaller packaging/brainsenser.spec
- Debug mode: Set debug=True in EXE() for verbose logging
- Size optimization: Set upx=True in EXE() (enabled by default)

Troubleshooting:
- If imports fail, add missing modules to hiddenimports list
- If data files are missing, add them to datas list
- Use --log-level=DEBUG for detailed build information:
  pyinstaller --log-level=DEBUG packaging/brainsenser.spec
- Check for runtime errors:
  dist/BrainSenser.app/Contents/MacOS/BrainSenser

Common Issues:
1. Missing PySide6 plugins:
   - Ensure PySide6 is properly installed in your environment
   - Check that Qt platform plugins are included

2. NumPy/SciPy import errors:
   - May need to add specific submodules to hiddenimports
   - Check for missing binary dependencies

3. Matplotlib backend issues:
   - Ensure matplotlib.backends.backend_qt5agg is in hiddenimports
   - May need to set MPLBACKEND environment variable

4. File not found errors:
   - Check that data files are properly added to datas list
   - Verify paths are correct at runtime (use sys._MEIPASS for bundled data)
"""
