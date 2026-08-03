"""Modelo económico de la priorización (§17.1).

La unidad de costo es el PUESTO/POSTE, no el cliente individual (§5.3, §5.4):
una visita a un puesto con N medidores cuesta prácticamente lo mismo que a uno
con 1, pero el beneficio es la suma sobre sus unidades. Esta asimetría cambia
qué se selecciona, no sólo el orden.

    Beneficio = Σ_unidad P(hallazgo|calibrada)·E_recuperable·meses·tarifa
    Costo     = costo_visita_por_puesto + costo_normalización
    VE_neto   = Beneficio − Costo ;  ROI = Beneficio / Costo
"""
from __future__ import annotations

import pandas as pd

from ..config import Config, load_config


def build_candidates(customer_risk: pd.DataFrame, customers: pd.DataFrame,
                     poles: pd.DataFrame | None = None,
                     cfg: Config | None = None,
                     reliability_map: dict[str, float] | None = None) -> pd.DataFrame:
    """Agrega el riesgo de clientes al nivel de puesto de transformación (unidad
    de visita) y calcula beneficio, costo, ROI y valor esperado neto.

    Si se da ``reliability_map`` (feeder→índice 0-100), penaliza el beneficio de
    los alimentadores poco confiables (§8.3/§16): donde el problema es de datos
    y no de hurto, se invierte menos presupuesto de campo.
    """
    cfg = cfg or load_config()
    econ = cfg.economics
    tariff = float(econ["tariff_usd_per_kwh"])
    months = float(econ["recovery_months"])
    cost_visit = float(econ["cost_per_visit_usd"]["transformer_site"])
    cost_norm = float(econ["cost_normalization_usd"]["transformer_site"])

    df = customer_risk.merge(
        customers[["customer_unit_id", "transformer_site_id", "feeder_id", "pole_id"]],
        on="customer_unit_id", how="left", suffixes=("", "_c"))
    df["recoverable_kwh_month"] = df.get("recoverable_kwh_month", 0.0).fillna(0.0)
    # beneficio por unidad = prob calibrada · energía · meses · tarifa
    df["unit_benefit_usd"] = (df["risk_score"].clip(0, 1) *
                              df["recoverable_kwh_month"] * months * tariff)

    grp = df.groupby("transformer_site_id")
    cand = grp.agg(
        feeder_id=("feeder_id", "first"),
        n_units=("customer_unit_id", "count"),
        benefit_usd=("unit_benefit_usd", "sum"),
        mean_risk=("risk_score", "mean"),
        max_risk=("risk_score", "max"),
        recoverable_kwh_month=("recoverable_kwh_month", "sum"),
    ).reset_index().rename(columns={"transformer_site_id": "site_id"})

    # penalización por confiabilidad del modelo (§8.3): factor 0,5-1,0
    if reliability_map:
        rel = cand["feeder_id"].map(reliability_map).fillna(100.0)
        cand["reliability_index"] = rel
        cand["benefit_usd"] = cand["benefit_usd"] * (0.5 + 0.5 * rel / 100.0)

    cand["cost_usd"] = cost_visit + cost_norm
    cand["ve_neto_usd"] = cand["benefit_usd"] - cand["cost_usd"]
    cand["roi"] = cand["benefit_usd"] / cand["cost_usd"]

    # geometría representativa (para clustering y ruteo)
    if poles is not None and not poles.empty:
        rep = df.dropna(subset=["pole_id"]).groupby("transformer_site_id")["pole_id"].first()
        xy = poles.set_index("pole_id")[["x", "y"]]
        cand = cand.merge(rep.rename("pole_id"), left_on="site_id", right_index=True, how="left")
        cand = cand.merge(xy, left_on="pole_id", right_index=True, how="left")
    cand["x"] = cand.get("x", 0.0)
    cand["y"] = cand.get("y", 0.0)
    return cand.sort_values("roi", ascending=False).reset_index(drop=True)
