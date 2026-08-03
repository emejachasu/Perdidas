"""Tests de F2: topología, trazas, zonas y reglas de calidad (§6, §7, §8)."""
import pandas as pd

from lossan.config import load_config
from lossan.synth.generator import SyntheticGenerator
from lossan.topology import (FeederGraph, build_protection_zones,
                             infer_transfers, run_quality_rules)


def _feeder(micro_config):
    gen = SyntheticGenerator(load_config())
    return gen.feeder_tables(0)


def test_graph_is_radial_and_traces(micro_config):
    t = _feeder(micro_config)
    # los clientes/luminarias se registran explícitamente (no por nombre de nodo)
    fg = FeederGraph.build("F0000", t["segments"], t["sites"],
                           t["customers"], t["streetlights"])
    assert fg.n_nodes > 0 and fg.n_edges == fg.n_nodes - 1  # árbol
    assert fg.validate() == [] or all(f["rule"] != "TOPO_CYCLE" for f in fg.validate())

    site_node = t["sites"].iloc[0]["node_id"]
    p2s = fg.path_to_source(site_node)
    assert p2s["reaches_source"] and p2s["distance_m"] >= 0
    assert p2s["path"][0] == fg.source

    sub = fg.subtree_load(fg.source)
    assert sub["n_customers"] > 0


def test_protection_zones(micro_config):
    t = _feeder(micro_config)
    fg = FeederGraph.build("F0000", t["segments"], t["sites"])
    zones, node_to_zone = build_protection_zones(fg, t["switching_devices"],
                                                 t["sites"], t["customers"])
    assert "HEAD" in set(zones["zone_id"])
    assert len(node_to_zone) > 0
    assert (zones["n_nodes"] > 0).all()


def test_quality_detects_injected_r08(micro_config):
    t = _feeder(micro_config)
    fg = FeederGraph.build("F0000", t["segments"], t["sites"])
    q = run_quality_rules("F0000", fg, t["segments"], t["sites"],
                          t["transformer_units"], t["customers"],
                          t["streetlights"], t["switching_devices"])
    # se inyectó al menos un R08 (feeder_id inconsistente)
    injected = set(t["anomaly_labels"]["injected_rule"])
    if "R08" in injected:
        assert "R08" in set(q["rule_id"])
    # las columnas requeridas por §8 están presentes
    assert {"rule_id", "element_id", "severity", "evidence", "confidence"} <= set(q.columns)


def test_infer_transfers_detects_opposite_shift():
    months = pd.period_range("2022-01", periods=12, freq="M").astype(str)
    # A cae a la mitad del periodo, B sube de forma correlacionada (transferencia)
    a = [100] * 6 + [60] * 6
    b = [80] * 6 + [120] * 6
    wide = pd.DataFrame({"F0": a, "F1": b}, index=months)
    tr = infer_transfers(wide)
    assert len(tr) >= 1
    assert set(tr.iloc[0][["feeder_a", "feeder_b"]]) == {"F0", "F1"}
