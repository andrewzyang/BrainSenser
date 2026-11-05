#!/usr/bin/env bash
# Smallest viable reproduction: runs each of the four standalone analysis
# scripts on the deposited CSVs and writes outputs to ./out/.
# DATA_DIR (default ./data) points at the folder holding the four CSVs;
# OUT_DIR (default ./out) redirects the outputs.
#
# Wall-clock at the locked spec (Python 3.13.5, 8-core macOS):
#   Script #1 (canonical-band stats)         ~ 30  s
#   Script #2 (5-Hz LOO classifier)           ~ 4-5 min
#   Script #3 (cluster permutation)           ~ 1-2 min
#   Script #4 (amplitude-threshold ML)        ~ 5-10 min  (--n-jobs 8)
#
# Outputs (in ./out/):
#   snapshot_stats_canonical.csv         15 rows (3 panels x 5 bands)
#   snapshot_5hz_classifier.csv              3 rows + .pkl
#   timeline_stats_cluster_permutation_bins.csv     33 rows
#   timeline_stats_cluster_permutation_clusters.csv 6-8 rows
#   timeline_stats_cluster_permutation_summary.csv  3 rows
#   timeline_amplitude_threshold_classifier.csv          3-4 rows + folds CSV + .pkl
#
# Cross-check the CSV values against VALIDATION_TARGETS.md to confirm the
# pipeline reproduces the manuscript numbers byte-identically.

set -euo pipefail

# One BLAS/OpenMP thread per process: script #4 already spreads its
# permutation null across cores, and nested threading can stall the run.
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1

DEPOSIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${OUT_DIR:-${DEPOSIT_DIR}/out}"
DATA_DIR="${DATA_DIR:-${DEPOSIT_DIR}/data}"
SCRIPTS_DIR="${DEPOSIT_DIR}/scripts"

mkdir -p "${OUT_DIR}"

echo "==> [1/4] Snapshot canonical-band stats (Supplementary Table 2)"
python "${SCRIPTS_DIR}/1_snapshot_stats_canonical.py" \
    --pt1-snapshots "${DATA_DIR}/pt1_snapshots_native.csv" \
    --pt2-snapshots "${DATA_DIR}/pt2_snapshots.csv" \
    --out-dir "${OUT_DIR}"

echo
echo "==> [2/4] Snapshot 5-Hz LOO classifier (Supplementary Table 5)"
python "${SCRIPTS_DIR}/2_snapshot_5hz_classifier.py" \
    --pt1-snapshots "${DATA_DIR}/pt1_snapshots_native.csv" \
    --pt2-snapshots "${DATA_DIR}/pt2_snapshots.csv" \
    --out-dir "${OUT_DIR}"

echo
echo "==> [3/4] Timeline cluster permutation (Supplementary Table 3)"
python "${SCRIPTS_DIR}/3_timeline_stats_cluster_permutation.py" \
    --pt1-snapshots "${DATA_DIR}/pt1_snapshots_native.csv" \
    --pt2-snapshots "${DATA_DIR}/pt2_snapshots.csv" \
    --pt1-timeline "${DATA_DIR}/pt1_timeline.csv" \
    --pt2-timeline "${DATA_DIR}/pt2_timeline.csv" \
    --out-dir "${OUT_DIR}"

echo
echo "==> [4/4] Timeline amplitude-threshold ML (Supplementary Table 4)"
python "${SCRIPTS_DIR}/4_timeline_amplitude_threshold_classifier.py" \
    --pt1-snapshots "${DATA_DIR}/pt1_snapshots_native.csv" \
    --pt2-snapshots "${DATA_DIR}/pt2_snapshots.csv" \
    --pt1-timeline "${DATA_DIR}/pt1_timeline.csv" \
    --pt2-timeline "${DATA_DIR}/pt2_timeline.csv" \
    --out-dir "${OUT_DIR}" \
    --n-jobs 8 \
    --panels pt1_left pt2_left pt2_right

echo
echo "Done. CSV outputs written to ${OUT_DIR}/"
echo "Cross-check against VALIDATION_TARGETS.md."
