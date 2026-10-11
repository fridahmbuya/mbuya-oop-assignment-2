"""Business taxes: VAT, corporate income tax and withholding tax."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Iterable, Tuple

from src.tax.core import LineItem, Tax, TaxContext, TaxResult
from src.tax.errors import InvalidInvoiceError
from src.tax.money import Money


# ---------------------------------------------------------------------------
# VAT
# ---------------------------------------------------------------------------
class SupplyType(Enum):
    """How a supply is treated for VAT.

    STANDARD    18 % VAT is charged; input VAT on related costs can be claimed.
    ZERO_RATED  taxable at 0 % (e.g. exports); input VAT can STILL be claimed.
    EXEMPT      outside VAT (e.g. financial or medical services); no VAT is charged and
                input VAT on related costs can NOT be claimed.
    """

    STANDARD = "standard-rated"
    ZERO_RATED = "zero-rated"
    EXEMPT = "exempt"


class InvoiceKind(Enum):
    SALE = "sale"          # we supplied goods/services -> output VAT
    PURCHASE = "purchase"  # we bought goods/services   -> input VAT


@dataclass(frozen=True)
class Invoice:
    """One invoice. ``net_amount`` is the value BEFORE VAT."""

    number: str
    kind: InvoiceKind
    supply_type: SupplyType
    net_amount: Money
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, InvoiceKind) or not isinstance(self.supply_type, SupplyType):
            raise InvalidInvoiceError(f"Invoice {self.number}: kind/supply_type must be enum values.")
        if not isinstance(self.net_amount, Money):
            raise InvalidInvoiceError(f"Invoice {self.number}: net_amount must be Money.")
        if self.net_amount.is_negative():
            raise InvalidInvoiceError(f"Invoice {self.number}: amount cannot be negative.")

    def vat(self, rate: Decimal) -> Money:
        """VAT on this invoice: rate x net for standard-rated supplies, otherwise zero."""
        return self.net_amount * rate if self.supply_type is SupplyType.STANDARD else Money.zero()


@dataclass(frozen=True)
class VatSummary:
    """Totals for one VAT period."""

    standard_sales: Money
    zero_rated_sales: Money
    exempt_sales: Money
    output_vat: Money
    input_vat: Money
    recoverable_fraction: Decimal
    claimable_input_vat: Money

    @property
    def taxable_sales(self) -> Money:
        return self.standard_sales + self.zero_rated_sales

    @property
    def net_vat_payable(self) -> Money:
        """Output VAT minus claimable input VAT. Negative means a credit/refund position."""
        return self.output_vat - self.claimable_input_vat


class VAT(Tax):
    """Value Added Tax for a list of invoices.

    net VAT payable = output VAT on sales - claimable input VAT on purchases

    Input VAT is fully claimable when all sales are taxable (standard or zero-rated). If
    some sales are exempt, input VAT is apportioned by taxable sales / total sales, with the
    usual de minimis rule: exempt share under 5 % -> claim everything; over 95 % -> claim
    nothing.

    Args:
        rate: Standard rate (18 % in Uganda).
    """

    name = "VAT"

    def __init__(self, rate: Decimal = Decimal("0.18")) -> None:
        if not isinstance(rate, Decimal) or not Decimal("0") <= rate <= Decimal("1"):
            raise ValueError("VAT rate must be a Decimal between 0 and 1.")
        self.rate = rate

    @staticmethod
    def _total(invoices: Iterable[Invoice], kind: InvoiceKind, supply: SupplyType) -> Money:
        return sum(
            (i.net_amount for i in invoices if i.kind is kind and i.supply_type is supply), Money.zero()
        )

    def recoverable_fraction(self, taxable_sales: Money, exempt_sales: Money) -> Decimal:
        """Share of input VAT that may be claimed (1 = all of it)."""
        total = taxable_sales + exempt_sales
        if not total or not exempt_sales:
            return Decimal("1")
        taxable_share = taxable_sales.ratio(total)
        if taxable_share > Decimal("0.95"):
            return Decimal("1")
        if taxable_share < Decimal("0.05"):
            return Decimal("0")
        return taxable_share

    def summarise(self, invoices: Iterable[Invoice]) -> VatSummary:
        invoices = tuple(invoices)
        for inv in invoices:
            if not isinstance(inv, Invoice):
                raise InvalidInvoiceError(f"Expected Invoice objects, got {type(inv).__name__}.")
        standard = self._total(invoices, InvoiceKind.SALE, SupplyType.STANDARD)
        zero = self._total(invoices, InvoiceKind.SALE, SupplyType.ZERO_RATED)
        exempt = self._total(invoices, InvoiceKind.SALE, SupplyType.EXEMPT)
        standard_purchases = self._total(invoices, InvoiceKind.PURCHASE, SupplyType.STANDARD)
        output_vat = standard * self.rate
        input_vat = standard_purchases * self.rate
        fraction = self.recoverable_fraction(standard + zero, exempt)
        return VatSummary(standard, zero, exempt, output_vat, input_vat, fraction, input_vat * fraction)

    def calculate(self, ctx: TaxContext) -> TaxResult:
        s = self.summarise(ctx.invoices)
        lines: Tuple[LineItem, ...] = (
            LineItem(f"Output VAT: {self.rate:.0%} of standard-rated sales {s.standard_sales.amount:,}", s.output_vat),
            LineItem(f"Zero-rated sales {s.zero_rated_sales.amount:,} at 0%", Money.zero()),
            LineItem(f"Exempt sales {s.exempt_sales.amount:,} (no VAT)", Money.zero()),
            LineItem("Input VAT on standard-rated purchases", s.input_vat),
            LineItem(f"Claimable input VAT ({s.recoverable_fraction:.2%} recoverable)", s.claimable_input_vat),
        )
        return TaxResult(self.name, s.net_vat_payable, s.taxable_sales, lines,
                         basis="VAT Act: standard rate 18%; input tax apportioned where exempt supplies are made")


# ---------------------------------------------------------------------------
# Corporate income tax
# ---------------------------------------------------------------------------
class CorporateIncomeTax(Tax):
    """Corporate income tax: rate x (revenue - allowable deductions), never below zero.

    A loss gives zero tax (it would be carried forward; that is noted in the breakdown,
    not modelled).
    """

    name = "Corporate income tax"

    def __init__(self, rate: Decimal = Decimal("0.30")) -> None:
        if not isinstance(rate, Decimal) or not Decimal("0") <= rate <= Decimal("1"):
            raise ValueError("Rate must be a Decimal between 0 and 1.")
        self.rate = rate

    def calculate(self, ctx: TaxContext) -> TaxResult:
        revenue = ctx.require("revenue")
        deductions = ctx.allowable_deductions
        basis = "Income Tax Act: 30% of chargeable income for resident companies"
        if deductions > revenue:
            loss = deductions - revenue
            lines = (
                LineItem(f"Revenue {revenue.amount:,} - deductions {deductions.amount:,}", -loss),
                LineItem("Tax loss carried forward: no tax this year", Money.zero()),
            )
            return TaxResult(self.name, Money.zero(), Money.zero(), lines, basis)
        chargeable = revenue - deductions
        tax = chargeable * self.rate
        lines = (
            LineItem(f"Chargeable income: {revenue.amount:,} - {deductions.amount:,}", chargeable),
            LineItem(f"{self.rate:.0%} of {chargeable.amount:,}", tax),
        )
        return TaxResult(self.name, tax, chargeable, lines, basis)


# ---------------------------------------------------------------------------
# Withholding tax (needed by the TaxPlanner extension)
# ---------------------------------------------------------------------------
class WithholdingTax(Tax):
    """A flat percentage withheld from a single payment (``ctx.payment``).

    Used here for dividends paid to a resident individual (15 %, a final tax).
    """

    def __init__(self, rate: Decimal = Decimal("0.15"), label: str = "dividends") -> None:
        if not isinstance(rate, Decimal) or not Decimal("0") <= rate <= Decimal("1"):
            raise ValueError("Rate must be a Decimal between 0 and 1.")
        self.rate = rate
        self.name = f"Withholding tax on {label} ({rate:.0%})"

    def calculate(self, ctx: TaxContext) -> TaxResult:
        payment = ctx.require("payment")
        tax = payment * self.rate
        line = LineItem(f"{self.rate:.0%} of {payment.amount:,}", tax)
        return TaxResult(self.name, tax, payment, (line,), basis="Income Tax Act: withholding tax on dividends")
