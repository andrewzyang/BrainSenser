# Validation targets — locked manuscript values

The values the four scripts in `scripts/` reproduce from the four CSV
inputs, byte-identically at the precision shown. `bash demo.sh` runs all
four; each script fixes its own seeds and resampling counts (see its
docstring).

| Script | Reproduces |
|---|---|
| #1 `1_snapshot_stats_canonical.py` | Supplementary Table 2 |
| #2 `2_snapshot_5hz_classifier.py` | Supplementary Table 5 |
| #3 `3_timeline_stats_cluster_permutation.py` | Supplementary Table 3 |
| #4 `4_timeline_amplitude_threshold_classifier.py` | Supplementary Table 4 |

The Pt1 Snapshot targets come from `pt1_snapshots_native.csv`, Pt1's Snapshot
spectra as exported by the device (0.98-Hz bins), which `demo.sh` passes as
`--pt1-snapshots`. Scripts #3 and #4 read only event times and labels from the
Snapshot CSVs.

---

## Script #1 — Snapshot canonical-band stats (Supp Table 2)

**File:** `code_release/scripts/snapshot_stats_canonical.py`
**Output:** `snapshot_stats_canonical.csv` — 15 rows (3 panels × 5 bands).

Bands: δ (1–4 Hz), θ (4–8), α (8–13), β (13–30), low γ (30–40). FDR within panel.

### Pt1 left NAc — n_craving = 56, n_non_craving = 159 (device-native `data/pt1_snapshots_native.csv`; targets updated 2026-10-29)

| Band  | Freq (Hz) | Med(cr) | Med(nc) | U       | p       | q (FDR) | r_rb [95% BCa CI]        | Cohen's d [95% BCa CI]    | Sig |
|:------|:----------|--------:|--------:|--------:|--------:|--------:|:-------------------------|:--------------------------|:----|
| δ     | 1–4       |  2.546  |  1.983  |  5609.0 | 0.0039  | 0.0152  | +0.260 [+0.067, +0.439]  | +0.569 [+0.216, +0.951]   | *   |
| θ     | 4–8       |  2.788  |  2.680  |  5060.5 | 0.1286  | 0.1608  | +0.137 [−0.050, +0.320]  | +0.401 [+0.065, +0.776]   |     |
| α     | 8–13      |  2.841  |  2.734  |  5550.5 | 0.0061  | 0.0152  | +0.247 [+0.083, +0.406]  | +0.475 [+0.196, +0.787]   | *   |
| β     | 13–30     |  6.862  |  7.076  |  4301.5 | 0.7079  | 0.7079  | −0.034 [−0.191, +0.135]  | −0.145 [−0.385, +0.119]   |     |
| low γ | 30–40     |  2.091  |  2.412  |  3629.5 | 0.0389  | 0.0648  | −0.185 [−0.344, −0.015]  | −0.381 [−0.605, −0.118]   |     |

Rounding note: the α Cohen's d lower bound is 0.19649976, which the CSV
(`%.6f`) prints as `0.196500`; at three decimals it is +0.196.

### Pt2 left NAc — n_craving = 25, n_non_craving = 62

| Band  | Freq (Hz) | Med(cr) | Med(nc) | U      | p       | q (FDR) | r_rb [95% BCa CI]        | Cohen's d [95% BCa CI]    | Sig |
|:------|:----------|--------:|--------:|-------:|--------:|--------:|:-------------------------|:--------------------------|:----|
| δ     | 1–4       |  6.435  |  6.976  |  586.5 | 0.0778  | 0.0778  | −0.243 [−0.488, +0.048]  | −0.478 [−0.841, −0.051]   |     |
| θ     | 4–8       |  4.848  |  5.011  |  546.0 | 0.0321  | 0.0401  | −0.295 [−0.533, −0.025]  | −0.555 [−0.970, −0.148]   | *   |
| α     | 8–13      |  4.261  |  4.908  |  415.5 | 0.0008  | 0.0033  | −0.464 [−0.691, −0.173]  | −0.716 [−1.186, −0.155]   | *   |
| β     | 13–30     |  8.356  |  9.865  |  432.5 | 0.0013  | 0.0033  | −0.442 [−0.669, −0.153]  | −0.677 [−1.133, −0.142]   | *   |
| low γ | 30–40     |  2.210  |  2.533  |  534.5 | 0.0242  | 0.0401  | −0.310 [−0.552, −0.006]  | −0.586 [−1.098, −0.043]   | *   |

