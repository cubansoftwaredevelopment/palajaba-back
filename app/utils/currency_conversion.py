from app.services.exchange_rates import SUPPORTED_CURRENCIES, get_cup_per_unit


def convert_amount(amount: float, from_currency: str, to_currency: str) -> float:
    if from_currency == to_currency:
        return float(amount)

    cup_per_unit = get_cup_per_unit()
    from_rate = cup_per_unit.get(from_currency)
    to_rate = cup_per_unit.get(to_currency)
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


VALID_CURRENCIES = frozenset(SUPPORTED_CURRENCIES)
