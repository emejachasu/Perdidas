"""Paso de sistema: construye el plan (F8) y marca la fase en el avance.

La priorización usa un único presupuesto de campo sobre todos los candidatos
del sistema, por lo que se ejecuta después de procesar los alimentadores.
"""
from __future__ import annotations

import pandas as pd

from ..config import Config
from ..lakehouse import Lakehouse
from ..prioritization import build_inspection_plan
from .runner import PIPELINE_STAGES


def build_plan_and_mark(lake: Lakehouse, cfg: Config) -> dict:
    res = build_inspection_plan(str(lake.root), cfg)

    # marcar la fase 'prioritization' en el avance de cada alimentador
    status = lake.read_entity("gold", "feeder_status")
    if status.empty:
        return res
    total = len(PIPELINE_STAGES)
    updated = []
    for _, row in status.iterrows():
        done = set(str(row["stages_done_list"]).split(",")) if row["stages_done_list"] else set()
        done.add("prioritization")
        row = row.copy()
        row["stages_done_list"] = ",".join(sorted(done))
        row["stages_done"] = len(done)
        row["progress_pct"] = round(100.0 * len(done) / total, 1)
        updated.append(row)
    df = pd.DataFrame(updated)
    for fid, g in df.groupby("feeder_id"):
        lake.write_partition("gold", "feeder_status", fid, g)
    return res
