"""Definiciones Dagster: assets particionados por alimentador (§2.3).

Reutiliza el procesamiento incremental por hash del runner. El alimentador es la
clave de partición; un asset de sistema agrega transferencias, reconciliación y
el plan de campaña.

Ejecutar:
    LOSSAN_LAKEHOUSE=data/lake dagster dev -m lossan.orchestration.dagster_defs
"""
from __future__ import annotations

import os

from dagster import (Definitions, MaterializeResult,
                     StaticPartitionsDefinition, asset)

from ..config import load_config
from ..lakehouse import Lakehouse
from ..pipeline.runner import _detect_transfers, _process_one, list_feeders


def _root() -> str:
    return os.environ.get("LOSSAN_LAKEHOUSE", os.path.join(os.getcwd(), "data", "lake"))


def _feeder_partitions() -> StaticPartitionsDefinition:
    try:
        feeders = list_feeders(Lakehouse(_root()))
    except Exception:
        feeders = []
    return StaticPartitionsDefinition(feeders or ["F0000"])


feeder_parts = _feeder_partitions()


@asset(partitions_def=feeder_parts, group_name="por_alimentador",
       description="Análisis completo de un alimentador (incremental por hash).")
def feeder_gold(context) -> MaterializeResult:
    fid = context.partition_key
    level = os.environ.get("LOSSAN_LEVEL", "full")
    res = _process_one(_root(), fid, force=False, level=level)
    return MaterializeResult(metadata={"status": res["status"], "input_hash": res["input_hash"]})


@asset(deps=[feeder_gold], group_name="sistema",
       description="Pasos de sistema: transferencias, reconciliación P/Q y plan.")
def system_results(context) -> MaterializeResult:
    cfg = load_config()
    lake = Lakehouse(_root())
    _detect_transfers(lake)
    from ..pipeline.transfer_credit import apply_transfer_credits
    from ..pipeline.reconciliation import reconcile_all
    from ..pipeline.prioritization_step import build_plan_and_mark

    apply_transfer_credits(lake, cfg)
    rec = reconcile_all(lake, cfg)
    plan = build_plan_and_mark(lake, cfg)
    return MaterializeResult(metadata={"reconciliation_feeders": rec.get("feeders", 0),
                                       "sites_selected": plan.get("selected", 0)})


defs = Definitions(assets=[feeder_gold, system_results])
