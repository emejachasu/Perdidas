"""Curvas de carga por clustering (§9.4).

Agrupa perfiles de consumo normalizados (k-means) y asigna cada cliente a una
curva representativa. Con datos mensuales agrupa la forma estacional; con
resolución horaria puede usarse DTW (extensión). Los clientes sin histórico se
asignan a la mediana de su clase/puesto.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def cluster_load_profiles(consumption: pd.DataFrame, customers: pd.DataFrame,
                          n_clusters: int = 4, seed: int = 0
                          ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve ``(asignaciones, centroides)``.

    asignaciones: customer_unit_id, cluster · centroides: forma normalizada media
    por clúster (una columna por periodo).
    """
    piv = consumption.pivot_table(index="customer_unit_id", columns="year_month",
                                  values="kwh", aggfunc="sum").fillna(0.0).sort_index(axis=1)
    ids = piv.index
    X = piv.to_numpy(dtype=float)
    # normalizar por la media de cada cliente (forma, no magnitud)
    means = X.mean(axis=1, keepdims=True)
    shape = np.divide(X, means, out=np.zeros_like(X), where=means > 0)

    valid = means.squeeze() > 0
    k = int(max(1, min(n_clusters, valid.sum())))
    labels = np.full(len(ids), -1)
    if valid.sum() >= k and k >= 1:
        from sklearn.cluster import KMeans
        km = KMeans(n_clusters=k, random_state=seed, n_init=10)
        labels[valid] = km.fit_predict(shape[valid])
        centroids = km.cluster_centers_
    else:
        centroids = np.zeros((0, X.shape[1]))

    assign = pd.DataFrame({"customer_unit_id": ids, "cluster": labels})
    cent = pd.DataFrame(centroids, columns=[str(c) for c in piv.columns])
    cent.insert(0, "cluster", range(len(cent)))
    return assign, cent