### Pt2 right NAc — n_craving = 25, n_non_craving = 62

| Band  | Freq (Hz) | Med(cr) | Med(nc) | U      | p       | q (FDR) | r_rb [95% BCa CI]        | Cohen's d [95% BCa CI]    | Sig |
|:------|:----------|--------:|--------:|-------:|--------:|--------:|:-------------------------|:--------------------------|:----|
| δ     | 1–4       |  6.356  |  7.041  |  496.0 | 0.0090  | 0.0112  | −0.360 [−0.573, −0.099]  | −0.619 [−0.977, −0.246]   | *   |
| θ     | 4–8       |  4.474  |  5.132  |  436.5 | 0.0015  | 0.0025  | −0.437 [−0.631, −0.203]  | −0.688 [−1.074, −0.298]   | *   |
| α     | 8–13      |  4.208  |  5.165  |  420.0 | 0.0009  | 0.0022  | −0.458 [−0.652, −0.195]  | −0.794 [−1.251, −0.319]   | *   |
| β     | 13–30     |  8.577  |  9.886  |  344.0 | 0.0001  | 0.0003  | −0.556 [−0.751, −0.300]  | −1.040 [−1.517, −0.544]   | *   |
| low γ | 30–40     |  2.239  |  2.403  |  598.0 | 0.0975  | 0.0975  | −0.228 [−0.468, +0.032]  | −0.445 [−0.903, +0.012]   |     |

Cohen's d is computed on **log₁₀** band power (Mann–Whitney U / r_rb are
rank-invariant to the log transform and therefore identical on raw vs.
log-transformed power; Cohen's d is not). All BCa CIs use 5,000-iter
stratified bootstrap, seed 2025.

