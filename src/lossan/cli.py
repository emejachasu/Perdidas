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
) -> None:
    """Ejecuta el pipeline por alimentador (incremental por hash)."""
    from .pipeline.runner import run as run_pipeline

    root = root or _default_root()
    result = run_pipeline(root, force=force, workers=workers)
    typer.echo(json.dumps(result, indent=2))


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
