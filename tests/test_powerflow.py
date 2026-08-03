"""Tests de F4: flujo de potencia propio y validación cruzada (§11)."""
import time

from lossan.powerflow.sweep import RadialNetwork, solve_bfs
from lossan.powerflow.validate import (canonical_radial_case, compare_engines,
                                        power_balance_error)


def test_sweep_converges_canonical():
    net = canonical_radial_case()
    res = solve_bfs(net)
    assert res.converged
    assert res.total_loss_kw > 0
    assert 0.9 < res.v_min_pu <= 1.0


def test_power_conservation():
    net = canonical_radial_case()
    assert power_balance_error(net) < 1e-4


def test_single_phase_no_sqrt3():
    # red monofásica: sin √3
    net = RadialNetwork(nodes=["S", "B"], branches=[(0, 1, complex(1.0, 0.0))],
                        loads_kva=[complex(0, 0), complex(10.0, 0.0)],
                        v_base_ln=240.0, three_phase=False)
    res = solve_bfs(net)
    assert res.converged and res.total_loss_kw > 0


def test_compare_with_opendss_within_tolerance():
    net = canonical_radial_case()
    cmp = compare_engines(net)
    if cmp["opendss_available"]:
        assert cmp["within_loss_tol"], f"diferencia {cmp['loss_diff_pct']}% > tolerancia"


def test_sweep_performance():
    # cadena radial de 200 nodos debe resolver muy rápido (< 100 ms objetivo §11)
    n = 200
    nodes = [f"N{i}" for i in range(n)]
    branches = [(i, i + 1, complex(0.05, 0.02)) for i in range(n - 1)]
    loads = [complex(0, 0)] + [complex(5.0, 2.0) for _ in range(n - 1)]
    net = RadialNetwork(nodes=nodes, branches=branches, loads_kva=loads, v_base_ln=7200.0)
    t0 = time.perf_counter()
    res = solve_bfs(net)
    assert res.converged
    assert (time.perf_counter() - t0) < 0.5   # holgado para CI


def test_3ph_converges_and_neutral():
    from lossan.powerflow.validate import canonical_unbalanced_3ph_case
    from lossan.powerflow.sweep3ph import solve_bfs_3ph
    net = canonical_unbalanced_3ph_case()
    res = solve_bfs_3ph(net)
    assert res.converged and res.total_loss_kw > 0
    # carga desbalanceada -> corriente de neutro no despreciable en cabecera
    assert res.neutral_currents[0] > 1.0
    assert res.max_unbalance_pct > 0


def test_3ph_matches_opendss():
    from lossan.powerflow.validate import (canonical_unbalanced_3ph_case,
                                           compare_engines_3ph)
    cmp = compare_engines_3ph(canonical_unbalanced_3ph_case())
    if cmp["opendss_available"]:
        assert cmp["within_loss_tol"], f"3φ dif {cmp['loss_diff_pct']}% > tol"


def test_zmatrix_from_sequence_symmetry():
    import numpy as np
    from lossan.powerflow.sweep3ph import zmatrix_from_sequence
    Z = zmatrix_from_sequence(complex(0.3, 0.6), complex(0.7, 1.8), 1.0)
    assert np.allclose(Z, Z.T)                      # simétrica
    assert abs(Z[0, 0]) > abs(Z[0, 1])              # propia > mutua


def test_ieee13_backbone_matches_opendss():
    from lossan.powerflow.ieee import build_ieee13_backbone
    from lossan.powerflow.validate import compare_engines_3ph
    cmp = compare_engines_3ph(build_ieee13_backbone())
    if cmp["opendss_available"]:
        # motor propio reproduce las matrices de configuración IEEE-13 vs OpenDSS
        assert cmp["within_loss_tol"], f"IEEE-13 dif {cmp['loss_diff_pct']}%"
        assert cmp["own_neutral_head_a"] > 0    # cargas desbalanceadas -> neutro
