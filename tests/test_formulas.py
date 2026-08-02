"""Tests de las fórmulas §9.2 con casos calculados a mano (§19.1, §22.4)."""
import math

import pytest
from hypothesis import given, strategies as st

from lossan.electrical import formulas as F


def test_mean_power():
    assert F.mean_power_kw(730.0, 730.0) == pytest.approx(1.0)


def test_loss_factor_bounds_and_value():
    fc = 0.5
    fp = F.loss_factor(fc, k=0.15)
    # 0.15*0.5 + 0.85*0.25 = 0.075 + 0.2125 = 0.2875
    assert fp == pytest.approx(0.2875)
    assert fc**2 <= fp <= fc


def test_current_3ph_vs_1ph():
    # 100 kVA a 380 V trifásico
    i3 = F.current_3ph(100.0, 380.0)
    assert i3 == pytest.approx(100_000 / (math.sqrt(3) * 380.0))
    # monofásico NO lleva √3 (§9.1 error 2)
    i1 = F.current_1ph_2wire(10.0, 220.0)
    assert i1 == pytest.approx(10_000 / 220.0)


def test_pf_from_energy():
    # kWh=kVArh -> cosφ = 1/√2
    assert F.pf_from_kwh_kvarh(100.0, 100.0) == pytest.approx(1 / math.sqrt(2))


def test_aggregate_never_sums_s():
    # dos cargas con distinto fp: S_total != suma de S
    p = [80.0, 60.0]
    q = [60.0, 80.0]
    pt, qt, st_ = F.aggregate_pqs(p, q)
    assert pt == 140.0 and qt == 140.0
    assert st_ == pytest.approx(math.hypot(140.0, 140.0))
    naive = math.hypot(80, 60) + math.hypot(60, 80)
    assert st_ < naive


def test_resistance_temperature_correction():
    r = F.resistance_at_temp(1.0, t_op=50.0, alpha=0.00403, t_ref=20.0)
    assert r == pytest.approx(1.0 * (1 + 0.00403 * 30))


def test_neutral_current_balanced_is_zero():
    # sistema balanceado -> In ≈ 0 (§9.2)
    assert F.neutral_current(100, 100, 100) == pytest.approx(0.0, abs=1e-6)


def test_neutral_current_unbalanced_nonzero():
    assert F.neutral_current(100, 50, 0) > 10.0


def test_conductor_loss_factors():
    # 3φ = 3·I²R ; 1φ bifilar = 2·I²R
    l3 = F.conductor_loss_3ph_balanced(100, 0.5, 1.0)
    l1 = F.conductor_loss_1ph_2wire(100, 0.5, 1.0)
    assert l3 == pytest.approx(3 * 100**2 * 0.5 / 1000)
    assert l1 == pytest.approx(2 * 100**2 * 0.5 / 1000)


def test_transformer_no_load_permanent():
    # E_loss con S=0 debe ser solo P0·h (vacío permanente, sin FP)
    e = F.transformer_energy_loss_kwh(p0_kw=0.2, pk_kw=1.0, s_max_kva=0.0,
                                      sn_kva=100.0, fp=0.3, hours=8760.0)
    assert e == pytest.approx(0.2 * 8760.0)


def test_coincidence_decreases_with_n():
    assert F.coincidence_factor(100, 0.2, 0.8) < F.coincidence_factor(4, 0.2, 0.8)


# --- Tests de propiedad (§19.3) ---

@given(fc=st.floats(min_value=0.0, max_value=1.0), k=st.floats(min_value=0.0, max_value=0.4))
def test_property_loss_factor_bounds(fc, k):
    fp = F.loss_factor(fc, k)
    assert fc**2 - 1e-9 <= fp <= fc + 1e-9


@given(p=st.floats(1, 1e6), pf=st.floats(0.5, 1.0))
def test_property_s_ge_p(p, pf):
    s = F.s_from_p_pf(p, pf)
    assert s >= p - 1e-6
