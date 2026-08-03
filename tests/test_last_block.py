"""Tests: efemérides+anomalías AP (§10), confiabilidad (§8.3), curvas (§9.4), IEEE caps."""
import pandas as pd

from lossan.config import load_config
from lossan.ml import cluster_load_profiles
from lossan.pipeline.reliability import reliability_index
from lossan.pipeline.streetlight import (annual_hours_on, compute_hours_on,
                                         detect_ap_anomalies)
from lossan.synth.generator import SyntheticGenerator


def _feeder(micro_config):
    return SyntheticGenerator(load_config()).feeder_tables(0)


def test_ephemeris_hours_vary_by_season():
    # en el hemisferio norte, la noche de junio es más corta que la de diciembre
    jun = compute_hours_on(45.0, 6)
    dec = compute_hours_on(45.0, 12)
    assert dec > jun
    assert 8.0 < jun < 16.0 and 8.0 < dec < 16.0


def test_annual_hours_default_vs_ephemeris(micro_config):
    cfg = load_config()
    cfg._streetlight["streetlight"]["use_ephemeris"] = False
    assert annual_hours_on(0.0, cfg) == cfg.streetlight["hours_on_default"]
    cfg._streetlight["streetlight"]["use_ephemeris"] = True
    assert 9.0 < annual_hours_on(0.0, cfg) < 14.0


def test_ap_anomalies(micro_config):
    t = _feeder(micro_config)
    ap = detect_ap_anomalies(t["streetlights"], "F0000", load_config())
    assert {"anomaly", "severity", "evidence"} <= set(ap.columns)
    # el generador inyecta discordancia de tecnología y day-burning
    assert ap["anomaly"].isin(["tech_mismatch", "day_burning",
                               "no_transformer_site"]).all()


def test_reliability_index_monotonic():
    few = reliability_index(pd.DataFrame({"severity": ["media"]}), 500, 0.1)
    many = reliability_index(pd.DataFrame({"severity": ["critica"] * 40}), 50, 3.0)
    assert few["reliability_index"] > many["reliability_index"]
    assert 0 <= many["reliability_index"] <= 100


def test_load_curve_clustering(micro_config):
    t = _feeder(micro_config)
    assign, cent = cluster_load_profiles(t["consumption"], t["customers"], n_clusters=4)
    assert (assign["cluster"] >= 0).sum() > 0
    assert cent.shape[0] >= 1 and "cluster" in cent.columns


def test_ieee13_with_capacitors():
    from lossan.powerflow.ieee import (build_ieee13_backbone,
                                       build_ieee13_with_capacitors)
    from lossan.powerflow.validate import compare_engines_3ph
    base = compare_engines_3ph(build_ieee13_backbone())
    caps = compare_engines_3ph(build_ieee13_with_capacitors())
    if caps["opendss_available"]:
        assert caps["within_loss_tol"]
        # los capacitores reducen las pérdidas
        assert caps["own_total_loss_kw"] < base["own_total_loss_kw"]
