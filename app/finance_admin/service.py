from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import OperationFailure

from app.constants import CURRENCY_CODES
from app.database import (
    get_finance_ledger_collection,
    get_platform_debts_collection,
    get_platform_expenses_collection,
)
from app.finance_admin.schemas import (
    DebtListPublic,
    DebtPublic,
    DeleteDebtsResult,
    ExpenseCreate,
    ExpensePublic,
    DebtUpdate,
    ExpenseUpdate,
    ExtractionCreate,
    GenerateDebtsResult,
    LedgerEntryPublic,
    LedgerListPublic,
    LiquidateDebtsResult,
)
from app.services.exchange_rates import SUPPORTED_CURRENCIES, snapshot_cup_per_unit
from app.utils.currency_conversion import convert_amount
from app.utils.datetime import APP_DISPLAY_TZ, as_utc_aware, to_utc_naive, utc_now

SPANISH_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


async def ensure_finance_indexes() -> None:
    expenses = get_platform_expenses_collection()
    debts = get_platform_debts_collection()
    ledger = get_finance_ledger_collection()
    await expenses.create_index([("created_at", DESCENDING)])
    await debts.create_index(
        [("expense_id", ASCENDING), ("period_year", ASCENDING), ("period_month", ASCENDING)],
        unique=True,
    )
    await debts.create_index([("created_at", DESCENDING)])
    await debts.create_index([("deleted", ASCENDING), ("liquidated", ASCENDING)])
    await ledger.create_index([("at", DESCENDING)])
    try:
        await ledger.drop_index("source_1_source_id_1")
    except OperationFailure:
        pass
    await ledger.create_index([("source", ASCENDING), ("source_id", ASCENDING)], unique=False)


def _oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro no encontrado.") from exc


def _as_currency(value: Any) -> str:
    code = str(value or "CUP").strip().upper()
    return code if code in CURRENCY_CODES else "CUP"


def _cup_amount(amount: float, currency: str) -> float:
    return float(convert_amount(amount, currency, "CUP"))


def _snapshot_rates() -> dict[str, float]:
    return snapshot_cup_per_unit()


def _stored_rates(doc: dict[str, Any]) -> dict[str, float] | None:
    stored = doc.get("rates")
    if not isinstance(stored, dict) or not stored:
        return None
    snapshot: dict[str, float] = {"CUP": 1.0}
    for code in SUPPORTED_CURRENCIES:
        raw = stored.get(code)
        if raw:
            snapshot[code] = float(raw)
    return snapshot


def _convert_with_rates(amount: float, from_currency: str, to_currency: str, rates: dict[str, float]) -> float:
    from_code = _as_currency(from_currency)
    to_code = _as_currency(to_currency)
    if from_code == to_code:
        return float(amount)
    from_rate = rates.get(from_code)
    to_rate = rates.get(to_code)
    if not from_rate or not to_rate:
        return float(amount)
    converted = float(amount) * from_rate / to_rate
    if to_code == "CUP":
        return float(round(converted))
    return float(round(converted, 2))


def _expense_public(doc: dict[str, Any]) -> ExpensePublic:
    return ExpensePublic(
        id=str(doc["_id"]),
        title=str(doc.get("title") or ""),
        amount=float(doc.get("amount") or 0),
        currency=_as_currency(doc.get("currency")),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _debt_public(doc: dict[str, Any], target_currency: str | None = None) -> DebtPublic:
    amount = float(doc.get("amount") or 0)
    currency = _as_currency(doc.get("currency"))
    expense_id = doc.get("expense_id")
    converted_amount = None
    converted_currency = None
    if target_currency:
        converted_currency = _as_currency(target_currency)
        converted_amount = float(convert_amount(amount, currency, converted_currency))
    return DebtPublic(
        id=str(doc["_id"]),
        expense_id=str(expense_id) if expense_id else None,
        title=str(doc.get("title") or ""),
        amount=amount,
        currency=currency,
        period_year=int(doc.get("period_year") or 0),
        period_month=int(doc.get("period_month") or 0),
        liquidated=bool(doc.get("liquidated")),
        liquidated_at=doc.get("liquidated_at"),
        ledger_id=str(doc["ledger_id"]) if doc.get("ledger_id") else None,
        deleted=bool(doc.get("deleted")),
        deleted_at=doc.get("deleted_at"),
        created_at=doc["created_at"],
        cup_amount=_cup_amount(amount, currency),
        converted_amount=converted_amount,
        converted_currency=converted_currency,
    )


def _ledger_public(doc: dict[str, Any], target_currency: str | None = None) -> LedgerEntryPublic:
    amount = float(doc.get("amount") or 0)
    currency = _as_currency(doc.get("currency"))
    source_id = doc.get("source_id")
    stored = _stored_rates(doc)
    rates = stored or _snapshot_rates()
    display_currency = _as_currency(target_currency) if target_currency else currency
    display_amount = _convert_with_rates(amount, currency, display_currency, rates)
    return LedgerEntryPublic(
        id=str(doc["_id"]),
        kind=doc.get("kind") or "extraction",
        amount=amount,
        currency=currency,
        reason=str(doc.get("reason") or ""),
        at=doc.get("at") or doc.get("created_at"),
        source=doc.get("source") or "manual",
        source_id=str(source_id) if source_id else None,
        cup_amount=_convert_with_rates(amount, currency, "CUP", rates),
        rates=stored or {},
        display_amount=display_amount,
        display_currency=display_currency,
    )


def _cuba_now() -> datetime:
    return utc_now().astimezone(APP_DISPLAY_TZ)


def _cuba_day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=APP_DISPLAY_TZ)


