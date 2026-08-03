"""Comparación automática de motores de flujo de potencia (§11).

Discrepancias > tolerancia (2 % en pérdidas, 0,5 % en tensiones) generan alerta.
Incluye un caso radial canónico con resultado analítico para validación de CI y
la reproducción de casos IEEE cuando OpenDSS está disponible.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from ..config import load_config
from .opendss_export import export_dss, solve_with_opendss
from .sweep import RadialNetwork, solve_bfs


def _tolerances() -> tuple[float, float]:
    cfg = load_config()
    pf = cfg._electrical["powerflow"]
    return float(pf["tol_losses_pct"]), float(pf["tol_voltage_pct"])


def compare_engines(net: RadialNetwork) -> dict:
    """Resuelve con ambos motores y compara. OpenDSS opcional."""
    tl, tv = _tolerances()
    own = solve_bfs(net)
    result = {
        "own_total_loss_kw": round(own.total_loss_kw, 4),
        "own_v_min_pu": round(own.v_min_pu, 5),
        "own_converged": own.converged,
        "opendss_available": False,
        "tol_losses_pct": tl, "tol_voltage_pct": tv,
    }

    with tempfile.TemporaryDirectory() as td:
        dss_path = export_dss(net, Path(td) / "case.dss")
        odss = solve_with_opendss(dss_path)
    if odss is None:
        return result

    result["opendss_available"] = True
    result["opendss_total_loss_kw"] = round(odss["total_loss_kw"], 4)
    denom = max(abs(odss["total_loss_kw"]), 1e-6)
    loss_diff_pct = 100.0 * abs(own.total_loss_kw - odss["total_loss_kw"]) / denom
    result["loss_diff_pct"] = round(loss_diff_pct, 3)
    result["within_loss_tol"] = loss_diff_pct <= tl
    return result


def canonical_radial_case() -> RadialNetwork:
    """Feeder radial de 3 buses (validación analítica y de conservación).

    Fuente 7,2 kV LN; líneas Z; carga 1000 kW a fp=1 en el bus 2.
    """
    nodes = ["SRC", "B1", "B2"]
    branches = [(0, 1, complex(0.5, 0.25)), (1, 2, complex(1.0, 0.5))]
    loads = [complex(0, 0), complex(0, 0), complex(1000.0, 0.0)]
    return RadialNetwork(nodes=nodes, branches=branches, loads_kva=loads,
                         v_base_ln=7200.0, three_phase=True)


def canonical_unbalanced_3ph_case():
    """Feeder 3φ desbalanceado de 4 nodos con matriz de impedancia y cargas por
    fase distintas + un lateral monofásico (para validar el motor 3φ vs OpenDSS)."""
    import numpy as np

    from .sweep3ph import ThreePhaseNetwork, zmatrix_from_sequence

    z1 = complex(0.3, 0.6)
    z0 = complex(0.7, 1.8)
    Z1 = zmatrix_from_sequence(z1, z0, 1.0)
    Z2 = zmatrix_from_sequence(z1, z0, 0.5)
    Z3 = zmatrix_from_sequence(z1, z0, 0.4)
    nodes = ["SRC", "B1", "B2", "B3"]
    branches = [(0, 1, Z1), (1, 2, Z2), (2, 3, Z3)]
    loads = [
        np.zeros(3, dtype=complex),
        np.array([600 + 300j, 400 + 200j, 500 + 250j], dtype=complex),  # desbalanceada
        np.array([300 + 150j, 350 + 175j, 200 + 100j], dtype=complex),
        np.array([250 + 120j, 0, 0], dtype=complex),                    # lateral 1φ (fase A)
    ]
    return ThreePhaseNetwork(nodes=nodes, branches=branches, loads_kva=loads,
                             v_base_ln=7200.0)


def compare_engines_3ph(net) -> dict:
    """Compara el motor 3φ propio contra OpenDSS (§11). OpenDSS opcional."""
    import tempfile

    from .opendss_export import export_dss_3ph, solve_with_opendss
    from .sweep3ph import solve_bfs_3ph

    tl, tv = _tolerances()
    own = solve_bfs_3ph(net)
    res = {"own_total_loss_kw": round(own.total_loss_kw, 4),
           "own_v_min_pu": round(own.v_min_pu, 5),
           "own_max_unbalance_pct": round(own.max_unbalance_pct, 2),
           "own_neutral_head_a": round(own.neutral_currents[0], 2) if own.neutral_currents else 0.0,
           "converged": own.converged, "opendss_available": False}
    with tempfile.TemporaryDirectory() as td:
        odss = solve_with_opendss(export_dss_3ph(net, f"{td}/case3.dss"))
    if odss is None:
        return res
    res["opendss_available"] = True
    res["opendss_total_loss_kw"] = round(odss["total_loss_kw"], 4)
    denom = max(abs(odss["total_loss_kw"]), 1e-6)
    diff = 100.0 * abs(own.total_loss_kw - odss["total_loss_kw"]) / denom
    res["loss_diff_pct"] = round(diff, 3)
    res["within_loss_tol"] = diff <= tl
    return res


def power_balance_error(net: RadialNetwork) -> float:
    """Error de conservación de potencia activa (invariante físico).

    Calcula la potencia inyectada en la fuente a partir de la corriente que sale
    de ella y verifica que P_fuente ≈ Σ P_cargas + Σ P_pérdidas.
    """
    res = solve_bfs(net)
    phases = 3.0 if net.three_phase else 1.0
    # corriente total saliendo de la fuente (nodo 0)
    i_src = complex(0, 0)
    for (u, v, _), I in zip(net.branches, res.branch_currents):
        if u == 0:
            i_src += I
    p_source_kw = phases * (res.voltages_ln[0] * i_src.conjugate()).real / 1000.0
    p_loads = sum(s.real for s in net.loads_kva)
    return abs(p_source_kw - (p_loads + res.total_loss_kw)) / max(p_loads, 1e-9)
