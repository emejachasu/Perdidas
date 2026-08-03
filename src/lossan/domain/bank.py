"""§5.2 — Reglas de agregación eléctrica de bancos de transformación.

Implementadas EXACTAMENTE como en el requerimiento. Estas reglas impiden los
tres errores sistemáticos declarados:

  (a) evaluar la cargabilidad del puesto contra el kVA de una sola unidad;
  (b) sumar aritméticamente las unidades de un delta abierto (subestima la
      cargabilidad real en 13,4 %);
  (c) evaluar un banco de unidades desiguales como si fuera balanceado.

Capacidad y pérdidas SIEMPRE se calculan por unidad y se agregan al puesto.
El factor sqrt(3) del delta abierto es parametrizable (thresholds.bank).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .enums import BankConfig


@dataclass(frozen=True)
class UnitPlate:
    """Características de placa de una unidad de transformador."""

    sn_kva: float           # potencia nominal
    p0_kw: float            # pérdidas de vacío (permanentes, 8760 h)
    pk_kw: float            # pérdidas de cobre a plena carga (nominal)
    voltage_ln: float | None = None   # tensión nominal (para P04)


@dataclass(frozen=True)
class BankResult:
    capacity_kva: float
    single_phase_headroom_kva: float   # excedente que sirve carga monofásica
    p0_total_kw: float
    n_units: int
    config: BankConfig


DEFAULT_OPEN_DELTA_FACTOR = math.sqrt(3.0)   # ≈ 1.7320508  (86.6 % de 2S)


def bank_capacity(
    config: BankConfig,
    units: list[UnitPlate],
    open_delta_factor: float = DEFAULT_OPEN_DELTA_FACTOR,
) -> tuple[float, float]:
    """Capacidad trifásica del puesto y excedente monofásico.

    Devuelve ``(capacity_kva, single_phase_headroom_kva)``.
    """
    if not units:
        raise ValueError("El puesto de transformación no tiene unidades")

    s = [u.sn_kva for u in units]

    if config is BankConfig.SINGLE:
        if len(units) != 1:
            raise ValueError("SINGLE requiere exactamente 1 unidad")
        return s[0], 0.0

    if config in (BankConfig.WYE_CLOSED, BankConfig.DELTA_CLOSED):
        if len(units) != 3:
            raise ValueError(f"{config.value} requiere exactamente 3 unidades")
        smin = min(s)
        balanced = 3.0 * smin
        headroom = sum(s) - balanced   # excedente sirve carga monofásica
        return balanced, headroom

    if config in (BankConfig.OPEN_DELTA, BankConfig.OPEN_WYE_OPEN_DELTA):
        if len(units) != 2:
            raise ValueError(f"{config.value} requiere exactamente 2 unidades")
        # V-V: √3·S con S = la unidad limitante; excedente monofásico en la mayor.
        smin = min(s)
        capacity = open_delta_factor * smin
        headroom = sum(s) - 2.0 * smin
        return capacity, headroom

    if config is BankConfig.DELTA_4WIRE:
        if len(units) != 3:
            raise ValueError("delta_4wire requiere 3 unidades (1 de alumbrado + 2 de potencia)")
        # La unidad de alumbrado (la mayor) aporta S_1φ + S_3φ/3; las de potencia S_3φ/3.
        s_sorted = sorted(s)
        s_power = s_sorted[0]                      # unidad de potencia limitante
        capacity = 3.0 * s_power                   # capacidad 3φ balanceada
        headroom = sum(s) - capacity               # fase de potencia adicional
        return capacity, headroom

    if config is BankConfig.INDEPENDENT:
        # No forman banco: la "capacidad del puesto" es la suma, pero cada unidad
        # se evalúa por separado (§5.2 distinción crítica).
        return sum(s), 0.0

    raise ValueError(f"Configuración de banco no soportada: {config}")


def bank_no_load_losses(units: list[UnitPlate]) -> float:
    """P0_puesto = Σ P0_unidad_i  (§5.2). Permanentes 8760 h, no llevan FP."""
    return float(sum(u.p0_kw for u in units))


def bank_load_losses_at(units: list[UnitPlate], unit_loads_kva: list[float]) -> float:
    """Pk_puesto referido a la carga real de cada unidad.

    Pk_unidad(S) = Pk_nominal · (S/Sn)^2 ; se suma por unidad.
    """
    if len(units) != len(unit_loads_kva):
        raise ValueError("Debe darse una carga por unidad")
    total = 0.0
    for u, s_load in zip(units, unit_loads_kva):
        if u.sn_kva <= 0:
            raise ValueError("sn_kva debe ser > 0")
        total += u.pk_kw * (s_load / u.sn_kva) ** 2
    return float(total)


def evaluate_bank(
    config: BankConfig,
    units: list[UnitPlate],
    open_delta_factor: float = DEFAULT_OPEN_DELTA_FACTOR,
) -> BankResult:
    """Evalúa un puesto: capacidad, excedente monofásico y P0 total (§5.2)."""
    capacity, headroom = bank_capacity(config, units, open_delta_factor)
    return BankResult(
        capacity_kva=capacity,
        single_phase_headroom_kva=headroom,
        p0_total_kw=bank_no_load_losses(units),
        n_units=len(units),
        config=config,
    )


# --- Validaciones de calidad de banco (P03-P05, §5.5) --------------------

def validate_bank_config(config: BankConfig, units: list[UnitPlate]) -> list[str]:
    """Devuelve códigos de regla P0x violados (lista vacía si es válido)."""
    findings: list[str] = []
    n = len(units)
    expected = {
        BankConfig.SINGLE: 1,
        BankConfig.WYE_CLOSED: 3,
        BankConfig.DELTA_CLOSED: 3,
        BankConfig.OPEN_DELTA: 2,
        BankConfig.OPEN_WYE_OPEN_DELTA: 2,
        BankConfig.DELTA_4WIRE: 3,
    }
    if config in expected and n != expected[config]:
        findings.append("P03")  # configuración de banco no válida
    # P04: tensiones nominales incompatibles
    volts = [u.voltage_ln for u in units if u.voltage_ln is not None]
    if len(volts) >= 2 and (max(volts) - min(volts)) / max(volts) > 0.01:
        findings.append("P04")
    return findings
