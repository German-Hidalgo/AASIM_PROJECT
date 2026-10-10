"""Pruebas de verificación funcional de los módulos de la Fase 2.

Equipo AASIM (Buitrago, Rocha, Hidalgo). Las señales usadas son sintéticas y
con verdad-terreno conocida; los resultados verifican el comportamiento de los
módulos, no el desempeño clínico del sistema.
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest
import synthetic_ecg as se

from src.features.extract_features import (
    FeatureConfig,
    benchmark_latency,
    extract_window_features,
    feature_names,
    nn_intervals,
    process_window,
    sample_entropy,
)
from src.partitioning.split_dataset import (
    SplitConfig,
    assert_disjoint_sites,
    assert_disjoint_subjects,
    assign_windows,
    fit_transform_partitions,
    hierarchical_split,
    leave_one_site_out,
    make_window_grid,
    patient_wise_split,
    seal_manifest,
    site_wise_split,
    subject_group_kfold,
    verify_seal,
)
from src.preprocessing.filters import (
    CausalECGFilter,
    FilterConfig,
    FilterMode,
    HemodynamicLimits,
    NonCausalFilterError,
    apply_filter_chain,
    assert_causal_for_inference,
    censor_discontinuities,
    censor_reference_labels,
    design_notch,
    estimate_mains_frequency,
    flag_unstable_reference,
)
from src.preprocessing.metadata_validation import validate_metadata
from src.preprocessing.transformations import (
    CovariateEncoder,
    DataLeakageError,
    TrainOnlyRobustScaler,
    apply_weights,
    fit_inverse_frequency_weights,
    robust_window_normalize,
    sbp_stratum,
)
from src.reports.generate_visualizations import (
    bland_altman_statistics,
    iso_distribution_check,
    label_statistics_table,
    plot_rejection_timeline,
    plot_spearman_heatmap,
)
from src.sqi.quality_assessment import (
    SQIThresholds,
    assess_window,
    gated_inference,
    rejection_by_subject,
    saturation_fraction,
)

FS = 250.0


@pytest.fixture(scope="module")
def clean_record() -> se.SyntheticRecord:
    return se.make_ecg(30.0, FS, 70.0, seed=3)


@pytest.fixture(scope="module")
def raw_ecg(clean_record: se.SyntheticRecord) -> np.ndarray:
    return se.contaminate(clean_record.ecg_mv, FS, mains_hz=50.0)


# ------------------------------------------------------------------ filtros
def test_notch_q_minimo() -> None:
    with pytest.raises(ValueError):
        design_notch(50.0, FS, 20.0)
    with pytest.raises(ValueError):
        FilterConfig(FS, notch_q=10.0)
    with pytest.raises(ValueError):
        FilterConfig(100.0)


@pytest.mark.parametrize("mains", [50.0, 60.2])
def test_estimacion_frecuencia_de_red(
    clean_record: se.SyntheticRecord, mains: float
) -> None:
    x = se.contaminate(clean_record.ecg_mv, FS, mains_hz=mains)
    est = estimate_mains_frequency(x, FilterConfig(FS))
    assert est.detected and abs(est.frequency_hz - mains) <= 0.5
    clean = estimate_mains_frequency(clean_record.ecg_mv, FilterConfig(FS))
    assert not clean.detected


def test_cadena_atenua_red_y_deriva(raw_ecg: np.ndarray) -> None:
    res = apply_filter_chain(raw_ecg, FilterConfig(FS), FilterMode.CAUSAL)
    f = np.fft.rfftfreq(raw_ecg.size, 1 / FS)
    p_raw = np.abs(np.fft.rfft(raw_ecg)) ** 2
    p_out = np.abs(np.fft.rfft(res.signal)) ** 2
    mains = (f > 49.5) & (f < 50.5)
    drift = f < 0.4
    assert p_out[mains].sum() < 1e-3 * p_raw[mains].sum()
    assert p_out[drift].sum() < 0.05 * p_raw[drift].sum()


def test_streaming_identico_a_bloque(raw_ecg: np.ndarray) -> None:
    cfg = FilterConfig(FS)
    f1, f2 = CausalECGFilter(cfg, 50.0), CausalECGFilter(cfg, 50.0)
    streamed = np.concatenate(
        [f1.process(raw_ecg[i : i + 333]) for i in range(0, raw_ecg.size, 333)]
    )
    assert np.allclose(streamed, f2.process(raw_ecg), atol=1e-9)


def test_fase_cero_prohibida_en_inferencia(raw_ecg: np.ndarray) -> None:
    with pytest.raises(NonCausalFilterError):
        assert_causal_for_inference(FilterMode.ZERO_PHASE)
    with pytest.raises(NonCausalFilterError):
        process_window(raw_ecg, FS, mode=FilterMode.ZERO_PHASE)


def test_fase_cero_no_desplaza_picos(
    clean_record: se.SyntheticRecord, raw_ecg: np.ndarray
) -> None:
    zp = apply_filter_chain(raw_ecg, FilterConfig(FS), FilterMode.ZERO_PHASE).signal
    seg = slice(int(3 * FS), int(27 * FS))
    peaks = clean_record.r_peaks[
        (clean_record.r_peaks > seg.start) & (clean_record.r_peaks < seg.stop)
    ]
    found = np.array([np.argmax(zp[p - 5 : p + 6]) + p - 5 for p in peaks])
    assert np.max(np.abs(found - peaks)) <= 2


def test_censura_hemodinamica() -> None:
    sbp = np.array([120, 69, 241, 120, 120, 90, np.nan, 80])
    dbp = np.array([80, 60, 90, 39, 141, 75, 70, 85])
    res = censor_reference_labels(sbp, dbp)
    # 120/80 ok; 69 fuera; 241 fuera; PAD 39; PAD 141; PP=15 <20; NaN; PAS<=PAD
    assert res.valid_mask.tolist() == [
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    assert res.counts["PAS fuera de rango"] == 2
    assert res.counts["presión de pulso inferior al mínimo"] == 1
    # Los límites son inclusivos: 70/40 y 240/140 son admisibles (PP >= 20).
    edge = censor_reference_labels(np.array([70.0, 240.0]), np.array([40.0, 140.0]))
    assert edge.valid_mask.all()
    lim = HemodynamicLimits(pulse_pressure_max=100.0)
    assert not censor_reference_labels(
        np.array([240.0]), np.array([100.0]), lim
    ).valid_mask[0]


def test_referencia_inestable() -> None:
    t = np.array([0, 30, 60, 90, 400, 430])
    sbp = np.array([120, 121, 140, 141, 120, 121], dtype=float)
    flags = flag_unstable_reference(t, sbp)
    assert flags[:4].all() and not flags[4:].any()


def test_discontinuidades() -> None:
    x = np.sin(np.linspace(0, 20, 2500))
    tp = np.ones(x.size, dtype=bool)
    x[500:504] = np.nan  # 16 ms en TP -> interpolable
    x[1000:1010] = np.nan  # 40 ms -> sin reparar
    y, valid, rep = censor_discontinuities(x, FS, tp_mask=tp)
    assert rep.n_interpolated == 1 and rep.n_unrepaired == 1
    assert np.isfinite(y[500:504]).all() and not valid[1000:1010].any()
    assert not rep.discard_window
    x[1500:1560] = np.nan  # 240 ms
    assert censor_discontinuities(x, FS, tp_mask=tp)[2].discard_window


# ---------------------------------------------------------------------- SQI
def test_compuerta_rf4(raw_ecg: np.ndarray, clean_record: se.SyntheticRecord) -> None:
    good = apply_filter_chain(raw_ecg, FilterConfig(FS)).signal[int(2 * FS) :]
    q = assess_window(good, FS)
    assert q.quality_flag == 0 and q.sqi_composite == pytest.approx(1.0)
    bad = apply_filter_chain(
        se.make_corrupted(clean_record.ecg_mv, FS), FilterConfig(FS)
    ).signal
    qb = assess_window(bad, FS)
    assert qb.quality_flag == 1 and "kSQI" in qb.failed_criteria


def test_inferencia_bloqueada_si_flag(clean_record: se.SyntheticRecord) -> None:
    calls: list[int] = []

    def predict(_: np.ndarray) -> dict[str, float]:
        calls.append(1)
        return {"sbp": 120.0, "dbp": 80.0, "map": 93.0}

    bad = apply_filter_chain(
        se.make_corrupted(clean_record.ecg_mv, FS), FilterConfig(FS)
    ).signal
    out = gated_inference(bad, FS, predict)
    assert out.blocked and out.prediction is None and not calls
    assert "Reposicione" in out.message


def test_umbrales_estrictos_bloquean(raw_ecg: np.ndarray) -> None:
    good = apply_filter_chain(raw_ecg, FilterConfig(FS)).signal[int(2 * FS) :]
    assert assess_window(good, FS, SQIThresholds(ksqi_min=50.0)).failed_criteria == (
        "kSQI",
    )


def test_metricas_dqr() -> None:
    assert saturation_fraction(np.array([0, 1, 2, 65535]), 0, 65535) == 0.5
    r = rejection_by_subject([1, 1, 0, 0, 0, 0], ["A", "A", "A", "B", "B", "B"])
    assert r["A"][1] and not r["B"][1]


# ---------------------------------------------------------- características
def test_caracteristicas_y_verdad_terreno(
    clean_record: se.SyntheticRecord, raw_ecg: np.ndarray
) -> None:
    filt = apply_filter_chain(raw_ecg, FilterConfig(FS)).signal
    res = extract_window_features(filt, FS)
    f = res.features
    assert list(f) == feature_names() or set(f) == set(feature_names())
    assert len(feature_names()) == 22 + 2 * 16 + 1 + 10
    assert not np.isnan(list(f.values())).any()
    rr = clean_record.rr_s * 1000
    assert f["feat_hrv_mean_nn_ms"] == pytest.approx(rr.mean(), abs=5.0)
    assert f["feat_hrv_sdnn_ms"] == pytest.approx(rr.std(ddof=1), abs=5.0)
    assert 60 < f["feat_qrs_duration_ms"] < 140
    assert 120 < f["feat_pr_interval_ms"] < 260
    q = f["feat_qt_interval_ms"] / 1000
    rr_s = f["feat_hrv_mean_nn_ms"] / 1000
    assert f["feat_qtc_bazett_ms"] == pytest.approx(q * 1000 / np.sqrt(rr_s), rel=0.06)
    assert f["feat_qtc_fridericia_ms"] == pytest.approx(
        q * 1000 / np.cbrt(rr_s), rel=0.06
    )
    assert abs(sum(f[f"feat_wpd_e_{i:02d}"] for i in range(16)) - 1.0) < 1e-9


def test_ventana_fuera_de_rango() -> None:
    with pytest.raises(ValueError):
        extract_window_features(np.zeros(int(5 * FS)), FS)
    with pytest.raises(ValueError):
        extract_window_features(np.zeros(int(40 * FS)), FS)


def test_entropia_y_nn() -> None:
    rng = np.random.default_rng(0)
    assert sample_entropy(np.ones(50)) != sample_entropy(np.ones(50))  # NaN
    assert sample_entropy(rng.normal(size=200)) > sample_entropy(
        np.sin(np.arange(200) / 4)
    )
    nn, _ = nn_intervals(np.array([0, 250, 500, 1200, 1450, 1700]), FS, FeatureConfig())
    assert nn.size == 4  # se descarta el intervalo de 2.8 s (fuera de rango)


def test_pipeline_rechaza_sin_extraer(clean_record: se.SyntheticRecord) -> None:
    res = process_window(se.make_corrupted(clean_record.ecg_mv, FS), FS)
    assert res.quality.quality_flag == 1 and res.features is None


def test_pipeline_a_125_hz_del_corpus_publico() -> None:
    """El pipeline completo opera a la frecuencia nativa de PulseDB (125 Hz, 10 s)."""
    fs = 125.0
    rec = se.make_ecg(10.0, fs, 72.0, seed=11)
    raw = se.contaminate(rec.ecg_mv, fs, mains_hz=60.0)
    filt = apply_filter_chain(raw, FilterConfig(fs)).signal
    res = process_window(raw, fs)
    assert res.quality.quality_flag == 0 and res.features is not None
    f = res.features.features
    assert len(f) == len(feature_names())
    # En ventanas de 10 s (unos 12 latidos) la entropía muestral puede quedar indefinida.
    indefinidas = {k for k, v in f.items() if np.isnan(v)}
    assert indefinidas <= {"feat_hrv_sampen"}
    assert 60 < f["feat_qrs_duration_ms"] < 160
    assert filt.shape == raw.shape


def test_latencia_rnf2(raw_ecg: np.ndarray) -> None:
    stats = benchmark_latency(raw_ecg, FS, n_runs=3)
    assert stats["max_s"] < 5.0


# ------------------------------------------------------------ transformaciones
def test_normalizacion_robusta() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(5, 2, 1000)
    x[10] = 1e6  # artefacto de gran voltaje
    z, ok = robust_window_normalize(x)
    assert ok and abs(np.median(z)) < 1e-12
    assert robust_window_normalize(np.ones(100))[1] is False


def test_covariables_fuente_publica_sin_imc_ni_postura() -> None:
    """Sesiones de una fuente pública (IMC, postura y medicación no disponibles)."""
    meta = pd.DataFrame(
        {
            "age_bracket": ["60-69", "70-79", "50-59"],
            "bmi_category": ["not_available", "normal", "not_available"],
            "biological_sex": ["male", "female", "male"],
            "posture": ["not_available"] * 3,
            "active_cardiovascular_medication": [["unknown"]] * 3,
        }
    )
    ids = ["S1", "S2", "S3"]
    enc = CovariateEncoder().fit(meta, ids, ids)
    out = enc.transform(meta)
    assert out["bmi__not_available"].tolist() == [1.0, 0.0, 1.0]
    assert out["posture__not_available"].eq(1.0).all()
    assert out["med__unknown"].eq(1.0).all()
    assert np.isfinite(out.to_numpy()).all()


def test_covariables_y_pesos() -> None:
    meta = pd.DataFrame(
        {
            "age_bracket": ["30-39", "60-69", "70-79", "50-59"],
            "bmi_category": ["normal", "obese_class_1", "overweight", "normal"],
            "biological_sex": ["female", "male", "male", "intersex"],
            "posture": ["supine", "seated", "standing", "ambulatory"],
            "active_cardiovascular_medication": [
                [],
                ["beta_blocker", "diuretic"],
                [],
                ["arb"],
            ],
        }
    )
    ids = ["S1", "S2", "S3", "S4"]
    enc = CovariateEncoder().fit(meta.iloc[:2], ids[:2], ["S1", "S2"])
    out = enc.transform(meta)
    assert out.loc[1, "med__beta_blocker"] == 1 and out.loc[0, "med__diuretic"] == 0
    assert out.filter(like="sex__").sum(axis=1).eq(1).all()
    with pytest.raises(DataLeakageError):
        CovariateEncoder().fit(meta, ids, ["S1", "S2"])
    bad = meta.copy()
    bad.loc[0, "posture"] = "running"
    with pytest.raises(ValueError):
        enc.transform(bad)

    strata = sbp_stratum(np.array([110] * 90 + [150] * 8 + [170] * 2, dtype=float))
    w = fit_inverse_frequency_weights(strata)
    assert w[4] >= w[3] > w[1] and np.average(
        apply_weights(strata, w)
    ) == pytest.approx(1.0)


# ------------------------------------------------------------- particionamiento
def _subjects(n: int = 200, sites: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(5)
    return pd.DataFrame(
        {
            "subject_id": [f"SUBJ-{i:05d}" for i in range(n)],
            "site_id": [f"SITE-{i % sites:03d}" for i in range(n)],
            "stratum": rng.choice(["a", "b", "c"], size=n, p=[0.6, 0.3, 0.1]),
        }
    )


def test_particion_70_15_15_y_determinismo() -> None:
    subs = _subjects()
    cfg = SplitConfig(stratify_by=("stratum",))
    m = patient_wise_split(subs, cfg)
    c = m.counts()
    assert c == {"train": 140, "val": 30, "test": 30}
    cert = assert_disjoint_subjects(m)
    assert all(v == 0 for v in cert.pairwise_subject_intersections.values())
    shuffled = subs.sample(frac=1.0, random_state=0)
    assert patient_wise_split(shuffled, cfg).partitions == m.partitions
    # cada estrato queda representado en las tres particiones
    st = dict(zip(subs["subject_id"], subs["stratum"], strict=True))
    for part in ("train", "val", "test"):
        assert {st[s] for s in m.partitions[part]} == {"a", "b", "c"}


def test_asercion_detecta_fuga_y_manipulacion() -> None:
    m = patient_wise_split(_subjects())
    digest = seal_manifest(m)
    verify_seal(m, digest)
    leaked = copy.deepcopy(m)
    leaked.partitions["test"].append(leaked.partitions["train"][0])
    with pytest.raises(DataLeakageError):
        assert_disjoint_subjects(leaked)
    with pytest.raises(DataLeakageError):
        verify_seal(leaked, digest)


def test_site_wise_y_jerarquica() -> None:
    subs = _subjects()
    sw = site_wise_split(subs)
    assert_disjoint_subjects(sw)
    assert_disjoint_sites(sw)
    h = hierarchical_split(subs)
    assert h.multicenter and h.site_wise is not None
    mono = hierarchical_split(subs[subs["site_id"].isin(["SITE-000", "SITE-001"])])
    assert not mono.multicenter and mono.notes
    for site, man in leave_one_site_out(subs):
        assert man.sites("test") == {site} and site not in man.sites("train")
        assert_disjoint_subjects(man)


def test_ventanas_y_pliegues() -> None:
    m = patient_wise_split(_subjects(60))
    wins = pd.DataFrame({"subject_id": np.repeat(sorted(m.assignment()), 3)})
    tab = assign_windows(wins, m)
    assert tab.groupby("subject_id")["partition"].nunique().max() == 1
    with pytest.raises(DataLeakageError):
        assign_windows(pd.DataFrame({"subject_id": ["SUBJ-99999"]}), m)
    grid = make_window_grid(int(60 * FS), FS, 30.0, 10.0)
    assert grid.shape == (4, 2) and (grid[:, 1] - grid[:, 0] == 7500).all()
    folds = subject_group_kfold(m.partitions["train"], 5, seed=1)
    assert all(not (tr & va) for tr, va in folds)


def test_normalizacion_solo_train() -> None:
    subs = _subjects(90)
    m = patient_wise_split(subs)
    rng = np.random.default_rng(2)
    rows = pd.DataFrame(
        {
            "subject_id": np.repeat(subs["subject_id"].to_numpy(), 4),
            "x": rng.normal(size=360),
        }
    )
    part = assign_windows(rows, m)
    part.loc[part["partition"] == "test", "x"] += 1000.0  # el test no debe influir
    out, scaler = fit_transform_partitions(part[["subject_id", "x"]], m, ["x"])
    train_x = part.loc[part["partition"] == "train", "x"]
    assert scaler.median_ is not None and scaler.median_[0] == pytest.approx(
        train_x.median()
    )
    assert out["test"]["x"].median() > 100  # se transforma con estadísticos de train
    with pytest.raises(DataLeakageError):
        TrainOnlyRobustScaler().fit(
            rows[["x"]], rows["subject_id"].tolist(), m.subjects("train")
        )
    again = TrainOnlyRobustScaler.from_json(scaler.to_json())
    assert again.fitted_on_subjects_digest_ == scaler.fitted_on_subjects_digest_


# ----------------------------------------------------------------- metadatos
VALID_META = {
    "schema_version": "1.1.0",
    "provenance": {
        "subject_id": "SUBJ-00042",
        "recording_id": "REC-0000123",
        "dataset_version": "0.1.0",
        "site_id": "SITE-001",
        "source_institution": "Centro-A",
        "anonymization_protocol": "HIPAA_SAFE_HARBOR_AND_GDPR_PSEUDONYMISATION",
        "custody_key_status": "destroyed_irreversible",
    },
    "acquisition": {
        "ecg_sampling_frequency_hz": 500,
        "adc_resolution_bits": 24,
        "sensor_hardware_model": "AFE-X1",
        "leads_utilized": ["II", "V5"],
        "primary_lead": "II",
        "lead_contact_impedance_kohm": 18.5,
        "mains_frequency_hz": 60,
    },
    "demographics": {
        "age_bracket": "60-69",
        "biological_sex": "female",
        "bmi_category": "overweight",
        "posture": "supine",
        "active_cardiovascular_medication": ["beta_blocker"],
        "known_arrhythmias": [],
    },
    "reference_sync": {
        "reference_device_type": "invasive_intra_arterial_line",
        "reference_device_model": "REF-1",
        "reference_measurement_uncertainty_mmhg": 3.0,
        "reference_validation_standard": "ANSI_AAMI_ISO_81060-2",
        "sync_protocol": "PTP",
        "sampling_offset_ms": 12.0,
        "max_timestamp_uncertainty_ms": 4.0,
        "clock_skew_tolerance_ppm": 5.0,
    },
    "quality_control": {
        "n_windows_total": 200,
        "n_windows_rejected": 20,
        "rejection_ratio_percentage": 10.0,
        "mean_bsqi_score": 0.93,
        "qc_review_required": False,
    },
}


def _mutated(path: list[str], value: object) -> dict:
    rec = copy.deepcopy(VALID_META)
    node = rec
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value
    return rec


def test_metadatos_validos() -> None:
    res = validate_metadata(VALID_META)
    assert res.is_valid and res.is_certifiable, res


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["acquisition", "ecg_sampling_frequency_hz"], 100),
        (["acquisition", "adc_resolution_bits"], 12),
        (["acquisition", "lead_contact_impedance_kohm"], 60),
        (["reference_sync", "sampling_offset_ms"], 50),
        (["reference_sync", "clock_skew_tolerance_ppm"], 10),
        (["reference_sync", "max_timestamp_uncertainty_ms"], 11),
        (["provenance", "subject_id"], "Juan Perez"),
        (["provenance", "recording_id"], "REC-12"),
        (["demographics", "age_bracket"], "45"),
        (["quality_control", "rejection_ratio_percentage"], 35.0),
    ],
)
def test_metadatos_invalidos(path: list[str], value: object) -> None:
    assert not validate_metadata(_mutated(path, value)).is_valid


def test_metadatos_reglas_cruzadas() -> None:
    assert validate_metadata(_mutated(["acquisition", "primary_lead"], "V5")).is_valid
    assert not validate_metadata(
        _mutated(["acquisition", "primary_lead"], "aVR")
    ).is_valid
    assert not validate_metadata(
        _mutated(["quality_control", "n_windows_rejected"], 50)
    ).is_valid
    warn = validate_metadata(
        _mutated(["reference_sync", "reference_validation_standard"], "none_documented")
    )
    assert warn.is_valid and not warn.is_certifiable
    extra = _mutated(["provenance", "patient_name"], "X")
    assert not validate_metadata(extra).is_valid  # additionalProperties: false


# --------------------------------------------------------------- visualizaciones
def test_estadisticas_y_cuotas(tmp_path) -> None:
    rng = np.random.default_rng(3)
    sbp = np.clip(rng.normal(125, 25, 1000), 71, 239)
    dbp = np.clip(rng.normal(78, 12, 1000), 41, 139)
    table = label_statistics_table(sbp, dbp)
    assert set(table.index) == {"PAS", "PAD", "PP", "PAM"}
    check = iso_distribution_check(np.full(100, 120.0), np.full(100, 80.0))
    assert not check["cumple"].any()
    ba = bland_altman_statistics(sbp, sbp + rng.normal(1, 3, sbp.size))
    assert ba["fraccion_dentro_limites"] > 0.9
    feats = pd.DataFrame(
        {"f1": sbp + rng.normal(0, 5, 1000), "f2": rng.normal(size=1000)}
    )
    assert plot_spearman_heatmap(feats, sbp, dbp, tmp_path)[0].exists()
    wins = pd.DataFrame(
        {
            "subject_id": np.repeat(["A", "B"], 50),
            "t_start_s": np.tile(np.arange(50) * 30.0, 2),
            "quality_flag": np.r_[rng.integers(0, 2, 50), np.zeros(50, dtype=int)],
        }
    )
    assert plot_rejection_timeline(wins, tmp_path)[0].exists()
