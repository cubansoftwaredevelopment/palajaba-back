from typing import Literal

OrderStatus = Literal["pending_confirmation", "completed", "cancelled"]
InvoiceType = Literal["store", "transporter"]
OrderOrigin = Literal["platform", "manual"]
OrderPaymentMethod = Literal["contact", "qvapay"]
PAYMENT_CURRENCIES = ("CUP", "USD", "EUR", "MLC", "QUSD")
