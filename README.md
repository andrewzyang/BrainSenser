# BrainSenser

BrainSenser is a desktop app for analysing recordings from Medtronic Percept
deep brain stimulation devices: BrainSense **Snapshots** (spectra captured when
a patient marks an event) and the BrainSense **Timeline** (the chronic
narrowband LFP log). It compares spectra and LFP amplitude between groups of
patient-marked events (for example, craving vs. non-craving) with the analyses
described in our paper (the citation will be added on publication): canonical
band statistics, a leave-one-out frequency-band classifier, a cluster-based
permutation test around events, and an amplitude-threshold classifier.

BrainSenser is research software, not a medical device. It is not affiliated
with Medtronic; BrainSense and Percept are Medtronic trademarks.

## Download

Get the latest version from the [Releases page](../../releases/latest):

| Your computer | File |
|---|---|
| Mac with Apple silicon (M1 or later), macOS 14 or later | `BrainSenser-<version>-silicon.dmg` |
| Intel Mac (2018 or newer), macOS 14 or later | `BrainSenser-<version>-intel.dmg` |
| Windows 10 or 11, 64-bit | `BrainSenser-<version>-windows-x64.zip` |

The apps aren't code-signed yet, so the first launch needs one extra step:

- **macOS:** drag BrainSenser to Applications and open it once. When macOS
  blocks it, go to System Settings → Privacy & Security and click
  **Open Anyway**. (Or, in Terminal:
  `xattr -dr com.apple.quarantine /Applications/BrainSenser.app`)
- **Windows:** unzip the whole folder, then open `BrainSenser\BrainSenser.exe`.
  If SmartScreen says "Windows protected your PC", click **More info → Run
  anyway**. On PCs with Smart App Control turned on, unsigned apps can't run
  at all.

`HOW_TO_OPEN.txt`, inside every download, has the details.

BrainSenser ships with no patient data. Everything you import stays on your
computer, in `~/Library/Application Support/BrainSenser` (macOS) or
`%LOCALAPPDATA%\BrainSenser` (Windows).

## Run from source

With Python 3.13:

```bash
python3.13 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

From source, data goes to `~/.brainsense_data`; set `BRAINSENSER_DATA_DIR` to
use another folder.

Tests: `pip install pytest pytest-qt pytest-cov pytest-mock pytest-timeout`,
then `pytest`. Tests listed in `tests/known_failures.txt` are reported as
expected failures.

## Build the downloads

`packaging/REEXPORT.md` builds the two macOS installers;
`.github/workflows/release.yml` builds the Windows zip. Release builds install
the exact versions in `packaging/requirements-build.txt`.

## Reproduce the paper's statistics

`code_release/` holds four standalone scripts that reproduce Figures 2–3 and
Supplementary Tables 2–5 from the de-identified data deposited on OSF. See
`code_release/README.md`.

## License

BrainSenser is released under the MIT License (`LICENSE`). The downloads bundle
third-party software under its own licenses, listed in
`THIRD_PARTY_NOTICES.txt`. For the LGPL components (Qt, FFmpeg), that file links
their source code, and each release page carries the matching FFmpeg source.

## How to cite

See `CITATION.cff`, and please cite the paper as well.
