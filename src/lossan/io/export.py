"""Exportación de datos de muestra y de resultados a formatos GIS (§18).

- ``export_sample``: vuelca el universo sintético a CSV + GeoPackage + FileGDB,
  para inspección, calibración y para probar el adaptador de ingesta FGDB.
- ``export_results``: publica capas de resultados (riesgo, cargabilidad,
  anomalías, plan de inspección) con geometría, unidas al modelo canónico.

Escritura FGDB vía GDAL/OpenFileGDB (sin arcpy). CRS sintético EPSG:3857.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from loguru import logger

from ..lakehouse import Lakehouse

CRS = "EPSG:3857"
_SAMPLE_ENTITIES = ["poles", "sites", "transformer_units", "customers",
                    "streetlights", "consumption", "header_meters", "segments",
                    "switching_devices", "theft_labels"]


def _node_coords(sites: pd.DataFrame, customers: pd.DataFrame,
                 poles: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """Mapa nodo -> (x, y) para construir geometría de tramos."""
    pxy = poles.set_index("pole_id")[["x", "y"]].to_dict("index")
    coords: dict[str, tuple[float, float]] = {}
    for r in sites.itertuples():
        p = pxy.get(getattr(r, "pole_id", None))
        if p and getattr(r, "node_id", None):
            coords[r.node_id] = (p["x"], p["y"])
            coords[f"{r.node_id}_S"] = (p["x"], p["y"])
    for r in customers.itertuples():
        p = pxy.get(getattr(r, "pole_id", None))
        if p:
            coords[r.customer_unit_id] = (p["x"], p["y"])
    # fuente aproximada al centroide
    if len(poles):
        coords.setdefault(f"{poles['feeder_id'].iloc[0]}-SRC",
                          (float(poles["x"].mean()), float(poles["y"].mean())))
    return coords


def build_geodataframes(root: str, feeders: list[str] | None = None) -> dict:
    """Construye GeoDataFrames de poste (punto), cliente (punto), puesto (punto)
    y tramo (línea) a partir de BRONZE."""
    import geopandas as gpd
    from shapely.geometry import LineString, Point

    lake = Lakehouse(root)
    poles = lake.read_entity("bronze", "poles")
    customers = lake.read_entity("bronze", "customers")
    sites = lake.read_entity("bronze", "sites")
    segments = lake.read_entity("bronze", "segments")
    if feeders:
        poles = poles[poles["feeder_id"].isin(feeders)]
        customers = customers[customers["feeder_id"].isin(feeders)]
        sites = sites[sites["feeder_id"].isin(feeders)]
        segments = segments[segments["feeder_id"].isin(feeders)]

    out = {}
    if not poles.empty:
        out["poles"] = gpd.GeoDataFrame(
            poles, geometry=[Point(xy) for xy in zip(poles.x, poles.y)], crs=CRS)
    if not customers.empty and not poles.empty:
        pxy = poles.set_index("pole_id")[["x", "y"]]
        cj = customers.merge(pxy, left_on="pole_id", right_index=True, how="left").dropna(subset=["x", "y"])
        out["customers"] = gpd.GeoDataFrame(
            cj, geometry=[Point(xy) for xy in zip(cj.x, cj.y)], crs=CRS)
    if not sites.empty and not poles.empty:
        pxy = poles.set_index("pole_id")[["x", "y"]]
        sj = sites.merge(pxy, left_on="pole_id", right_index=True, how="left").dropna(subset=["x", "y"])
        out["sites"] = gpd.GeoDataFrame(
            sj, geometry=[Point(xy) for xy in zip(sj.x, sj.y)], crs=CRS)
    if not segments.empty:
        coords = _node_coords(sites, customers, poles)
        geoms, keep = [], []
        for r in segments.itertuples():
            a, b = coords.get(r.node_from), coords.get(r.node_to)
            if a and b:
                geoms.append(LineString([a, b]))
                keep.append(True)
            else:
                keep.append(False)
        seg = segments[keep].reset_index(drop=True)
        out["segments"] = gpd.GeoDataFrame(seg, geometry=geoms, crs=CRS)
    return out


def _write_layers(layers: dict, out_path: Path, fmt: str) -> Path:
    """Escribe un dict {nombre: GeoDataFrame} a GPKG o FileGDB."""
    fmt = fmt.lower()
    if fmt in ("gpkg", "geopackage"):
        out = out_path.with_suffix(".gpkg")
        driver = "GPKG"
    elif fmt in ("fgdb", "gdb", "openfilegdb"):
        out = out_path.with_suffix(".gdb")
        driver = "OpenFileGDB"
    else:
        raise ValueError(f"Formato no soportado: {fmt} (usa gpkg|fgdb)")
    if out.exists():
        import shutil
        shutil.rmtree(out) if out.is_dir() else out.unlink()
    for name, gdf in layers.items():
        gdf.to_file(out, layer=name, driver=driver)
    return out


# Entidades no espaciales que se embeben como tablas en el contenedor GIS.
_TABULAR_ENTITIES = ["transformer_units", "streetlights", "switching_devices"]


def _write_tables(container: Path, driver: str, tables: dict) -> list[str]:
    """Escribe DataFrames no espaciales como tablas en el mismo GPKG/FGDB."""
    from pyogrio import write_dataframe
    written = []
    for name, df in tables.items():
        try:
            write_dataframe(df, str(container), layer=name, driver=driver, append=True)
            written.append(name)
        except Exception as e:  # pragma: no cover
            logger.warning(f"No se pudo escribir la tabla '{name}': {e}")
    return written


def export_sample(root: str, out_dir: str, fmt: str = "gpkg",
                  feeders: list[str] | None = None) -> dict:
    """Exporta el universo (o unos alimentadores) a CSV + contenedor GIS."""
    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)
    lake = Lakehouse(root)

    # CSV por entidad (para Excel / pandas / calibración)
    csv_dir = outp / "csv"
    csv_dir.mkdir(exist_ok=True)
    written = {}
    for e in _SAMPLE_ENTITIES:
        df = lake.read_entity("bronze", e)
        if df.empty:
            continue
        if feeders:
            df = df[df["feeder_id"].isin(feeders)]
        df.to_csv(csv_dir / f"{e}.csv", index=False)
        written[e] = len(df)

    # capa GIS espacial (poste/cliente/puesto/tramo)
    gis = build_geodataframes(root, feeders)
    gis_path, driver = None, None
    if gis:
        gis_path = _write_layers(gis, outp / "lossan_sample", fmt)
        driver = "OpenFileGDB" if gis_path.suffix == ".gdb" else "GPKG"
        # embeber tablas no espaciales para un dataset auto-contenido
        tabs = {}
        for e in _TABULAR_ENTITIES:
            df = lake.read_entity("bronze", e)
            if not df.empty:
                tabs[e] = df[df["feeder_id"].isin(feeders)] if feeders else df
        _write_tables(gis_path, driver, tabs)
    return {"csv": written, "gis": str(gis_path) if gis_path else None,
            "gis_layers": (list(gis.keys()) + list(_TABULAR_ENTITIES)) if gis else []}


def export_results(root: str, out_path: str, fmt: str = "gpkg") -> dict:
    """Publica capas de resultados con geometría (§18)."""
    import geopandas as gpd

    lake = Lakehouse(root)
    gis = build_geodataframes(root)
    layers = {}

    # CustomerUnits_Risk
    risk = lake.read_entity("gold", "customer_risk")
    if not risk.empty and "customers" in gis:
        cu = gis["customers"].merge(
            risk.drop(columns=[c for c in ("feeder_id",) if c in risk.columns]),
            on="customer_unit_id", how="inner")
        layers["CustomerUnits_Risk"] = cu

    # TransformerSites_Balance (cargabilidad)
    load = lake.read_entity("gold", "transformer_loadability")
    if not load.empty and "sites" in gis:
        ts = gis["sites"].merge(
            load.drop(columns=[c for c in ("feeder_id", "pole_id") if c in load.columns]),
            on="site_id", how="inner")
        layers["TransformerSites_Balance"] = ts

    # Segments_Anomalies
    dq = lake.read_entity("gold", "data_quality_findings")
    if not dq.empty and "segments" in gis:
        seg_an = gis["segments"].merge(
            dq.rename(columns={"element_id": "segment_id"}),
            on="segment_id", how="inner")
        if not seg_an.empty:
            layers["Segments_Anomalies"] = seg_an

    # Inspection_Plan
    plan = lake.read_entity("gold", "inspection_plan")
    if not plan.empty and "sites" in gis:
        ip = gis["sites"][["site_id", "geometry"]].merge(plan, on="site_id", how="inner")
        if not ip.empty:
            layers["Inspection_Plan"] = ip

    if not layers:
        logger.warning("No hay resultados con geometría para exportar.")
        return {"layers": []}
    path = _write_layers(layers, Path(out_path), fmt)
    return {"path": str(path), "layers": list(layers.keys())}
