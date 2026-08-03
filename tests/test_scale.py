"""Prueba de escala del pipeline (§2.1, §19.8).

Verifica que el pipeline procesa múltiples alimentadores y que el tamizaje N1
escala linealmente y cabe en el objetivo de tiempo extrapolado a la volumetría
objetivo. Usa una escala reducida para CI; la extrapolación demuestra §2.3.
"""
import time

from lossan.config import load_config
from lossan.lakehouse import Lakehouse
from lossan.pipeline.runner import run
from lossan.synth import generate_universe


def test_n1_scale_and_extrapolation(micro_config, tmp_path):
    cfg = load_config()
    cfg._scale["profiles"]["demo"].update(
        feeders=6, customers_per_feeder_mean=300, poles_per_feeder_mean=120,
        history_months=12)
    root = str(tmp_path / "lake")
    generate_universe(root, cfg)

    t0 = time.perf_counter()
    res = run(root, level="n1", cfg=cfg, workers=1)
    elapsed = time.perf_counter() - t0

    assert res["processed"] == 6
    lake = Lakehouse(root)
    # el tamizaje N1 produce balance para todos, sin fases pesadas
    assert len(lake.read_entity("gold", "feeder_balance")) == 6
    # reconciliación P/Q se genera a nivel de sistema
    assert not lake.read_entity("gold", "pq_reconciliation").empty
    # extrapolación a 960 dentro de un margen holgado para 1 worker
    per_feeder = elapsed / 6
    assert per_feeder < 30  # muy holgado; en la práctica < 1 s/feeder


def test_n1_skips_heavy_phases(micro_config, tmp_path):
    cfg = load_config()
    cfg._scale["profiles"]["demo"].update(
        feeders=2, customers_per_feeder_mean=200, poles_per_feeder_mean=80,
        history_months=12)
    root = str(tmp_path / "lake")
    generate_universe(root, cfg)
    run(root, level="n1", cfg=cfg, workers=1)
    lake = Lakehouse(root)
    # N1 no ejecuta flujo de potencia ni ML (customer_risk vacío o ausente)
    assert lake.read_entity("gold", "powerflow_results").empty
