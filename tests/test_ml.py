"""Tests de F7: minería de etiquetas, PU learning y riesgo (§15, §22.8-9)."""
import warnings

import numpy as np

from lossan.config import load_config
from lossan.ml import (build_features, mine_labels, precision_at_k,
                       train_risk_model, validate_against_confirmed)
from lossan.ml.pu import PU_METHODS, fit_pu
from lossan.synth.generator import SyntheticGenerator

warnings.filterwarnings("ignore")


def _feeder(profile_overrides=None):
    cfg = load_config()
    cfg._scale["active_profile"] = "demo"
    base = dict(feeders=1, customers_per_feeder_mean=500, poles_per_feeder_mean=200,
                history_months=24, theft_rate=0.12, seed=7)
    if profile_overrides:
        base.update(profile_overrides)
    cfg._scale["profiles"]["demo"] = base
    gen = SyntheticGenerator(cfg)
    return gen.feeder_tables(0), cfg


def test_label_mining_recovers_confirmed(micro_config):
    t, cfg = _feeder()
    mined = mine_labels(t["consumption"], t["customers"], cfg)
    val = validate_against_confirmed(mined, t["theft_labels"])
    # criterio §22.8: los mecanismos deben recuperar buena parte de los confirmados
    assert val["confirmed"] > 0
    assert val["recall_all"] >= 0.5


def test_features_no_leakage_cutoff(micro_config):
    t, _ = _feeder()
    cutoff = sorted(t["consumption"]["year_month"].unique())[12]
    f_full = build_features(t["consumption"], t["customers"])
    f_cut = build_features(t["consumption"], t["customers"], cutoff=cutoff)
    # el corte no debe usar meses posteriores: medias distintas
    assert not np.allclose(f_full["mean_6"].to_numpy(), f_cut["mean_6"].to_numpy())


def test_pu_methods_run(micro_config):
    t, _ = _feeder()
    feats = build_features(t["consumption"], t["customers"])
    ids = feats["customer_unit_id"].to_numpy()
    X = feats.drop(columns=["customer_unit_id"]).to_numpy(dtype=float)
    pos = set(t["theft_labels"].loc[t["theft_labels"]["is_theft"], "customer_unit_id"])
    s = np.array([1 if i in pos else 0 for i in ids])
    for m in PU_METHODS:
        scores, info = fit_pu(X, s, method=m)
        assert scores.shape[0] == len(ids)
        assert (0 <= scores).all() and (scores <= 1).all()


def test_precision_at_k_head_of_ranking(micro_config):
    t, cfg = _feeder()
    scores, info = train_risk_model(t["consumption"], t["customers"],
                                    t["theft_labels"], method="elkan_noto", cfg=cfg)
    truth = set(t["theft_labels"].loc[t["theft_labels"]["is_theft"], "customer_unit_id"])
    # precisión en la cabeza del ranking (lo único que importa, §17.2)
    assert precision_at_k(scores, truth, 20) >= 0.5
    assert {"reason_1", "reason_2", "reason_3"} <= set(scores.columns)
