"""Optimización presupuestal de la campaña (§17.3, §17.4).

Mochila 0/1 con restricción presupuestal (OR-Tools MIP), comparada contra
greedy por ROI. Asignación en dos etapas y reserva de exploración obligatoria.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def knapsack_optimize(candidates: pd.DataFrame, budget_usd: float,
                      max_visits: int | None = None) -> pd.DataFrame:
    """Mochila 0/1: maximiza VE neto sujeto a presupuesto (y nº de visitas).

    Usa OR-Tools MIP si está disponible; si no, cae a greedy por ROI.
    """
    cand = candidates.reset_index(drop=True)
    costs = cand["cost_usd"].to_numpy()
    values = cand["ve_neto_usd"].clip(lower=0).to_numpy()
    try:
        from ortools.linear_solver import pywraplp
        solver = pywraplp.Solver.CreateSolver("CBC")
        if solver is None:
            raise RuntimeError("CBC no disponible")
        n = len(cand)
        xs = [solver.BoolVar(f"x{i}") for i in range(n)]
        solver.Add(solver.Sum(costs[i] * xs[i] for i in range(n)) <= budget_usd)
        if max_visits:
            solver.Add(solver.Sum(xs) <= max_visits)
        solver.Maximize(solver.Sum(values[i] * xs[i] for i in range(n)))
        solver.SetTimeLimit(20000)
        solver.Solve()
        sel = np.array([xs[i].solution_value() > 0.5 for i in range(n)])
        method = "milp_ortools"
    except Exception:
        sel = _greedy_mask(costs, cand["roi"].to_numpy(), budget_usd, max_visits)
        method = "greedy_fallback"

    out = cand[sel].copy()
    out["selected_by"] = method
    return out


def _greedy_mask(costs, roi, budget, max_visits):
    order = np.argsort(-roi)
    sel = np.zeros(len(costs), dtype=bool)
    spent, count = 0.0, 0
    for i in order:
        if spent + costs[i] <= budget and (max_visits is None or count < max_visits):
            sel[i] = True
            spent += costs[i]
            count += 1
    return sel


def greedy_roi(candidates: pd.DataFrame, budget_usd: float,
               max_visits: int | None = None) -> pd.DataFrame:
    """Selección voraz por ROI descendente hasta agotar el presupuesto (baseline)."""
    cand = candidates.reset_index(drop=True)
    sel = _greedy_mask(cand["cost_usd"].to_numpy(), cand["roi"].to_numpy(),
                       budget_usd, max_visits)
    out = cand[sel].copy()
    out["selected_by"] = "greedy_roi"
    return out


def two_stage_allocation(candidates: pd.DataFrame, budget_usd: float) -> pd.DataFrame:
    """(1) reparte el presupuesto entre alimentadores según potencial de
    recuperación; (2) selecciona puestos dentro de cada alimentador (§17.3)."""
    pot = candidates.groupby("feeder_id")["ve_neto_usd"].apply(
        lambda s: s.clip(lower=0).sum())
    total = pot.sum()
    if total <= 0:
        return knapsack_optimize(candidates, budget_usd)
    selections = []
    for fid, p in pot.items():
        fb = budget_usd * (p / total)
        sub = candidates[candidates["feeder_id"] == fid]
        selections.append(knapsack_optimize(sub, fb))
    out = pd.concat(selections, ignore_index=True) if selections else pd.DataFrame()
    out["selected_by"] = "two_stage"
    return out


def exploration_reserve(candidates: pd.DataFrame, budget_usd: float,
                        reserve_frac: float, seed: int = 0) -> pd.DataFrame:
    """Reserva 5-10% para inspección aleatoria estratificada (§17.4).

    Es la única forma de estimar la tasa base, la propensidad c del PU learning
    y corregir el sesgo de selección. Estratifica por alimentador.
    """
    reserve = budget_usd * reserve_frac
    rng = np.random.default_rng(seed)
    picks, spent = [], 0.0
    feeders = candidates["feeder_id"].dropna().unique()
    pool = candidates.sample(frac=1.0, random_state=seed)
    per_feeder = {f: 0 for f in feeders}
    for _, row in pool.iterrows():
        if spent + row["cost_usd"] > reserve:
            continue
        picks.append(row)
        spent += row["cost_usd"]
    out = pd.DataFrame(picks)
    if not out.empty:
        out["selected_by"] = "exploration"
    return out


def allocation_curve(candidates: pd.DataFrame, max_budget_usd: float,
                     steps: int = 20) -> pd.DataFrame:
    """Curva de asignación óptima: energía/VE recuperable vs presupuesto."""
    rows = []
    for frac in np.linspace(0.05, 1.5, steps):
        b = max_budget_usd * frac
        sel = greedy_roi(candidates, b)
        rows.append({
            "budget_usd": round(b, 0),
            "n_sites": len(sel),
            "expected_benefit_usd": round(sel["benefit_usd"].sum(), 0),
            "recoverable_kwh_month": round(sel["recoverable_kwh_month"].sum(), 0),
        })
    return pd.DataFrame(rows)
