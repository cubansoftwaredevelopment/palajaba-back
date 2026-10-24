PHONE_PREFIX = "+53"


def phone_display(digits: str) -> str:
    return f"{PHONE_PREFIX}{digits}"


def normalize_phone_digits(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits.startswith("53") and len(digits) == 10:
        digits = digits[2:]
    if len(digits) != 8:
        raise ValueError("El teléfono debe tener 8 dígitos.")
    return digits


def to_e164(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("+"):
        digits = "".join(ch for ch in raw[1:] if ch.isdigit())
        return f"+{digits}" if digits else ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("53") and len(digits) >= 10:
        return f"+{digits}"
    if len(digits) == 8:
        return f"{PHONE_PREFIX}{digits}"
    return f"+{digits}"


def can_send_sms(phone: str | None) -> bool:
    return to_e164(phone).startswith(PHONE_PREFIX)


def normalize_admin_phone(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    e164 = to_e164(raw)
    if len(e164) < 8:
        raise ValueError("Indica un teléfono válido.")
    return e164
