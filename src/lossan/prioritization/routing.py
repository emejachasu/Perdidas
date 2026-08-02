"""Eficiencia de campo: clustering geográfico y ruteo (§17.5).

30 puestos concentrados cuestan una fracción de 30 dispersos, y eso cambia el
óptimo. Agrupa con HDBSCAN y secuencia cada clúster (vecino más cercano, con
OR-Tools VRP opcional). Genera órdenes de trabajo por cuadrilla y día.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _cluster(xy: np.ndarray, min_cluster_size: int) -> np.ndarray:
    try:
        from sklearn.cluster import HDBSCAN
        labels = HDBSCAN(min_cluster_size=max(2, min_cluster_size)).fit_predict(xy)
        return labels
    except Exception:
        # rejilla simple como respaldo
        if len(xy) == 0:
            return np.array([], dtype=int)
        gx = (xy[:, 0] // 1000).astype(int)
        gy = (xy[:, 1] // 1000).astype(int)
        return gx * 10000 + gy


def _nearest_neighbor_route(points: np.ndarray) -> list[int]:
    n = len(points)
    if n <= 1:
        return list(range(n))
    visited = [0]
    remaining = set(range(1, n))
    while remaining:
        last = points[visited[-1]]
        nxt = min(remaining, key=lambda j: np.hypot(*(points[j] - last)))
        visited.append(nxt)
        remaining.discard(nxt)
    return visited


def cluster_and_route(selected: pd.DataFrame, visits_per_crew_day: int,
                      num_crews: int, min_cluster_size: int = 5) -> pd.DataFrame:
    """Agrupa geográficamente los puestos seleccionados y arma órdenes de trabajo
    por cuadrilla y día con secuencia de visita."""
    if selected.empty:
        return selected.assign(cluster=[], crew=[], day=[], visit_seq=[])
    df = selected.reset_index(drop=True).copy()
    xy = df[["x", "y"]].fillna(0.0).to_numpy()
    df["cluster"] = _cluster(xy, min_cluster_size)

    # ordenar clústeres por beneficio y secuenciar internamente
    order_rows = []
    seq_global = 0
    for cl, g in df.groupby("cluster"):
        pts = g[["x", "y"]].fillna(0.0).to_numpy()
        route = _nearest_neighbor_route(pts)
        gg = g.iloc[route].copy()
        gg["cluster_benefit"] = g["benefit_usd"].sum()
        order_rows.append(gg)
    ordered = pd.concat(order_rows, ignore_index=True) if order_rows else df
    ordered = ordered.sort_values("cluster_benefit", ascending=False).reset_index(drop=True)

    # asignar a cuadrillas y días round-robin respetando visitas/día
    cap = max(1, visits_per_crew_day)
    ordered["visit_seq"] = np.arange(len(ordered))
    ordered["crew"] = (ordered["visit_seq"] // cap) % max(1, num_crews)
    ordered["day"] = ordered["visit_seq"] // (cap * max(1, num_crews))
    return ordered
