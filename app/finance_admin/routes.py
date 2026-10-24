from datetime import date

from fastapi import APIRouter, Body, Depends, Query, status

from app.constants import CURRENCY_CODES
from app.auth.utils import require_admin
from app.finance_admin import service
from app.finance_admin.schemas import (
    DebtIdsPayload,
    DebtListPublic,
    DebtPublic,
    DebtUpdate,
    DeleteDebtsResult,
    ExpenseCreate,
    ExpensePublic,
    ExpenseUpdate,
    ExtractionCreate,
    GenerateDebtsRequest,
    GenerateDebtsResult,
    LedgerEntryPublic,
    LedgerListPublic,
    LiquidateDebtsResult,
)

router = APIRouter(prefix="/api/admin/finance", tags=["finance"])


def _currency_query(value: str | None) -> str | None:
    if not value:
        return None
    code = value.strip().upper()
    return code if code in CURRENCY_CODES else None


@router.get("/expenses", response_model=list[ExpensePublic])
async def list_expenses(_: dict = Depends(require_admin)):
    return await service.list_expenses()


@router.post("/expenses", response_model=ExpensePublic, status_code=status.HTTP_201_CREATED)
async def create_expense(payload: ExpenseCreate, _: dict = Depends(require_admin)):
    return await service.create_expense(payload)


@router.patch("/expenses/{expense_id}", response_model=ExpensePublic)
async def update_expense(expense_id: str, payload: ExpenseUpdate, _: dict = Depends(require_admin)):
    return await service.update_expense(expense_id, payload)


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(expense_id: str, _: dict = Depends(require_admin)):
    await service.delete_expense(expense_id)


@router.get("/debts", response_model=DebtListPublic)
async def list_debts(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    currency: str | None = Query(default=None),
    include_liquidated: bool = Query(default=False),
    include_deleted: bool = Query(default=False),
    _: dict = Depends(require_admin),
):
    return await service.list_debts(
        start=start,
        end=end,
        currency=_currency_query(currency),
        include_liquidated=include_liquidated,
        include_deleted=include_deleted,
    )


@router.patch("/debts/{debt_id}", response_model=DebtPublic)
async def update_debt(debt_id: str, payload: DebtUpdate, _: dict = Depends(require_admin)):
    return await service.update_debt(debt_id, payload)


@router.post("/debts/generate", response_model=GenerateDebtsResult)
async def generate_debts(
    payload: GenerateDebtsRequest = Body(default_factory=GenerateDebtsRequest),
    _: dict = Depends(require_admin),
):
    return await service.generate_debts(year=payload.year, month=payload.month)


@router.post("/debts/liquidate", response_model=LiquidateDebtsResult)
async def liquidate_debts(payload: DebtIdsPayload, _: dict = Depends(require_admin)):
    return await service.liquidate_debts(payload.ids, payload.reason)


@router.post("/debts/delete", response_model=DeleteDebtsResult)
async def delete_debts(payload: DebtIdsPayload, _: dict = Depends(require_admin)):
    return await service.delete_debts(payload.ids)


@router.get("/ledger", response_model=LedgerListPublic)
async def list_ledger(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    currency: str | None = Query(default=None),
    _: dict = Depends(require_admin),
):
    return await service.list_ledger(start=start, end=end, currency=_currency_query(currency))


@router.post("/ledger/extractions", response_model=LedgerEntryPublic, status_code=status.HTTP_201_CREATED)
async def create_extraction(payload: ExtractionCreate, _: dict = Depends(require_admin)):
    return await service.create_extraction(payload)
