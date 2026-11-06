# Naturalistic NAc-LFP craving biomarker — code deposit

Standalone analysis scripts that reproduce the primary results of the
manuscript byte-identically from four de-identified CSV inputs.

## What this deposit contains

| Path | Purpose |
|---|---|
| `scripts/1_snapshot_stats_canonical.py` | Canonical-band (δ/θ/α/β/low-γ) Mann–Whitney U + Benjamini–Hochberg FDR + rank-biserial r_rb (BCa CI) + Cohen's d on log₁₀ band power (BCa CI). Reproduces Supplementary Table 2. |
| `scripts/2_snapshot_5hz_classifier.py` | Strict leave-one-out classifier over 10 candidate 5-bin × 3-step frequency bands (5.31–37.5 Hz) with max-statistic permutation FWER null. Reproduces Supplementary Table 5 + Figure 2 d–i underlying numbers. |
| `scripts/3_timeline_stats_cluster_permutation.py` | Cluster-based permutation peri-event analysis of BrainSense Timeline narrowband (5.31–10.31 Hz) amplitude. Reproduces Supplementary Table 3 + Figure 3 a–c underlying numbers. |
| `scripts/4_timeline_amplitude_threshold_classifier.py` | L2 logistic regression amplitude-threshold classifier on Timeline µV with stratified bootstrap CIs and label-shuffle permutation null. Reproduces Supplementary Table 4 + Figure 3 d–i underlying numbers. |
| `data/pt1_snapshots_native.csv`, `data/pt2_snapshots.csv` | Per-snapshot PSD bin amplitudes (`0.00Hz`…`97.02Hz` columns) and event metadata for the two participants (not included; see Inputs). |
| `data/{pt1,pt2}_timeline.csv` | BrainSense Timeline narrowband amplitude stream for the two participants (not included; see Inputs). |
| `VALIDATION_TARGETS.md` | Locked manuscript values that the four scripts must reproduce. |
| `requirements.txt` / `environment.yml` | Pinned dependency versions used to produce the manuscript values. |
| `demo.sh` | Smallest viable reproduction — runs each script on the deposited CSVs and reports headline numbers. |

## Quickstart

```bash
# 1. Create a fresh Python 3.13 environment.
python3.13 -m venv .venv
source .venv/bin/activate

# 2. Install pinned dependencies.
pip install -r requirements.txt

# 3. Reproduce all four analyses from the deposited CSVs.
bash demo.sh
```

Each script is invocable independently with `--help` for argument documentation.

## Inputs

The four CSV inputs are de-identified extracts of the two participants'
BrainSense recordings, labelled `pt1` and `pt2` as in the paper, with all dates
shifted. They are not part of this repository and are not public yet;
`demo.sh` expects them in `data/`.

**`{pt}_snapshots.csv`** (PSD bin amplitudes per Snapshot event):

| Column | Type | Notes |
|---|---|---|
| `time` | ISO-8601 string | Snapshot event timestamp (UTC) |
| `hemisphere` | `"Left"` / `"Right"` | one row per snapshot × hemisphere |
| `snapshot_name` | str | parsed for craving / non-craving keywords |
| `0.00Hz` … `97.02Hz` | float | PSD power per frequency bin (~0.98 Hz spacing) |

Snapshot classification (applied in every script):
- `"Craving"` or `"Drinking"` substring → craving (label = 1)
- `"Happy"` or `"Neutral"` substring → non-craving (label = 0)
- otherwise → drop

**`{pt}_timeline.csv`** (BrainSense Timeline narrowband stream):

| Column | Type | Notes |
|---|---|---|
| `timestamp` | ISO-8601 string | Timeline reading timestamp (UTC) |
| `left_uV` | float, NaN if missing | left-hemisphere amplitude (µV) |
| `right_uV` | float, NaN if missing | right-hemisphere amplitude (µV) |
| `is_outlier` | int, 0/1 | rows with `is_outlier=1` are dropped before windowing |

## Reproducibility

All seeds, permutation counts, and bootstrap iteration counts are pinned and
documented in each script's module-level docstring. See `VALIDATION_TARGETS.md`
for the full set of locked manuscript numbers.

Tested on macOS 15 (Darwin 24.6.0) with Python 3.13.5. The threshold-classifier
script (`4_timeline_amplitude_threshold_classifier.py`) parallelizes the permutation null
across cores via `joblib`; pass `--n-jobs 8` for the validation-equivalent run.

## License

MIT — see the repository's [`LICENSE`](../LICENSE).

## Citation

See the repository's [`CITATION.cff`](../CITATION.cff), and please cite the paper
as well if you use the analyses.
