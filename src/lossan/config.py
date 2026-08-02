"""Carga de configuración desde ``config/*.yaml``.

Criterio de aceptación §22.13: ningún valor de volumetría, costo, tarifa o
umbral puede aparecer en el código; todo se lee desde ``config/``.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml


def _repo_root() -> Path:
    # src/lossan/config.py -> repo root
    return Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    env = os.environ.get("LOSSAN_CONFIG_DIR")
    if env:
        return Path(env)
    return _repo_root() / "config"


@functools.lru_cache(maxsize=None)
def _load_file(name: str) -> dict[str, Any]:
    path = config_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"Falta el archivo de configuración: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class Config:
    """Acceso unificado y cacheado a la configuración del proyecto."""

    def __init__(self) -> None:
        self._scale = _load_file("scale.yaml")
        self._budget = _load_file("budget.yaml")
        self._electrical = _load_file("electrical.yaml")
        self._thresholds = _load_file("thresholds.yaml")
        self._streetlight = _load_file("streetlight.yaml")

    # --- bloques crudos ---
    @property
    def scale(self) -> dict[str, Any]:
        return self._scale["scale"]

    @property
    def budget(self) -> dict[str, Any]:
        return self._budget["budget"]

    @property
    def economics(self) -> dict[str, Any]:
        return self._budget["economics"]

    @property
    def electrical(self) -> dict[str, Any]:
        return self._electrical["electrical"]

    @property
    def thresholds(self) -> dict[str, Any]:
        return self._thresholds

    @property
    def streetlight(self) -> dict[str, Any]:
        return self._streetlight["streetlight"]

    # --- perfil activo (escala de una corrida) ---
    @property
    def active_profile_name(self) -> str:
        return self._scale.get("active_profile", "demo")

    @property
    def active_profile(self) -> dict[str, Any]:
        name = self.active_profile_name
        return self._scale["profiles"][name]

    def get(self, dotted: str, default: Any = None) -> Any:
        """Lee un valor por ruta con puntos, p.ej. ``economics.tariff_usd_per_kwh``."""
        blocks = {
            "scale": self.scale,
            "budget": self.budget,
            "economics": self.economics,
            "electrical": self.electrical,
            "streetlight": self.streetlight,
        }
        head, _, rest = dotted.partition(".")
        node: Any = blocks.get(head, self._thresholds.get(head, {}))
        for part in rest.split("."):
            if not part:
                break
            node = node[part]
        return node if node is not None else default


@functools.lru_cache(maxsize=1)
def load_config() -> Config:
    return Config()


def reset_cache() -> None:
    """Limpia la cache (para tests que cambian ``LOSSAN_CONFIG_DIR``)."""
    _load_file.cache_clear()
    load_config.cache_clear()
