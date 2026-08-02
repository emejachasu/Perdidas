"""Tests de F6: estimación de estado y reconciliación (§14.3)."""
import numpy as np
import pandas as pd

from lossan.stateest import pseudo_measurements, reconcile_by_zone, run_wls


def test_wls_localizes_unaccounted_load():
    # 6 puestos de 100 kW; el último es muy variable (sigma alta).
    # La cabecera mide 700 kW => 100 kW no contabilizados deben cargarse al
    # puesto de mayor incertidumbre (reconciliación proporcional, no uniforme).
    stats = pd.DataFrame({
        "site_id": [f"S{i}" for i in range(6)],
        "mean_kw": [100.0] * 6,
        "std_kw": [5, 5, 5, 5, 5, 50],
    })
    ids, z, sigma = pseudo_measurements(stats)
    res = run_wls(z, sigma, measured_total=700.0)
    assert ids[res.lnr_index] == "S5"
    assert res.correction[-1] > res.correction[:-1].max() * 5   # concentrada en S5
    assert res.correction[-1] > 50.0


def test_reconcile_by_zone_shares():
    stats = pd.DataFrame({"site_id": [f"S{i}" for i in range(4)],
                          "mean_kw": [100.0] * 4, "std_kw": [5, 5, 5, 40]})
    ids, z, sigma = pseudo_measurements(stats)
    res = run_wls(z, sigma, measured_total=500.0)
    s2z = {"S0": "Z1", "S1": "Z1", "S2": "Z2", "S3": "Z2"}
    zse = reconcile_by_zone(ids, res.correction, res.normalized_residuals, s2z, "F0")
    top = zse.iloc[0]
    assert top["zone_id"] == "Z2"          # la zona con el puesto incierto
    assert top["share_of_unaccounted"] > 0.5


def test_uniform_uncertainty_spreads_load():
    # con incertidumbre uniforme, la carga no contabilizada se reparte parejo
    stats = pd.DataFrame({"site_id": [f"S{i}" for i in range(4)],
                          "mean_kw": [100.0] * 4, "std_kw": [10, 10, 10, 10]})
    ids, z, sigma = pseudo_measurements(stats)
    res = run_wls(z, sigma, measured_total=440.0)
    assert np.allclose(res.correction, res.correction[0], rtol=1e-3)
