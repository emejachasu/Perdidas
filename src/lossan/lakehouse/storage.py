"""Almacenamiento lakehouse particionado por ``feeder_id`` (§2.2, §2.3).

BRONZE  extracto crudo inmutable (con hash de origen y fecha)
SILVER  modelo canónico validado y normalizado (Parquet particionado)
GOLD    resultados (pérdidas, balances, scores, plan)

DuckDB es el motor analítico principal sobre Parquet: maneja el volumen en una
sola máquina, sin servidor (elección de §2.2). El hash por alimentador habilita
el procesamiento incremental obligatorio (§2.3).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pandas as pd

_LAYERS = ("bronze", "silver", "gold")


class Lakehouse:
    """Gestiona rutas, escritura Parquet particionada y consultas DuckDB."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        for layer in _LAYERS:
            (self.root / layer).mkdir(parents=True, exist_ok=True)
        (self.root / "_state").mkdir(parents=True, exist_ok=True)

    # --- rutas ---
    def partition_path(self, layer: str, entity: str, feeder_id: str,
                       extra: dict[str, str] | None = None) -> Path:
        assert layer in _LAYERS, layer
        parts = [self.root, layer, entity, f"feeder_id={feeder_id}"]
        if extra:
            for k, v in extra.items():
                parts.append(f"{k}={v}")
        return Path(*[str(p) for p in parts])

    # --- escritura ---
    def write_partition(self, layer: str, entity: str, feeder_id: str,
                        df: pd.DataFrame, extra: dict[str, str] | None = None) -> Path:
        path = self.partition_path(layer, entity, feeder_id, extra)
        path.mkdir(parents=True, exist_ok=True)
        out = path / "data.parquet"
        df.to_parquet(out, index=False)
        return out

    def entity_glob(self, layer: str, entity: str) -> str:
        return str(self.root / layer / entity / "**" / "*.parquet")

    # --- lectura vía DuckDB ---
    def query(self, sql: str) -> pd.DataFrame:
        con = duckdb.connect()
        try:
            return con.execute(sql).fetchdf()
        finally:
            con.close()

    def read_entity(self, layer: str, entity: str,
                    feeder_id: str | None = None) -> pd.DataFrame:
        if feeder_id is not None:
            base = self.partition_path(layer, entity, feeder_id)
            glob = str(base / "**" / "*.parquet")
        else:
            glob = self.entity_glob(layer, entity)
        con = duckdb.connect()
        try:
            return con.execute(
                "SELECT * FROM read_parquet(?, hive_partitioning=1, union_by_name=1)",
                [glob],
            ).fetchdf()
        except duckdb.IOException:
            return pd.DataFrame()
        finally:
            con.close()

    # --- estado incremental (input_hash por alimentador, §2.3) ---
    def _state_file(self) -> Path:
        return self.root / "_state" / "input_hash.json"

    def load_state(self) -> dict[str, str]:
        f = self._state_file()
        if f.exists():
            return json.loads(f.read_text())
        return {}

    def save_state(self, state: dict[str, str]) -> None:
        self._state_file().write_text(json.dumps(state, indent=2, sort_keys=True))

    def needs_recompute(self, feeder_id: str, input_hash: str) -> bool:
        return self.load_state().get(feeder_id) != input_hash

    def mark_done(self, feeder_id: str, input_hash: str) -> None:
        state = self.load_state()
        state[feeder_id] = input_hash
        self.save_state(state)


def feeder_input_hash(*frames: pd.DataFrame, extra: str = "") -> str:
    """Hash determinístico de las entradas de un alimentador (§2.3).

    Combina geometría + atributos + ventana de consumo. Si no cambió, el
    resultado se reutiliza.
    """
    h = hashlib.sha256()
    for df in frames:
        # ordenar columnas y filas para estabilidad
        cols = sorted(df.columns)
        payload = df[cols].sort_values(cols).to_csv(index=False).encode("utf-8")
        h.update(payload)
    h.update(extra.encode("utf-8"))
    return h.hexdigest()[:16]
