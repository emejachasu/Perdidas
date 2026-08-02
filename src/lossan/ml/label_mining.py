"""Minería de etiquetas desde el histórico de consumo (§15.2).

El histórico es confiable, así que se usa para generar etiquetas nuevas sin
depender de inspecciones. Cada etiqueta lleva ``label_source``,
``confidence_weight`` y ``evidence`` reproducible.

Validación cruzada obligatoria: contrastar las etiquetas minadas contra los
hurtos confirmados. Si M1-M3 recuperan un alto porcentaje, el mecanismo queda
validado (criterio de aceptación §22.8).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Config, load_config


def _pivot(consumption: pd.DataFrame) -> tuple[pd.Index, np.ndarray, np.ndarray]:
    piv = consumption.pivot_table(index="customer_unit_id", columns="year_month",
                                  values="kwh", aggfunc="sum").sort_index(axis=1)
    kwh = piv.to_numpy(dtype=float)
    kvarh = None
    if "kvarh" in consumption.columns:
        pv2 = consumption.pivot_table(index="customer_unit_id", columns="year_month",
                                      values="kvarh", aggfunc="sum").reindex(
            index=piv.index, columns=piv.columns)
        kvarh = pv2.to_numpy(dtype=float)
    return piv.index, kwh, kvarh


def _label(ids, mask, mechanism, weight, evidences):
    idx = np.where(mask)[0]
    return pd.DataFrame({
        "customer_unit_id": [ids[i] for i in idx],
        "label_source": mechanism,
        "confidence_weight": weight,
        "evidence": [evidences[i] for i in idx],
    })


def m1_drop_recovery(ids, kwh, drop_pct, min_months) -> pd.DataFrame:
    """Caída sostenida ≥ X% durante ≥ N meses seguida de recuperación."""
    n, T = kwh.shape
    mask = np.zeros(n, dtype=bool)
    ev = [""] * n
    for i in range(n):
        s = kwh[i]
        base = np.median(s[: max(1, T // 4)])
        if base <= 0:
            continue
        low = s < base * (1 - drop_pct)
        # racha de meses bajos seguida de recuperación
        run = 0
        for t in range(T):
            if low[t]:
                run += 1
            else:
                if run >= min_months and s[t] >= base * 0.9:
                    mask[i] = True
                    ev[i] = f"caída>{int(drop_pct*100)}% por {run} meses y recuperación"
                    break
                run = 0
    return _label(ids, mask, "M1_drop_recovery", 0.9, ev)


def m2_jump_after_intervention(ids, kwh, jump_pct) -> pd.DataFrame:
    """Aumento permanente ≥ X% (proxy de salto tras intervención)."""
    n, T = kwh.shape
    h = T // 2
    mask = np.zeros(n, dtype=bool)
    ev = [""] * n
    for i in range(n):
        first, second = np.median(kwh[i][:h]), np.median(kwh[i][h:])
        if first > 0 and second >= first * (1 + jump_pct):
            mask[i] = True
            ev[i] = f"salto permanente +{100*(second/first-1):.0f}%"
    return _label(ids, mask, "M2_jump_after_intervention", 0.85, ev)


def m4_zero_active(ids, kwh, min_zeros) -> pd.DataFrame:
    """Cero sostenido con servicio activo."""
    n, T = kwh.shape
    zeros = (kwh <= 0.01)
    # racha máxima de ceros
    mask = np.zeros(n, dtype=bool)
    ev = [""] * n
    for i in range(n):
        best = cur = 0
        for t in range(T):
            cur = cur + 1 if zeros[i, t] else 0
            best = max(best, cur)
        if best >= min_zeros and kwh[i].sum() > 0:
            mask[i] = True
            ev[i] = f"{best} meses en cero con servicio activo"
    return _label(ids, mask, "M4_zero_active", 0.5, ev)


def m5_level_break(ids, kwh) -> pd.DataFrame:
    """Ruptura de nivel (change point) sin causa comercial (PELT si disponible)."""
    try:
        import ruptures as rpt
    except Exception:
        return pd.DataFrame(columns=["customer_unit_id", "label_source",
                                     "confidence_weight", "evidence"])
    n, T = kwh.shape
    mask = np.zeros(n, dtype=bool)
    ev = [""] * n
    for i in range(n):
        s = kwh[i]
        if s.std() < 1e-6:
            continue
        try:
            bkps = rpt.Pelt(model="l2", min_size=3).fit(s).predict(pen=np.var(s) * 3)
        except Exception:
            continue
        internal = [b for b in bkps if 0 < b < T]
        if internal:
            b = internal[0]
            if abs(s[:b].mean() - s[b:].mean()) > 0.3 * (s.mean() + 1e-9):
                mask[i] = True
                ev[i] = f"ruptura de nivel en el mes {b}"
    return _label(ids, mask, "M5_level_break", 0.5, ev)


def m6_pf_collapse(ids, kwh, kvarh) -> pd.DataFrame:
    """Colapso del factor de potencia (cambio abrupto de kVArh/kWh)."""
    if kvarh is None:
        return pd.DataFrame(columns=["customer_unit_id", "label_source",
                                     "confidence_weight", "evidence"])
    n, T = kwh.shape
    h = T // 2
    mask = np.zeros(n, dtype=bool)
    ev = [""] * n
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(kwh > 0, kvarh / kwh, np.nan)
    for i in range(n):
        a, b = np.nanmedian(ratio[i][:h]), np.nanmedian(ratio[i][h:])
        if np.isfinite(a) and np.isfinite(b) and a > 0 and abs(b - a) / a > 0.5:
            mask[i] = True
            ev[i] = f"cambio de kVArh/kWh {a:.2f}->{b:.2f}"
    return _label(ids, mask, "M6_pf_collapse", 0.5, ev)


def m7_peer_divergence(ids, kwh, customers) -> pd.DataFrame:
    """Divergencia del grupo par (bajo el percentil 5 del puesto+clase)."""
    df = pd.DataFrame({"customer_unit_id": ids, "mean_kwh": kwh.mean(axis=1)})
    meta = customers[["customer_unit_id", "transformer_site_id", "tariff_class"]]
    df = df.merge(meta, on="customer_unit_id", how="left")
    df["p05"] = df.groupby(["transformer_site_id", "tariff_class"])["mean_kwh"].transform(
        lambda s: s.quantile(0.05))
    flagged = df[(df["mean_kwh"] < df["p05"]) & (df["mean_kwh"] > 0)]
    return pd.DataFrame({
        "customer_unit_id": flagged["customer_unit_id"].to_numpy(),
        "label_source": "M7_peer_divergence", "confidence_weight": 0.35,
        "evidence": "bajo el percentil 5 del grupo par",
    })


def m8_intra_site_dispersion(ids, kwh, customers) -> pd.DataFrame:
    """Dispersión intra-puesto de cliente (§5.3): unidades muy por debajo de
    sus pares del mismo puesto de cliente con acometida equivalente."""
    if "site_id" not in customers.columns:
        return pd.DataFrame(columns=["customer_unit_id", "label_source",
                                     "confidence_weight", "evidence"])
    df = pd.DataFrame({"customer_unit_id": ids, "mean_kwh": kwh.mean(axis=1)})
    df = df.merge(customers[["customer_unit_id", "site_id"]], on="customer_unit_id", how="left")
    grp = df.groupby("site_id")["mean_kwh"]
    df["site_med"] = grp.transform("median")
    df["site_n"] = grp.transform("count")
    flagged = df[(df["site_n"] >= 2) & (df["mean_kwh"] < 0.4 * df["site_med"]) &
                 (df["mean_kwh"] > 0)]
    return pd.DataFrame({
        "customer_unit_id": flagged["customer_unit_id"].to_numpy(),
        "label_source": "M8_intra_site_dispersion", "confidence_weight": 0.6,
        "evidence": "muy por debajo de sus pares del mismo puesto",
    })


def mine_labels(consumption: pd.DataFrame, customers: pd.DataFrame,
                cfg: Config | None = None) -> pd.DataFrame:
    """Ejecuta todos los mecanismos M1-M8 y concatena las etiquetas minadas."""
    cfg = cfg or load_config()
    th = cfg.thresholds["label_mining"]
    ids, kwh, kvarh = _pivot(consumption)
    ids = np.array(ids)

    parts = [
        m1_drop_recovery(ids, kwh, float(th["drop_recovery_pct"]),
                         int(th["drop_recovery_months"])),
        m2_jump_after_intervention(ids, kwh, float(th["jump_after_intervention_pct"])),
        m4_zero_active(ids, kwh, int(th.get("zero_active_months", 4))),
        m5_level_break(ids, kwh),
        m6_pf_collapse(ids, kwh, kvarh),
        m7_peer_divergence(ids, kwh, customers),
        m8_intra_site_dispersion(ids, kwh, customers),
    ]
    out = pd.concat([p for p in parts if not p.empty], ignore_index=True) \
        if any(not p.empty for p in parts) else \
        pd.DataFrame(columns=["customer_unit_id", "label_source",
                              "confidence_weight", "evidence"])
    return out


def validate_against_confirmed(mined: pd.DataFrame, theft_labels: pd.DataFrame,
                               high_conf_sources=("M1_drop_recovery",
                                                  "M2_jump_after_intervention")) -> dict:
    """Contrasta las etiquetas minadas contra los hurtos confirmados (§22.8).

    Reporta el recall de los mecanismos de alta confianza sobre los confirmados.
    """
    confirmed = set(theft_labels.loc[theft_labels["is_theft"], "customer_unit_id"])
    if not confirmed:
        return {"confirmed": 0, "recall_high_conf": None, "recall_all": None}
    all_mined = set(mined["customer_unit_id"])
    high = set(mined.loc[mined["label_source"].isin(high_conf_sources), "customer_unit_id"])
    return {
        "confirmed": len(confirmed),
        "recall_high_conf": round(len(confirmed & high) / len(confirmed), 4),
        "recall_all": round(len(confirmed & all_mined) / len(confirmed), 4),
        "mined_total": len(all_mined),
        "precision_all_vs_confirmed": round(
            len(confirmed & all_mined) / max(1, len(all_mined)), 4),
    }
