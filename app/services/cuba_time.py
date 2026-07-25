"""Hora local de Cuba (UTC-4, sin DST) para agregaciones de tráfico."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.utils.datetime import to_utc_naive

# Cuba permanece en UTC-4 de forma permanente desde 2022.
CUBA_UTC_OFFSET = timedelta(hours=-4)

SPANISH_WEEKDAYS = (
    "Lun",
    "Mar",
    "Mié",
    "Jue",
    "Vie",
    "Sáb",
    "Dom",
)


def to_cuba_local(value: datetime) -> datetime:
    """Convierte un datetime UTC (naive o aware) a hora local de Cuba naive."""
    utc = to_utc_naive(value)
    return utc + CUBA_UTC_OFFSET


def cuba_date_str(value: datetime) -> str:
    return to_cuba_local(value).strftime("%Y-%m-%d")


def cuba_hour(value: datetime) -> int:
    return to_cuba_local(value).hour


def cuba_weekday(value: datetime) -> int:
    """0 = lunes … 6 = domingo (igual que datetime.weekday)."""
    return to_cuba_local(value).weekday()


def cuba_hour_label(hour: int) -> str:
    return f"{hour:02d}:00"


def cuba_weekday_label(weekday: int) -> str:
    if weekday < 0 or weekday > 6:
        raise ValueError("weekday debe estar entre 0 y 6")
    return SPANISH_WEEKDAYS[weekday]
