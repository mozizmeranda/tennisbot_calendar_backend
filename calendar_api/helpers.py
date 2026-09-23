# calendar_api/helpers.py
"""
Общие вспомогательные функции для calendar_api/calendar.py и calendar_api/event.py.
Выделено для устранения дублирования кода.
"""
import logging
from datetime import datetime, timedelta, date
from typing import Optional, List, Set, Tuple

from fastapi import HTTPException

from database.database import db
from calendar_api.grid_utils import _build_cancelled_pairs, _build_grid  # noqa: F401 — реэкспорт

logger = logging.getLogger(__name__)


async def require_calendar_access(calendar_id: str, telegram_id: int) -> dict:
    """Проверяет доступ и возвращает данные календаря. 403 если нет доступа."""
    has_access = await db.check_member_access(calendar_id, telegram_id)
    if not has_access:
        raise HTTPException(status_code=403, detail="You do not have access to this calendar")
    calendar = await db.get_calendar(calendar_id)
    if not calendar:
        raise HTTPException(status_code=404, detail="Calendar not found")
    return calendar






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
    from_date = start.date()
    to_date = end.date()

    from_str = f"{from_date} 00:00:00"
    to_str = f"{to_date} 23:59:59"

    active = await db.get_single_events_for_calendar(
        calendar_id, from_str, to_str, statuses=["confirmed", "pending_payment"]
    )
    cancelled = await db.get_single_events_for_calendar(
        calendar_id, from_str, to_str, statuses=["cancelled"]
    )
    cancelled_pairs = _build_cancelled_pairs(cancelled)
    recurring = await db.get_recurring_events_for_calendar(calendar_id)

    # Строим плоскую сетку событий
    grid = []
    for e in active:
        grid.append({
            "type": "single",
            "id": e["id"],
            "start": e["start_datetime"],
            "end": e["end_datetime"],
        })

    current = from_date
    while current <= to_date:
        weekday = current.weekday()
        date_str = current.isoformat()
        for re in recurring:
            if re["day_of_week"] == weekday and (re["id"], date_str) not in cancelled_pairs:
                grid.append({
                    "type": "recurring_instance",
                    "id": re["id"],
                    "start": f"{current} {re['start_time']}",
                    "end": f"{current + timedelta(days=1) if re['end_time'] == '00:00:00' else current} {re['end_time']}",
                })
        current += timedelta(days=1)

    if exclude_event_id is not None:
        grid = [e for e in grid if not (e["type"] == "single" and e["id"] == exclude_event_id)]

    current_hour = start.replace(minute=0, second=0, microsecond=0)
    end_hour = end.replace(minute=0, second=0, microsecond=0)
    if end.minute > 0 or end.second > 0:
        end_hour += timedelta(hours=1)

    while current_hour < end_hour:
        block_end = current_hour + timedelta(hours=1)
        count = sum(
            1 for e in grid
            if datetime.fromisoformat(e["start"]) < block_end
            and datetime.fromisoformat(e["end"]) > current_hour
        )
        if count + 1 > max_events:
            raise HTTPException(
                status_code=400,
                detail=f"Limit reached: max {max_events} events/hour at {current_hour.time().isoformat()}"
            )
        current_hour += timedelta(hours=1)



async def _check_recurring_capacity(
    calendar_id: str,
    start_time: str,
    end_time: str,
    days_of_week: List[int],
    max_events: int,
):
    """
    Checks capacity for a new recurring event against all existing events
    (single_events + recurring_events) over the next 4 weeks.
    Raises HTTPException 400 if limit is exceeded for any day_of_week.
    """
    from datetime import date as date_type

    today = date_type.today()
    look_ahead = today + timedelta(weeks=4)

    from_str = f"{today} 00:00:00"
    to_str = f"{look_ahead} 23:59:59"

    active = await db.get_single_events_for_calendar(
        calendar_id, from_str, to_str, statuses=["confirmed", "pending_payment"]
    )
    cancelled = await db.get_single_events_for_calendar(
        calendar_id, from_str, to_str, statuses=["cancelled"]
    )
    cancelled_pairs = _build_cancelled_pairs(cancelled)
    recurring = await db.get_recurring_events_for_calendar(calendar_id)

    for target_day in days_of_week:
        # Nearest date with the required weekday
        days_ahead = (target_day - today.weekday()) % 7
        check_date = today + timedelta(days=days_ahead)
        date_str = check_date.isoformat()

        grid = []

        # Single events on this day
        for e in active:
            if e["start_datetime"][:10] == date_str:
                grid.append({"start": e["start_datetime"], "end": e["end_datetime"]})

        # Recurring instances on this day (excluding cancelled)
        for re in recurring:
            if re["day_of_week"] == target_day and (re["id"], date_str) not in cancelled_pairs:
                end_date = check_date + timedelta(days=1) if re["end_time"] == "00:00:00" else check_date
                grid.append({
                    "start": f"{check_date} {re['start_time']}",
                    "end": f"{end_date} {re['end_time']}",
                })

        # New slot datetime
        new_start = datetime.fromisoformat(f"{check_date} {start_time}")
        end_date_new = check_date + timedelta(days=1) if end_time == "00:00:00" else check_date
        new_end = datetime.fromisoformat(f"{end_date_new} {end_time}")

        overlap_count = sum(
            1 for e in grid
            if datetime.fromisoformat(e["start"]) < new_end
            and datetime.fromisoformat(e["end"]) > new_start
        )

        if overlap_count + 1 > max_events:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Limit reached for day_of_week={target_day} at {start_time[:5]}: "
                    f"max {max_events} events/slot, found {overlap_count}"
                )
            )
