REJECTION_REASON_UNCONFIRMED_PAYMENT = (
    "No pudimos confirmar el pago de la transferencia."
)

PLAN_PRICES_CUP = {
    "monthly": 1000,
    "yearly": 10000,
}

SUPPORTED_CURRENCIES = [
    {"code": "CUP", "label": "Peso cubano (CUP)", "symbol": "$"},
    {"code": "USD", "label": "Dólar (USD)", "symbol": "$"},
    {"code": "MLC", "label": "MLC", "symbol": "$"},
]

CURRENCY_CODES = {item["code"] for item in SUPPORTED_CURRENCIES}
