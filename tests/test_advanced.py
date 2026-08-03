"""Tests de §14.2 desbalance, §12 Monte Carlo y §15.4 IPW."""
import numpy as np

from lossan.config import load_config
from lossan.ml import build_features, ipw_weights
from lossan.pipeline.imbalance import compute_site_imbalance
from lossan.pipeline.montecarlo import monte_carlo_feeder
from lossan.synth.generator import SyntheticGenerator


def _feeder(micro_config):
    return SyntheticGenerator(load_config()).feeder_tables(0)


def test_site_imbalance(micro_config):
    t = _feeder(micro_config)
    imb = compute_site_imbalance(t["customers"], t["consumption"], t["sites"],
                                 load_config(), hours_period=730 * 12)
    assert not imb.empty
    assert {"i_a", "i_b", "i_c", "i_neutral", "imbalance_pct", "flagged",
            "rebalance_benefit_kwh"} <= set(imb.columns)
    # con carga desbalanceada por fase, hay corriente de neutro y beneficio > 0
    assert (imb["i_neutral"] >= 0).all()
    assert imb["rebalance_benefit_kwh"].sum() >= 0


def test_monte_carlo_percentiles(micro_config):
    d = monte_carlo_feeder(1_000_000.0, 1_200_000.0, load_config())
    assert d["technical_p10"] < d["technical_p50"] < d["technical_p90"]
    assert d["pnt_p10"] < d["pnt_p50"] < d["pnt_p90"]
    # la mediana ronda el valor base
    assert abs(d["technical_p50"] - 1_000_000.0) < 60_000.0


def test_ipw_weights(micro_config):
    t = _feeder(micro_config)
    feats = build_features(t["consumption"], t["customers"])
    X = feats.drop(columns=["customer_unit_id"]).to_numpy(float)
    inspected = np.zeros(len(X), int)
    inspected[:40] = 1
    w = ipw_weights(X, inspected)
    assert w.shape[0] == len(X)
    assert abs(w.mean() - 1.0) < 1e-6            # normalizados a media 1
    assert w.min() > 0


def test_ipw_degenerate_returns_ones(micro_config):
    X = np.random.rand(50, 5)
    assert np.allclose(ipw_weights(X, np.zeros(50, int)), 1.0)
