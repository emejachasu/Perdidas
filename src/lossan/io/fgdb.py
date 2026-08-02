"""Lectura de File Geodatabase a la capa BRONZE (§2.5, §2.1).

Usa GDAL/OpenFileGDB vía pyogrio (sin arcpy). Aplica un mapeo de esquema
declarativo (``config/schema_mapping.yaml``) para traducir los nombres de capas
y campos del SIG del cliente al modelo canónico. Particiona por ``feeder_id``.

A escala de millones de elementos, GDAL lee por capa con proyección de columnas;
la partición por alimentador permite el procesamiento incremental posterior.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from loguru import logger

from ..lakehouse import Lakehouse


def list_layers(path: str) -> list[str]:
    """Lista las capas (feature classes / tablas) de una FGDB."""
    import pyogrio
    return [name for name, _ in pyogrio.list_layers(path)]


def read_layer(path: str, layer: str, columns: list[str] | None = None):
    """Lee una capa como GeoDataFrame (o DataFrame si no tiene geometría)."""
    import geopandas as gpd
    try:
        return gpd.read_file(path, layer=layer, columns=columns, engine="pyogrio")
    except Exception:
        from pyogrio import read_dataframe
        return read_dataframe(path, layer=layer, columns=columns, read_geometry=False)


def _apply_mapping(gdf, entity_map: dict, default_feeder_field: str | None,
                   entity: str) -> pd.DataFrame:
    """Renombra campos fuente -> canónicos y deriva geometría/feeder_id."""
    fields = entity_map.get("fields", {})
    out = pd.DataFrame()
    for canonical, source in fields.items():
        if source in gdf.columns:
            out[canonical] = gdf[source].to_numpy()
        else:
            logger.warning(f"[{entity}] campo fuente ausente: {source} -> {canonical}")

    # feeder_id (declarado)
    ff = entity_map.get("feeder_field", default_feeder_field)
    if ff and ff in gdf.columns:
        out["feeder_id"] = gdf[ff].astype(str).to_numpy()
        out["feeder_id_declared"] = out["feeder_id"]

    # geometría -> coordenadas / longitud
    geom_col = getattr(gdf, "geometry", None)
    if geom_col is not None and hasattr(gdf, "geometry"):
        try:
            gtype = gdf.geom_type.dropna().iloc[0] if len(gdf) else ""
        except Exception:
            gtype = ""
        if "Point" in str(gtype):
            out["x"] = gdf.geometry.x.to_numpy()
            out["y"] = gdf.geometry.y.to_numpy()
        elif "Line" in str(gtype):
            if "length_m" not in out.columns:
                out["length_m"] = gdf.geometry.length.to_numpy()
            # nodos extremos si no vienen mapeados
            if "node_from" not in out.columns:
                out["node_from"] = [f"{entity}_{i}_a" for i in range(len(gdf))]
            if "node_to" not in out.columns:
                out["node_to"] = [f"{entity}_{i}_b" for i in range(len(gdf))]
    return out


def ingest_fgdb(path: str, root: str, mapping: dict,
                extract_date: str | None = None) -> dict[str, int]:
    """Ingiere una FGDB a BRONZE según el mapeo. Devuelve conteos reales (§2.1).

    ``mapping``: dict con ``feeder_field`` global y ``layers`` (entidad ->
    {layer, fields, feeder_field}).
    """
    lake = Lakehouse(root)
    default_ff = mapping.get("feeder_field")
    counts: dict[str, int] = {}
    for entity, emap in mapping.get("layers", {}).items():
        layer = emap.get("layer")
        if not layer:
            continue
        try:
            gdf = read_layer(path, layer)
        except Exception as e:
            logger.error(f"No se pudo leer la capa '{layer}' para '{entity}': {e}")
            continue
        df = _apply_mapping(gdf, emap, default_ff, entity)
        if "feeder_id" not in df.columns:
            logger.warning(f"[{entity}] sin feeder_id; se asigna 'UNKNOWN'")
            df["feeder_id"] = "UNKNOWN"
        n = 0
        for fid, part in df.groupby("feeder_id"):
            extra = {"extract_date": extract_date} if extract_date else None
            lake.write_partition("bronze", entity, str(fid), part, extra)
            n += len(part)
        counts[entity] = n
        logger.info(f"Ingerido '{entity}' desde '{layer}': {n} registros")
    return counts
