"""Boundary tests for PAYE: every band edge of every schedule, plus error cases.

Expected values are worked by hand from the brief, e.g. at 485,000:
    20% x 75,000 + 25% x 75,000 = 15,000 + 18,750 = 33,750
"""
import datetime as dt

import pytest

from src.tax import (
    InvalidIncomeError,
    Money,
    NoScheduleForDateError,
    PAYE,
    Residency,
    TaxContext,
    TaxError,
)

AFTER = dt.date(2026, 9, 15)     # new schedule (from 1 Jul 2026) - the assignment baseline
BEFORE = dt.date(2026, 3, 15)    # old schedule (1 Jul 2012 - 30 Jun 2026)
paye = PAYE()


def tax(gross: int, on: dt.date = AFTER, residency: Residency = Residency.RESIDENT) -> int:
    ctx = TaxContext(on_date=on, residency=residency, gross_pay=Money(gross))
    return int(paye.calculate(ctx).amount.amount)


# --- the six edges named in the brief ----------------------------------------
@pytest.mark.parametrize(
    "gross, expected",
    [
        (0, 0),
        (335_000, 0),               # top of the nil band
        (335_001, 0),               # 20% of 1 = 0.20 -> rounds to 0
        (410_000, 15_000),          # 20% x 75,000
        (485_000, 33_750),          # 15,000 + 25% x 75,000
        (10_000_000, 2_888_250),    # 33,750 + 30% x 9,515,000
        (10_000_001, 2_888_250),    # + 0.30 + 0.10 = 0.40 -> rounds to 0
    ],
)
def test_resident_2026_band_edges(gross, expected):
    assert tax(gross) == expected


@pytest.mark.parametrize(
    "gross, expected",
    [
        (335_100, 20),              # just inside the 20% band: 20% x 100
        (410_100, 15_025),          # just inside the 25% band: + 25% x 100
        (485_100, 33_780),          # just inside the 30% band: + 30% x 100
        (10_000_100, 2_888_290),    # surcharge band: + (30% + 10%) x 100
        (12_000_000, 3_688_250),    # 33,750 + 30% x 11,515,000 + 10% x 2,000,000
    ],
)
def test_resident_2026_just_inside_each_band(gross, expected):
    assert tax(gross) == expected


# --- non-resident schedule ----------------------------------------------------
@pytest.mark.parametrize(
    "gross, expected",
    [
        (0, 0),
        (100_000, 10_000),          # no tax-free threshold: 10% from the first shilling
        (335_000, 33_500),
        (410_000, 48_500),          # 33,500 + 20% x 75,000
        (10_000_000, 2_925_500),    # 48,500 + 30% x 9,590,000
        (10_000_100, 2_925_540),
    ],
)
def test_non_resident_band_edges(gross, expected):
    assert tax(gross, residency=Residency.NON_RESIDENT) == expected


# --- the older resident schedule is selected by date ---------------------------
@pytest.mark.parametrize(
    "gross, expected",
    [(235_000, 0), (335_000, 10_000), (410_000, 25_000), (3_000_000, 802_000), (10_000_000, 2_902_000)],
)
def test_resident_pre_july_2026_schedule(gross, expected):
    assert tax(gross, on=BEFORE) == expected


def test_schedule_switches_exactly_on_1_july_2026():
    assert tax(300_000, on=dt.date(2026, 6, 30)) == 6_500     # old: 10% x 65,000
    assert tax(300_000, on=dt.date(2026, 7, 1)) == 0          # new: below the 335,000 threshold


# --- allowances and pre-tax deductions ------------------------------------------
def test_allowances_are_taxed_and_lst_is_deducted_first():
    ctx = TaxContext(on_date=AFTER, gross_pay=Money(400_000), allowances=Money(110_000),
                     pre_tax_deductions=Money(25_000))
    # chargeable = 400,000 + 110,000 - 25,000 = 485,000 -> 33,750
    result = paye.calculate(ctx)
    assert result.base == Money(485_000)
    assert result.amount == Money(33_750)


# --- errors: never fail silently ----------------------------------------------------
def test_no_schedule_before_2012():
    with pytest.raises(NoScheduleForDateError):
        tax(1_000_000, on=dt.date(2010, 1, 1))


def test_negative_income_rejected():
    with pytest.raises(InvalidIncomeError):
        TaxContext(on_date=AFTER, gross_pay=Money(-1))


def test_missing_income_rejected():
    with pytest.raises(InvalidIncomeError):
        paye.calculate(TaxContext(on_date=AFTER))


def test_non_money_income_rejected():
    with pytest.raises(InvalidIncomeError):
        TaxContext(on_date=AFTER, gross_pay=1_000_000)


def test_deductions_larger_than_income_rejected():
    with pytest.raises(InvalidIncomeError):
        paye.calculate(TaxContext(on_date=AFTER, gross_pay=Money(100), pre_tax_deductions=Money(200)))


def test_all_engine_errors_share_one_base_class():
    for exc in (InvalidIncomeError, NoScheduleForDateError):
        assert issubclass(exc, TaxError)
