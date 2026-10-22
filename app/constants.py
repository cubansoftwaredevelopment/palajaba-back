REJECTION_REASON_UNCONFIRMED_PAYMENT = (
    "No pudimos confirmar el pago de la transferencia."
)

DEFAULT_PLAN_PRICES = {
    "standard": {
        "monthly": {"amount": 2, "currency": "USD"},
        "yearly": {"amount": 20, "currency": "USD"},
    },
    "pro": {
        "monthly": {"amount": 8, "currency": "USD"},
        "yearly": {"amount": 80, "currency": "USD"},
    },
    "premium": {
        "monthly": {"amount": 4, "currency": "USD"},
        "yearly": {"amount": 30, "currency": "USD"},
    },
}

SUPPORTED_CURRENCIES = [
    {"code": "CUP", "label": "Peso cubano (CUP)", "symbol": "$"},
    {"code": "USD", "label": "Dólar (USD)", "symbol": "$"},
    {"code": "EUR", "label": "Euro (EUR)", "symbol": "€"},
    {"code": "MLC", "label": "MLC", "symbol": "$"},
]

CURRENCY_CODES = {item["code"] for item in SUPPORTED_CURRENCIES}
