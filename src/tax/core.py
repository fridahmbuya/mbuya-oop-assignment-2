"""Core abstractions shared by every tax: TaxContext, TaxResult and the abstract Tax class.

    TaxContext  --->  Tax.calculate(ctx)  --->  TaxResult
    (the facts)       (the rule)               (the answer + how it was reached)

Every concrete tax (PAYE, NSSF, LST, VAT, corporate income tax, withholding tax) is a
subclass of :class:`Tax` and implements ``calculate``. Code that uses taxes, such as the
payroll pipeline and the tax planner, depends only on this interface.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple

from src.tax.errors import InvalidIncomeError
from src.tax.money import Money


class Residency(Enum):
    """Tax residency of an individual. It decides which PAYE schedule applies."""

    RESIDENT = "resident"
    NON_RESIDENT = "non-resident"


@dataclass(frozen=True)
class TaxContext:
    """The facts a tax needs. Immutable, so a calculation can never change its inputs.

    One context type serves all taxes; each tax reads only the fields it needs and
    raises a :class:`~src.tax.errors.TaxError` if a field it needs is missing or invalid.

    Attributes:
        on_date: The date the tax applies to. It selects the rate schedule in force.
        residency: Resident or non-resident (employment taxes).
        gross_pay: Monthly basic pay (employment taxes).
        allowances: Monthly taxable allowances (housing, transport, ...).
        pre_tax_deductions: Amounts allowed as a deduction before PAYE (Local Service Tax).
        revenue: Annual gross income of a company (corporate income tax).
        allowable_deductions: Annual deductible expenses (corporate income tax).
        invoices: VAT invoices for the period (VAT).
        payment: A single payment subject to withholding tax (e.g. a dividend).
    """

    on_date: dt.date
    residency: Residency = Residency.RESIDENT
    gross_pay: Optional[Money] = None
    allowances: Money = field(default_factory=Money.zero)
    pre_tax_deductions: Money = field(default_factory=Money.zero)
    revenue: Optional[Money] = None
    allowable_deductions: Money = field(default_factory=Money.zero)
    invoices: Tuple[object, ...] = ()
    payment: Optional[Money] = None

    def __post_init__(self) -> None:
        if not isinstance(self.on_date, dt.date):
            raise TypeError("on_date must be a datetime.date.")
        if not isinstance(self.residency, Residency):
            raise TypeError("residency must be a Residency value.")
        for name in ("gross_pay", "allowances", "pre_tax_deductions", "revenue",
                     "allowable_deductions", "payment"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, Money):
                raise InvalidIncomeError(
                    f"{name} must be Money, got {type(value).__name__}. Wrap it: Money({value!r})."
                )
            if value.is_negative():
                raise InvalidIncomeError(f"{name} cannot be negative ({value}).")

    # -- helpers used by several taxes -----------------------------------------
    def require(self, field_name: str) -> Money:
        """Return a monetary field, or raise InvalidIncomeError if it was not supplied."""
        value = getattr(self, field_name)
        if value is None:
            raise InvalidIncomeError(f"This tax needs '{field_name}', but it was not provided.")
        return value

    @property
    def total_employment_income(self) -> Money:
        """Gross pay plus taxable allowances."""
        return self.require("gross_pay") + self.allowances


@dataclass(frozen=True)
class LineItem:
    """One explanatory line of a result, e.g. ('20% of 75,000', UGX 15,000)."""

    label: str
    amount: Money


@dataclass(frozen=True)
class TaxResult:
    """The outcome of one tax calculation.

    Attributes:
        tax_name: Which tax produced it, e.g. "PAYE".
        amount: Tax payable (never negative, except net VAT which can be a refund).
        base: The amount the tax was charged on (chargeable income, taxable value, ...).
        breakdown: Step-by-step lines so a person can check the arithmetic.
        basis: The schedule or legal source applied, for the audit trail.
    """

    tax_name: str
    amount: Money
    base: Money
    breakdown: Tuple[LineItem, ...] = ()
    basis: str = ""

    def effective_rate(self) -> Optional[Decimal]:
        """amount / base as a Decimal, or None when the base is zero."""
        return None if not self.base else self.amount.ratio(self.base)

    def explain(self) -> str:
        """A printable, human-readable explanation."""
        lines = [f"{self.tax_name}: {self.amount}  (on a base of {self.base})"]
        lines += [f"    {item.label:<52} {str(item.amount):>18}" for item in self.breakdown]
        if self.basis:
            lines.append(f"    basis: {self.basis}")
        return "\n".join(lines)


class Tax(ABC):
    """Abstract base class: the contract every tax must fulfil.

    Subclasses set ``name`` and implement :meth:`calculate`. ``Tax()`` itself cannot be
    instantiated.
    """

    name: str = "Tax"

    @abstractmethod
    def calculate(self, ctx: TaxContext) -> TaxResult:
        """Compute this tax for the given context and return a TaxResult."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"
