"""Deriva un catálogo de conductores desde CATALOGOESTRUCTURA.DESCRIPCIONLARGA
cuando el cliente no entrega impedancias de placa (Anexo D1).

CNEL identifica cada conductor por un código interno (``CODIGOESTRUCTURA``,
el mismo valor que ``CODIGOCONDUCTORFASE`` en los tramos) sin dominio propio,
pero la tabla ``CATALOGOESTRUCTURA`` describe cada código en texto libre, p.
ej. ``"Conductor ACSR #2 AWG"`` o ``"Conductor TW Cu # 250 MCM"``. No trae
calibre en mm² ni impedancia — se derivan de la física:

- Área de sección desde el calibre AWG (fórmula estándar de diámetro por
  gauge) o directo si viene en MCM/kcmil.
- Resistencia ``R = ρ/A`` con la resistividad del material (cobre o
  aluminio) a temperatura de referencia — sin corrección por trenzado/acero
  de refuerzo (ACSR), aproximación razonable para MVP.
- Reactancia y sección (primario/secundario) por regla según el tipo de
  aislamiento/uso descrito (bare/ACSR overhead vs. insulated service).

Es un catálogo APROXIMADO: calibrar contra ensayos o el catálogo real del
fabricante cuando esté disponible (mismo criterio que P0/Pk, Anexo B.4).
"""
from __future__ import annotations

import math
import re

import pandas as pd
from loguru import logger

# Resistividad a 20°C, ohm·mm²/km (= ohm·m * 1e6 / 1e3... ver docstring de
# resistivity_r): cobre recocido ~1.7241e-8 Ω·m, aluminio EC ~2.8264e-8 Ω·m.
_RHO_OHM_MM2_PER_KM = {"cu": 17.241, "al": 28.264}

# Reactancia representativa ohm/km por sección (GMD típica; no depende del
# calibre exacto para esta aproximación).
_X_PRIMARY_OVERHEAD = 0.38
_X_PRIMARY_CABLE = 0.12       # cable aislado subterráneo/"clase 15kV": GMD menor
_X_SECONDARY = 0.09

_AWG_ALIAS = {
    "1/0": 0, "2/0": -1, "3/0": -2, "4/0": -3,
}


def _awg_area_mm2(awg_str: str) -> float | None:
    """Área de sección (mm²) por calibre AWG (fórmula estándar del gauge)."""
    n = _AWG_ALIAS.get(awg_str)
    if n is None:
        if not awg_str.isdigit():
            return None
        n = int(awg_str)
    diameter_mils = 5.0 * (92.0 ** ((36.0 - n) / 39.0))
    area_circular_mils = diameter_mils ** 2
    return area_circular_mils * 0.0005067   # 1 CM = 0.0005067 mm²


def _mcm_area_mm2(mcm_str: str) -> float | None:
    if not mcm_str.replace(".", "").isdigit():
        return None
    return float(mcm_str) * 0.5067          # 1 kcmil = 0.5067 mm²


def parse_conductor_description(desc: str) -> dict | None:
    """Extrae material/calibre/sección de una DESCRIPCIONLARGA de CNEL.

    Devuelve ``None`` si el texto no matchea el patrón esperado (no es un
    conductor, o formato no reconocido) — el llamador debe usar un
    representativo por defecto en ese caso.
    """
    if not isinstance(desc, str) or not desc.strip():
        return None
    d = desc.strip()
    du = d.upper()
    if "CONDUCTOR" not in du:
        return None

    m = re.search(r"(?:#\s*)?([\d/]+)\s*(AWG|MCM)", du)
    if not m:
        return None
    size_str, unit = m.group(1), m.group(2)

    if unit == "MCM":
        area = _mcm_area_mm2(size_str)
    else:
        area = _awg_area_mm2(size_str)
    if area is None or area <= 0:
        return None

    # Material: distingue cobre de aluminio por palabra clave.
    if "CU" in du:
        material = "cu"
    elif any(k in du for k in ("ACSR", "ASC", "ACAR", "AAAC", "AL ")) or du.endswith(" AL"):
        material = "al"
    else:
        return None

    # Sección y tipo de tendido por el prefijo descriptivo.
    is_cable = "15KV" in du or "SEMIAISLADO" in du or "ECOLÓGICO" in du or "ECOLOGICO" in du
    is_bare_overhead = any(k in du for k in ("ACSR", "ASC", "ACAR", "AAAC")) or "DESNUDO" in du
    if is_bare_overhead:
        section, x = "primary", _X_PRIMARY_OVERHEAD
    elif is_cable:
        section, x = "primary", _X_PRIMARY_CABLE
    else:
        # aislados de baja tensión: TW/THHN/TTU Cu o Al -> acometida/secundario
        section, x = "secondary", _X_SECONDARY

    r = _RHO_OHM_MM2_PER_KM[material] / area
    return {"material": material, "r_ohm_km": round(r, 4), "x_ohm_km": x,
            "ampacity_a": None, "section": section, "area_mm2": round(area, 2)}


def build_catalog_from_structure_table(catalogo_estructura: pd.DataFrame,
                                       code_col: str = "CODIGOESTRUCTURA",
                                       desc_col: str = "DESCRIPCIONLARGA"
                                       ) -> dict[str, dict]:
    """Construye {codigo: {material,r_ohm_km,x_ohm_km,section,...}} desde
    CATALOGOESTRUCTURA. Filas que no describen un conductor reconocible se
    omiten (con log agregado, no por fila)."""
    catalog: dict[str, dict] = {}
    n_skipped = 0
    for _, row in catalogo_estructura.iterrows():
        code = row.get(code_col)
        desc = row.get(desc_col)
        if not isinstance(code, str) or not code.strip():
            continue
        parsed = parse_conductor_description(desc)
        if parsed is None:
            continue
        parsed.pop("area_mm2", None)
        catalog[code] = parsed
    if n_skipped:
        logger.info(f"{n_skipped} filas de CATALOGOESTRUCTURA no reconocidas como conductor.")
    logger.info(f"Catálogo de conductores derivado de CATALOGOESTRUCTURA: {len(catalog)} códigos "
                f"(aproximado por física de calibre/material, Anexo D1 — calibrar cuando haya dato real).")
    return catalog
