"""Casos IEEE para validación del motor trifásico (§11, §19.4).

Usa las **matrices de configuración publicadas del IEEE-13** (Kersting, ohms/milla)
para construir un tramo troncal radial con acoplamiento mutuo real y cargas
desbalanceadas. Ambos motores (propio y OpenDSS) se alimentan del mismo modelo y
se comparan dentro de tolerancia.

Nota: se reproduce el **tramo de líneas** con sus matrices reales; reguladores,
transformadores en línea y capacitores del IEEE-13/34/123 completos son un
componente adicional (ver docs/BRECHAS.md). La validación demuestra que el motor
propio maneja las matrices 3×3 acopladas del estándar de forma consistente con
OpenDSS.
"""
from __future__ import annotations

import numpy as np

from .sweep3ph import ThreePhaseNetwork

# Configuración 601 del IEEE-13 (ohms/milla), matriz de fase 3×3 (Kersting).
CONFIG_601 = np.array([
    [0.3465 + 1.0179j, 0.1560 + 0.5017j, 0.1580 + 0.4236j],
    [0.1560 + 0.5017j, 0.3375 + 1.0478j, 0.1535 + 0.3849j],
    [0.1580 + 0.4236j, 0.1535 + 0.3849j, 0.3414 + 1.0348j],
])
# Configuración 602 (ohms/milla).
CONFIG_602 = np.array([
    [0.7526 + 1.1814j, 0.1580 + 0.4236j, 0.1560 + 0.5017j],
    [0.1580 + 0.4236j, 0.7475 + 1.1983j, 0.1535 + 0.3849j],
    [0.1560 + 0.5017j, 0.1535 + 0.3849j, 0.7436 + 1.2112j],
])

_FT_PER_MILE = 5280.0


def _z(config: np.ndarray, length_ft: float) -> np.ndarray:
    return config * (length_ft / _FT_PER_MILE)


def build_ieee13_backbone() -> ThreePhaseNetwork:
    """Tramo troncal del IEEE-13 (config 601/602) con cargas desbalanceadas.

    Nodos 650(fuente)→632→671→680 y una derivación 632→633 (config 602).
    Cargas de punto desbalanceadas por fase (kW + j·kVAr).
    """
    nodes = ["650", "632", "671", "680", "633"]
    branches = [
        (0, 1, _z(CONFIG_601, 2000.0)),   # 650-632
        (1, 2, _z(CONFIG_601, 2000.0)),   # 632-671
        (2, 3, _z(CONFIG_601, 1000.0)),   # 671-680
        (1, 4, _z(CONFIG_602, 500.0)),    # 632-633
    ]
    z = np.zeros(3, dtype=complex)
    loads = [
        z.copy(),
        np.array([160 + 110j, 120 + 90j, 120 + 90j], dtype=complex),   # 632
        np.array([385 + 220j, 385 + 220j, 385 + 220j], dtype=complex), # 671
        np.array([200 + 116j, 0, 0], dtype=complex),                   # 680 (1φ)
        np.array([160 + 110j, 0, 120 + 90j], dtype=complex),           # 633 (2φ)
    ]
    return ThreePhaseNetwork(nodes=nodes, branches=branches, loads_kva=loads,
                             v_base_ln=2401.78)   # 4,16 kV LL / √3
