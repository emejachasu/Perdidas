"""Tests de F8: economía, optimización y ruteo de la campaña (§17)."""
import numpy as np
import pandas as pd

from lossan.config import load_config
from lossan.prioritization import (build_candidates, cluster_and_route,
                                    exploration_reserve, greedy_roi,
                                    knapsack_optimize, two_stage_allocation)


def _fixture():
    cfg = load_config()
    n = 40
    risk = pd.DataFrame({
        "customer_unit_id": [f"C{i}" for i in range(n)],
        "risk_score": np.linspace(0.95, 0.05, n),
        "recoverable_kwh_month": np.linspace(600, 40, n),
        "feeder_id": np.where(np.arange(n) % 2 == 0, "F0", "F1"),
    })
    cust = pd.DataFrame({
        "customer_unit_id": [f"C{i}" for i in range(n)],
        "transformer_site_id": [f"TS{i % 10}" for i in range(n)],
        "feeder_id": risk["feeder_id"],
        "pole_id": [f"P{i % 10}" for i in range(n)],
    })
    poles = pd.DataFrame({"pole_id": [f"P{i}" for i in range(10)],
                          "x": np.arange(10) * 100.0, "y": (np.arange(10) % 3) * 100.0})
    return cfg, risk, cust, poles


def test_cost_is_per_site_not_per_customer():
    cfg, risk, cust, poles = _fixture()
    cand = build_candidates(risk, cust, poles, cfg)
    # 10 puestos aunque hay 40 clientes: el costo es por puesto (§5.3, §17.1)
    assert len(cand) == 10
    # el beneficio del puesto es la suma sobre sus unidades
    assert (cand["n_units"] >= 1).all()
    assert {"benefit_usd", "cost_usd", "roi", "ve_neto_usd"} <= set(cand.columns)


def test_knapsack_respects_budget():
    cfg, risk, cust, poles = _fixture()
    cand = build_candidates(risk, cust, poles, cfg)
    budget = 3 * cand["cost_usd"].iloc[0]
    sel = knapsack_optimize(cand, budget_usd=budget)
    assert sel["cost_usd"].sum() <= budget + 1e-6


def test_milp_not_worse_than_greedy():
    cfg, risk, cust, poles = _fixture()
    cand = build_candidates(risk, cust, poles, cfg)
    budget = 4 * cand["cost_usd"].iloc[0]
    milp = knapsack_optimize(cand, budget_usd=budget)
    grd = greedy_roi(cand, budget_usd=budget)
    assert milp["ve_neto_usd"].clip(lower=0).sum() >= grd["ve_neto_usd"].clip(lower=0).sum() - 1e-6


def test_exploration_reserve_bounded():
    cfg, risk, cust, poles = _fixture()
    cand = build_candidates(risk, cust, poles, cfg)
    total = cand["cost_usd"].sum() * 2
    expl = exploration_reserve(cand, budget_usd=total, reserve_frac=0.1)
    assert expl["cost_usd"].sum() <= total * 0.1 + cand["cost_usd"].max()


def test_routing_assigns_crews_and_days():
    cfg, risk, cust, poles = _fixture()
    cand = build_candidates(risk, cust, poles, cfg)
    routed = cluster_and_route(cand, visits_per_crew_day=3, num_crews=2)
    assert {"cluster", "crew", "day", "visit_seq"} <= set(routed.columns)
    assert routed["crew"].nunique() >= 1
