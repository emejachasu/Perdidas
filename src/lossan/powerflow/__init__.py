"""Módulo M4 — flujo de potencia (§11).

Doble motor: sweep propio (redes radiales) y exportador a OpenDSS. Ambos se
comparan automáticamente dentro de tolerancia.
"""
from .sweep import RadialNetwork, SweepResult, solve_bfs, network_from_feeder
from .sweep3ph import (ThreePhaseNetwork, Sweep3phResult, solve_bfs_3ph,
                       zmatrix_from_sequence)
from .opendss_export import export_dss, export_dss_3ph
from .validate import compare_engines, compare_engines_3ph

__all__ = [
    "RadialNetwork", "SweepResult", "solve_bfs", "network_from_feeder",
    "ThreePhaseNetwork", "Sweep3phResult", "solve_bfs_3ph", "zmatrix_from_sequence",
    "export_dss", "export_dss_3ph", "compare_engines", "compare_engines_3ph",
]