def _balance_bucket(value: datetime | None) -> datetime:
    local = as_utc_aware(value or datetime.min).astimezone(APP_DISPLAY_TZ)
    return local.replace(second=0, microsecond=0)


def _window(start: date | None, end: date | None) -> tuple[datetime, datetime]:
    local = _cuba_now()
    today = local.date()
    max_end = today + timedelta(days=1)
    if start is None and end is None:
        month_start = date(today.year, today.month, 1)
        return to_utc_naive(_cuba_day_start(month_start)), to_utc_naive(_cuba_day_start(today + timedelta(days=1)))
    if start is None or end is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Indica la fecha de inicio y la de fin.",
        )
    if end < start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha final no puede ser anterior a la inicial.",
        )
    if start > max_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ese rango aún no ha comenzado.",
        )
    capped_end = end if end <= max_end else max_end
    start_dt = to_utc_naive(_cuba_day_start(start))
    end_dt = to_utc_naive(_cuba_day_start(capped_end + timedelta(days=1)))
    if start_dt >= end_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rango no tiene días para mostrar.",
        )
    return start_dt, end_dt


def _period_keys_from_dates(start: date, end: date) -> list[dict[str, int]]:
    keys: list[dict[str, int]] = []
    cursor = date(start.year, start.month, 1)
    end_month = date(end.year, end.month, 1)
    while cursor <= end_month:
        keys.append({"period_year": cursor.year, "period_month": cursor.month})
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return keys


def _add_total(totals: dict[str, float], currency: str, amount: float) -> None:
    totals[currency] = round(totals.get(currency, 0.0) + amount, 2)


async def list_expenses() -> list[ExpensePublic]:
    docs = await get_platform_expenses_collection().find({}).sort("created_at", DESCENDING).to_list(length=500)
    return [_expense_public(doc) for doc in docs]


async def create_expense(payload: ExpenseCreate) -> ExpensePublic:
    now = to_utc_naive(utc_now())
    document = {
        "title": payload.title,
        "amount": float(payload.amount),
        "currency": payload.currency,
        "created_at": now,
        "updated_at": now,
    }
    result = await get_platform_expenses_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return _expense_public(document)


async def update_expense(expense_id: str, payload: ExpenseUpdate) -> ExpensePublic:
    collection = get_platform_expenses_collection()
    doc = await collection.find_one({"_id": _oid(expense_id)})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gasto no encontrado.")
    updates: dict[str, Any] = {"updated_at": to_utc_naive(utc_now())}
    if payload.title is not None:
        updates["title"] = payload.title
    if payload.amount is not None:
        updates["amount"] = float(payload.amount)
    if payload.currency is not None:
        updates["currency"] = payload.currency
    await collection.update_one({"_id": doc["_id"]}, {"$set": updates})
    updated = await collection.find_one({"_id": doc["_id"]})
    return _expense_public(updated)


