"""Property-based tests with hypothesis.

Instead of checking a few hand-picked incomes, hypothesis generates hundreds of random
ones and checks that rules which must ALWAYS hold really do:

    1. tax is never negative;
    2. tax never exceeds income;
    3. tax is monotonic: earning more never means paying less tax;
    4. (bonus) take-home pay is monotonic too: a pay rise never reduces net pay.
"""
import datetime as dt

from hypothesis import given, settings
from hypothesis import strategies as st

from src.tax import PAYE, LocalServiceTax, Money, PayrollPipeline, Residency, TaxContext

incomes = st.integers(min_value=0, max_value=1_000_000_000)        # 0 to UGX 1 billion a month
residencies = st.sampled_from(list(Residency))
dates = st.dates(min_value=dt.date(2012, 7, 1), max_value=dt.date(2030, 12, 31))

paye = PAYE()
payroll = PayrollPipeline()


def paye_amount(income: int, residency: Residency, on: dt.date) -> int:
    ctx = TaxContext(on_date=on, residency=residency, gross_pay=Money(income))
    return int(paye.calculate(ctx).amount.amount)


@settings(max_examples=300)
@given(income=incomes, residency=residencies, on=dates)
def test_tax_is_never_negative(income, residency, on):
    assert paye_amount(income, residency, on) >= 0


@settings(max_examples=300)
@given(income=incomes, residency=residencies, on=dates)
def test_tax_never_exceeds_income(income, residency, on):
    assert paye_amount(income, residency, on) <= income


@settings(max_examples=300)
@given(a=incomes, b=incomes, residency=residencies, on=dates)
def test_tax_is_monotonic_in_income(a, b, residency, on):
    low, high = sorted((a, b))
    assert paye_amount(low, residency, on) <= paye_amount(high, residency, on)


@settings(max_examples=200)
@given(income=incomes, residency=residencies, on=dates)
def test_payslip_adds_up_and_net_pay_is_not_negative(income, residency, on):
    slip = payroll.run(Money(income), on, residency=residency)
    assert slip.gross == slip.net_pay + slip.total_deductions
    assert not slip.net_pay.is_negative()


@settings(max_examples=200)
@given(a=incomes, b=incomes, on=dates)
def test_net_pay_is_monotonic_when_lst_is_off(a, b, on):
    """With LST switched off, a pay rise never reduces net pay.

    (With LST on, crossing an LST bracket can cost slightly more than the rise itself in a
    deduction month; the notebook demonstrates this "cliff".)
    """
    no_lst = PayrollPipeline(lst=LocalServiceTax(enabled=False))
    low, high = sorted((a, b))
    assert no_lst.run(Money(low), on).net_pay <= no_lst.run(Money(high), on).net_pay
