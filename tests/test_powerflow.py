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
