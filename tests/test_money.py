"""Tests for the Money value object."""
from decimal import Decimal

import pytest

from src.tax import Money, MoneyTypeError, TaxError


def test_add_subtract_multiply():
    assert Money(1000) + Money("250") == Money(1250)
    assert Money(1000) - Money(250) == Money(750)
    assert Money(1000) * Decimal("0.18") == Money(180)
    assert 3 * Money(100) == Money(300)


def test_rounding_is_half_up_to_whole_shillings():
    assert Money("184.5") == Money(185)          # half goes UP (banker's rounding would give 184)
    assert Money("184.4") == Money(184)
    assert Money(1025) * Decimal("0.18") == Money(185)   # 184.5 exactly


def test_ordering_and_equality():
    assert Money(1) < Money(2) <= Money(2) < Money(3)
    assert max(Money(5), Money(9)) == Money(9)
    assert Money(7) == Money("7.00")
    assert Money(7) != 7                          # Money never equals a bare number


def test_repr_and_str_are_readable():
    assert repr(Money(1234567)) == "Money('UGX 1,234,567')"
    assert str(Money(0)) == "UGX 0"


def test_hashable_and_usable_in_sum():
    assert len({Money(5), Money(5), Money(6)}) == 2
    assert sum([Money(1), Money(2), Money(3)]) == Money(6)


def test_ratio_is_exact_decimal():
    assert Money(1).ratio(Money(4)) == Decimal("0.25")
    with pytest.raises(ZeroDivisionError):
        Money(1).ratio(Money(0))


# --- float is refused everywhere --------------------------------------------
def test_float_is_rejected_on_construction():
    with pytest.raises(MoneyTypeError):
        Money(0.1)
    with pytest.raises(TaxError):                 # MoneyTypeError is a TaxError
        Money(1500.50)


def test_float_is_rejected_in_multiplication():
    with pytest.raises(MoneyTypeError):
        Money(1000) * 0.18


def test_money_times_money_is_rejected():
    with pytest.raises(MoneyTypeError):
        Money(10) * Money(10)


def test_garbage_and_nan_rejected():
    for bad in ("abc", "NaN", None, True):
        with pytest.raises(MoneyTypeError):
            Money(bad)


def test_money_is_immutable():
    m = Money(10)
    with pytest.raises(AttributeError):
        m.amount = Decimal(99)
    with pytest.raises(AttributeError):
        m._amount = Decimal(99)
