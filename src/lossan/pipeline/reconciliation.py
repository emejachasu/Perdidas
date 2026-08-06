"""Informe de reconciliación de P y Q (§9.3) — primer entregable de valor.

Compara el cálculo **corregido** (fórmulas §9.2) contra el cálculo **actual**
(que se presume erróneo, §9.1) y descompone la diferencia por causa:
energía-vs-demanda, coincidencia, cosφ y factor √3. Se produce por alimentador
y para el agregado del sistema.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..config import Config, load_config
from ..electrical import formulas as F

_CLASS_KEY = {"residential": "residential", "commercial": "commercial",
              "industrial": "industrial"}


def reconcile_feeder(consumption: pd.DataFrame, customers: pd.DataFrame,
                     feeder_id: str, cfg: Config | None = None
                     ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve ``(resumen, causas)`` de la reconciliación de un alimentador."""
    cfg = cfg or load_config()
    vel = cfg.electrical["velander"]
    coin = cfg.electrical["coincidence"]
    pf_by_class = cfg.electrical["power_factor_by_class"]
    v_ll = float(cfg.electrical["voltage"]["ll_mv"])
    hours_month = float(cfg.electrical["hours_per_month"])

    # energía mensual media por cliente y su clase
    e_month = consumption.groupby("customer_unit_id")["kwh"].mean()
    # customer_unit_id debería ser único (CODIGOUNICO); un puñado de
    # duplicados por doble captura en el SIG no debe tumbar el reporte.
    cust = customers.drop_duplicates(subset=["customer_unit_id"]).set_index("customer_unit_id")
    df = pd.DataFrame({"e_month": e_month})
    df["tariff_class"] = cust["tariff_class"].reindex(df.index).fillna("residential")

    # demanda máxima por cliente (Velander) según su clase
    def dmax(row):
        k = _CLASS_KEY.get(row["tariff_class"], "residential")
        ab = vel.get(k, vel["residential"])
        return F.velander_dmax_kw(max(row["e_month"], 0.0), ab["a"], ab["b"])

    df["dmax_kw"] = df.apply(dmax, axis=1)
    n = int(len(df))
    if n == 0:
        empty = pd.DataFrame()
        return empty, empty

    # cosφ agregado ponderado por energía y clase
    def pf(row):
        return pf_by_class.get(_CLASS_KEY.get(row["tariff_class"], "residential"), 0.92)
    w = df["e_month"].clip(lower=0) + 1e-9
    pf_agg = float((df.apply(pf, axis=1) * w).sum() / w.sum())
    tanphi = math.tan(math.acos(pf_agg))

    # ---- CORREGIDO (§9.2) ----
    sum_peaks = float(df["dmax_kw"].sum())
    fcoinc = F.coincidence_factor(n, coin["A"], coin["B"])
    p_corr = fcoinc * sum_peaks                       # demanda diversificada
    q_corr = p_corr * tanphi
    s_corr = math.hypot(p_corr, q_corr)
    i_corr = F.current_3ph(s_corr, v_ll)

    # ---- ACTUAL / ERRÓNEO (§9.1) ----
    e_total = float(df["e_month"].sum())
    p_mean = e_total / hours_month                    # energía-vs-demanda (usar media)
    p_sumpeaks = sum_peaks                            # coincidencia (sumar picos)
    # cosφ mal aplicado: asumir un fp plano por defecto en vez del real calibrado
    naive_pf = float(cfg.electrical.get("naive_pf_default", 0.80))
    q_cosphi_err = p_corr * math.tan(math.acos(naive_pf))
    i_no_sqrt3 = s_corr * 1000.0 / v_ll               # √3 omitido

    summary = pd.DataFrame([{
        "feeder_id": feeder_id, "n_customers": n, "pf_agg": round(pf_agg, 4),
        "P_corr_kw": round(p_corr, 2), "Q_corr_kvar": round(q_corr, 2),
        "S_corr_kva": round(s_corr, 2), "I_corr_a": round(i_corr, 2),
        "P_naive_sumpeaks_kw": round(p_sumpeaks, 2),
        "P_naive_meandemand_kw": round(p_mean, 2),
        "Q_naive_cosphi_kvar": round(q_cosphi_err, 2),
        "I_naive_no_sqrt3_a": round(i_no_sqrt3, 2),
        "dP_coincidence_pct": round(100 * (p_sumpeaks - p_corr) / p_corr, 2) if p_corr else 0,
        "dI_sqrt3_pct": round(100 * (i_no_sqrt3 - i_corr) / i_corr, 2) if i_corr else 0,
    }])

    def cause(name, unit, corrected, current):
        delta = current - corrected
        return {"feeder_id": feeder_id, "cause": name, "unit": unit,
                "corrected": round(corrected, 2), "current": round(current, 2),
                "delta": round(delta, 2),
                "pct": round(100 * delta / corrected, 2) if corrected else 0.0}

    causes = pd.DataFrame([
        cause("coincidencia (sumar picos)", "kW", p_corr, p_sumpeaks),
        cause("energia_vs_demanda (usar media)", "kW", p_corr, p_mean),
        cause("cosphi_sobre_energia", "kVAr", q_corr, q_cosphi_err),
        cause("factor_sqrt3 (omitido)", "A", i_corr, i_no_sqrt3),
    ])
    return summary, causes


def reconcile_all(lake, cfg: Config | None = None) -> dict:
    """Reconciliación para todos los alimentadores + agregado del sistema.

    Escribe ``pq_reconciliation`` y ``pq_reconciliation_causes`` en GOLD.
    """
    cfg = cfg or load_config()
    from ..pipeline.runner import list_feeders
    summaries, causes = [], []
    for fid in list_feeders(lake):
        cons = lake.read_entity("bronze", "consumption", fid)
        cust = lake.read_entity("bronze", "customers", fid)
        if cons.empty or cust.empty:
            continue
        s, c = reconcile_feeder(cons, cust, fid, cfg)
        if not s.empty:
            summaries.append(s)
            causes.append(c)
    if not summaries:
        return {"feeders": 0}
    summ = pd.concat(summaries, ignore_index=True)
    caus = pd.concat(causes, ignore_index=True)
    for name, dfp in (("pq_reconciliation", summ), ("pq_reconciliation_causes", caus)):
        path = lake.root / "gold" / name
        path.mkdir(parents=True, exist_ok=True)
        dfp.to_parquet(path / "data.parquet", index=False)
    return {"feeders": len(summ),
            "system_dP_coincidence_pct": round(float(summ["dP_coincidence_pct"].mean()), 2)}
