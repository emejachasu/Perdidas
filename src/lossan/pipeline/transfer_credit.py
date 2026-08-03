"""Acreditación de energía transferida al balance (§7.3/§7.4) — nivel sistema.

Tras detectar transferencias entre alimentadores, cuantifica la energía y
actualiza ``feeder_balance`` en GOLD, recalculando la PNT. Se ejecuta después de
procesar los alimentadores porque requiere la cabecera de todos ellos.
"""
from __future__ import annotations

import pandas as pd
from loguru import logger

from ..config import Config
from ..lakehouse import Lakehouse
from ..topology import quantify_transfers


def apply_transfer_credits(lake: Lakehouse, cfg: Config) -> dict:
    """Cuantifica las transferencias y actualiza ``feeder_balance`` en GOLD,
    recalculando la PNT con el término de energía transferida (§7.3)."""
    transfers = lake.read_entity("gold", "feeder_transfers")
    balance = lake.read_entity("gold", "feeder_balance")
    header = lake.read_entity("bronze", "header_meters")
    if transfers.empty or balance.empty or header.empty:
        return {"adjusted": 0}

    wide = header.pivot_table(index="year_month", columns="feeder_id",
                              values="kwh", aggfunc="sum").sort_index()
    credits = quantify_transfers(wide, transfers)
    if credits.empty:
        return {"adjusted": 0}

    cmap = credits.set_index("feeder_id")["transferred_kwh"].to_dict()
    adjusted = 0
    for fid, e_t in cmap.items():
        row = balance[balance["feeder_id"] == fid]
        if row.empty:
            continue
        b = row.iloc[0].to_dict()
        hdr = b["energy_header_kwh"]
        b["energy_transferred_kwh"] = e_t
        losses = hdr + e_t - b["energy_billed_kwh"] - b["energy_streetlight_kwh"] - b["energy_ens_kwh"]
        b["losses_total_kwh"] = round(losses, 1)
        b["pnt_kwh"] = round(losses - b["energy_technical_kwh"], 1)
        b["pnt_pct"] = round(100.0 * b["pnt_kwh"] / hdr, 3) if hdr else 0.0
        b["total_losses_pct"] = round(100.0 * losses / hdr, 3) if hdr else 0.0
        b["pnt_negative_alert"] = bool(b["pnt_kwh"] < 0)
        lake.write_partition("gold", "feeder_balance", fid, pd.DataFrame([b]))
        adjusted += 1
    logger.info(f"Transferencias acreditadas a {adjusted} alimentadores")
    return {"adjusted": adjusted, "credits": cmap}
