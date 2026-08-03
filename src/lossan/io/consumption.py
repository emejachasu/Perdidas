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


def link_consumption_to_connections(consumption: pd.DataFrame,
                                    customers: pd.DataFrame,
                                    key: str = "cuenta_contrato") -> tuple[pd.DataFrame, dict]:
    """Cruza el consumo comercial con las conexiones del SIG (modelo CNEL).

    En CNEL los identificadores únicos son **CUENTACONTRATO** (sistema
    comercial) y **CODIGOUNICO** (conexión en el SIG). El histórico suele venir
    por cuenta contrato; esta función lo traduce a ``customer_unit_id``
    (CODIGOUNICO) y reporta la tasa de emparejamiento, que es el control de
    calidad más importante de la ingesta: un cruce bajo invalida el balance.

    ``consumption`` debe traer la columna ``key`` (o ya ``customer_unit_id``).
    """
    if consumption is None or consumption.empty:
        return consumption, {"matched": 0, "unmatched": 0, "match_rate": 0.0}

    df = consumption.copy()
    stats: dict = {"key": key}

    if key in df.columns and customers is not None and key in customers.columns:
        lookup = (customers[[key, "customer_unit_id"]]
                  .dropna(subset=[key])
                  .drop_duplicates(subset=[key])
                  .set_index(key)["customer_unit_id"])
        mapped = df[key].map(lookup)
        if "customer_unit_id" in df.columns:
            df["customer_unit_id"] = df["customer_unit_id"].fillna(mapped)
        else:
            df["customer_unit_id"] = mapped
    elif "customer_unit_id" not in df.columns:
        raise ValueError(
            f"El consumo no trae '{key}' ni 'customer_unit_id'. Usa --map para "
            f"indicar qué columna es el identificador.")

    known = set(customers["customer_unit_id"]) if customers is not None else set()
    if known:
        ok = df["customer_unit_id"].isin(known)
    else:
        ok = df["customer_unit_id"].notna()
    matched = int(ok.sum())
    total = int(len(df))
    stats.update({
        "records": total, "matched": matched, "unmatched": total - matched,
        "match_rate": round(matched / total, 4) if total else 0.0,
        "customers_matched": int(df.loc[ok, "customer_unit_id"].nunique()),
    })
    if stats["match_rate"] < 0.95:
        logger.warning(
            f"Cruce comercial↔SIG bajo: {stats['match_rate']:.1%} "
            f"({stats['unmatched']} registros sin conexión). Revisa que el "
            f"identificador sea el correcto (CUENTACONTRATO / CODIGOUNICO).")
    return df, stats


def ingest_consumption(path: str, root: str, field_map: dict | None = None,
                       chunksize: int | None = None) -> dict:
    """Ingiere el consumo histórico a BRONZE (partición por feeder_id).

    Columnas canónicas: customer_unit_id, feeder_id, year_month, kwh,
    [kvarh, estimated]. ``field_map`` renombra {canónico: campo_fuente}.
    """
    lake = Lakehouse(root)
    df = _apply_map(_read_any(path), field_map)

    # Cruce con el SIG (modelo CNEL): traduce CUENTACONTRATO -> CODIGOUNICO y
    # resuelve el feeder_id desde la conexión cuando el comercial no lo trae.
    link_stats: dict = {}
    customers = lake.read_entity("bronze", "customers")
    if not customers.empty:
        needs_link = ("customer_unit_id" not in df.columns
                      or "cuenta_contrato" in df.columns)
        if needs_link:
            df, link_stats = link_consumption_to_connections(df, customers)
        if "feeder_id" not in df.columns and "feeder_id" in customers.columns:
            fmap = (customers.drop_duplicates(subset=["customer_unit_id"])
                    .set_index("customer_unit_id")["feeder_id"])
            df["feeder_id"] = df["customer_unit_id"].map(fmap)

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
    out = {"records": total, "customers": int(df["customer_unit_id"].nunique()),
           "months": len(months), "range": [months[0], months[-1]]}
    if link_stats:
        out["commercial_link"] = link_stats
    return out


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
