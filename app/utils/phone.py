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
