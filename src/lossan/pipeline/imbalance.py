"""Desbalance por puesto de transformación (§14.2).

Con el mapeo cliente/unidad → fase se calcula el desbalance real de corriente,
la corriente de neutro y las pérdidas adicionales por neutro (In²·Rn), y el
**beneficio energético del rebalanceo** (alto retorno, baja inversión).
"""
from __future__ import annotations

import pandas as pd

from ..config import Config, load_config
from ..electrical import formulas as F

_PHASES = ["A", "B", "C"]


def compute_site_imbalance(customers: pd.DataFrame, consumption: pd.DataFrame,
                           sites: pd.DataFrame, cfg: Config | None = None,
                           hours_period: float = 8760.0) -> pd.DataFrame:
    """Desbalance por puesto de transformación con el mapeo cliente→fase."""
    cfg = cfg or load_config()
    if customers.empty or "phase" not in customers.columns:
        return pd.DataFrame()
    warn = float(cfg.thresholds["imbalance"]["warn_pct"])
    v_ln = float(cfg.electrical["voltage"]["ln_lv"])
    k = float(cfg.electrical["loss_factor_k"])
    # resistencia de neutro aproximada del secundario (Ω) — parámetro
    rn_ohm = float(cfg.electrical.get("neutral_r_ohm", 0.3))
    fp = F.loss_factor(0.45, k)

    # energía por cliente y su fase
    e_cust = consumption.groupby("customer_unit_id")["kwh"].sum()
    cols = ["customer_unit_id", "transformer_site_id", "phase"]
    if "feeder_id" in customers.columns:
        cols.append("feeder_id")
    cu = customers[cols].copy()
    cu["kwh"] = cu["customer_unit_id"].map(e_cust).fillna(0.0)

    rows = []
    for sid, g in cu.groupby("transformer_site_id"):
        if not sid:
            continue
        e_ph = {p: float(g.loc[g["phase"] == p, "kwh"].sum()) for p in _PHASES}
        # corriente media por fase (potencia media / V_LN, monofásico)
        i_ph = {p: F.mean_power_kw(e_ph[p], hours_period) * 1000.0 / v_ln
                if e_ph[p] > 0 else 0.0 for p in _PHASES}
        i_vals = [i_ph[p] for p in _PHASES]
        i_avg = sum(i_vals) / 3.0
        if i_avg <= 0:
            continue
        pct = max(abs(i - i_avg) for i in i_vals) / i_avg * 100.0
        i_n = F.neutral_current(i_vals[0], i_vals[1], i_vals[2])
        # pérdidas adicionales por neutro y beneficio del rebalanceo (kWh)
        neutral_loss_kwh = (i_n ** 2) * rn_ohm * fp * hours_period / 1000.0
        rows.append({
            "feeder_id": g["feeder_id"].iloc[0] if "feeder_id" in g else None,
            "site_id": sid,
            "i_a": round(i_vals[0], 2), "i_b": round(i_vals[1], 2),
            "i_c": round(i_vals[2], 2), "i_neutral": round(i_n, 2),
            "imbalance_pct": round(pct, 1), "flagged": bool(pct > warn),
            "neutral_loss_kwh": round(neutral_loss_kwh, 1),
            "rebalance_benefit_kwh": round(neutral_loss_kwh, 1),   # ~ recuperable al balancear
        })
    df = pd.DataFrame(rows)
    if not df.empty and "feeder_id" not in df.columns:
        df["feeder_id"] = None
    return df
