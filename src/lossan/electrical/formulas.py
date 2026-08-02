"""§9.2 — Fórmulas de referencia (implementación obligatoria).

Cada función implementa una fórmula del requerimiento y evita explícitamente
los errores enumerados en §9.1. Todas las constantes físicas de calibración
(k, cosφ, a/b, A/B, α, temperaturas) se leen de ``config/electrical.yaml``;
aquí solo viven las relaciones físicas.
"""
from __future__ import annotations

import cmath
import math

SQRT3 = math.sqrt(3.0)


# --- Demanda, factor de carga y de pérdidas -----------------------------

def mean_power_kw(energy_kwh: float, hours: float) -> float:
    """P_media [kW] = E [kWh] / h."""
    if hours <= 0:
        raise ValueError("hours debe ser > 0")
    return energy_kwh / hours


def load_factor(p_mean_kw: float, p_max_kw: float) -> float:
    """FC = P_media / P_max."""
    if p_max_kw <= 0:
        raise ValueError("p_max_kw debe ser > 0")
    return p_mean_kw / p_max_kw


def loss_factor(fc: float, k: float = 0.15) -> float:
    """FP = k·FC + (1−k)·FC²  (Buller–Woodrow). Verifica FC² ≤ FP ≤ FC."""
    if not 0.0 <= fc <= 1.0:
        raise ValueError("FC debe estar en [0, 1]")
    fp = k * fc + (1.0 - k) * fc * fc
    # invariante físico del requerimiento
    eps = 1e-9
    assert fc * fc - eps <= fp <= fc + eps, "Se viola FC² ≤ FP ≤ FC"
    return fp


# --- Velander y coincidencia --------------------------------------------

def velander_dmax_kw(energy_kwh: float, a: float, b: float) -> float:
    """D_max = a·E + b·√E  (estimación de demanda sin curva)."""
    if energy_kwh < 0:
        raise ValueError("energy_kwh debe ser >= 0")
    return a * energy_kwh + b * math.sqrt(energy_kwh)


def coincidence_factor(n: int, A: float, B: float) -> float:
    """FCoinc(n) = A + B/√n."""
    if n < 1:
        raise ValueError("n debe ser >= 1")
    return A + B / math.sqrt(n)


def diversified_demand_kw(dmax_list: list[float], A: float, B: float) -> float:
    """D_diversificada = FCoinc(n)·Σ D_max,i  (§9.1 error 3: no sumar picos)."""
    n = len(dmax_list)
    if n == 0:
        return 0.0
    return coincidence_factor(n, A, B) * sum(dmax_list)


# --- Relación P–Q–S ------------------------------------------------------

def pf_from_kwh_kvarh(kwh: float, kvarh: float) -> float:
    """cosφ = kWh / √(kWh² + kVArh²) (método preferente con energía reactiva)."""
    denom = math.hypot(kwh, kvarh)
    if denom == 0:
        return 1.0
    return kwh / denom


def tanphi_from_kwh_kvarh(kwh: float, kvarh: float) -> float:
    """tanφ = kVArh/kWh."""
    if kwh == 0:
        raise ValueError("kwh debe ser distinto de 0")
    return kvarh / kwh


def q_from_p(p_kw: float, pf: float) -> float:
    """Q = P·tanφ, con tanφ derivado de cosφ."""
    if not 0 < pf <= 1:
        raise ValueError("pf debe estar en (0, 1]")
    tanphi = math.tan(math.acos(pf))
    return p_kw * tanphi


def s_from_p_pf(p_kw: float, pf: float) -> float:
    """S = P/cosφ."""
    if not 0 < pf <= 1:
        raise ValueError("pf debe estar en (0, 1]")
    return p_kw / pf


def s_from_pq(p: float, q: float) -> float:
    """S = √(P² + Q²)."""
    return math.hypot(p, q)


def aggregate_pqs(p_list: list[float], q_list: list[float]) -> tuple[float, float, float]:
    """Agregación correcta (§9.1 error 7 / §9.2): NUNCA sumar S.

    P_total = ΣPi ; Q_total = ΣQi ; S_total = √(P_total² + Q_total²).
    """
    p_total = float(sum(p_list))
    q_total = float(sum(q_list))
    return p_total, q_total, math.hypot(p_total, q_total)


# --- Corriente -----------------------------------------------------------

def current_3ph(s_kva: float, v_ll: float) -> float:
    """I = S_3φ / (√3·V_LL)  [A], con S en kVA y V en V."""
    if v_ll <= 0:
        raise ValueError("v_ll debe ser > 0")
    return (s_kva * 1000.0) / (SQRT3 * v_ll)


def current_1ph_2wire(s_kva: float, v_ln: float) -> float:
    """I = S / V_LN  (monofásico bifilar). Sin √3 (§9.1 error 2)."""
    if v_ln <= 0:
        raise ValueError("v_ln debe ser > 0")
    return (s_kva * 1000.0) / v_ln


