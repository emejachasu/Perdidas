"""Ingesta del consumo histórico y de la cabecera desde CSV/tabla (§F1).

El consumo (2,7 M clientes × 36–60 meses) y la cabecera vienen del sistema
comercial/SCADA, no de la FGDB. Este adaptador los normaliza al modelo canónico
y los escribe en BRONZE particionado por ``feeder_id``.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from loguru import logger

from ..lakehouse import Lakehouse

_CONSUMPTION_REQUIRED = ["customer_unit_id", "feeder_id", "year_month", "kwh"]
_HEADER_REQUIRED = ["feeder_id", "year_month", "kwh"]


def _read_any(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() in (".parquet", ".pq"):
        return pd.read_parquet(p)
    if p.suffix.lower() in (".csv", ".txt"):
        return pd.read_csv(p)
    if p.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(p)
    raise ValueError(f"Formato no soportado: {p.suffix}")


def _apply_map(df: pd.DataFrame, field_map: dict | None) -> pd.DataFrame:
    if not field_map:
        return df
    # field_map: canonical <- source
    inv = {src: canon for canon, src in field_map.items() if src in df.columns}
    return df.rename(columns=inv)


def _normalize_year_month(s: pd.Series) -> pd.Series:
    """Lleva la columna de periodo a 'YYYY-MM'."""
    try:
        return pd.to_datetime(s, errors="coerce").dt.strftime("%Y-%m").fillna(s.astype(str))
    except Exception:
        return s.astype(str)


def ingest_consumption(path: str, root: str, field_map: dict | None = None,
                       chunksize: int | None = None) -> dict:
    """Ingiere el consumo histórico a BRONZE (partición por feeder_id).

    Columnas canónicas: customer_unit_id, feeder_id, year_month, kwh,
    [kvarh, estimated]. ``field_map`` renombra {canónico: campo_fuente}.
    """
    lake = Lakehouse(root)
    df = _apply_map(_read_any(path), field_map)
    missing = [c for c in _CONSUMPTION_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas en consumo: {missing}. "
                         f"Usa field_map para renombrar.")
    df["feeder_id"] = df["feeder_id"].astype(str)
    df["year_month"] = _normalize_year_month(df["year_month"])
    df["kwh"] = pd.to_numeric(df["kwh"], errors="coerce").fillna(0.0)
    if "kvarh" in df.columns:
        df["kvarh"] = pd.to_numeric(df["kvarh"], errors="coerce")
    if "estimated" not in df.columns:
        df["estimated"] = False

    total = 0
    for fid, part in df.groupby("feeder_id"):
        lake.write_partition("bronze", "consumption", str(fid), part)
        total += len(part)
    months = sorted(df["year_month"].unique())
    logger.info(f"Consumo ingerido: {total} registros, {df['customer_unit_id'].nunique()} "
                f"clientes, {len(months)} meses [{months[0]}..{months[-1]}]")
    return {"records": total, "customers": int(df["customer_unit_id"].nunique()),
            "months": len(months), "range": [months[0], months[-1]]}


def ingest_header(path: str, root: str, field_map: dict | None = None) -> dict:
    """Ingiere el medidor de cabecera por alimentador y mes a BRONZE."""
    lake = Lakehouse(root)
    df = _apply_map(_read_any(path), field_map)
    missing = [c for c in _HEADER_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas en cabecera: {missing}.")
    df["feeder_id"] = df["feeder_id"].astype(str)
    df["year_month"] = _normalize_year_month(df["year_month"])
    df["kwh"] = pd.to_numeric(df["kwh"], errors="coerce").fillna(0.0)

    total = 0
    for fid, part in df.groupby("feeder_id"):
        lake.write_partition("bronze", "header_meters", str(fid), part)
        total += len(part)
    logger.info(f"Cabecera ingerida: {total} filas, {df['feeder_id'].nunique()} alimentadores")
    return {"rows": total, "feeders": int(df["feeder_id"].nunique())}
