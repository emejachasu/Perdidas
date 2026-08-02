"""Modelo de riesgo de hurto: ensamble PU + no supervisado, calibración y SHAP.

- LightGBM dentro del marco PU como núcleo.
- No supervisado en paralelo (pyod) con consenso por rank averaging.
- Calibración isotónica indispensable (el score alimenta valor esperado en $).
- SHAP obligatorio: cada caso llega a campo con sus 3 razones.
- Métrica principal: Precision@k y energía recuperable@k (§15.4, §17.2).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from ..config import Config, load_config
from .features import build_features
from .label_mining import mine_labels
from .pu import fit_pu

_FEATURE_DROP = {"customer_unit_id", "installed_load_kw", "service_drop_kva"}


def _rank(x: np.ndarray) -> np.ndarray:
    order = np.argsort(np.argsort(x))
    return order / max(1, len(x) - 1)


def _unsupervised_scores(X: np.ndarray) -> np.ndarray:
    """Consenso no supervisado (pyod si está; si no, IsolationForest sklearn)."""
    try:
        from pyod.models.iforest import IForest
        from pyod.models.ecod import ECOD
        models = [IForest(random_state=0), ECOD()]
        ranks = []
        for m in models:
            m.fit(X)
            ranks.append(_rank(m.decision_scores_))
        return np.mean(ranks, axis=0)
    except Exception:
        from sklearn.ensemble import IsolationForest
        m = IsolationForest(random_state=0)
        m.fit(X)
        return _rank(-m.score_samples(X))


def _shap_reasons(model, X: np.ndarray, feat_names: list[str], top: int = 3) -> list[list[str]]:
    """Top-N razones por caso (SHAP si está; si no, contribución por importancia)."""
    try:
        import shap
        expl = shap.TreeExplainer(model)
        sv = expl.shap_values(X)
        if isinstance(sv, list):
            sv = sv[1] if len(sv) > 1 else sv[0]
        sv = np.asarray(sv)
        reasons = []
        for i in range(X.shape[0]):
            idx = np.argsort(-np.abs(sv[i]))[:top]
            reasons.append([f"{feat_names[j]} ({'+' if sv[i, j] > 0 else '-'})" for j in idx])
        return reasons
    except Exception:
        imp = getattr(model, "feature_importances_", np.ones(X.shape[1]))
        top_idx = np.argsort(-imp)[:top]
        base = [feat_names[j] for j in top_idx]
        return [base for _ in range(X.shape[0])]


def train_risk_model(consumption: pd.DataFrame, customers: pd.DataFrame,
                     theft_labels: pd.DataFrame | None = None,
                     method: str = "elkan_noto", cutoff: str | None = None,
                     cfg: Config | None = None) -> tuple[pd.DataFrame, dict]:
    """Entrena el modelo y devuelve ``(scores_df, info)``.

    scores_df: customer_unit_id, risk_score (calibrado), score_pu, score_unsup,
    recoverable_kwh_month, reason_1..3.
    """
    cfg = cfg or load_config()
    feats = build_features(consumption, customers, cutoff=cutoff)
    ids = feats["customer_unit_id"].to_numpy()
    feat_cols = [c for c in feats.columns if c not in _FEATURE_DROP]
    X = feats[feat_cols].to_numpy(dtype=float)

    # positivos P: hurtos confirmados si existen; si no, minería de alta confianza
    if theft_labels is not None and theft_labels["is_theft"].any():
        pos_ids = set(theft_labels.loc[theft_labels["is_theft"], "customer_unit_id"])
    else:
        mined = mine_labels(consumption, customers, cfg)
        pos_ids = set(mined.loc[mined["label_source"].isin(
            ["M1_drop_recovery", "M2_jump_after_intervention"]), "customer_unit_id"])
    s = np.array([1 if i in pos_ids else 0 for i in ids], dtype=int)

    if s.sum() == 0:
        # sin positivos: solo no supervisado
        unsup = _unsupervised_scores(X)
        df = pd.DataFrame({"customer_unit_id": ids, "risk_score": unsup,
                           "score_pu": 0.0, "score_unsup": unsup})
        return _finalize(df, feats), {"method": "unsupervised_only"}

    score_pu, pu_info = fit_pu(X, s, method=method)
    score_unsup = _unsupervised_scores(X)
    # ensamble por rank averaging
    ens = 0.6 * _rank(score_pu) + 0.4 * score_unsup

    # calibración isotónica score -> probabilidad
    iso = IsotonicRegression(out_of_bounds="clip")
    calibrated = iso.fit_transform(ens, s)

    # razones SHAP sólo en la cabeza del ranking (lo único accionable, §17.2):
    # calcular explicaciones para todos los clientes es innecesario y costoso.
    from .pu import _base_estimator
    expl_model = _base_estimator()
    expl_model.fit(X, s)
    n = len(ids)
    top_n = min(n, int(cfg.thresholds.get("explain", {}).get("top_n", 1000)))
    order = np.argsort(-calibrated)[:top_n]
    reasons = [["", "", ""] for _ in range(n)]
    sub_reasons = _shap_reasons(expl_model, X[order], feat_cols)
    for pos, gi in enumerate(order):
        reasons[gi] = sub_reasons[pos]

    df = pd.DataFrame({
        "customer_unit_id": ids,
        "risk_score": np.round(calibrated, 5),
        "score_pu": np.round(score_pu, 5),
        "score_unsup": np.round(score_unsup, 5),
        "reason_1": [r[0] if len(r) > 0 else "" for r in reasons],
        "reason_2": [r[1] if len(r) > 1 else "" for r in reasons],
        "reason_3": [r[2] if len(r) > 2 else "" for r in reasons],
    })
    info = {"method": method, "n_positives": int(s.sum()), **pu_info}
    return _finalize(df, feats), info


def _finalize(df: pd.DataFrame, feats: pd.DataFrame) -> pd.DataFrame:
    rec = feats[["customer_unit_id"]].copy()
    rec["recoverable_kwh_month"] = feats.get("mean_6", 0.0)
    out = df.merge(rec, on="customer_unit_id", how="left")
    return out.sort_values("risk_score", ascending=False).reset_index(drop=True)


def precision_at_k(scores_df: pd.DataFrame, truth_ids: set, k: int) -> float:
    """Precision@k: fracción de verdaderos positivos en el top-k del ranking."""
    top = scores_df.sort_values("risk_score", ascending=False).head(k)
    if len(top) == 0:
        return 0.0
    hits = top["customer_unit_id"].isin(truth_ids).sum()
    return round(float(hits) / len(top), 4)


def energy_recoverable_at_k(scores_df: pd.DataFrame, truth_ids: set, k: int) -> float:
    """Energía recuperable esperada en el top-k (kWh/mes) sobre verdaderos positivos."""
    top = scores_df.sort_values("risk_score", ascending=False).head(k)
    hit = top[top["customer_unit_id"].isin(truth_ids)]
    return round(float(hit.get("recoverable_kwh_month", pd.Series(dtype=float)).sum()), 1)
