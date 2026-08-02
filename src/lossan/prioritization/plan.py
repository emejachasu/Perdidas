"""Construcción del plan de inspección bajo presupuesto (§17.5, §17.6).

Orquesta el modelo económico, la optimización con reserva de exploración, el
clustering/ruteo y los rankings entregables (alimentadores, zonas, puestos,
unidades de cliente). Es un paso a nivel de sistema (un único presupuesto).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from ..config import Config, load_config
from ..lakehouse import Lakehouse
from .economics import build_candidates
from .optimize import (allocation_curve, exploration_reserve,
                       greedy_roi, two_stage_allocation)
from .routing import cluster_and_route


def _precision_at_k(risk: pd.DataFrame, truth_ids: set, k: int) -> float:
    top = risk.sort_values("risk_score", ascending=False).head(k)
    if len(top) == 0:
        return 0.0
    return round(float(top["customer_unit_id"].isin(truth_ids).sum()) / len(top), 4)


def build_inspection_plan(root: str, cfg: Config | None = None) -> dict:
    cfg = cfg or load_config()
    lake = Lakehouse(root)

    risk = lake.read_entity("gold", "customer_risk")
    customers = lake.read_entity("bronze", "customers")
    poles = lake.read_entity("bronze", "poles")
    balance = lake.read_entity("gold", "feeder_balance")
    zones = lake.read_entity("gold", "zone_state_estimation")
    if risk.empty or customers.empty:
        logger.warning("Sin score de riesgo; no se construye plan.")
        return {"selected": 0}

    budget = float(cfg.budget["field_usd"])
    reserve_frac = float(cfg.budget["exploration_reserve_frac"])
    directed_budget = budget * (1.0 - reserve_frac)
    campaign = cfg._budget["campaign"]
    vpc = int(campaign["visits_per_crew_day"])
    crews = int(campaign["num_crews"])

    candidates = build_candidates(risk, customers, poles, cfg)

    # optimización dirigida (dos etapas) + comparación con greedy
    selected = two_stage_allocation(candidates, directed_budget)
    greedy = greedy_roi(candidates, directed_budget)
    improvement = (selected["ve_neto_usd"].clip(lower=0).sum()
                   - greedy["ve_neto_usd"].clip(lower=0).sum())

    # reserva de exploración (aleatoria estratificada, §17.4)
    explore = exploration_reserve(candidates, budget, reserve_frac)

    # razones/checklist por puesto (razón del cliente de mayor riesgo)
    rcols = [c for c in ["reason_1", "reason_2", "reason_3"] if c in risk.columns]
    if rcols:
        top_by_site = (risk.merge(customers[["customer_unit_id", "transformer_site_id"]],
                                  on="customer_unit_id", how="left")
                       .sort_values("risk_score", ascending=False)
                       .groupby("transformer_site_id").first().reset_index())
        selected = selected.merge(
            top_by_site[["transformer_site_id"] + rcols].rename(
                columns={"transformer_site_id": "site_id"}), on="site_id", how="left")

    # clustering geográfico + ruteo -> órdenes de trabajo
    plan = cluster_and_route(selected, vpc, crews)
    plan["checklist"] = plan.apply(
        lambda r: " | ".join(str(r.get(c, "")) for c in rcols if r.get(c)), axis=1)

    # curva de asignación óptima (0 a >budget)
    curve = allocation_curve(candidates, budget)

    # --- rankings entregables (§17.6) ---
    ranking_feeders = (balance.sort_values("pnt_kwh", ascending=False)
                       [["feeder_id", "pnt_pct", "technical_pct", "pnt_kwh",
                         "total_losses_pct"]] if not balance.empty else pd.DataFrame())
    ranking_sites = candidates.sort_values("roi", ascending=False).head(500)
    ranking_units = risk.sort_values("risk_score", ascending=False).head(1000)
    ranking_zones = (zones.sort_values("unaccounted_load_kw", ascending=False)
                     if not zones.empty else pd.DataFrame())

    # Precision@k con k derivado del presupuesto (§17.2)
    theft = lake.read_entity("bronze", "theft_labels")
    prec = {}
    if not theft.empty:
        truth = set(theft.loc[theft["is_theft"], "customer_unit_id"])
        cost_visit = float(cfg.economics["cost_per_visit_usd"]["transformer_site"])
        for cpv in (20, 30, 50, 80):
            k = int(budget / cpv)
            prec[f"precision@{k}(cost={cpv})"] = _precision_at_k(risk, truth, min(k, len(risk)))

    summary = pd.DataFrame([{
        "budget_field_usd": budget,
        "directed_budget_usd": round(directed_budget, 0),
        "exploration_budget_usd": round(budget * reserve_frac, 0),
        "sites_selected": len(selected),
        "exploration_sites": len(explore),
        "visits_total": len(plan),
        "expected_benefit_usd": round(selected["benefit_usd"].sum(), 0),
        "expected_recoverable_kwh_month": round(selected["recoverable_kwh_month"].sum(), 0),
        "cost_spent_usd": round(selected["cost_usd"].sum(), 0),
        "roi_campaign": round(selected["benefit_usd"].sum() /
                              max(1.0, selected["cost_usd"].sum()), 2),
        "milp_vs_greedy_improvement_usd": round(float(improvement), 0),
        "crews": crews, "visits_per_crew_day": vpc,
        **prec,
    }])

    # persistir en GOLD
    def _write(name, df):
        if df is None or df.empty:
            return
        path = lake.root / "gold" / name
        path.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path / "data.parquet", index=False)

    _write("inspection_plan", plan)
    _write("exploration_plan", explore)
    _write("campaign_summary", summary)
    _write("allocation_curve", curve)
    _write("ranking_feeders", ranking_feeders)
    _write("ranking_sites", ranking_sites)
    _write("ranking_customer_units", ranking_units)
    _write("ranking_zones", ranking_zones)

    return {"selected": len(selected), "visits": len(plan),
            "exploration": len(explore),
            "expected_benefit_usd": float(summary["expected_benefit_usd"].iloc[0])}
