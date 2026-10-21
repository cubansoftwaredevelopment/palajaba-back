from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.constants import CURRENCY_CODES
from app.utils.datetime import UtcDateTime

FinanceCurrency = Literal["CUP", "USD", "EUR", "MLC"]
LedgerKind = Literal["income", "extraction"]
LedgerSource = Literal["subscription", "debt_liquidation", "manual"]


def _normalize_currency(value: str) -> str:
    code = str(value or "").strip().upper()
    if code not in CURRENCY_CODES:
        raise ValueError("Moneda no soportada.")
    return code


class ExpenseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    amount: float = Field(..., ge=0)
    currency: FinanceCurrency = "CUP"

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("El título es obligatorio.")
        return cleaned

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return _normalize_currency(value)


class ExpenseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    amount: float | None = Field(default=None, ge=0)
    currency: FinanceCurrency | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("El título es obligatorio.")
        return cleaned

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_currency(value)


class ExpensePublic(BaseModel):
    id: str
    title: str
    amount: float
    currency: FinanceCurrency
    created_at: UtcDateTime
    updated_at: UtcDateTime


class DebtUpdate(ExpenseUpdate):
    pass


class DebtPublic(BaseModel):
    id: str
    expense_id: str | None = None
    title: str
    amount: float
    currency: FinanceCurrency
    period_year: int
    period_month: int
    liquidated: bool = False
    liquidated_at: UtcDateTime | None = None
    ledger_id: str | None = None
    deleted: bool = False
    deleted_at: UtcDateTime | None = None
    created_at: UtcDateTime
    cup_amount: float | None = None
    converted_amount: float | None = None
    converted_currency: FinanceCurrency | None = None


class DebtListPublic(BaseModel):
    items: list[DebtPublic]
    totals: dict[str, float] = Field(default_factory=dict)


class GenerateDebtsRequest(BaseModel):
    year: int | None = Field(default=None, ge=2020, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)


class GenerateDebtsResult(BaseModel):
    period_year: int
    period_month: int
    created_count: int
    skipped: int
    message: str = ""


class DebtIdsPayload(BaseModel):
    ids: list[str] = Field(..., min_length=1)
    reason: str | None = Field(default=None, max_length=240)

    @field_validator("ids")
    @classmethod
    def strip_ids(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("Indica al menos una deuda.")
        return cleaned


class LiquidateDebtsResult(BaseModel):
    liquidated: int
    skipped: int


class DeleteDebtsResult(BaseModel):
    deleted: int
    skipped: int


class LedgerEntryPublic(BaseModel):
    id: str
    kind: LedgerKind
    amount: float
    currency: FinanceCurrency
    reason: str
    at: UtcDateTime
    source: LedgerSource
    source_id: str | None = None
    cup_amount: float | None = None
    rates: dict[str, float] = Field(default_factory=dict)
    display_amount: float
    display_currency: FinanceCurrency
    balance: float = 0


class LedgerListPublic(BaseModel):
    items: list[LedgerEntryPublic]
    totals: dict[str, float] = Field(default_factory=dict)


class ExtractionCreate(BaseModel):
    amount: float = Field(..., gt=0)
    currency: FinanceCurrency = "CUP"
    reason: str = Field(..., min_length=1, max_length=240)
    at: UtcDateTime | None = None

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("El motivo es obligatorio.")
        return cleaned

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return _normalize_currency(value)
