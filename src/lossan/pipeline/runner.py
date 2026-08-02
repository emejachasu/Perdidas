"""Orquestador por alimentador con procesamiento incremental por hash (§2.3).

El alimentador es la unidad atómica y clave de partición. Cada uno se reprocesa
solo si su ``input_hash`` cambió. Se registra el avance por alimentador para el
dashboard (qué fases del pipeline se completaron).
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
from loguru import logger

from ..config import Config, load_config
from ..lakehouse import Lakehouse, feeder_input_hash
from .balance import analyze_feeder

# Fases del pipeline reportadas como avance (§20). Las de fase >F5 se declaran
# como pendientes (planned) para que el tablero muestre el roadmap real.
PIPELINE_STAGES = [
    "ingest",            # F1
    "topology",          # F2 (placeholder en F0)
    "electrical",        # F3
    "power_flow",        # F4 (planned)
    "balance",           # F5
    "state_estimation",  # F6 (planned)
    "ml_risk",           # F7 (proxy en F0)
    "prioritization",    # F8 (planned)
]
STAGES_DONE_F0 = {"ingest", "electrical", "balance", "ml_risk"}


def _bronze_entities(lake: Lakehouse, fid: str) -> dict[str, pd.DataFrame]:
    entities = ["poles", "sites", "transformer_units", "customers",
                "streetlights", "consumption", "header_meters"]
    return {e: lake.read_entity("bronze", e, fid) for e in entities}


def list_feeders(lake: Lakehouse) -> list[str]:
    base = lake.root / "bronze" / "header_meters"
    if not base.exists():
        return []
    feeders = sorted(p.name.split("=", 1)[1] for p in base.glob("feeder_id=*"))
    return feeders


def _process_one(root: str, fid: str, force: bool) -> dict:
    cfg = load_config()
    lake = Lakehouse(root)
    tables = _bronze_entities(lake, fid)
    ihash = feeder_input_hash(
        tables["sites"], tables["transformer_units"],
        tables["customers"], tables["consumption"], tables["header_meters"],
        extra=cfg.active_profile_name,
    )
    if not force and not lake.needs_recompute(fid, ihash):
        return {"feeder_id": fid, "status": "skipped", "input_hash": ihash}

    t0 = time.perf_counter()
    gold = analyze_feeder(tables, cfg)
    for entity, df in gold.items():
        lake.write_partition("gold", entity, fid, df)

    bal = gold["feeder_balance"].iloc[0]
    status = pd.DataFrame([{
        "feeder_id": fid,
        "input_hash": ihash,
        "stages_total": len(PIPELINE_STAGES),
        "stages_done": len(STAGES_DONE_F0),
        "progress_pct": round(100.0 * len(STAGES_DONE_F0) / len(PIPELINE_STAGES), 1),
        "stages_done_list": ",".join(sorted(STAGES_DONE_F0)),
        "balance_closed": bool(abs(bal["residual_pct"]) < 0.5 and not bal["pnt_negative_alert"]),
        "pnt_pct": float(bal["pnt_pct"]),
        "technical_pct": float(bal["technical_pct"]),
        "n_customers": int(bal["n_customers"]),
        "n_tx_sites": int(bal["n_tx_sites"]),
        "runtime_s": round(time.perf_counter() - t0, 3),
    }])
    lake.write_partition("gold", "feeder_status", fid, status)
    lake.mark_done(fid, ihash)
    return {"feeder_id": fid, "status": "processed", "input_hash": ihash}


def run(root: str, feeders: list[str] | None = None, force: bool = False,
        workers: int | None = None, cfg: Config | None = None) -> dict:
    """Ejecuta el pipeline sobre todos (o algunos) alimentadores."""
    cfg = cfg or load_config()
    lake = Lakehouse(root)
    feeders = feeders or list_feeders(lake)
    if not feeders:
        logger.warning("No hay alimentadores en BRONZE. ¿Generaste el universo?")
        return {"processed": 0, "skipped": 0, "feeders": 0}

    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    t0 = time.perf_counter()
    results = []
    if workers == 1 or len(feeders) == 1:
        for fid in feeders:
            results.append(_process_one(root, fid, force))
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_process_one, root, fid, force) for fid in feeders]
            for f in futs:
                results.append(f.result())

    processed = sum(1 for r in results if r["status"] == "processed")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    elapsed = time.perf_counter() - t0
    logger.info(f"Pipeline: {processed} procesados, {skipped} reutilizados en {elapsed:.2f}s")
    return {"processed": processed, "skipped": skipped, "feeders": len(feeders),
            "elapsed_s": round(elapsed, 3)}