async def delete_expense(expense_id: str) -> None:
    result = await get_platform_expenses_collection().delete_one({"_id": _oid(expense_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gasto no encontrado.")


async def list_debts(
    *,
    start: date | None,
    end: date | None,
    currency: str | None,
    include_liquidated: bool,
    include_deleted: bool,
) -> DebtListPublic:
    local = _cuba_now().date()
    period_start = start or date(local.year, local.month, 1)
    period_end = end or local
    period_keys = _period_keys_from_dates(period_start, period_end)
    query: dict[str, Any] = {"$or": period_keys} if period_keys else {"_id": None}
    if not include_deleted:
        query["deleted"] = {"$ne": True}
    if not include_liquidated:
        query["liquidated"] = {"$ne": True}
    target = _as_currency(currency) if currency else None

    docs = await get_platform_debts_collection().find(query).sort("created_at", DESCENDING).to_list(length=2000)
    items = [_debt_public(doc, target) for doc in docs]
    totals: dict[str, float] = {}
    for item in items:
        if item.deleted:
            continue
        if target and item.converted_amount is not None:
            _add_total(totals, target, item.converted_amount)
        else:
            _add_total(totals, item.currency, item.amount)
    return DebtListPublic(items=items, totals=totals)


async def update_debt(debt_id: str, payload: DebtUpdate) -> DebtPublic:
    debts = get_platform_debts_collection()
    doc = await debts.find_one({"_id": _oid(debt_id)})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deuda no encontrada.")
    if doc.get("deleted"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No se puede editar una deuda eliminada.")

    updates: dict[str, Any] = {}
    if payload.title is not None:
        updates["title"] = payload.title
    if payload.amount is not None:
        updates["amount"] = float(payload.amount)
    if payload.currency is not None:
        updates["currency"] = payload.currency
    if updates:
        await debts.update_one({"_id": doc["_id"]}, {"$set": updates})
        ledger_id = doc.get("ledger_id")
        if doc.get("liquidated") and ledger_id:
            ledger_updates: dict[str, Any] = {}
            if "amount" in updates:
                ledger_updates["amount"] = updates["amount"]
            if "currency" in updates:
                ledger_updates["currency"] = updates["currency"]
            if ledger_updates:
                await get_finance_ledger_collection().update_one({"_id": ledger_id}, {"$set": ledger_updates})
        doc = await debts.find_one({"_id": doc["_id"]})
    return _debt_public(doc)


def _generate_debts_message(
    *,
    period_label: str,
    expense_count: int,
    created: int,
    skipped_zero: int,
    skipped_existing: int,
) -> str:
    if created > 0:
        suffix = f" para {period_label}" if period_label else ""
        return f"Se generaron {created} deuda{'s' if created != 1 else ''}{suffix}."
    if expense_count == 0:
        return "No hay gastos de plataforma configurados. Añade al menos uno con monto mayor que 0."
    if skipped_existing and not skipped_zero:
        return f"Las deudas de {period_label} ya están generadas."
    if skipped_zero and not skipped_existing:
        return "Ningún gasto tiene un monto mayor que 0. Actualiza los gastos e inténtalo de nuevo."
    return f"No se generó ninguna deuda nueva para {period_label}: ya existen o el monto es 0."


async def generate_debts(*, year: int | None, month: int | None) -> GenerateDebtsResult:
    now = to_utc_naive(utc_now())
    period_year = year or now.year
    period_month = month or now.month
    period_label = _period_label(period_year, period_month)
    expenses = await get_platform_expenses_collection().find({}).to_list(length=500)
    debts = get_platform_debts_collection()
    created = 0
    skipped_zero = 0
    skipped_existing = 0
    for expense in expenses:
        amount = float(expense.get("amount") or 0)
        if amount <= 0:
            skipped_zero += 1
            continue
        expense_id = expense["_id"]
        existing = await debts.find_one(
            {"expense_id": expense_id, "period_year": period_year, "period_month": period_month}
        )
        if existing is not None:
            skipped_existing += 1
            continue
        await debts.insert_one(
            {
                "expense_id": expense_id,
                "title": str(expense.get("title") or "Gasto de plataforma"),
                "amount": amount,
                "currency": _as_currency(expense.get("currency")),
                "period_year": period_year,
                "period_month": period_month,
                "liquidated": False,
                "liquidated_at": None,
                "ledger_id": None,
                "deleted": False,
                "deleted_at": None,
                "created_at": now,
            }
        )
        created += 1
    skipped = skipped_zero + skipped_existing
    return GenerateDebtsResult(
        period_year=period_year,
        period_month=period_month,
        created_count=created,
        skipped=skipped,
        message=_generate_debts_message(
            period_label=period_label,
            expense_count=len(expenses),
            created=created,
            skipped_zero=skipped_zero,
            skipped_existing=skipped_existing,
        ),
    )


def _period_label(year: int, month: int) -> str:
    name = SPANISH_MONTHS[month - 1] if 1 <= month <= 12 else str(month)
    return f"{name} {year}"


def _shared_liquidation_reason(docs: list[dict[str, Any]], reason: str | None) -> str | None:
    shared = (reason or "").strip()
    if shared:
        return shared
    if len(docs) < 2:
        return None
    periods = {
        _period_label(int(doc.get("period_year") or 0), int(doc.get("period_month") or 0))
        for doc in docs
    }
    periods.discard("0 0")
    if len(periods) == 1:
        return f"Liquidación · {next(iter(periods))}"
    return "Liquidación de deudas"


async def liquidate_debts(ids: list[str], reason: str | None) -> LiquidateDebtsResult:
    debts = get_platform_debts_collection()
    ledger = get_finance_ledger_collection()
    now = to_utc_naive(utc_now())
    skipped = 0
    seen: set[str] = set()
    pending_docs: list[dict[str, Any]] = []
    for raw_id in ids:
        key = str(raw_id or "").strip()
        if not key or key in seen:
            skipped += 1
            continue
        seen.add(key)
        try:
            oid = ObjectId(key)
        except Exception:
            skipped += 1
            continue
        doc = await debts.find_one({"_id": oid})
        if doc is None or doc.get("deleted") or doc.get("liquidated"):
            skipped += 1
            continue
        pending_docs.append(doc)

    shared_reason = _shared_liquidation_reason(pending_docs, reason)
    liquidated = 0
    for doc in pending_docs:
        period_label = _period_label(int(doc.get("period_year") or now.year), int(doc.get("period_month") or now.month))
        entry_reason = shared_reason or f"Liquidación · {doc.get('title')} · {period_label}"
        entry = {
            "kind": "extraction",
            "amount": float(doc.get("amount") or 0),
            "currency": _as_currency(doc.get("currency")),
            "reason": entry_reason,
            "at": now,
            "source": "debt_liquidation",
            "source_id": str(doc["_id"]),
            "created_at": now,
            "rates": _snapshot_rates(),
        }
        inserted = await ledger.insert_one(entry)
        await debts.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "liquidated": True,
                    "liquidated_at": now,
                    "ledger_id": inserted.inserted_id,
                }
            },
        )
        liquidated += 1
    return LiquidateDebtsResult(liquidated=liquidated, skipped=skipped)


async def delete_debts(ids: list[str]) -> DeleteDebtsResult:
    debts = get_platform_debts_collection()
    now = to_utc_naive(utc_now())
    deleted = 0
    skipped = 0
    for raw_id in ids:
        doc = await debts.find_one({"_id": _oid(raw_id)})
        if doc is None or doc.get("deleted"):
            skipped += 1
            continue
        await debts.update_one(
            {"_id": doc["_id"]},
            {"$set": {"deleted": True, "deleted_at": now}},
        )
        deleted += 1
    return DeleteDebtsResult(deleted=deleted, skipped=skipped)


async def list_ledger(
    *,
    start: date | None,
    end: date | None,
    currency: str | None,
) -> LedgerListPublic:
    window_start, window_end = _window(start, end)
    target = _as_currency(currency) if currency else None
    query: dict[str, Any] = {"at": {"$gte": window_start, "$lt": window_end}}
    docs = await get_finance_ledger_collection().find(query).to_list(length=5000)
    items = [_ledger_public(doc, target) for doc in docs]
    chronological = sorted(items, key=lambda item: (item.at or datetime.min, item.id))
    running = 0.0
    totals: dict[str, float] = {}
    bucket_balance: dict[datetime, float] = {}
    for item in chronological:
        signed_original = item.amount if item.kind == "income" else -item.amount
        if target:
            signed = item.display_amount if item.kind == "income" else -item.display_amount
            _add_total(totals, target, signed)
        else:
            _add_total(totals, item.currency, signed_original)
            signed = float(item.cup_amount or 0)
            signed = signed if item.kind == "income" else -signed
        running = round(running + signed, 2)
        bucket_balance[_balance_bucket(item.at)] = running
    for item in items:
        item.balance = bucket_balance.get(_balance_bucket(item.at), running)
    items.sort(key=lambda item: (item.at or datetime.min, item.id), reverse=True)
    return LedgerListPublic(items=items, totals=totals)


async def create_extraction(payload: ExtractionCreate) -> LedgerEntryPublic:
    now = to_utc_naive(utc_now())
    if payload.at is None:
        at = now
    elif payload.at.tzinfo is None:
        at = to_utc_naive(payload.at.replace(tzinfo=APP_DISPLAY_TZ))
    else:
        at = to_utc_naive(payload.at)
    document = {
        "kind": "extraction",
        "amount": float(payload.amount),
        "currency": payload.currency,
        "reason": payload.reason,
        "at": at,
        "source": "manual",
        "source_id": None,
        "created_at": now,
        "rates": _snapshot_rates(),
    }
    result = await get_finance_ledger_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return _ledger_public(document)
