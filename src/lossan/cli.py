"""CLI de lossan (§1.1). ``lossan --help`` para ver los comandos."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import typer

from .config import load_config

app = typer.Typer(add_completion=False, help="Plataforma de análisis de pérdidas (F0).")
schema_app = typer.Typer(help="Inspección del esquema canónico.")
app.add_typer(schema_app, name="schema")


def _default_root() -> str:
    return os.environ.get("LOSSAN_LAKEHOUSE", str(Path.cwd() / "data" / "lake"))


@app.command()
def generate(
    root: str = typer.Option(None, help="Raíz del lakehouse."),
    profile: str = typer.Option(None, help="Perfil de escala (demo|full). Sobrescribe config."),
) -> None:
    """Genera el universo sintético en la capa BRONZE."""
    from .synth import generate_universe

    root = root or _default_root()
    cfg = load_config()
    if profile:
        cfg._scale["active_profile"] = profile  # override en memoria
    typer.echo(f"Generando universo (perfil={cfg.active_profile_name}) en {root} ...")
    counts = generate_universe(root, cfg)
    typer.echo("Conteos reales generados (primer informe de ingesta, §2.1):")
    typer.echo(json.dumps(counts, indent=2))


@app.command()
def run(
    root: str = typer.Option(None, help="Raíz del lakehouse."),
    force: bool = typer.Option(False, help="Reprocesar aunque el hash no haya cambiado."),
    workers: int = typer.Option(None, help="Procesos paralelos (default: núcleos-1)."),
    level: str = typer.Option("full", help="'full' (todas las fases) o 'n1' (tamizaje rápido)."),
) -> None:
    """Ejecuta el pipeline por alimentador (incremental por hash)."""
    from .pipeline.runner import run as run_pipeline

    root = root or _default_root()
    result = run_pipeline(root, force=force, workers=workers, level=level)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def bench(
    feeders: int = typer.Option(24, help="Nº de alimentadores sintéticos a generar."),
    level: str = typer.Option("n1", help="Nivel del pipeline: 'n1' (tamizaje) o 'full'."),
    root: str = typer.Option(None, help="Raíz del lakehouse (temporal por defecto)."),
    target: int = typer.Option(960, help="Nº de alimentadores objetivo para extrapolar."),
) -> None:
    """Prueba de escala (§2.1, §19.8): genera N alimentadores, corre el pipeline
    y extrapola el tiempo a la volumetría objetivo."""
    import tempfile, time as _t

    from .config import load_config
    from .pipeline.runner import run as run_pipeline
    from .synth import generate_universe

    cfg = load_config()
    cfg._scale["profiles"][cfg.active_profile_name]["feeders"] = feeders
    root = root or tempfile.mkdtemp(prefix="lossan_bench_")
    t0 = _t.perf_counter()
    counts = generate_universe(root, cfg)
    t_gen = _t.perf_counter() - t0
    res = run_pipeline(root, force=True, level=level, cfg=cfg)
    per_feeder = res["elapsed_s"] / max(1, feeders)
    workers = max(1, (os.cpu_count() or 2) - 1)
    extrap_h = per_feeder * target / 3600.0
    out = {
        "feeders": feeders, "level": level, "counts": counts,
        "gen_s": round(t_gen, 2), "run_s": res["elapsed_s"],
        "s_per_feeder": round(per_feeder, 3), "workers": workers,
        f"extrapolado_{target}_h": round(extrap_h, 2),
        "objetivo_8h": extrap_h <= 8.0,
    }
    typer.echo(json.dumps(out, indent=2, ensure_ascii=False))


@app.command()
def status(root: str = typer.Option(None, help="Raíz del lakehouse.")) -> None:
    """Resumen del avance por alimentador desde GOLD."""
    from .lakehouse import Lakehouse

    root = root or _default_root()
    lake = Lakehouse(root)
    df = lake.read_entity("gold", "feeder_status")
    if df.empty:
        typer.echo("Sin resultados. Ejecuta 'lossan generate' y 'lossan run'.")
        raise typer.Exit(code=1)
    cols = ["feeder_id", "progress_pct", "balance_closed", "pnt_pct", "technical_pct", "runtime_s"]
    typer.echo(df[cols].to_string(index=False))
    typer.echo(f"\nAlimentadores: {len(df)} | Balance cerrado: {int(df['balance_closed'].sum())}")


@schema_app.command("inspect")
def schema_inspect() -> None:
    """Imprime el esquema canónico de cada entidad (§4, §5)."""
    from .domain.models import CANONICAL_MODELS

    for name, model in CANONICAL_MODELS.items():
        typer.echo(f"\n=== {name} ({model.__name__}) ===")
        for field, info in model.model_fields.items():
            typ = getattr(info.annotation, "__name__", str(info.annotation))
            req = "requerido" if info.is_required() else "opcional"
            typer.echo(f"  - {field}: {typ} [{req}]")


@schema_app.command("template")
def schema_template(
    out: str = typer.Option("config/schema_mapping.generated.yaml", help="Ruta de salida."),
) -> None:
    """Genera un archivo editable para MODELAR el mapeo de tu SIG al modelo
    canónico (cada campo canónico -> campo de tu FGDB, con tipo y obligatoriedad)."""
    from .domain.models import CANONICAL_MODELS

    lines = [
        "# Plantilla de modelado de datos de entrada del SIG.",
        "# Rellena 'layer' con tu feature class y cada '<canónico>: <TU_CAMPO>'.",
        "# Comentarios [req]/[opc] y (tipo) indican obligatoriedad y tipo esperado.",
        "feeder_field: FEEDER_ID   # campo global con el id de alimentador",
        "layers:",
    ]
    spatial = {"poles", "sites", "segments", "customers", "streetlights", "switching_devices"}
    for name, model in CANONICAL_MODELS.items():
        if name not in spatial:
            continue
        lines.append(f"  {name}:")
        lines.append(f"    layer: \"\"            # <-- feature class de tu FGDB para '{name}'")
        lines.append("    fields:")
        for field, info in model.model_fields.items():
            if field in ("feeder_id_declared", "feeder_id_traced", "run_id",
                         "quality_flags", "created_date"):
                continue
            typ = getattr(info.annotation, "__name__", str(info.annotation))
            req = "req" if info.is_required() else "opc"
            lines.append(f"      {field}: \"\"        # [{req}] ({typ})")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    typer.echo(f"Plantilla de modelado escrita en: {out}")


@app.command("export-sample")
def export_sample_cmd(
    root: str = typer.Option(None, help="Raíz del lakehouse."),
    out: str = typer.Option("export/sample", help="Carpeta de salida."),
    fmt: str = typer.Option("gpkg", help="Formato GIS: gpkg | fgdb."),
    feeders: str = typer.Option(None, help="Alimentadores separados por coma (ej. F0000,F0001)."),
) -> None:
    """Exporta datos de prueba (CSV + capa GIS) para calibrar y probar la ingesta."""
    from .io import export_sample

    root = root or _default_root()
    fl = feeders.split(",") if feeders else None
    res = export_sample(root, out, fmt=fmt, feeders=fl)
    typer.echo(json.dumps(res, indent=2))


@app.command("export-results")
def export_results_cmd(
    root: str = typer.Option(None, help="Raíz del lakehouse."),
    out: str = typer.Option("export/results", help="Ruta de salida (sin extensión)."),
    fmt: str = typer.Option("gpkg", help="Formato GIS: gpkg | fgdb."),
) -> None:
    """Publica capas de resultados con geometría (riesgo, cargabilidad, plan)."""
    from .io import export_results

    root = root or _default_root()
    res = export_results(root, out, fmt=fmt)
    typer.echo(json.dumps(res, indent=2))


@app.command("fgdb-layers")
def fgdb_layers(path: str = typer.Argument(..., help="Ruta a la .gdb")) -> None:
    """Lista las capas de una File Geodatabase."""
    from .io import list_layers

    for name in list_layers(path):
        typer.echo(name)


@app.command("ingest-fgdb")
def ingest_fgdb_cmd(
    path: str = typer.Argument(..., help="Ruta a la .gdb"),
    root: str = typer.Option(None, help="Raíz del lakehouse."),
    mapping: str = typer.Option(None, help="YAML de mapeo (default: config/schema_mapping.yaml)."),
    extract_date: str = typer.Option(None, help="Fecha de extracción (YYYY-MM-DD)."),
) -> None:
    """Ingiere una FGDB a BRONZE aplicando el mapeo de esquema (§2.5)."""
    import yaml

    from .config import config_dir
    from .io import ingest_fgdb

    root = root or _default_root()
    mpath = Path(mapping) if mapping else config_dir() / "schema_mapping.yaml"
    mp = yaml.safe_load(Path(mpath).read_text())
    counts = ingest_fgdb(path, root, mp, extract_date=extract_date)
    typer.echo("Conteos reales ingeridos (§2.1):")
    typer.echo(json.dumps(counts, indent=2))


@app.command("ingest-cnel")
def ingest_cnel_cmd(
    path: str = typer.Argument(..., help="Ruta a la .gdb con el modelo CNEL/SIGELEC."),
    root: str = typer.Option(None, help="Raíz del lakehouse."),
    mapping: str = typer.Option(None, help="YAML de mapeo (default: config/cnel_mapping.yaml)."),
    extract_date: str = typer.Option(None, help="Fecha de extracción (YYYY-MM-DD)."),
) -> None:
    """Ingiere una FGDB con el modelo de datos de CNEL EP resolviendo la
    jerarquía Estructura→Puesto→Unidad y PuntoCarga→ConexionConsumidor."""
    from .io.cnel import ingest_cnel_fgdb, load_cnel_mapping

    root = root or _default_root()
    mp = load_cnel_mapping(mapping)
    counts = ingest_cnel_fgdb(path, root, mp, extract_date=extract_date)
    hier = counts.pop("_hierarchy", [])
    typer.echo("Conteos ingeridos (§2.1):")
    typer.echo(json.dumps(counts, indent=2))
    if hier:
        typer.echo("\nJerarquía puesto/unidad detectada:")
        for r in hier:
            typer.echo(f"  {r['relacion']}: {r['padres']} padres, {r['hijos']} hijos "
                       f"(máx {r['hijos_por_padre_max']}/padre, "
                       f"{r['padres_multi']} con más de uno)")


@app.command("cnel-domains")
def cnel_domains_cmd(
    path: str = typer.Argument(..., help="Ruta a la .gdb"),
    domain: str = typer.Option(None, help="Filtrar por nombre de dominio."),
) -> None:
    """Lista los dominios reales de la GDB para verificar el mapeo de fases y
    configuración de banco de `config/cnel_mapping.yaml`."""
    try:
        from osgeo import ogr
    except Exception:
        typer.echo("Requiere GDAL/osgeo. Alternativa: revisar los dominios en ArcGIS Pro.")
        raise typer.Exit(1)
    ds = ogr.Open(path)
    if ds is None:
        typer.echo(f"No se pudo abrir {path}")
        raise typer.Exit(1)
    import xml.etree.ElementTree as ET
    md = ds.GetMetadata("xml:FileGDB") or []
    if not md:
        typer.echo("La GDB no expone dominios por esta vía; usar ArcGIS Pro.")
        raise typer.Exit(1)
    root_el = ET.fromstring(md[0])
    for dom in root_el.iter():
        name_el = dom.find("DomainName")
        if name_el is None:
            continue
        name = name_el.text or ""
        if domain and domain.lower() not in name.lower():
            continue
        typer.echo(f"\n=== {name} ===")
        for cv in dom.iter("CodedValue"):
            code = cv.findtext("Code", "")
            nm = cv.findtext("Name", "")
            typer.echo(f"  {code} = {nm}")


@app.command("ingest-consumption")
def ingest_consumption_cmd(
    path: str = typer.Argument(..., help="CSV/Parquet/Excel de consumo histórico."),
    root: str = typer.Option(None, help="Raíz del lakehouse."),
    map_: str = typer.Option(None, "--map", help="Renombres canónico=fuente separados por coma."),
) -> None:
    """Ingiere el consumo histórico del sistema comercial a BRONZE."""
    from .io import ingest_consumption

    root = root or _default_root()
    fmap = dict(kv.split("=", 1) for kv in map_.split(",")) if map_ else None
    typer.echo(json.dumps(ingest_consumption(path, root, fmap), indent=2))


@app.command("ingest-header")
def ingest_header_cmd(
    path: str = typer.Argument(..., help="CSV/Parquet de cabecera (feeder_id, year_month, kwh)."),
    root: str = typer.Option(None, help="Raíz del lakehouse."),
    map_: str = typer.Option(None, "--map", help="Renombres canónico=fuente separados por coma."),
) -> None:
    """Ingiere el medidor de cabecera por alimentador y mes a BRONZE."""
    from .io import ingest_header

    root = root or _default_root()
    fmap = dict(kv.split("=", 1) for kv in map_.split(",")) if map_ else None
    typer.echo(json.dumps(ingest_header(path, root, fmap), indent=2))


@app.command("data-templates")
def data_templates(
    out: str = typer.Option("export/plantillas", help="Carpeta de salida."),
) -> None:
    """Genera plantillas vacías (CSV + Excel) por cada dato requerido, para que
    los equipos de SIG/Comercial/Operación las llenen."""
    from .io import build_templates

    res = build_templates(out)
    typer.echo(json.dumps(res, indent=2, ensure_ascii=False))


@app.command("report")
def report_cmd(
    feeder: str = typer.Option(None, help="Alimentador (omitir para consolidado regional)."),
    out: str = typer.Option(None, help="Ruta de salida (.pdf o .html)."),
    root: str = typer.Option(None, help="Raíz del lakehouse."),
    no_pdf: bool = typer.Option(False, help="Forzar HTML en vez de PDF."),
) -> None:
    """Genera el reporte ejecutivo por alimentador o consolidado regional (§18)."""
    from .reports import consolidated_report, executive_report

    root = root or _default_root()
    pdf = not no_pdf
    if feeder:
        out = out or f"export/reporte_{feeder}.pdf"
        path = executive_report(root, feeder, out, pdf=pdf)
    else:
        out = out or "export/reporte_consolidado.pdf"
        path = consolidated_report(root, out, pdf=pdf)
    typer.echo(f"Reporte escrito en: {path}")


@app.command("inspection-sheet")
def inspection_sheet_cmd(
    site: str = typer.Argument(..., help="Id del puesto (ej. F0000-TS0007)."),
    out: str = typer.Option(None, help="Ruta de salida (.pdf o .html)."),
    root: str = typer.Option(None, help="Raíz del lakehouse."),
    no_pdf: bool = typer.Option(False, help="Forzar HTML en vez de PDF."),
) -> None:
    """Genera la ficha de inspección por puesto/poste para la cuadrilla (§17.5)."""
    from .reports import inspection_sheet

    root = root or _default_root()
    out = out or f"export/ficha_{site}.pdf"
    path = inspection_sheet(root, site, out, pdf=not no_pdf)
    typer.echo(f"Ficha escrita en: {path}")


@app.command("feeder-report")
def feeder_report(
    feeder: str = typer.Argument(..., help="Id de alimentador (ej. F0000)."),
    root: str = typer.Option(None, help="Raíz del lakehouse."),
) -> None:
    """Analiza los elementos conectados por traza y el desglose de pérdidas."""
    import pandas as pd

    from .lakehouse import Lakehouse
    from .topology import FeederGraph

    root = root or _default_root()
    lake = Lakehouse(root)
    segs = lake.read_entity("bronze", "segments", feeder)
    sites = lake.read_entity("bronze", "sites", feeder)
    if segs.empty:
        typer.echo("Sin topología para ese alimentador. ¿Generaste/ingeriste la red?")
        raise typer.Exit(1)
    cust = lake.read_entity("bronze", "customers", feeder)
    sl = lake.read_entity("bronze", "streetlights", feeder)
    fg = FeederGraph.build(feeder, segs, sites, cust, sl)
    down = fg.subtree_load(fg.source)
    typer.echo(f"=== Elementos conectados a {feeder} (por traza desde la fuente) ===")
    typer.echo(f"  nodos={fg.n_nodes}  tramos={fg.n_edges}")
    typer.echo(f"  clientes aguas abajo={down['n_customers']}  puestos={len(sites)}")
    val = fg.validate()
    typer.echo(f"  validación topológica: {'OK' if not val else val}")

    bal = lake.read_entity("gold", "feeder_balance", feeder)
    if not bal.empty:
        b = bal.iloc[0]
        typer.echo("\n=== Desglose de pérdidas (GOLD) ===")
        typer.echo(f"  Energía cabecera : {b['energy_header_kwh']:.0f} kWh")
        typer.echo(f"  − Facturada      : {b['energy_billed_kwh']:.0f} kWh")
        typer.echo(f"  − Alumbrado púb. : {b['energy_streetlight_kwh']:.0f} kWh")
        typer.echo(f"  − Técnicas       : {b['energy_technical_kwh']:.0f} kWh "
                   f"({b['technical_pct']:.2f}%)")
        typer.echo(f"  = PNT            : {b['pnt_kwh']:.0f} kWh ({b['pnt_pct']:.2f}%)")
        coherent = bool(b.get("balance_coherent", False))
        typer.echo(f"  Cierre coherente : {'sí' if coherent else 'NO'}"
                   + ("" if coherent else f"  [{b.get('failed_checks', '')}]"))
        unexp = b.get("unexplained_pct")
        if unexp is not None and pd.notna(unexp):
            typer.echo(f"  No explicado vs. estimación independiente (DSSE): {unexp:.3f}%")
    else:
        typer.echo("\n(Ejecuta 'lossan run' para el desglose de pérdidas.)")


@app.command()
def dashboard(
    root: str = typer.Option(None, help="Raíz del lakehouse."),
    port: int = typer.Option(8501, help="Puerto del servidor Streamlit."),
) -> None:
    """Lanza el dashboard web por alimentador (Streamlit)."""
    root = root or _default_root()
    app_path = Path(__file__).parent / "dashboard" / "app.py"
    env = dict(os.environ, LOSSAN_LAKEHOUSE=root)
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path),
         "--server.port", str(port), "--server.headless", "true"],
        env=env, check=False,
    )


if __name__ == "__main__":
    app()
