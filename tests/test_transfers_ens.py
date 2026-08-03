"""Tests de ENS y acreditación de transferencias (§7.3/§7.4/§7.6)."""
import pandas as pd

from lossan.topology import (estimate_ens_kwh, infer_transfers,
                             quantify_transfers)


def test_estimate_ens():
    events = pd.DataFrame({
        "motivo": ["falla", "falla", "maniobra"],
        "duration_h": [2.0, 3.0, 5.0],
        "affected_kw": [10.0, 20.0, 100.0],
    })
    # solo cuentan las fallas: 2*10 + 3*20 = 80 (la maniobra no)
    assert estimate_ens_kwh(events) == 80.0


def test_estimate_ens_empty():
    assert estimate_ens_kwh(pd.DataFrame()) == 0.0


def test_quantify_transfers_signs():
    months = pd.period_range("2022-01", periods=12, freq="M").astype(str)
    # F0 cae (pierde carga) -> crédito positivo; F1 sube (gana) -> negativo
    wide = pd.DataFrame({"F0": [100] * 6 + [60] * 6,
                         "F1": [80] * 6 + [120] * 6}, index=months)
    tr = infer_transfers(wide)
    q = quantify_transfers(wide, tr).set_index("feeder_id")["transferred_kwh"]
    assert q["F0"] > 0 and q["F1"] < 0
    # el crédito es de signo opuesto y magnitud similar
    assert abs(q["F0"] + q["F1"]) < 1.0


def test_quantify_no_transfers():
    months = pd.period_range("2022-01", periods=12, freq="M").astype(str)
    wide = pd.DataFrame({"F0": [100] * 12, "F1": [80] * 12}, index=months)
    tr = infer_transfers(wide)
    assert quantify_transfers(wide, tr).empty