**Locked CSV column set** (refined from plan §6.1 — adds 3 Cohen's d columns):
`patient, hemisphere, band_name, fmin_hz, fmax_hz, n_craving, n_non_craving,
median_craving, median_non_craving, U, p_raw, p_fdr, fdr_significant, r_rb,
r_rb_ci_lo, r_rb_ci_hi, cohens_d, cohens_d_ci_lo, cohens_d_ci_hi`.

---

## Script #2 — Snapshot 5-Hz ML classifier (Supp Table 5)

**File:** `code_release/scripts/snapshot_5hz_classifier.py`
**Output:** `snapshot_5hz_classifier.csv` + `.pkl` — 3 rows (one per panel).

Search envelope: 5.31–37.5 Hz, 10 candidate 5-bin × 3-step bands. Strict LOO
with in-fold band selection. 10,000-permutation max-statistic FWER null.
2,000-iter stratified percentile bootstrap CI on pooled out-of-fold AUC.

| Panel    | n (c/n) | Modal band (Hz) | Stability | LOO AUC [95% CI]        | FWER P  | Direction | Youden thr. | Sens. [95% CI]          | Spec. [95% CI]          | Cohen's d [95% CI]            | r_rb [95% BCa CI]           |
|:---------|:-------:|:----------------|:---------:|:------------------------|--------:|:----------|:-----------:|:------------------------|:------------------------|:------------------------------|:----------------------------|
| Pt1 L    | 56/159  | 8.33–13.23      | 100%      | 0.6212 [0.5419, 0.7032] | 0.1098  | +1        | −0.097701   | 0.4464 [0.3750, 0.9821] | 0.7610 [0.2075, 0.8365] | +0.4728 [+0.1844, +0.7829]    | +0.242 [+0.080, +0.402]     |
| Pt2 L    | 25/62   | 8.30–13.19      | 100%      | 0.7284 [0.5970, 0.8487] | 0.0382  | −1        | −0.068115   | 0.7600 [0.5200, 0.9200] | 0.7097 [0.6290, 0.8871] | −0.7179 [−1.2519, −0.2514]    | −0.457 [−0.686, −0.162]     |
| Pt2 R    | 25/62   | 17.09–21.97     | 100%      | 0.7677 [0.6484, 0.8748] | 0.0152  | −1        |  0.227240   | 0.5600 [0.4000, 0.9600] | 0.8710 [0.4839, 0.9839] | −1.0522 [−1.5545, −0.6058]    | −0.535 [−0.729, −0.272]     |

`Pt1 L` row: device-native `data/pt1_snapshots_native.csv` (targets updated
2026-10-29; see the change note at the top).

r_rb is computed on `modal_log_power` (per-event log₁₀ mean linear power
within the modal band selected by LOO). BCa CI uses 5,000-iter stratified
bootstrap, seed 2025. Sens/Spec CIs use 2,000-iter stratified percentile
bootstrap that re-finds Youden's J in each resample, seed 42.

**Locked CSV column set** (refined from plan §6.2 — adds 3 r_rb columns):
`patient, hemisphere, n_craving, n_neutral, n_bands_searched, window_bins,
step_bins, bin_step_hz, freq_min_hz, freq_max_hz, modal_band_lo_hz,
modal_band_hi_hz, modal_band_freq_pct, loo_auc, loo_auc_ci_lo, loo_auc_ci_hi,
fwer_p, n_perm, n_boot, direction, youden_threshold, sens, sens_ci_lo,
sens_ci_hi, spec, spec_ci_lo, spec_ci_hi, cohens_d, cohens_d_ci_lo,
cohens_d_ci_hi, r_rb, r_rb_ci_lo, r_rb_ci_hi`.

Patient column values: `pt1`, `pt2`.

Pickle: per-panel held-out scores, labels, per-band LOO-AUC vectors,
permutation max-stat null distribution.

---

## Script #3 — Timeline cluster permutation (Supp Table 3)

**File:** `code_release/scripts/timeline_stats_cluster_permutation.py`
**Output:** 3 CSVs (bins, clusters, summary).

Per-bin tie-corrected Mann–Whitney U → |z|. Cluster-forming threshold |z| > 1.96.
Cluster mass = Σ|z| across consecutive suprathreshold bins. Null: max cluster
mass across 10,000 event-level label permutations. p = (Σ[null ≥ obs] + 1) /
(n_perm + 1) (Phipson & Smyth 2010). 5,000-resample percentile bootstrap CI
on per-bin means.

Event exclusion: same-timestamp mixed-label discarded; same-class within 60 min
pruned to highest-coverage event per connected component.

### Panel a — Pt1 left NAc (33 craving / 118 non-craving)

| Bin (min) | n_cr | mean_cr (µV) | 95% CI cr            | n_nc | mean_nc (µV) | 95% CI nc            | \|z\| | cluster (p)         |
|:---------:|-----:|-------------:|:---------------------|-----:|-------------:|:---------------------|------:|:--------------------|
| −50       | 21   | 1055.95      | [776.61, 1407.10]    | 51   | 786.00       | [639.01, 950.02]     | 2.16  | C1 (p=0.2415)       |
| −40       | 33   | 785.79       | [631.39, 947.40]     | 118  | 824.49       | [639.95, 1074.60]    | 1.18  | —                   |
| −30       | 33   | 670.21       | [559.69, 794.37]     | 118  | 749.44       | [615.77, 926.68]     | 0.35  | —                   |
| −20       | 33   | 790.85       | [615.51, 1001.68]    | 118  | 689.91       | [598.66, 794.72]     | 1.29  | —                   |
| −10       | 33   | 763.15       | [618.88, 930.34]     | 118  | 737.21       | [614.57, 913.03]     | 1.09  | —                   |
|  +0       | 33   | 774.27       | [604.84, 971.24]     | 118  | 689.06       | [575.76, 840.33]     | 1.65  | —                   |
| +10       | 33   | 846.39       | [643.36, 1096.67]    | 118  | 643.00       | [566.94, 743.51]     | 2.03  | C2 (p=0.0317 *)     |
| +20       | 33   | 1080.52      | [740.41, 1538.77]    | 118  | 668.83       | [593.65, 760.76]     | 3.08  | C2 (p=0.0317 *)     |
| +30       | 33   | 1053.76      | [763.93, 1421.64]    | 118  | 945.58       | [712.24, 1234.10]    | 1.30  | —                   |
| +40       | 33   | 849.48       | [662.51, 1083.01]    | 117  | 761.26       | [627.76, 931.44]     | 1.74  | —                   |
| +50       | 13   | 1364.54      | [787.61, 2065.40]    | 66   | 705.68       | [581.28, 862.45]     | 2.15  | C3 (p=0.2445)       |

Clusters: C1 (−50 to −50, mass 2.16, p=0.2415); **C2 (+10 to +20, mass 5.11, p=0.0317 *)**; C3 (+50 to +50, mass 2.15, p=0.2445).

### Panel b — Pt2 left NAc (24 craving / 62 non-craving)

| Bin (min) | n_cr | mean_cr (µV) | 95% CI cr            | n_nc | mean_nc (µV) | 95% CI nc            | \|z\| | cluster (p)         |
|:---------:|-----:|-------------:|:---------------------|-----:|-------------:|:---------------------|------:|:--------------------|
| −50       |  9   | 857.89       | [748.66, 970.34]     | 21   | 1343.43      | [1137.66, 1565.72]   | 2.76  | C1 (p=0.1053)       |
| −40       | 21   | 1212.52      | [998.65, 1447.91]    | 43   | 1150.95      | [1024.86, 1285.10]   | 0.06  | —                   |
| −30       | 21   | 1085.62      | [893.05, 1301.11]    | 43   | 1185.44      | [1037.86, 1341.12]   | 1.10  | —                   |
| −20       | 21   | 1094.00      | [907.42, 1300.84]    | 43   | 1299.21      | [1168.85, 1441.26]   | 2.23  | C2 (p=0.0015 *)     |
| −10       | 21   | 1014.24      | [844.71, 1213.83]    | 43   | 1286.58      | [1165.00, 1415.58]   | 2.77  | C2 (p=0.0015 *)     |
|  +0       | 21   | 1036.33      | [892.71, 1210.87]    | 43   | 1315.84      | [1207.37, 1429.10]   | 3.13  | C2 (p=0.0015 *)     |
| +10       | 21   | 1023.76      | [850.14, 1219.50]    | 43   | 1309.93      | [1186.32, 1434.12]   | 2.65  | C2 (p=0.0015 *)     |
| +20       | 21   | 1125.67      | [896.09, 1399.45]    | 43   | 1295.47      | [1168.14, 1428.12]   | 2.26  | C2 (p=0.0015 *)     |
| +30       | 21   | 1159.48      | [873.28, 1546.96]    | 43   | 1320.65      | [1181.46, 1469.16]   | 2.41  | C2 (p=0.0015 *)     |
| +40       | 21   | 1250.43      | [934.68, 1695.95]    | 43   | 1317.00      | [1170.92, 1478.68]   | 1.54  | —                   |
| +50       | 12   | 1249.50      | [974.16, 1548.85]    | 22   | 1260.68      | [1061.73, 1497.36]   | 0.02  | —                   |

Clusters: C1 (−50 to −50, mass 2.76, p=0.1053); **C2 (−20 to +30, mass 15.44, p=0.0015 *)**.

### Panel c — Pt2 right NAc (24 craving / 62 non-craving)

| Bin (min) | n_cr | mean_cr (µV) | 95% CI cr            | n_nc | mean_nc (µV) | 95% CI nc            | \|z\| | cluster (p)         |
|:---------:|-----:|-------------:|:---------------------|-----:|-------------:|:---------------------|------:|:--------------------|
| −50       |  9   | 734.56       | [608.89, 857.23]     | 21   | 1218.95      | [1022.48, 1442.58]   | 2.76  | C1 (p=0.1149)       |
| −40       | 21   | 988.48       | [824.43, 1160.29]    | 43   | 1068.21      | [936.04, 1207.17]    | 0.62  | —                   |
| −30       | 21   | 907.86       | [761.90, 1064.82]    | 43   | 1072.88      | [929.53, 1224.36]    | 1.24  | —                   |
| −20       | 21   | 924.24       | [791.61, 1070.10]    | 43   | 1189.14      | [1053.79, 1335.84]   | 2.25  | C2 (p=0.0081 *)     |
| −10       | 21   | 841.19       | [717.00, 977.81]     | 43   | 1180.74      | [1058.48, 1315.61]   | 3.27  | C2 (p=0.0081 *)     |
|  +0       | 21   | 884.52       | [779.66, 1006.05]    | 43   | 1205.14      | [1078.63, 1338.82]   | 3.05  | C2 (p=0.0081 *)     |
| +10       | 21   | 872.76       | [730.14, 1027.53]    | 43   | 1185.51      | [1061.17, 1311.61]   | 2.85  | C2 (p=0.0081 *)     |
| +20       | 21   | 991.33       | [796.52, 1225.53]    | 43   | 1158.23      | [1029.11, 1291.33]   | 1.80  | —                   |
| +30       | 21   | 993.48       | [757.42, 1317.43]    | 43   | 1157.67      | [1032.86, 1289.23]   | 2.14  | C3 (p=0.2117)       |
| +40       | 21   | 1035.29      | [796.37, 1363.30]    | 43   | 1189.21      | [1061.66, 1324.28]   | 1.94  | —                   |
| +50       | 12   | 1004.75      | [789.48, 1228.09]    | 22   | 1089.23      | [928.72, 1261.37]    | 0.31  | —                   |

Clusters: C1 (−50 to −50, mass 2.76, p=0.1149); **C2 (−20 to +10, mass 11.42, p=0.0081 *)**; C3 (+30 to +30, mass 2.14, p=0.2117).

**Locked CSV column sets** (per plan §6.3):
- `timeline_stats_cluster_permutation_bins.csv` — `patient, hemisphere, bin_min,
  n_craving, mean_craving, ci_lo_craving, ci_hi_craving, n_non_craving,
  mean_non_craving, ci_lo_non_craving, ci_hi_non_craving, abs_z, usable`.
- `timeline_stats_cluster_permutation_clusters.csv` — `patient, hemisphere,
  cluster_id, start_bin_min, end_bin_min, cluster_mass, p_value`.
- `timeline_stats_cluster_permutation_summary.csv` — `patient, hemisphere,
  n_craving, n_non_craving, n_clusters, min_cluster_p,
  max_component_span_min, drop_mixed_label, drop_cross_class,
  drop_same_class`.

---

## Script #4 — Timeline amplitude-threshold ML (Supp Table 4)

**File:** `code_release/scripts/timeline_amplitude_threshold_classifier.py` (consolidated, ~1,500 LOC)
**Output:** `timeline_amplitude_threshold_classifier.csv` + `_folds.csv` + `.pkl`.

Feature: `np.nanmean` of Timeline µV across 5 offset bins at [−20, −10, 0, +10, +20]
min, ±5 min tolerance per bin. L2 logistic regression (sklearn
`LogisticRegression(C=1, class_weight="balanced")`). Decision boundary in µV =
−intercept/coef. LOO out-of-fold pooled probabilities → AUC. Cluster-bootstrap
CI on threshold (2,000 resamples). Label-shuffle permutation null over full
LOO pipeline (10,000 perms). Event exclusion: cross-class within 60 min
mutually excluded (NO same-class CC pruning — that's script #3 only).

### Per-panel headline numbers

| Panel  | n (c/n) | LR thr. (µV) | LR thr. 95% CI       | LOO-fold thr. median | LOO-fold IQR     | AUC    | AUC 95% CI         | P_perm  | Sens 95% CI            | Spec 95% CI            | Cohen's d [95% CI]        | r_rb [95% BCa CI]         |
|:-------|:-------:|-------------:|:--------------------:|:--------------------:|:----------------:|-------:|:------------------:|--------:|:-----------------------|:-----------------------|:--------------------------|:--------------------------|
| Pt1 L  | 43/149  | 725          | [670, 787]           | 725                  | [725, 726]       | 0.617  | [0.517, 0.718]     | 0.0090  | 0.442 [0.302, 0.581]   | 0.711 [0.631, 0.779]   | +0.379 [+0.031, +0.787]   | +0.265 [+0.055, +0.446]   |
| Pt2 L  | 22/43   | 1137         | [1037, 1231]         | 1138                 | [1134, 1141]     | 0.751  | [0.608, 0.884]     | 0.0005  | 0.727 [0.544, 0.909]   | 0.651 [0.512, 0.791]   | −0.855 [−1.589, −0.300]   | −0.541 [−0.776, −0.218]   |
| Pt2 R  | 22/43   | 994          | [914, 1074]          | 995                  | [991, 998]       | 0.756  | [0.629, 0.871]     | 0.0003  | 0.773 [0.591, 0.909]   | 0.674 [0.535, 0.814]   | −0.961 [−1.499, −0.529]   | −0.541 [−0.746, −0.263]   |

Directions: Pt1 L — craving **above** threshold (LR coef sign +1). Pt2 L, Pt2 R — craving **below** threshold (LR coef sign −1).

**Seeds:** main pipeline uses `RANDOM_STATE=42` (LOO/threshold/perm/AUC bootstrap).
**Sens/Spec CIs use a separate seed** `RNG_SEED=20260423` (stratified bootstrap,
2,000 resamples; resample craving and neutral events independently with
replacement; binarize at oof_prob ≥ 0.5; report 2.5/97.5 percentiles). r_rb
[BCa CI] uses `BOOTSTRAP_SEED=2025`, 5,000-iter stratified bootstrap on the
per-event Timeline mean amplitude feature.

Null AUC distributions (per-panel, 10k label perms):
- Pt1 L: mean 0.449, 95th pctile 0.578, bootstrap SD 0.051
- Pt2 L: mean 0.430, 95th pctile 0.621, bootstrap SD 0.072
- Pt2 R: mean 0.444, 95th pctile 0.623, bootstrap SD 0.063

Coefficient sign stability (full-data fit): Pt1 L 98.7%, Pt2 L 99.9%, Pt2 R 100.0%.
LOO-fold sign stability: 100% in all three panels.

Sanity check (manuscript-prose values must reproduce):
- Pt1 L: Mann–Whitney p = 0.0083 (per-event mean µV); craving 803±386 (median 703), neutral 664±357 (median 566).
- Pt2 L: Mann–Whitney p = 0.0004; craving 1014±336 (median 904), neutral 1288±313 (median 1299).
- Pt2 R: Mann–Whitney p = 0.0004; craving 863±247 (median 816), neutral 1168±348 (median 1117).

**Locked CSV column sets** (refined from plan §6.4 — adds sens/spec CIs, r_rb [CI]):
- `timeline_amplitude_threshold_classifier.csv` — `patient, hemisphere, n_craving,
  n_non_craving, auc, auc_ci_lo, auc_ci_hi, threshold_uv, threshold_ci_lo,
  threshold_ci_hi, threshold_fold_median, threshold_fold_iqr_lo,
  threshold_fold_iqr_hi, sens, sens_ci_lo, sens_ci_hi, spec, spec_ci_lo,
  spec_ci_hi, youden_j, p_perm, perm_p_floor, n_perm, lr_coef_sign, cohens_d,
  cohens_d_ci_lo, cohens_d_ci_hi, r_rb, r_rb_ci_lo, r_rb_ci_hi`.
- `timeline_amplitude_threshold_classifier_folds.csv` — `patient, hemisphere,
  fold_event_idx, fold_event_timestamp, fold_threshold_uv, fold_loo_prob,
  fold_true_label`.

Pickle: per-event offset matrices, LOO predictions, bootstrap distribution,
permutation null distribution.

Pt1 right NAc is intentionally excluded from the manuscript headline (Supp
Note 2, Supp Fig. 1 — electrode-position artifact). Pt1 R rows in the CSV
inputs are silently ignored by all four scripts.

---

## Checking a run

`bash demo.sh` writes its CSVs to `out/`. Compare them with the tables above;
every value should match at the precision shown.
