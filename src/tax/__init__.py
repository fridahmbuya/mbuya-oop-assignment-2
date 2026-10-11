"""Uganda tax engine (Mini-Project 2).

Public API, importable as ``from src.tax import ...``.
"""
from src.tax.business import (
    VAT,
    CorporateIncomeTax,
    Invoice,
    InvoiceKind,
    SupplyType,
    VatSummary,
    WithholdingTax,
)
from src.tax.core import LineItem, Residency, Tax, TaxContext, TaxResult
from src.tax.employment import NSSF, PAYE, LocalServiceTax, PayrollPipeline, Payslip
from src.tax.errors import (
    InvalidIncomeError,
    InvalidInvoiceError,
    MoneyTypeError,
    NoScheduleForDateError,
    TaxError,
)
from src.tax.money import Money
from src.tax.planner import (
    Comparison,
    DividendScenario,
    SalaryScenario,
    Scenario,
    ScenarioOutcome,
    TaxPlanner,
)
from src.tax.schedules import (
    NON_RESIDENT_2012,
    RESIDENT_2012,
    RESIDENT_2026,
    Band,
    ProgressiveSchedule,
    ScheduleRegistry,
    default_registry,
)

__all__ = [
    "Band", "Comparison", "CorporateIncomeTax", "DividendScenario", "Invoice", "InvoiceKind",
    "InvalidIncomeError", "InvalidInvoiceError", "LineItem", "LocalServiceTax", "Money",
    "MoneyTypeError", "NON_RESIDENT_2012", "NSSF", "NoScheduleForDateError", "PAYE",
    "PayrollPipeline", "Payslip", "ProgressiveSchedule", "RESIDENT_2012", "RESIDENT_2026",
    "Residency", "SalaryScenario", "Scenario", "ScenarioOutcome", "ScheduleRegistry",
    "SupplyType", "Tax", "TaxContext", "TaxError", "TaxPlanner", "TaxResult", "VAT",
    "VatSummary", "WithholdingTax", "default_registry",
]
