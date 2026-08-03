"""Índice de confiabilidad del modelo 0-100 (§8.3).

Combina la densidad y severidad de hallazgos de calidad de datos con el residuo
del balance. Alimenta la incertidumbre y **penaliza la priorización de campo
donde el problema es de datos y no de hurto** (§16).
"""
from __future__ import annotations

import pandas as pd

_SEV_WEIGHT = {"critica": 5.0, "alta": 2.0, "media": 1.0}


def reliability_index(quality_df: pd.DataFrame, n_elements: int,
                      residual_pct: float) -> dict:
    """Devuelve el índice 0-100 y sus componentes para un alimentador/zona."""
    n_elements = max(1, int(n_elements))
    penalty_pts = 0.0
    if quality_df is not None and not quality_df.empty:
        for sev, w in _SEV_WEIGHT.items():
            penalty_pts += w * int((quality_df["severity"] == sev).sum())
    density = penalty_pts / n_elements
    quality_penalty = 80.0 * min(1.0, density)              # hasta 80 pts por calidad
    balance_penalty = min(20.0, abs(residual_pct) * 4.0)    # hasta 20 pts por residuo
    score = max(0.0, 100.0 - quality_penalty - balance_penalty)
    return {"reliability_index": round(score, 1),
            "quality_penalty": round(quality_penalty, 1),
            "balance_penalty": round(balance_penalty, 1),
            "n_findings": 0 if quality_df is None or quality_df.empty else int(len(quality_df))}


def reliability_table(feeder_id: str, quality_df: pd.DataFrame, n_elements: int,
                      residual_pct: float) -> pd.DataFrame:
    """Fila GOLD con el índice de confiabilidad de un alimentador."""
    d = reliability_index(quality_df, n_elements, residual_pct)
    d["feeder_id"] = feeder_id
    return pd.DataFrame([d])
