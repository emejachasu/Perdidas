"""Pérdidas técnicas por puesto de transformación (§12, §5.2).

Física compartida por el generador sintético y el balance, para que el residuo
del balance (§22.3) refleje solo la incertidumbre de estimación de carga y no
una discrepancia de fórmulas.
"""
from __future__ import annotations

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
    factor de pérdidas. Sustituible por el cálculo por tramo (I²R) cuando la
    topología detallada esté disponible (F2/F4).
    """
    return energy_delivered_kwh * loss_pct * loss_factor
