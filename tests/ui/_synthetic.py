"""Deterministic synthetic UI state for layout, golden and sweep tests.

``populate_main_window`` fills every page of a real ``MainWindow`` — patient
card, metadata, upload table, event-type lists, groups, plots and statistics
tables — with fixed synthetic values (seeded RNG). It never reads patient data:
no database, no files, no fixtures. Ported from the responsive-UI audit harness
(``notes/responsive_ui_v2_audit/harness/sweep.py``) so the goldens, the
responsive invariants and ``tools/responsive_sweep.py`` share one populated state.
"""

import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import QApplication

from src.ui.widgets.responsive_figure import ResponsiveFigureWidget

# Event-type counts and the two groups every populated page uses.
EVENT_COUNTS = {"Anxious": 14, "Craving": 37, "Depressed": 9, "Drinking": 22,
                "Drinking/Craving": 11, "Happy": 31, "Neutral": 48, "Sad": 12}
GROUP_1 = ["Anxious", "Happy", "Neutral", "Sad", "Depressed"]
GROUP_2 = ["Craving", "Drinking", "Drinking/Craving"]


def settle(win, ms: int = 300) -> None:
    """Process events for ``ms`` and until every plot shows its final frame."""
    app = QApplication.instance()
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 30)
        time.sleep(0.005)
    for _ in range(200):  # wait for the plots' final frames
        busy = [f for f in win.findChildren(ResponsiveFigureWidget)
                if not f.is_layout_settled()]
        if not busy:
            break
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 30)
        time.sleep(0.01)
    app.processEvents()


