"""Balance jerárquico, cargabilidad y PNT por alimentador (M5, M6, M7).

Consume BRONZE de un alimentador y produce GOLD:
  - feeder_balance          (§13 balance de energía y PNT)
  - transformer_loadability (§14.1 cargabilidad por configuración de banco)
  - customer_risk           (proxy de riesgo por caída de consumo, base de M9)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Config, load_config
from ..domain.bank import UnitPlate, bank_capacity, validate_bank_config
from ..domain.enums import BankConfig, LoadabilityClass
from ..electrical import formulas as F
from .technical import secondary_conductor_loss_kwh, transformer_site_energy_loss_kwh



def _classify_loadability(ratio: float, th: dict) -> str:
    if ratio > th["overloaded_critical"]:
        return LoadabilityClass.OVERLOADED_CRITICAL.value
    if ratio >= th["overloaded"]:
        return LoadabilityClass.OVERLOADED.value
    if ratio >= th["high_load"]:
        return LoadabilityClass.HIGH_LOAD.value
    if ratio >= th["adequate"]:
        return LoadabilityClass.ADEQUATE.value
    if ratio >= th["underutilized"]:
        return LoadabilityClass.UNDERUTILIZED.value
    return LoadabilityClass.VERY_UNDERUTILIZED.value


def analyze_feeder(tables: dict[str, pd.DataFrame], cfg: Config | None = None,
                   with_risk_proxy: bool = True) -> dict[str, pd.DataFrame]:
    """Ejecuta el balance de un alimentador y devuelve tablas GOLD.

    ``with_risk_proxy`` calcula el proxy de riesgo por caída de consumo; se
    desactiva cuando el modelo ML (F7) lo va a reemplazar, para no pagar dos
    veces el pivote del histórico.
    """
    cfg = cfg or load_config()
    fid = tables["header_meters"]["feeder_id"].iloc[0]
    k = float(cfg.electrical["loss_factor_k"])
    th_load = cfg.thresholds["loadability"]

    consumption = tables["consumption"]
    header = tables["header_meters"]
    sites = tables["sites"]
    units = tables["transformer_units"]
    customers = tables["customers"]
    streetlights = tables["streetlights"]

    n_months = header.shape[0]
    hours_month = float(cfg.electrical["hours_per_month"])
    hours_period = hours_month * n_months

    energy_header = float(header["kwh"].sum())
    energy_billed = float(consumption["kwh"].sum())

    # --- Alumbrado público (§10): consumo conocido NO facturado ---
    # Se calcula POR LUMINARIA y se acumula en SU puesto de transformación por
    # traza (§10.2): repartirlo uniformemente distorsiona la cargabilidad.
    from .streetlight import annual_hours_on
    lat = float(cfg.streetlight.get("latitude_default", 0.0))
    hours_on = annual_hours_on(lat, cfg)   # efemérides si use_ephemeris, si no default
    tech = cfg.streetlight["technology"]
    ap_by_site: dict[str, float] = {}
    energy_streetlight = 0.0
    for r in streetlights.itertuples():
        t = tech.get(r.technology, tech["led"])
        p_kw = r.lamp_w / 1000.0 * (1.0 + t["ballast_loss_frac"])
        e = p_kw * hours_on * 30.0 * n_months
        energy_streetlight += e
        tx = getattr(r, "transformer_site_id", None)
        if tx is not None and not (isinstance(tx, float) and pd.isna(tx)):
            ap_by_site[tx] = ap_by_site.get(tx, 0.0) + e

    # --- Pérdidas técnicas (§12) por puesto de transformación ---
    fc = float(cfg.electrical["default_load_factor"])
    site_pf = float(cfg.electrical["default_site_pf"])
    fp = F.loss_factor(fc, k)
    billed_by_site = consumption.merge(
        customers[["customer_unit_id", "transformer_site_id"]],
        on="customer_unit_id", how="left",
    ).groupby("transformer_site_id")["kwh"].sum()

    load_rows, energy_technical = [], 0.0
    units_by_site = {sid: g for sid, g in units.groupby("site_id")}
    for _, s in sites.iterrows():
        sid = s["site_id"]
        g = units_by_site.get(sid)
        if g is None:
            continue
        plates = [UnitPlate(r.sn_kva, r.p0_kw, r.pk_kw, r.voltage_ln) for r in g.itertuples()]
        cfg_bank = BankConfig(s["bank_config"])
        cap, headroom = bank_capacity(cfg_bank, plates)
        site_energy = float(billed_by_site.get(sid, 0.0))
        # AP del puesto por traza (§10.2), no repartida uniformemente
        site_energy += ap_by_site.get(sid, 0.0)
        p_mean = F.mean_power_kw(site_energy, hours_period) if site_energy > 0 else 0.0
        s_max = (p_mean / fc) / site_pf if p_mean > 0 else 0.0
        loss = transformer_site_energy_loss_kwh(plates, s_max, cap, fp, hours_period)
        energy_technical += loss
        ratio = s_max / cap if cap > 0 else 0.0
        load_rows.append({
            "feeder_id": fid, "site_id": sid, "pole_id": s.get("pole_id"),
            "bank_config": s["bank_config"], "n_units": len(plates),
            "capacity_kva": round(cap, 2), "s_max_kva": round(s_max, 2),
            "loadability": round(ratio, 4),
            "loadability_class": _classify_loadability(ratio, th_load),
            "single_phase_headroom_kva": round(headroom, 2),
            "energy_technical_kwh": round(loss, 1),
            "bank_quality_flags": ",".join(validate_bank_config(cfg_bank, plates)),
        })
    energy_technical += secondary_conductor_loss_kwh(
        energy_billed + energy_streetlight,
        float(cfg.electrical["secondary_loss_frac"]), fp)

    # --- Balance jerárquico (§13) ---
    # ENS (§7.6): energía no suministrada por fallas; no es pérdida.
    from ..topology import estimate_ens_kwh
    ens = estimate_ens_kwh(tables.get("switching_events"))
    # Transferencias entre alimentadores: se acreditan a nivel de sistema
    # (apply_transfer_credits) tras detectarlas; aquí el término base es 0.
    transferred = 0.0
    losses_total = energy_header + transferred - energy_billed - energy_streetlight - ens
    # La PNT se define POR DIFERENCIA: es una identidad contable, no una medición
    # independiente. Por eso el "cierre" NO puede verificarse recomputando esta
    # misma resta (daría 0 siempre); se verifica con coherencia física (abajo).
    pnt = losses_total - energy_technical
    pnt_pct = 100.0 * pnt / energy_header if energy_header else 0.0
    tech_pct = 100.0 * energy_technical / energy_header if energy_header else 0.0
    total_pct = 100.0 * losses_total / energy_header if energy_header else 0.0

    # --- Verificaciones de coherencia del balance (§13, §22.3) ---
    thb = cfg.thresholds["balance"]
    checks = {
        "pnt_non_negative": bool(pnt >= 0),
        "accounted_within_header": bool(
            energy_billed + energy_streetlight + ens <= energy_header * 1.0001),
        "total_losses_plausible": bool(0.0 <= total_pct <= float(thb["total_losses_max_pct"])),
        "technical_plausible": bool(
            float(thb["technical_min_pct"]) <= tech_pct <= float(thb["technical_max_pct"])),
        "header_positive": bool(energy_header > 0),
    }
    failed = [name for name, ok in checks.items() if not ok]

    balance = pd.DataFrame([{
        "feeder_id": fid,
        "energy_header_kwh": round(energy_header, 1),
        "energy_billed_kwh": round(energy_billed, 1),
        "energy_streetlight_kwh": round(energy_streetlight, 1),
        "energy_ens_kwh": round(ens, 1),
        "energy_technical_kwh": round(energy_technical, 1),
        "losses_total_kwh": round(losses_total, 1),
        "pnt_kwh": round(pnt, 1),
        "pnt_pct": round(pnt_pct, 3),
        "technical_pct": round(tech_pct, 3),
        "total_losses_pct": round(total_pct, 3),
        # Cierre verificado por coherencia física, NO por la identidad contable.
        "balance_coherent": len(failed) == 0,
        "failed_checks": ",".join(failed),
        # Discrepancia contra una estimación independiente de PNT (DSSE). Se
        # rellena en analyze_feeder_full cuando F6 está disponible; None => no verificable.
        "pnt_independent_kwh": None,
        "unexplained_pct": None,
        "pnt_negative_alert": bool(pnt < 0),
        "n_customers": int(customers.shape[0]),
        "n_tx_sites": int(sites.shape[0]),
        "n_streetlights": int(streetlights.shape[0]),
        "n_months": n_months,
    }])

    loadability = pd.DataFrame(load_rows)
    out = {"feeder_balance": balance, "transformer_loadability": loadability}
    if with_risk_proxy:
        risk = _customer_risk(consumption, cfg)
        risk["feeder_id"] = fid
        out["customer_risk"] = risk
    return out


def _customer_risk(consumption: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Proxy de riesgo por caída de consumo (base del mecanismo M1, §15.2).

    Score = magnitud relativa de la mayor caída sostenida respecto al nivel
    previo. No es el modelo PU (F7); alimenta el ranking preliminar y el tablero.
    """
    th = cfg.thresholds["label_mining"]
    drop_pct = float(th["drop_recovery_pct"])
    piv = consumption.pivot_table(index="customer_unit_id", columns="year_month",
                                  values="kwh", aggfunc="sum").fillna(0.0)
    vals = piv.to_numpy()
    if vals.shape[1] < 4:
        scores = np.zeros(vals.shape[0])
    else:
        baseline = np.median(vals[:, : vals.shape[1] // 3], axis=1)
        recent_min = vals.min(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            rel_drop = np.where(baseline > 0, (baseline - recent_min) / baseline, 0.0)
        scores = np.clip(rel_drop, 0, 1)
    out = pd.DataFrame({
        "customer_unit_id": piv.index,
        "risk_score": np.round(scores, 4),
        "flagged_drop": scores >= drop_pct,
    })
    return out.sort_values("risk_score", ascending=False).reset_index(drop=True)
