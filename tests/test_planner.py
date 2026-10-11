"""Tests for Extension B: the TaxPlanner (salary versus dividend)."""
import datetime as dt
from decimal import Decimal

import pytest

from src.tax import DividendScenario, InvalidIncomeError, Money, SalaryScenario, TaxPlanner

planner = TaxPlanner(year_start=dt.date(2026, 7, 1))


def test_dividend_route_hand_calculation():
    out = DividendScenario().evaluate(Money(100_000_000), dt.date(2026, 7, 1))
    # 30% corporate tax = 30m; dividend 70m; 15% WHT = 10.5m; net 59.5m
    assert out.total_tax == Money(40_500_000)
    assert out.net_cash == Money(59_500_000)
    assert out.effective_tax_rate == Decimal("0.405")


def test_salary_route_accounts_for_every_shilling():
    profit = Money(132_000_000)                    # gross salary 120m + employer NSSF 12m
    out = SalaryScenario().evaluate(profit, dt.date(2026, 7, 1))
    # monthly gross 10,000,000: PAYE 2,888,250 normally; in 4 LST months chargeable is 25,000 lower
    assert out.retirement_savings == Money(18_000_000)                 # 15% of 120m
    assert out.total_tax + out.retirement_savings + out.net_cash == profit


def test_comparison_reports_difference_and_winner():
    c = planner.compare(SalaryScenario(), DividendScenario(), Money(60_000_000))
    assert c.net_cash_difference == c.first.net_cash - c.second.net_cash
    assert c.lower_tax == "Salary"
    assert c.better_for_cash in ("Salary", "Dividend")


def test_break_even_exists_between_small_and_large_profit():
    point = planner.break_even(SalaryScenario(), DividendScenario(), Money(5_000_000), Money(2_000_000_000))
    assert point is not None
    below = planner.compare(SalaryScenario(), DividendScenario(), Money(point.amount - 5_000_000))
    above = planner.compare(SalaryScenario(), DividendScenario(), Money(point.amount + 5_000_000))
    assert below.better_for_cash == "Salary" and above.better_for_cash == "Dividend"


def test_zero_or_negative_profit_rejected():
    with pytest.raises(InvalidIncomeError):
        SalaryScenario().evaluate(Money(0), dt.date(2026, 7, 1))
    with pytest.raises(InvalidIncomeError):
        DividendScenario().evaluate(Money(-1), dt.date(2026, 7, 1))
