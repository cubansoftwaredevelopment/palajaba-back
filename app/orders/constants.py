from typing import Literal

OrderStatus = Literal["pending_confirmation", "in_transit", "completed", "cancelled"]
OPEN_ORDER_STATUSES = ("pending_confirmation", "in_transit")
InvoiceType = Literal["store", "transporter"]
OrderOrigin = Literal["platform", "manual"]
OrderPaymentMethod = Literal["contact", "qvapay"]
PAYMENT_CURRENCIES = ("CUP", "USD", "EUR", "MLC", "QUSD")
