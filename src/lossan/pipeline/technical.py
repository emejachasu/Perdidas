"""Pérdidas técnicas por puesto de transformación (§12, §5.2).

Física compartida por el generador sintético y el balance, para que el residuo
del balance (§22.3) refleje solo la incertidumbre de estimación de carga y no
una discrepancia de fórmulas.
"""
from __future__ import annotations

import math

import pandas as pd
from loguru import logger

from ..config import Config
from ..domain.bank import UnitPlate, bank_no_load_losses
from ..electrical import formulas as F


def transformer_site_energy_loss_kwh(
    units: list[UnitPlate],
    site_load_kva_max: float,
    site_capacity_kva: float,
    loss_factor: float,
    hours: float,
) -> float:
    """Energía perdida en un puesto de transformación en el periodo.

    - Vacío: Σ P0_unidad · h (permanente, sin FP).
    - Carga: se reparte la demanda del puesto entre unidades en proporción a su
      capacidad y se aplica Pk·(S/Sn)²·FP·h por unidad (§9.2).
    """
    if site_capacity_kva <= 0:
        raise ValueError("site_capacity_kva debe ser > 0")

    no_load = bank_no_load_losses(units) * hours

    total_sn = sum(u.sn_kva for u in units)
    load = 0.0
    for u in units:
        share = (u.sn_kva / total_sn) if total_sn > 0 else 0.0
        s_unit = site_load_kva_max * share
        load += F.transformer_energy_loss_kwh(
            p0_kw=0.0, pk_kw=u.pk_kw, s_max_kva=s_unit,
            sn_kva=u.sn_kva, fp=loss_factor, hours=hours,
        )
    return no_load + load


def secondary_conductor_loss_kwh(
    energy_delivered_kwh: float,
    loss_pct: float,
    loss_factor: float,
) -> float:
    """Aproximación de pérdidas de red secundaria + acometidas.

    Modelo agregado: un porcentaje de la energía entregada, modulado por el
    factor de pérdidas. Fallback cuando no hay tramos BT reales enlazados al
    puesto (ver ``secondary_conductor_loss_by_site_kwh`` para el caso con
    topología real).
    """
    return energy_delivered_kwh * loss_pct * loss_factor


def attach_conductor_impedance(segments: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Añade r_ohm_per_km/x_ohm_per_km/section a los tramos por conductor_code
    (§9). Compartida por el balance (pérdidas BT reales) y la topología F2.

    Cuando el código de conductor no está en el catálogo (``config/
    conductors.yaml`` + ``config/conductors_cnel.yaml``), se usa un
    representativo por sección (primario/secundario, según voltage_ll) para
    no bloquear el cálculo — resultado aproximado hasta completar el
    catálogo real (Anexo D1).
    """
    if segments is None or segments.empty or "r_ohm_per_km" in segments.columns:
        return segments
    cat = cfg.conductors
    lookup_r = {k: v["r_ohm_km"] for k, v in cat.items()}
    lookup_x = {k: v["x_ohm_km"] for k, v in cat.items()}
    primary = [k for k, v in cat.items() if v.get("section") == "primary"]
    secondary = [k for k, v in cat.items() if v.get("section") == "secondary"]
    default_primary = primary[len(primary) // 2] if primary else next(iter(cat))
    default_secondary = secondary[len(secondary) // 2] if secondary else next(iter(cat))

    code = segments.get("conductor_code")
    voltage = segments.get("voltage_ll")
    r, x, section = [], [], []
    n_fallback = 0
    for i in range(len(segments)):
        is_primary = bool(voltage is not None and pd.notna(voltage.iloc[i])
                          and voltage.iloc[i] > 1000)
        section.append("primary" if is_primary else "secondary")
        c = code.iloc[i] if code is not None else None
        if c in lookup_r:
            r.append(lookup_r[c]); x.append(lookup_x[c])
            continue
        n_fallback += 1
        d = default_primary if is_primary else default_secondary
        r.append(lookup_r[d]); x.append(lookup_x[d])
    segments = segments.copy()
    segments["r_ohm_per_km"] = r
    segments["x_ohm_per_km"] = x
    if "section" not in segments.columns:
        segments["section"] = section
    if n_fallback:
        logger.warning(
            f"{n_fallback}/{len(segments)} tramos con conductor_code fuera "
            f"del catálogo: impedancia aproximada por representativo de "
            f"sección. Cargar el catálogo real del cliente para precisión "
            f"(Anexo D1).")
    return segments


def secondary_network_by_site(segments: pd.DataFrame) -> dict[str, float]:
    """R equivalente (ohm) de la red BT de cada puesto, agregando en serie
    todos sus tramos reales (método de "conductor/longitud equivalente").

    Enlaza tramos -> puesto por conectividad ArcFM real
    (``parent_circuit_guid`` del tramo == ``node_id`` del puesto,
    CIRCUITSOURCEGUID), no por snapping de coordenadas: es la clave que
    CNEL usa para la traza de circuito (§ mapeo cnel_mapping.yaml).
    """
    if segments is None or segments.empty or "parent_circuit_guid" not in segments.columns:
        return {}
    lv = segments[segments.get("section") == "secondary"].copy()
    if lv.empty:
        return {}
    lv["r_ohm"] = (lv["length_m"] / 1000.0) * lv["r_ohm_per_km"]
    return lv.groupby("parent_circuit_guid")["r_ohm"].sum().to_dict()


def secondary_conductor_loss_by_site_kwh(
    r_eq_ohm: float, s_kva: float, v_ll: float, three_phase: bool,
    loss_factor: float, hours: float,
) -> float:
    """Pérdidas I²R de la red BT real de UN puesto (§F4 simplificado).

    Agrega toda la red BT aguas abajo del puesto como una impedancia
    equivalente en serie ("longitud/conductor equivalente"): usa el R real
    de los conductores de ESE puesto en vez de un % fijo, sin requerir un
    flujo de carga completo tramo-por-tramo. Aproximación razonable para
    MVP — un backward-forward sweep (§F4, powerflow/sweep.py) daría la
    distribución real de corriente por tramo si se necesita mayor precisión.
    """
    if r_eq_ohm <= 0 or s_kva <= 0:
        return 0.0
    if three_phase:
        i_amp = s_kva * 1000.0 / (math.sqrt(3) * v_ll)
        p_loss_kw = 3.0 * i_amp * i_amp * r_eq_ohm / 1000.0
    else:
        i_amp = s_kva * 1000.0 / v_ll
        p_loss_kw = 2.0 * i_amp * i_amp * r_eq_ohm / 1000.0
    return p_loss_kw * hours * loss_factor
