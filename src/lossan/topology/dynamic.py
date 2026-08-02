"""Topología dinámica: versiones y detección de transferencias (§7).

La red no es estática. El balance se calcula por intervalo de topología estable
y luego se agrega. La energía transferida entre alimentadores es la causa nº 1
de balances que no cierran (PNT falsamente alta en uno y negativa en el vecino).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def reconstruct_topology_versions(events: pd.DataFrame,
                                  period_start: str, period_end: str) -> pd.DataFrame:
    """Reconstruye estados topológicos válidos por intervalo (§7.3).

    ``events``: columnas ``device_id, timestamp, estado_previo, estado_nuevo``.
    Devuelve intervalos ``topology_version_id, valid_from, valid_to``.
    """
    if events is None or events.empty:
        return pd.DataFrame([{
            "topology_version_id": "TV000", "valid_from": period_start,
            "valid_to": period_end, "n_events": 0,
        }])
    ev = events.sort_values("timestamp").reset_index(drop=True)
    stamps = [period_start] + ev["timestamp"].astype(str).tolist() + [period_end]
    rows = []
    for i in range(len(stamps) - 1):
        rows.append({
            "topology_version_id": f"TV{i:03d}",
            "valid_from": stamps[i], "valid_to": stamps[i + 1],
            "n_events": 1 if 0 < i <= len(ev) else 0,
        })
    return pd.DataFrame(rows)


def infer_transfers(header_wide: pd.DataFrame, *, min_shift_pct: float = 0.15,
                    corr_threshold: float = -0.6) -> pd.DataFrame:
    """Infiere transferencias entre alimentadores cuando falta el log (§7.4).

    Busca cambios abruptos y sostenidos en la energía de cabecera de dos
    alimentadores, de signos opuestos y magnitudes correlacionadas.

    ``header_wide``: índice ``year_month``, columnas = feeder_id, valores kWh.
    Devuelve pares candidatos con confianza y mes estimado.
    """
    feeders = list(header_wide.columns)
    if len(feeders) < 2 or header_wide.shape[0] < 6:
        return pd.DataFrame(columns=["feeder_a", "feeder_b", "confidence",
                                     "month", "shift_a_pct", "shift_b_pct"])

    deltas = header_wide.diff().dropna()
    months = header_wide.index.tolist()
    half = header_wide.shape[0] // 2

    def level_shift(series: np.ndarray) -> float:
        first, second = series[:half].mean(), series[half:].mean()
        base = abs(first) + 1e-9
        return (second - first) / base

    shifts = {f: level_shift(header_wide[f].to_numpy()) for f in feeders}

    rows = []
    for i, fa in enumerate(feeders):
        for fb in feeders[i + 1:]:
            sa, sb = shifts[fa], shifts[fb]
            # signos opuestos y magnitud relevante
            if sa * sb >= 0 or max(abs(sa), abs(sb)) < min_shift_pct:
                continue
            corr = np.corrcoef(deltas[fa], deltas[fb])[0, 1]
            if corr <= corr_threshold:
                # mes de mayor cambio opuesto
                opp = -np.sign(sa) * deltas[fa].to_numpy() + np.sign(sa) * deltas[fb].to_numpy()
                m = months[1 + int(np.argmax(np.abs(opp)))]
                conf = min(1.0, abs(corr) * (abs(sa) + abs(sb)))
                rows.append({"feeder_a": fa, "feeder_b": fb,
                             "confidence": round(float(conf), 3), "month": m,
                             "shift_a_pct": round(float(sa) * 100, 2),
                             "shift_b_pct": round(float(sb) * 100, 2)})
    return pd.DataFrame(rows).sort_values("confidence", ascending=False) if rows else \
        pd.DataFrame(columns=["feeder_a", "feeder_b", "confidence", "month",
                              "shift_a_pct", "shift_b_pct"])
