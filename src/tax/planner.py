"""Extension B: a TaxPlanner that compares two ways of taking money out of a company.

Question: an owner-manager's company has made a profit (before paying the owner anything).
Is it better to take it as SALARY or as a DIVIDEND?

    Salary route     company pays gross salary + 10% employer NSSF (both deductible, so no
                     corporate tax on that money); the owner pays PAYE, LST and 5% NSSF.
    Dividend route   company pays 30% corporate income tax on the profit, then distributes the
                     rest; 15% withholding tax is deducted from the dividend (a final tax).

Both routes reuse the existing Tax classes: nothing about rates is repeated here.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from src.tax.business import CorporateIncomeTax, WithholdingTax
from src.tax.core import LineItem, TaxContext
from src.tax.employment import PayrollPipeline
from src.tax.errors import InvalidIncomeError
from src.tax.money import Money


@dataclass(frozen=True)
class ScenarioOutcome:
    """What one scenario does with the profit.

    Attributes:
        name: Scenario label.
        profit: Company profit available before the owner is paid.
        taxes: (label, amount) for every tax paid, by the company or the owner.
        retirement_savings: NSSF contributions. They leave the owner's pocket today but
            remain the owner's money, so they are reported separately from tax.
        net_cash: Cash the owner receives now.
    """

    name: str
    profit: Money
    taxes: Tuple[LineItem, ...]
    retirement_savings: Money
    net_cash: Money

    @property
    def total_tax(self) -> Money:
        return sum((t.amount for t in self.taxes), Money.zero())

    @property
    def net_including_savings(self) -> Money:
        return self.net_cash + self.retirement_savings

    @property
    def effective_tax_rate(self) -> Decimal:
        return self.total_tax.ratio(self.profit)


class Scenario(ABC):
    """A strategy for extracting profit. Subclasses implement :meth:`evaluate`."""

    name: str = "Scenario"

    @abstractmethod
    def evaluate(self, profit: Money, year_start: dt.date) -> ScenarioOutcome:
        """Apply the scenario to an annual profit for the 12 months from ``year_start``."""

    @staticmethod
    def _check(profit: Money) -> None:
        if not isinstance(profit, Money) or profit.is_negative() or not profit:
            raise InvalidIncomeError("Profit must be a positive Money amount.")


def _months_from(start: dt.date, count: int = 12) -> Tuple[dt.date, ...]:
    """First day of ``count`` consecutive months starting with ``start``'s month."""
    months = []
    year, month = start.year, start.month
    for _ in range(count):
        months.append(dt.date(year, month, 1))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return tuple(months)


class SalaryScenario(Scenario):
    """Pay the whole profit out as salary (gross salary + employer NSSF = profit)."""

    name = "Salary"

    def __init__(self, payroll: Optional[PayrollPipeline] = None) -> None:
        self.payroll = payroll or PayrollPipeline()

    def evaluate(self, profit: Money, year_start: dt.date) -> ScenarioOutcome:
        self._check(profit)
        employer_rate = self.payroll.nssf.employer_rate
        annual_gross = Money(profit.amount / (1 + employer_rate))   # gross x 1.10 = profit
        monthly_gross = Money(annual_gross.amount / 12)
        slips = [self.payroll.run(monthly_gross, month) for month in _months_from(year_start)]
        paye = sum((s.paye.amount for s in slips), Money.zero())
        lst = sum((s.lst.amount for s in slips), Money.zero())
        nssf = sum((s.nssf.amount + s.employer_nssf for s in slips), Money.zero())
        net = sum((s.net_pay for s in slips), Money.zero())
        taxes = (LineItem("PAYE (12 months)", paye), LineItem("Local Service Tax", lst))
        return ScenarioOutcome(self.name, profit, taxes, nssf, net)


class DividendScenario(Scenario):
    """Leave the profit in the company, pay corporate tax, distribute the rest as a dividend."""

    name = "Dividend"

    def __init__(
        self, corporate_tax: Optional[CorporateIncomeTax] = None, withholding: Optional[WithholdingTax] = None
    ) -> None:
        self.corporate_tax = corporate_tax or CorporateIncomeTax()
        self.withholding = withholding or WithholdingTax(Decimal("0.15"), "dividends")

    def evaluate(self, profit: Money, year_start: dt.date) -> ScenarioOutcome:
        self._check(profit)
        cit = self.corporate_tax.calculate(TaxContext(on_date=year_start, revenue=profit))
        dividend = profit - cit.amount
        wht = self.withholding.calculate(TaxContext(on_date=year_start, payment=dividend))
        taxes = (LineItem(cit.tax_name, cit.amount), LineItem(wht.tax_name, wht.amount))
        return ScenarioOutcome(self.name, profit, taxes, Money.zero(), dividend - wht.amount)


@dataclass(frozen=True)
class Comparison:
    """Two outcomes side by side and the difference between them (first minus second)."""

    first: ScenarioOutcome
    second: ScenarioOutcome

    @property
    def tax_difference(self) -> Money:
        return self.first.total_tax - self.second.total_tax

    @property
    def net_cash_difference(self) -> Money:
        return self.first.net_cash - self.second.net_cash

    @property
    def better_for_cash(self) -> str:
        if self.first.net_cash == self.second.net_cash:
            return "Equal"
        return self.first.name if self.first.net_cash > self.second.net_cash else self.second.name

    @property
    def lower_tax(self) -> str:
        if self.first.total_tax == self.second.total_tax:
            return "Equal"
        return self.first.name if self.first.total_tax < self.second.total_tax else self.second.name


class TaxPlanner:
    """Compares two scenarios on the same profit and reports the difference."""

    def __init__(self, year_start: dt.date = dt.date(2026, 7, 1)) -> None:
        self.year_start = year_start

    def compare(self, first: Scenario, second: Scenario, profit: Money) -> Comparison:
        return Comparison(first.evaluate(profit, self.year_start), second.evaluate(profit, self.year_start))

    def break_even(self, first: Scenario, second: Scenario, low: Money, high: Money) -> Optional[Money]:
        """Profit level (to the nearest 10,000) where the cash advantage switches, if any.

        Uses bisection, so it assumes the advantage switches at most once between
        ``low`` and ``high``. Returns None if the same scenario wins at both ends.
        """
        def advantage(amount: Decimal) -> Decimal:
            return self.compare(first, second, Money(amount)).net_cash_difference.amount

        lo, hi = low.amount, high.amount
        if advantage(lo) * advantage(hi) > 0:
            return None
        while hi - lo > Decimal("10000"):
            mid = (lo + hi) / 2
            if advantage(lo) * advantage(mid) <= 0:
                hi = mid
            else:
                lo = mid
        return Money(hi)
