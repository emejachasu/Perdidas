"""Aprendizaje Positivo–No etiquetado (PU learning, §15.1).

P: hurtos confirmados (confiables, no exhaustivos). U: nunca inspeccionados
(la mayoría) — NO son negativos. Implementa y permite comparar por Precision@k:
Elkan–Noto, Bagging PU y two-step con espías. Estrategias intercambiables por
configuración (Anexo C).
"""
from __future__ import annotations

import numpy as np

try:
    from lightgbm import LGBMClassifier

    def _base_estimator(**kw):
        return LGBMClassifier(n_estimators=200, learning_rate=0.05,
                              num_leaves=31, verbose=-1, **kw)
except Exception:  # pragma: no cover
    from sklearn.ensemble import HistGradientBoostingClassifier

    def _base_estimator(**kw):
        return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05)


PU_METHODS = ("elkan_noto", "bagging_pu", "spies")


def _as_arrays(X, s):
    return np.asarray(X, dtype=float), np.asarray(s, dtype=int)


def elkan_noto(X, s, seed: int = 0):
    """Elkan–Noto: corrige por la propensidad c = P(etiquetado|positivo).

    Entrena g(x)=P(s=1|x) tratando U como negativo, estima c sobre los positivos
    etiquetados y corrige P(y=1|x) = g(x)/c.
    """
    X, s = _as_arrays(X, s)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(s))
    cut = int(0.7 * len(s))
    tr, va = idx[:cut], idx[cut:]

    clf = _base_estimator()
    clf.fit(X[tr], s[tr])
    g = clf.predict_proba(X)[:, 1]
    # c estimado como media de g sobre positivos etiquetados en validación
    pos_va = va[s[va] == 1]
    c = float(np.mean(g[pos_va])) if len(pos_va) else float(np.mean(g[s == 1]) or 1.0)
    c = max(c, 1e-3)
    scores = np.clip(g / c, 0.0, 1.0)
    return scores, {"method": "elkan_noto", "c": round(c, 4)}


def bagging_pu(X, s, n_estimators: int = 15, seed: int = 0):
    """Bagging PU: en cada iteración muestrea de U como negativos, promedia OOB."""
    X, s = _as_arrays(X, s)
    pos = np.where(s == 1)[0]
    unl = np.where(s == 0)[0]
    rng = np.random.default_rng(seed)
    n = len(s)
    scores = np.zeros(n)
    counts = np.zeros(n)
    k = max(len(pos), 1)
    for b in range(n_estimators):
        samp = rng.choice(unl, size=min(k, len(unl)), replace=False)
        oob = np.setdiff1d(unl, samp)
        idx = np.concatenate([pos, samp])
        y = np.concatenate([np.ones(len(pos)), np.zeros(len(samp))])
        clf = _base_estimator()
        clf.fit(X[idx], y)
        if len(oob):
            scores[oob] += clf.predict_proba(X[oob])[:, 1]
            counts[oob] += 1
        scores[pos] += clf.predict_proba(X[pos])[:, 1]
        counts[pos] += 1
    counts[counts == 0] = 1
    return scores / counts, {"method": "bagging_pu", "n_estimators": n_estimators}


def spies(X, s, spy_frac: float = 0.15, seed: int = 0):
    """Two-step con técnica de espías: envía una fracción de positivos a U para
    fijar un umbral que identifique negativos confiables, y reentrena."""
    X, s = _as_arrays(X, s)
    rng = np.random.default_rng(seed)
    pos = np.where(s == 1)[0]
    unl = np.where(s == 0)[0]
    n_spy = max(1, int(spy_frac * len(pos)))
    spy = rng.choice(pos, size=n_spy, replace=False)

    s_mix = s.copy()
    s_mix[spy] = 0  # espías ocultos en U
    clf = _base_estimator()
    clf.fit(X, s_mix)
    p = clf.predict_proba(X)[:, 1]
    thr = np.percentile(p[spy], 10)          # umbral: percentil bajo de los espías
    reliable_neg = unl[p[unl] < thr]

    idx = np.concatenate([pos, reliable_neg])
    y = np.concatenate([np.ones(len(pos)), np.zeros(len(reliable_neg))])
    clf2 = _base_estimator()
    clf2.fit(X[idx], y)
    scores = clf2.predict_proba(X)[:, 1]
    return scores, {"method": "spies", "threshold": round(float(thr), 4),
                    "reliable_negatives": int(len(reliable_neg))}


def fit_pu(X, s, method: str = "elkan_noto", seed: int = 0):
    """Punto de entrada: devuelve ``(scores, info)`` según el método elegido."""
    if method == "elkan_noto":
        return elkan_noto(X, s, seed)
    if method == "bagging_pu":
        return bagging_pu(X, s, seed=seed)
    if method == "spies":
        return spies(X, s, seed=seed)
    raise ValueError(f"Método PU no soportado: {method} (opciones: {PU_METHODS})")
