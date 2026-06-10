REJECTION_REASON_UNCONFIRMED_PAYMENT = (
    "No pudimos confirmar el pago de la transferencia."
)

PLAN_PRICES_USD = {
    "standard": {
        "monthly": 2,
        "yearly": 20,
    },
    "premium": {
        "monthly": 4,
        "yearly": 30,
    },
}

# Alias interno mientras el campo en BD sigue llamándose payment_amount_cup.
PLAN_PRICES_CUP = PLAN_PRICES_USD

SUPPORTED_CURRENCIES = [
    {"code": "CUP", "label": "Peso cubano (CUP)", "symbol": "$"},
    {"code": "USD", "label": "Dólar (USD)", "symbol": "$"},
    {"code": "MLC", "label": "MLC", "symbol": "$"},
]

CURRENCY_CODES = {item["code"] for item in SUPPORTED_CURRENCIES}