def populate_main_window(win, appdata: Path, settle_ms: int = 300) -> None:
    """Fill every page of ``win`` with deterministic synthetic results (no real data)."""
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    from src.core.models import Patient, PatientStatistics, UploadedFile
    rng = np.random.default_rng(7)
    now = datetime(2026, 1, 15, 9, 30)
    md = {"first_name": "Synthetic", "last_name": "Patient-01", "date_of_birth": "1970-01-01T00:00:00Z",
          "gender": "Unspecified", "device_patient_id": "SYN-0001",
          "diagnosis": "Synthetic diagnosis (no real data)", "neurostimulator": "Percept PC",
          "neurostimulator_model": "B35200", "serial_number": "SYN0000000X",
          "implant_date": "2024-01-15T09:00:00Z", "device_location": "Synthetic site",
          "battery_percentage": 87, "battery_life_months": 96,
          "last_session_date": "2025-06-01T12:00:00Z"}
    patient = Patient(patient_id="SYNTH_001", patient_name="Synthetic Patient 01",
                      data_directory=appdata / "patients" / "SYNTH_001",
                      database_path=appdata / "patients" / "SYNTH_001" / "brainsense_data.db",
                      created_at=now, updated_at=now, metadata=md)
    win.top_bar.update_patient_list([patient])
    win.top_bar.set_selected_patient("SYNTH_001")
    dm = win.data_management_page
    dm._on_patient_selected(patient)
    dm._on_metadata_updated(md)
    dm._on_statistics_updated(PatientStatistics(
        patient_id="SYNTH_001", snapshots_original=1312, snapshots_deduplicated=1187,
        timeline_original=48210, timeline_deduplicated=45977,
        indefinite_streaming_original=36, indefinite_streaming_deduplicated=34,
        definite_streaming_original=12, definite_streaming_deduplicated=12,
        total_files_uploaded=12, total_duplicates_skipped=2350,
        last_upload_date=now, last_calculated=now))
    ups = []
    for i in range(12):
        t = now - timedelta(days=17 * i, hours=i)
        ups.append(UploadedFile(
            file_id=i + 1, patient_id="SYNTH_001",
            file_name=f"Report_Json_Session_Report_{t.strftime('%Y%m%dT%H%M%S')}.json",
            file_path=appdata / f"synthetic_{i}.json", file_hash=f"{i:064x}",
            file_size_bytes=int(rng.uniform(0.4, 25) * 1024 * 1024),
            timeline_count=int(rng.integers(0, 4000)), timeline_original_count=4100,
            snapshot_count=int(rng.integers(0, 120)), snapshot_original_count=130,
            indefinite_streaming_count=int(i % 3 == 0), indefinite_streaming_original_count=1,
            definite_streaming_count=int(i % 4 == 0), definite_streaming_original_count=1,
            duplicates_skipped=10, outliers_detected=0, processing_time_seconds=1.2,
            extractor_version="1.0.0", processing_settings=None, errors_encountered=0,
            error_details=None, processed_at=t))
    dm._on_upload_history_updated(ups)

    counts = dict(EVENT_COUNTS)
    g1, g2 = list(GROUP_1), list(GROUP_2)
    n1 = sum(counts[k] for k in g1)
    n2 = sum(counts[k] for k in g2)

    def fill_groups(gp):
        if hasattr(gp, "populate_event_types_with_classification"):
            gp.populate_event_types_with_classification(counts)
        else:
            gp.set_available_event_types(counts)
        for target, names, btn in ((1, g1, gp.add_to_group1_btn), (2, g2, gp.add_to_group2_btn)):
            lst = gp.event_types_list
            lst.clearSelection()
            for i in range(lst.count()):
                it = lst.item(i)
                it.setSelected(it.data(Qt.ItemDataRole.UserRole) in names)
            btn.click()

    # --- Snapshots / canonical bands (PSD)
    psd = win.snapshots_psd_page
    psd.content_stack.setCurrentIndex(1)
    fill_groups(psd.grouping_panel)
    f = np.arange(0, 97, 0.9765625)

    def curve(k, peak, n):
        base = 2.0 / (1 + f) ** 1.1 + peak * np.exp(-0.5 * ((f - 6.0) / 1.5) ** 2) \
            + 0.02 * np.exp(-0.5 * ((f - 20) / 4) ** 2)
        med = base * k
        return (med, med * 0.82, med * 1.22, n)
    psd.psd_plot.update_psd_data(f, curve(1.15, 0.6, n2), curve(1.0, 0.35, n1),
                                 curve(1.08, 0.5, n2), curve(1.0, 0.4, n1))
    sig = lambda b: SimpleNamespace(is_significant=b)
    psd.psd_plot.update_band_statistics(
        {"Delta": sig(False), "Theta": sig(True), "Alpha": sig(False), "Beta": sig(True), "Gamma_low": sig(False)},
        {"Delta": sig(False), "Theta": sig(True), "Alpha": sig(False), "Beta": sig(False), "Gamma_low": sig(False)})
    rows = []
    for hemi in ("L", "R"):
        for band, rng_s in (("Delta", "1-4 Hz"), ("Theta", "4-8 Hz"), ("Alpha", "8-13 Hz"),
                            ("Beta", "13-30 Hz"), ("Gamma_low", "30-40 Hz")):
            p = float(rng.uniform(0.0004, 0.6))
            rows.append(dict(band_label=f"{band} ({hemi})", freq_range=rng_s,
                             group1_median_text=f"{rng.uniform(0.01, 2):.3f}",
                             group2_median_text=f"{rng.uniform(0.01, 2):.3f}",
                             central_tendency_ci_text=f"[{-rng.uniform(0, .3):.3f}, {rng.uniform(0, .3):.3f}]",
                             p_value_text=f"{p:.4f}", p_value_highlight=p < 0.05,
                             q_value_text=f"{min(1, p * 2.5):.4f}", q_value_highlight=p * 2.5 < 0.05,
                             effect_size_value_text=f"{rng.uniform(-.5, .5):.3f}",
                             effect_size_ci_text=f"[{-rng.uniform(0, .6):.3f}, {rng.uniform(0, .6):.3f}]"))
    gp = psd.grouping_panel
    gp.set_central_tendency_header("Median Δ 95% CI")
    gp.set_effect_size_header("Rank-biserial r")
    gp.update_statistics_table(rows)

    # --- Snapshots / 5 Hz band (AUC profile)
    from src.core.services.snapshot_ml_analysis_service import AucProfileResult
    centers = 5.31 + 2.44 + np.arange(11) * 2.93

    def auc_res(h, modal):
        auc = 0.5 + 0.18 * np.exp(-0.5 * ((centers - 9) / 4) ** 2) + rng.normal(0, 0.02, centers.size)
        return AucProfileResult(hemisphere=h, band_centers_hz=centers,
                                band_edges_hz=np.c_[centers - 2.44, centers + 2.44],
                                per_band_auc=auc, per_band_ci_lo=auc - 0.08, per_band_ci_hi=auc + 0.08,
                                modal_band_idx=modal, pipeline_loo_auc=0.712, pipeline_loo_ci_lo=0.611,
                                pipeline_loo_ci_hi=0.803, fwer_p=0.0021, n_craving=n2,
                                n_non_craving=n1, n_perm=10000, n_boot=2000)
    hz = win.snapshots_5hz_band_page
    hz.content_stack.setCurrentIndex(1)
    fill_groups(hz.grouping_panel)
    L5, R5 = auc_res("L", 1), auc_res("R", 2)
    hz.auc_plot.set_results(L5, R5)
    hz.grouping_panel.populate_ml_table(L5, R5)

    # --- Timeline / LFP threshold (violins)
    from src.core.services.timeline_threshold_ml_service import ThresholdMlResult
    from src.ui.views.timeline_lfp_threshold.timeline_lfp_threshold_view import _format_group_label

    def thr_res(h):
        X = np.r_[rng.normal(900, 150, n1), rng.normal(1050, 180, n2)]
        y = np.r_[np.zeros(n1, int), np.ones(n2, int)]
        return ThresholdMlResult(
            hemisphere=h, n_craving=n2, n_neutral=n1, n_valid=n1 + n2, n_dropped=3,
            bin_coverage_mean=0.97, X=X, y=y, lr_threshold=985.0, lr_threshold_ci=(940.0, 1030.0),
            lr_coef_sign=1, direction="higher", auc_loo=0.684, auc_ci=(0.601, 0.763),
            oof_prob=rng.uniform(0, 1, n1 + n2), sensitivity_yj=0.62, specificity_yj=0.66,
            sensitivity_lr=0.6, specificity_lr=0.68, mann_whitney_p=0.0003,
            perm_p=1 / 1001, perm_p_floor=1 / 1001, null_aucs=rng.normal(0.5, 0.04, 1000),
            fold_thr_median=985.0, fold_thr_iqr=(975.0, 995.0), fold_sign_stability=1.0,
            verdict=True, sens_ci=(0.48, 0.71), spec_ci=(0.59, 0.76), r_rb=0.34, r_rb_ci=(0.18, 0.49))
    lfp = win.timeline_lfp_threshold_page
    lfp.content_stack.setCurrentIndex(1)
    fill_groups(lfp.grouping_panel)
    lfp.violin_widget.set_group_labels(_format_group_label(g1, "Group 1"), _format_group_label(g2, "Group 2"))
    TL, TR = thr_res("Left"), thr_res("Right")
    lfp.violin_widget.update_results({"Left": TL, "Right": TR})
    lfp.grouping_panel.populate_threshold_table({"Left": TL, "Right": TR})

    # --- Timeline / peri-event (cluster permutation)
    from src.core.services.timeline_peri_event_service import PeriEventResult
    bins = tuple(range(-50, 51, 10))

    def peri_res(h, sigp):
        x = np.asarray(bins, float)
        cm = 1000 + 120 * np.exp(-0.5 * (x / 15) ** 2) + rng.normal(0, 10, x.size)
        nm = 980 + rng.normal(0, 10, x.size)
        return PeriEventResult(
            hemisphere=h, n_craving=n2, n_neutral=n1, n_ts_raw=48000, drop={},
            max_component_span_min=100.0, offset_bins=bins, obs_z=rng.normal(0, 1.5, x.size),
            usable_mask=np.ones(x.size, bool),
            clusters=({"start_bin": -10, "end_bin": 10, "start_idx": 4, "end_idx": 6, "mass": 8.42, "p": sigp},
                      {"start_bin": 40, "end_bin": 40, "start_idx": 9, "end_idx": 9, "mass": 2.1, "p": 0.41}),
            null_max=rng.gamma(2, 2, 10000), craving_mean=cm, craving_lo=cm - 40, craving_hi=cm + 40,
            neutral_mean=nm, neutral_lo=nm - 30, neutral_hi=nm + 30, n_perm=10000, window_minutes=50)
    peri = win.timeline_peri_event_page
    peri.content_stack.setCurrentIndex(1)
    fill_groups(peri.grouping_panel)
    PL, PR = peri_res("Left", 0.0123), peri_res("Right", 0.0007)
    peri.plot_widget.update_results({"Left": PL, "Right": PR})
    peri.grouping_panel.populate_cluster_table({"Left": PL, "Right": PR})
    settle(win, settle_ms)
