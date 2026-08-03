"""Tests del informe de reconciliación de P y Q (§9.3)."""
from lossan.config import load_config
from lossan.pipeline.reconciliation import reconcile_feeder
from lossan.synth.generator import SyntheticGenerator


def _feeder(micro_config):
    return SyntheticGenerator(load_config()).feeder_tables(0)


def test_reconciliation_causes(micro_config):
    t = _feeder(micro_config)
    summ, causes = reconcile_feeder(t["consumption"], t["customers"], "F0000", load_config())
    assert not summ.empty
    row = summ.iloc[0]
    # sumar picos sin coincidencia sobreestima la demanda
    assert row["P_naive_sumpeaks_kw"] > row["P_corr_kw"]
    assert row["dP_coincidence_pct"] > 0
    # omitir √3 en 3φ sobreestima la corriente
    assert row["I_naive_no_sqrt3_a"] > row["I_corr_a"]
    # las 4 causas están presentes
    assert set(causes["cause"]) == {
        "coincidencia (sumar picos)", "energia_vs_demanda (usar media)",
        "cosphi_sobre_energia", "factor_sqrt3 (omitido)"}


def test_reconciliation_sqrt3_factor(micro_config):
    t = _feeder(micro_config)
    summ, _ = reconcile_feeder(t["consumption"], t["customers"], "F0000", load_config())
    # el error √3 ronda +73% (1/√3 -> √3)
    assert 60 < summ.iloc[0]["dI_sqrt3_pct"] < 80
