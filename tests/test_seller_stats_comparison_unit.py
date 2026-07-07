from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.services.seller_stats import (
    build_period_comparison,
    comparison_available_for_seller,
    compute_change_percent,
    resolve_comparison_window,
)
from tests.helpers_seller_stats import seller_document


def test_daily_window_compares_today_with_yesterday() -> None:
    reference = datetime(2026, 3, 15, 18, 30, 0)
    window = resolve_comparison_window("daily", reference=reference)

    assert window.current_start == datetime(2026, 3, 15)
    assert window.current_end == datetime(2026, 3, 16)
    assert window.previous_start == datetime(2026, 3, 14)
    assert window.previous_end == datetime(2026, 3, 15)
    assert window.comparison_label == "vs ayer"


def test_daily_window_crosses_month_boundary() -> None:
    reference = datetime(2026, 3, 1, 9, 0, 0)
    window = resolve_comparison_window("daily", reference=reference)

    assert window.previous_start == datetime(2026, 2, 28)
    assert window.previous_end == datetime(2026, 3, 1)


def test_daily_window_crosses_month_boundary_leap_year() -> None:
    reference = datetime(2024, 3, 1, 9, 0, 0)
    window = resolve_comparison_window("daily", reference=reference)

    assert window.previous_start == datetime(2024, 2, 29)
    assert window.previous_end == datetime(2024, 3, 1)


def test_weekly_window_compares_this_week_with_previous() -> None:
    # Wednesday 2026-03-11
    reference = datetime(2026, 3, 11, 12, 0, 0)
    window = resolve_comparison_window("weekly", reference=reference)

    assert window.current_start == datetime(2026, 3, 9)
    assert window.current_end == datetime(2026, 3, 12)
    assert window.previous_start == datetime(2026, 3, 2)
    assert window.previous_end == datetime(2026, 3, 5)
    assert window.comparison_label == "vs semana pasada"


def test_monthly_window_compares_mtd_with_same_span_previous_month() -> None:
    reference = datetime(2026, 7, 7, 15, 0, 0)
    window = resolve_comparison_window("monthly", reference=reference)

    assert window.current_start == datetime(2026, 7, 1)
    assert window.current_end == datetime(2026, 7, 8)
    assert window.previous_start == datetime(2026, 6, 1)
    assert window.previous_end == datetime(2026, 6, 8)
    assert window.comparison_label == "vs mes pasado"


def test_monthly_window_january_uses_december_previous_year() -> None:
    reference = datetime(2026, 1, 10, 8, 0, 0)
    window = resolve_comparison_window("monthly", reference=reference)

    assert window.previous_start == datetime(2025, 12, 1)
    assert window.previous_end == datetime(2025, 12, 11)


def test_monthly_window_caps_previous_span_on_shorter_month() -> None:
    reference = datetime(2026, 3, 31, 12, 0, 0)
    window = resolve_comparison_window("monthly", reference=reference)

    assert window.current_start == datetime(2026, 3, 1)
    assert window.current_end == datetime(2026, 4, 1)
    assert window.previous_start == datetime(2026, 2, 1)
    assert window.previous_end == datetime(2026, 3, 1)


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        (0.0, 0.0, 0.0),
        (50.0, 0.0, 100.0),
        (150.0, 100.0, 50.0),
        (80.0, 100.0, -20.0),
        (105.0, 100.0, 5.0),
    ],
)
def test_compute_change_percent(current: float, previous: float, expected: float) -> None:
    assert compute_change_percent(current, previous) == expected


def test_build_period_comparison_marks_unavailable() -> None:
    window = resolve_comparison_window("daily", reference=datetime(2026, 3, 15))
    comparison = build_period_comparison(10.0, 5.0, window, available=False)

    assert comparison.comparison_available is False
    assert comparison.change_percent is None
    assert comparison.direction == "unavailable"


def test_comparison_unavailable_before_seller_approval() -> None:
    window = resolve_comparison_window("daily", reference=datetime(2026, 3, 15))
    seller = seller_document()
    seller["approved_at"] = datetime(2026, 3, 14, 23, 0, 0)

    assert comparison_available_for_seller(window, seller) is False

    seller["approved_at"] = datetime(2026, 3, 13, 12, 0, 0)
    assert comparison_available_for_seller(window, seller) is True


def test_build_period_comparison_directions() -> None:
    window = resolve_comparison_window("daily", reference=datetime(2026, 3, 15))

    up = build_period_comparison(20.0, 10.0, window, available=True)
    down = build_period_comparison(5.0, 10.0, window, available=True)
    flat = build_period_comparison(10.0, 10.0, window, available=True)

    assert up.direction == "up"
    assert up.change_percent == 100.0
    assert down.direction == "down"
    assert down.change_percent == -50.0
    assert flat.direction == "flat"
    assert flat.change_percent == 0.0
