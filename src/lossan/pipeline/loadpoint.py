"""Agregación eléctrica por PUNTO DE CARGA (§5.3, modelo CNEL).

En CNEL un ``PuntoCarga`` (edificio, predio) agrupa N ``CONEXIONCONSUMIDOR``
(medidores). Esa distinción cambia el cálculo, no es contable:

1. **Coincidencia**: el factor de coincidencia se aplica sobre la demanda del
   PUNTO DE CARGA, no sumando los picos de cada medidor. Las cargas de un mismo
   edificio ya están diversificadas entre sí a través de la acometida común.
2. **Acometida**: la capacidad es del punto de carga y se contrasta contra la
   suma del consumo de sus conexiones (hallazgo si hay desajuste).
3. **Dispersión intra-punto**: medidores muy por debajo de sus pares del mismo
   punto, con acometida equivalente, son señal fuerte de derivación en el
   tablero o riser común (alimenta el mecanismo M8).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Config, load_config
from ..electrical import formulas as F

_CLASS_KEY = {"residential": "residential", "commercial": "commercial",
              "industrial": "industrial"}


def aggregate_load_points(consumption: pd.DataFrame, customers: pd.DataFrame,
                          cfg: Config | None = None) -> pd.DataFrame:
    """Demanda diversificada y coherencia de acometida por punto de carga.

    Devuelve una fila por punto de carga con: nº de conexiones, energía y
    demanda del punto (con coincidencia interna), utilización de la acometida y
    dispersión intra-punto.
    """
    cfg = cfg or load_config()
    if customers is None or customers.empty or "site_id" not in customers.columns:
        return pd.DataFrame()
    vel = cfg.electrical["velander"]
    coin = cfg.electrical["coincidence"]
    pf_by_class = cfg.electrical["power_factor_by_class"]
    hours_month = float(cfg.electrical["hours_per_month"])

    n_months = max(1, consumption["year_month"].nunique())
    e_by_cust = consumption.groupby("customer_unit_id")["kwh"].sum()

    cols = ["customer_unit_id", "site_id", "tariff_class"]
    for extra in ("transformer_site_id", "service_drop_kva", "feeder_id"):
        if extra in customers.columns:
            cols.append(extra)
    cu = customers[cols].copy()
    cu["kwh_total"] = cu["customer_unit_id"].map(e_by_cust).fillna(0.0)
    cu["e_month"] = cu["kwh_total"] / n_months

    def dmax(row) -> float:
        ab = vel.get(_CLASS_KEY.get(row["tariff_class"], "residential"),
                     vel["residential"])
        return F.velander_dmax_kw(max(float(row["e_month"]), 0.0), ab["a"], ab["b"])

    cu["dmax_kw"] = cu.apply(dmax, axis=1)
    cu["pf"] = cu["tariff_class"].map(
        lambda c: pf_by_class.get(_CLASS_KEY.get(c, "residential"), 0.92))

    rows = []
    for site_id, g in cu.groupby("site_id"):
        n_units = int(len(g))
        # (1) coincidencia DENTRO del punto de carga: no sumar picos (§9.1 error 3)
        p_max_kw = F.diversified_demand_kw(g["dmax_kw"].tolist(), coin["A"], coin["B"])
        # potencia media y factor de potencia ponderado por energía
        w = g["e_month"].clip(lower=0) + 1e-9
        pf_site = float((g["pf"] * w).sum() / w.sum())
        s_max_kva = F.s_from_p_pf(p_max_kw, pf_site) if p_max_kw > 0 else 0.0

        # (2) coherencia de la acometida compartida
        drop_kva = float(g["service_drop_kva"].max()) if "service_drop_kva" in g \
            and g["service_drop_kva"].notna().any() else np.nan
        util = s_max_kva / drop_kva if drop_kva and drop_kva > 0 else np.nan

        # (3) dispersión intra-punto (insumo de M8)
        vals = g["e_month"].to_numpy(dtype=float)
        med = float(np.median(vals)) if n_units else 0.0
        dispersion = float(np.std(vals) / med) if med > 0 else 0.0
        min_ratio = float(vals.min() / med) if med > 0 else 1.0

        rows.append({
            "feeder_id": g["feeder_id"].iloc[0] if "feeder_id" in g else None,
            "load_point_id": site_id,
            "transformer_site_id": (g["transformer_site_id"].iloc[0]
                                    if "transformer_site_id" in g else None),
            "n_connections": n_units,
            "energy_kwh": round(float(g["kwh_total"].sum()), 1),
            "p_max_diversified_kw": round(p_max_kw, 3),
            "s_max_kva": round(s_max_kva, 3),
            "pf": round(pf_site, 4),
            "service_drop_kva": None if np.isnan(drop_kva) else round(drop_kva, 2),
            "drop_utilization": None if np.isnan(util) else round(util, 3),
            "intra_dispersion": round(dispersion, 4),
            "min_to_median_ratio": round(min_ratio, 4),
            "sum_of_peaks_kw": round(float(g["dmax_kw"].sum()), 3),
        })
    return pd.DataFrame(rows)


def load_point_findings(lp: pd.DataFrame, cfg: Config | None = None) -> pd.DataFrame:
    """Hallazgos a nivel de punto de carga (§5.3 puntos 3 y 4)."""
    if lp is None or lp.empty:
        return pd.DataFrame(columns=["feeder_id", "load_point_id", "finding",
                                     "severity", "evidence"])
    cfg = cfg or load_config()
    th = cfg.thresholds.get("load_point", {})
    max_util = float(th.get("drop_overload_ratio", 1.0))
    min_util = float(th.get("drop_underuse_ratio", 0.1))
    disp_min = float(th.get("intra_dispersion_min_ratio", 0.4))

    rows = []
    for r in lp.itertuples():
        if r.drop_utilization is not None and not pd.isna(r.drop_utilization):
            if r.drop_utilization > max_util:
                rows.append((r.feeder_id, r.load_point_id, "acometida_sobrecargada",
                             "alta", f"utilización {r.drop_utilization:.2f} > {max_util}"))
            elif r.drop_utilization < min_util:
                rows.append((r.feeder_id, r.load_point_id, "acometida_subutilizada",
                             "media", f"utilización {r.drop_utilization:.2f} < {min_util}"))
        if r.n_connections >= 2 and r.min_to_median_ratio < disp_min:
            rows.append((r.feeder_id, r.load_point_id, "dispersion_intra_punto", "alta",
                         f"una conexión consume {r.min_to_median_ratio:.0%} de la "
                         f"mediana del punto ({r.n_connections} medidores)"))
    return pd.DataFrame(rows, columns=["feeder_id", "load_point_id", "finding",
                                       "severity", "evidence"])