def current_1ph_3wire(s_kva: float, v_240: float) -> float:
    """I_línea = S / V_240  (monofásico trifilar 120/240)."""
    if v_240 <= 0:
        raise ValueError("v_240 debe ser > 0")
    return (s_kva * 1000.0) / v_240


# --- Resistencia por temperatura ----------------------------------------

def resistance_at_temp(r_ref: float, t_op: float, alpha: float, t_ref: float = 20.0) -> float:
    """R_T = R_ref·[1 + α(T_op − T_ref)]  (§9.2 error 6: corregir por T)."""
    return r_ref * (1.0 + alpha * (t_op - t_ref))


# --- Corriente de neutro y pérdidas en conductor ------------------------

def neutral_current(ia: float, ib: float, ic: float,
                    theta_a: float = 0.0, theta_b: float = 0.0, theta_c: float = 0.0) -> float:
    """In = |Ia∠θa + Ib∠(θb−120°) + Ic∠(θc+120°)|. OBLIGATORIA (§9.2)."""
    a = cmath.rect(ia, math.radians(theta_a))
    b = cmath.rect(ib, math.radians(theta_b - 120.0))
    c = cmath.rect(ic, math.radians(theta_c + 120.0))
    return abs(a + b + c)


def conductor_loss_3ph_balanced(i: float, r_ohm_per_km: float, length_km: float) -> float:
    """P_loss = 3·I²·R·L  [kW] (R en Ω/km, L en km, I en A)."""
    return 3.0 * i * i * r_ohm_per_km * length_km / 1000.0


def conductor_loss_3ph_unbalanced(ia: float, ib: float, ic: float, in_: float,
                                  r_ohm_per_km: float, rn_ohm_per_km: float,
                                  length_km: float) -> float:
    """P_loss = (Ia²+Ib²+Ic²)·R·L + In²·R_n·L  [kW]. Incluye neutro."""
    phase = (ia * ia + ib * ib + ic * ic) * r_ohm_per_km
    neutral = in_ * in_ * rn_ohm_per_km
    return (phase + neutral) * length_km / 1000.0


def conductor_loss_1ph_2wire(i: float, r_ohm_per_km: float, length_km: float) -> float:
    """P_loss = 2·I²·R·L  [kW] (§9.2 error 5)."""
    return 2.0 * i * i * r_ohm_per_km * length_km / 1000.0


def conductor_loss_1ph_3wire(i1: float, i2: float, in_: float,
                             r_ohm_per_km: float, rn_ohm_per_km: float,
                             length_km: float) -> float:
    """P_loss = (I1²+I2²)·R·L + In²·R_n·L  [kW]."""
    return ((i1 * i1 + i2 * i2) * r_ohm_per_km + in_ * in_ * rn_ohm_per_km) * length_km / 1000.0


def energy_loss_kwh(p_loss_peak_kw: float, fp: float, hours: float) -> float:
    """E_loss = P_loss,pico · FP · h  (§9.1 error 4: usar FP, no FC)."""
    return p_loss_peak_kw * fp * hours


# --- Pérdidas en transformador (por unidad) -----------------------------

def transformer_power_loss_kw(p0_kw: float, pk_kw: float, s_kva: float, sn_kva: float) -> float:
    """P_loss = P0 + Pk·(S/Sn)²  [kW]."""
    if sn_kva <= 0:
        raise ValueError("sn_kva debe ser > 0")
    return p0_kw + pk_kw * (s_kva / sn_kva) ** 2


def transformer_energy_loss_kwh(p0_kw: float, pk_kw: float, s_max_kva: float,
                                sn_kva: float, fp: float, hours: float) -> float:
    """E_loss = P0·h + Pk·(S_max/Sn)²·FP·h.

    Las pérdidas de vacío son PERMANENTES (no llevan FP); solo las de carga sí.
    """
    if sn_kva <= 0:
        raise ValueError("sn_kva debe ser > 0")
    no_load = p0_kw * hours
    load = pk_kw * (s_max_kva / sn_kva) ** 2 * fp * hours
    return no_load + load


# --- Caída de tensión (validación) --------------------------------------

def voltage_drop(i: float, length_km: float, r_ohm_per_km: float, x_ohm_per_km: float,
                 pf: float, three_phase: bool = True) -> float:
    """ΔV ≈ k·I·L·(R·cosφ + X·sinφ) ; k=√3 (3φ), 2 (1φ bifilar)."""
    k = SQRT3 if three_phase else 2.0
    sinphi = math.sqrt(max(0.0, 1.0 - pf * pf))
    return k * i * length_km * (r_ohm_per_km * pf + x_ohm_per_km * sinphi)
