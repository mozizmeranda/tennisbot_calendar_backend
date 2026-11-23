# calendar_api/helpers.py
"""
Общие вспомогательные функции для calendar_api/calendar.py и calendar_api/event.py.
Выделено для устранения дублирования кода.
"""
import logging
from datetime import datetime, timedelta, date
from typing import Optional, List

from fastapi import HTTPException

from database.database import db
from calendar_api.grid_utils import _build_cancelled_pairs, _build_grid  # noqa: F401 — реэкспорт

logger = logging.getLogger(__name__)

# На сколько недель вперёд (от start_date) проверяем лимит при создании бессрочной серии
RECURRING_CHECK_WEEKS = 8
# Максимальный период для закрепления слота (пакетных броней)
MAX_RESERVATION_DAYS = 366


async def require_calendar_access(calendar_id: str, telegram_id: int) -> dict:
    """Проверяет доступ и возвращает данные календаря. 403 если нет доступа."""
    has_access = await db.check_member_access(calendar_id, telegram_id)
    if not has_access:
        raise HTTPException(status_code=403, detail="You do not have access to this calendar")
    calendar = await db.get_calendar(calendar_id)
    if not calendar:
        raise HTTPException(status_code=404, detail="Calendar not found")
    return calendar


async def _load_grid(calendar_id: str, from_date: date, to_date: date) -> List[dict]:
    """Плоская сетка (одиночные + экземпляры серий) за период, с учётом start/end серий и отмен."""
    from_str = f"{from_date} 00:00:00"
    to_str = f"{to_date} 23:59:59"
    active = await db.get_single_events_for_calendar(
        calendar_id, from_str, to_str, statuses=["confirmed", "pending_payment"]
    )
    cancelled = await db.get_single_events_for_calendar(calendar_id, from_str, to_str, statuses=["cancelled"])
    cancelled_pairs = _build_cancelled_pairs(cancelled)
    recurring = await db.get_recurring_events_for_calendar(calendar_id)
    return _build_grid(active, cancelled_pairs, recurring, from_date, to_date)


def _slot_bounds(day: date, start_time: str, end_time: str):
    """(start, end) datetime слота в конкретный день; end_time == 00:00:00 → полночь следующего дня."""
    end_day = day + timedelta(days=1) if end_time == "00:00:00" else day
    return (
        datetime.fromisoformat(f"{day} {start_time}"),
        datetime.fromisoformat(f"{end_day} {end_time}"),
    )


def _first_overflow_hour(grid: List[dict], start: datetime, end: datetime, max_events: int) -> Optional[datetime]:
    """Первый часовой блок интервала, где уже занято >= max_events. None если места хватает."""
    parsed = [
        (datetime.fromisoformat(e["start_datetime"]), datetime.fromisoformat(e["end_datetime"]))
        for e in grid
    ]
    current_hour = start.replace(minute=0, second=0, microsecond=0)
    end_hour = end.replace(minute=0, second=0, microsecond=0)
    if end.minute > 0 or end.second > 0:
        end_hour += timedelta(hours=1)
    while current_hour < end_hour:
        block_end = current_hour + timedelta(hours=1)
        count = sum(1 for s, e in parsed if s < block_end and e > current_hour)
        if count + 1 > max_events:
            return current_hour
        current_hour += timedelta(hours=1)
    return None


async def _check_capacity(
    calendar_id: str,
    start_dt: str,
    end_dt: str,
    max_events: int,
    exclude_event_id: Optional[int] = None,
):
    """Проверяет лимит событий в час. Бросает 400 если превышен."""
    start = datetime.fromisoformat(start_dt)
    end = datetime.fromisoformat(end_dt)

    grid = await _load_grid(calendar_id, start.date(), end.date())
    if exclude_event_id is not None:
        grid = [e for e in grid if not (e["type"] == "single" and e["id"] == exclude_event_id)]

    hour = _first_overflow_hour(grid, start, end, max_events)
    if hour is not None:
        raise HTTPException(
            status_code=400,
            detail=f"Limit reached: max {max_events} events/hour at {hour.time().isoformat()}",
        )


async def _find_conflict_dates(
    calendar_id: str,
    dates: List[date],
    start_time: str,
    end_time: str,
    max_events: int,
) -> List[date]:
    """Из списка дат возвращает те, где слот start_time-end_time не помещается по лимиту."""
    if not dates:
        return []
    grid = await _load_grid(calendar_id, min(dates), max(dates) + timedelta(days=1))
    conflicts = []
    for d in dates:
        s, e = _slot_bounds(d, start_time, end_time)
        if _first_overflow_hour(grid, s, e, max_events) is not None:
            conflicts.append(d)
    return conflicts


def _dates_for_weekdays(first: date, last: date, days_of_week: List[int]) -> List[date]:
    days = set(days_of_week)
    result = []
    cur = first
    while cur <= last:
        if cur.weekday() in days:
            result.append(cur)
        cur += timedelta(days=1)
    return result


def _format_conflicts(dates: List[date], start_time: str) -> str:
    shown = ", ".join(d.isoformat() for d in dates[:5])
    more = f" (+{len(dates) - 5} more)" if len(dates) > 5 else ""
    return f"at {start_time[:5]} on {shown}{more}"


async def _check_recurring_capacity(
    calendar_id: str,
    start_time: str,
    end_time: str,
    days_of_week: List[int],
    max_events: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    """
    Проверяет вместимость новой серии, начиная со start_date (по умолчанию сегодня),
    на RECURRING_CHECK_WEEKS недель вперёд (или до end_date). Даты до start_date НЕ проверяются —
    поэтому серия «с воскресенья через неделю» не блокируется событием в ближайшее воскресенье.
    """
    first = start_date or date.today()
    last = first + timedelta(weeks=RECURRING_CHECK_WEEKS)
    if end_date and end_date < last:
        last = end_date

    dates = _dates_for_weekdays(first, last, days_of_week)
    conflicts = await _find_conflict_dates(calendar_id, dates, start_time, end_time, max_events)
    if conflicts:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Limit reached {_format_conflicts(conflicts, start_time)}: max {max_events} events/slot. "
                f"Choose a later start_date or free the slot."
            ),
        )