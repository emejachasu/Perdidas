"""Ingeniería de features para el score de riesgo (§15.3).

Regla anti-fuga estricta: ninguna feature con información posterior a la fecha
de corte. La construcción usa sólo el histórico de consumo hasta ``cutoff``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _theil_sen_slope(y: np.ndarray) -> float:
    n = len(y)
    if n < 2:
        return 0.0
    x = np.arange(n)
    # muestreo de pares para O(n) aproximado si n grande
    idx = np.triu_indices(n, k=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        slopes = (y[idx[1]] - y[idx[0]]) / (x[idx[1]] - x[idx[0]])
    slopes = slopes[np.isfinite(slopes)]
    return float(np.median(slopes)) if slopes.size else 0.0


def build_features(consumption: pd.DataFrame, customers: pd.DataFrame,
                   cutoff: str | None = None) -> pd.DataFrame:
    """Construye la matriz de features por cliente.

    Estadísticos por ventanas, tendencia Theil-Sen, ceros y rachas, fracción de
    lecturas estimadas, entropía, ratio kVArh/kWh y su estabilidad, z-scores
    contra el grupo par, y ratio consumo/carga instalada.
    """
    c = consumption
    if cutoff:
        c = c[c["year_month"] <= cutoff]

    piv = c.pivot_table(index="customer_unit_id", columns="year_month",
                        values="kwh", aggfunc="sum").sort_index(axis=1)
    ids = piv.index
    kwh = piv.to_numpy(dtype=float)
    n, T = kwh.shape

    def win_stats(a, w):
        seg = a[:, -w:] if w < T else a
        return seg.mean(axis=1), seg.std(axis=1)

    feats = {"customer_unit_id": ids}
    for w in (3, 6, 12, min(24, T)):
        m, s = win_stats(kwh, w)
        feats[f"mean_{w}"] = m
        feats[f"std_{w}"] = s
        feats[f"cv_{w}"] = np.where(m > 0, s / m, 0.0)

    feats["trend"] = np.array([_theil_sen_slope(kwh[i]) for i in range(n)])
    feats["zeros_frac"] = (kwh <= 0.01).mean(axis=1)
    # racha máxima de ceros
    max_zero_run = np.zeros(n)
    for i in range(n):
        best = cur = 0
        for t in range(T):
            cur = cur + 1 if kwh[i, t] <= 0.01 else 0
            best = max(best, cur)
        max_zero_run[i] = best
    feats["max_zero_run"] = max_zero_run

    # ratio interanual (último 12 vs previo 12 si hay)
    if T >= 24:
        recent = kwh[:, -12:].mean(axis=1)
        prev = kwh[:, -24:-12].mean(axis=1)
        feats["yoy_ratio"] = np.where(prev > 0, recent / prev, 1.0)
    else:
        feats["yoy_ratio"] = np.ones(n)

    # entropía/planitud de la distribución mensual
    p = kwh / (kwh.sum(axis=1, keepdims=True) + 1e-9)
    with np.errstate(divide="ignore", invalid="ignore"):
        ent = -np.nansum(np.where(p > 0, p * np.log(p), 0.0), axis=1)
    feats["entropy"] = ent

    # fracción de lecturas estimadas
    if "estimated" in c.columns:
        est = c.groupby("customer_unit_id")["estimated"].mean().reindex(ids).fillna(0.0)
        feats["estimated_frac"] = est.to_numpy()
    else:
        feats["estimated_frac"] = np.zeros(n)

    # ratio kVArh/kWh y su estabilidad
    if "kvarh" in c.columns:
        pv2 = c.pivot_table(index="customer_unit_id", columns="year_month",
                            values="kvarh", aggfunc="sum").reindex(
            index=ids, columns=piv.columns).to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.where(kwh > 0, pv2 / kwh, np.nan)
        feats["kvarh_ratio_mean"] = np.nanmean(r, axis=1)
        feats["kvarh_ratio_std"] = np.nanstd(r, axis=1)

    df = pd.DataFrame(feats)

    # z-scores contra grupo par (puesto de transformación y clase) + ratio carga
    meta = customers[["customer_unit_id", "transformer_site_id", "tariff_class",
                      "installed_load_kw", "service_drop_kva"]]
    df = df.merge(meta, on="customer_unit_id", how="left")
    grp = df.groupby(["transformer_site_id", "tariff_class"])["mean_6"]
    df["z_peer"] = (df["mean_6"] - grp.transform("mean")) / (grp.transform("std") + 1e-9)
    df["consumo_vs_instalada"] = df["mean_6"] / (df["installed_load_kw"] * 720 + 1e-9)

    df = df.drop(columns=["transformer_site_id", "tariff_class"])
    df = df.fillna(0.0)
    return df
