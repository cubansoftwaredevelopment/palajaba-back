"""Tasas stub hasta integrar El Toque (CUP por unidad de moneda)."""

STUB_CUP_PER_UNIT = {
    "CUP": 1,
    "USD": 250,
    "MLC": 250,
}

VALID_CURRENCIES = frozenset(STUB_CUP_PER_UNIT.keys())


def convert_amount(amount: float, from_currency: str, to_currency: str) -> float:
    if from_currency == to_currency:
        return float(amount)

    from_rate = STUB_CUP_PER_UNIT.get(from_currency)
    to_rate = STUB_CUP_PER_UNIT.get(to_currency)
    if not from_rate or not to_rate:
        return float(amount)

    in_cup = float(amount) * from_rate
    converted = in_cup / to_rate

    if to_currency == "CUP":
        return float(round(converted))

    return float(round(converted, 2))


def format_money(amount: float, currency: str) -> str:
    if currency == "CUP":
        formatted = f"{int(round(amount)):,}".replace(",", ".")
    else:
        formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} {currency}"
