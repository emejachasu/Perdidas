"""Tests de capacidad y pérdidas de banco (§5.2, §19.2, §22.5)."""
import math

import pytest

from lossan.domain.bank import (
    UnitPlate,
    bank_capacity,
    bank_load_losses_at,
    bank_no_load_losses,
    validate_bank_config,
)
from lossan.domain.enums import BankConfig


def u(sn, p0=0.0, pk=0.0, v=220.0):
    return UnitPlate(sn_kva=sn, p0_kw=p0, pk_kw=pk, voltage_ln=v)


def test_single_unit_capacity():
    cap, head = bank_capacity(BankConfig.SINGLE, [u(50)])
    assert cap == 50.0 and head == 0.0


def test_wye_closed_equal_units():
    cap, head = bank_capacity(BankConfig.WYE_CLOSED, [u(50), u(50), u(50)])
    assert cap == 150.0 and head == 0.0


def test_open_delta_capacity_is_86_6_pct():
    # delta abierto: √3·S = 86,6% de 2S. NO sumar aritméticamente (error b, §5.2).
    cap, head = bank_capacity(BankConfig.OPEN_DELTA, [u(50), u(50)])
    assert cap == pytest.approx(math.sqrt(3) * 50.0)
    assert cap == pytest.approx(0.866 * 100.0, rel=1e-3)
    assert cap < 100.0  # menor que la suma aritmética


def test_unequal_bank_balanced_is_3_min():
    # banco desigual: capacidad balanceada ≈ 3·min; excedente sirve carga 1φ.
    cap, head = bank_capacity(BankConfig.WYE_CLOSED, [u(25), u(50), u(50)])
    assert cap == pytest.approx(75.0)
    assert head == pytest.approx(50.0)  # 125 - 75


def test_delta_4wire_lighting_unit():
    cap, head = bank_capacity(BankConfig.DELTA_4WIRE, [u(50), u(50), u(100)])
    assert cap == pytest.approx(150.0)   # 3 * min
    assert head == pytest.approx(50.0)


def test_losses_are_summed_per_unit():
    # tres de 25 tienen más P0 que una de 75 (§5.2)
    three = [u(25, p0=0.1), u(25, p0=0.1), u(25, p0=0.1)]
    one = [u(75, p0=0.22)]
    assert bank_no_load_losses(three) > bank_no_load_losses(one)


def test_load_losses_referred_to_unit_load():
    units = [u(50, pk=0.6), u(50, pk=0.6)]
    loss = bank_load_losses_at(units, [50.0, 25.0])  # plena y media carga
    expected = 0.6 * 1.0 + 0.6 * 0.25
    assert loss == pytest.approx(expected)


def test_validate_bank_config_flags():
    # delta cerrado declarado con 2 unidades -> P03
    assert "P03" in validate_bank_config(BankConfig.DELTA_CLOSED, [u(50), u(50)])
    # tensiones incompatibles -> P04
    assert "P04" in validate_bank_config(BankConfig.OPEN_DELTA, [u(50, v=220), u(50, v=127)])


def test_wrong_unit_count_raises():
    with pytest.raises(ValueError):
        bank_capacity(BankConfig.OPEN_DELTA, [u(50)])
