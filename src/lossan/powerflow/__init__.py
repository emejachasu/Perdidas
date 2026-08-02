"""Módulo M4 — flujo de potencia (§11).

Doble motor: sweep propio (redes radiales) y exportador a OpenDSS. Ambos se
comparan automáticamente dentro de tolerancia.
"""
from .sweep import RadialNetwork, SweepResult, solve_bfs, network_from_feeder
from .opendss_export import export_dss
from .validate import compare_engines

__all__ = [
    "RadialNetwork", "SweepResult", "solve_bfs", "network_from_feeder",
    "export_dss", "compare_engines",
]
