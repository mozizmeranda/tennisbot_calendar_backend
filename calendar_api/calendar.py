# routers/calendars.py
import logging
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from database.database import db
from calendar_api.helpers import require_calendar_access, _check_capacity, _check_recurring_capacity, _build_grid, _build_cancelled_pairs

from config.calendar import CalendarResponse, CreateCalendar, CreateUser, CalendarMembers, MigrateGoogleCalendarRequest
from config.event import (
    GridEventResponse,
    RecurringEventCreate,
    RecurringEventResponse,
    SingleEventCreate,
    SingleEventResponse,
)
from migration.migrate_from_google import get_service, run_google_migration

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/calendars", tags=["Calendars"])


# ─── endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def list_calendars(telegram_id: int = Header(..., alias="X-Telegram-Id")):
    """
    Список календарей пользователя.
    Для роли 'admin' дополнительно возвращает статистику за текущий месяц.
    """
    from datetime import date
    from calendar import monthrange

    calendars = await db.get_user_calendars(telegram_id)

    today = date.today()
    first_day = today.replace(day=1).isoformat()
    _, last = monthrange(today.year, today.month)
    last_day = today.replace(day=last).isoformat()

    result = []
    for cal in calendars:
        role = await db.get_member_role(cal["id"], telegram_id)
        entry = dict(cal)
        entry["role"] = role or "trainer"
        if role == "admin":
            entry["stats"] = await db.get_monthly_stats(cal["id"], first_day, last_day)
        else:
            entry["stats"] = None
        result.append(entry)

    return result


@router.get("/{calendar_id}/stats")
async def get_calendar_stats(
    calendar_id: str,
    from_date: date = Query(..., description="Начало периода (YYYY-MM-DD)"),
    to_date: date = Query(..., description="Конец периода (YYYY-MM-DD)"),
    telegram_id: int = Header(..., alias="X-Telegram-Id"),
):
    """
    Статистика заработков по датам — только для роли 'admin'.
    Возвращает количество броней и сумму по каждому дню в периоде.
    """
    role = await db.get_member_role(calendar_id, telegram_id)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Access denied: admin role required")

    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be <= to_date")

    stats = await db.get_monthly_stats(
        calendar_id,
        from_date.isoformat(),
        to_date.isoformat(),
    )
    return stats


@router.get("/{calendar_id}/events")
async def get_events(
    calendar_id: str,
    from_date: date = Query(...),
    to_date: date = Query(...),
    telegram_id: int = Header(..., alias="X-Telegram-Id"),
):
    """Сетка событий (одиночные + виртуальные повторяющиеся) за период."""
    await require_calendar_access(calendar_id, telegram_id)

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

    return _build_grid(active, cancelled_pairs, recurring, from_date, to_date)


@router.post("/{calendar_id}/single-events", status_code=201)
async def create_single_event(
    calendar_id: str,
    event_in: SingleEventCreate,
    telegram_id: int = Header(..., alias="X-Telegram-Id"),
):
    """Создать одиночное событие."""
    calendar = await require_calendar_access(calendar_id, telegram_id)

    start_str = event_in.start_datetime.strftime("%Y-%m-%d %H:%M:%S")
    end_str = event_in.end_datetime.strftime("%Y-%m-%d %H:%M:%S")

    await _check_capacity(calendar_id, start_str, end_str, calendar["max_events_per_hour"])

    event = await db.create_single_event(
        calendar_id=calendar_id,
        created_by=telegram_id,
        title=event_in.title,
        start_datetime=start_str,
        end_datetime=end_str,
        status=event_in.status,
    )
    if not event:
        raise HTTPException(status_code=500, detail="Failed to create event")
    return event


@router.post("/{calendar_id}/recurring-events", status_code=201)
async def create_recurring_event(
    calendar_id: str,
    event_in: RecurringEventCreate,
    telegram_id: int = Header(..., alias="X-Telegram-Id"),
):
    """Создать повторяющееся событие (для одного или нескольких дней недели)."""
    calendar = await require_calendar_access(calendar_id, telegram_id)

    start_str = event_in.start_time.strftime("%H:%M:%S")
    end_str = event_in.end_time.strftime("%H:%M:%S")

    await _check_recurring_capacity(
        calendar_id=calendar_id,
        start_time=start_str,
        end_time=end_str,
        days_of_week=event_in.days_of_week,
        max_events=calendar["max_events_per_hour"],
    )

    events = await db.create_recurring_events_bulk(
        calendar_id=calendar_id,
        created_by=telegram_id,
        title=event_in.title,
        days_of_week=event_in.days_of_week,
        start_time=start_str,
        end_time=end_str,
    )
    return events


@router.post("")
async def create_calendar(calendar: CreateCalendar, telegram_id: int = Header(..., alias="X-Telegram-Id")):
    existing = await db.get_calendar(calendar.id)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Calendar with id '{calendar.id}' already exists"
        )
    clndr = await db.create_calendar(
        id=calendar.id,
        name=calendar.name,
        max_events_per_hour=calendar.max_events_per_hour,
        owner_telegram_id=telegram_id,
    )
    if not clndr:
        raise HTTPException(status_code=500, detail="Failed to create calendar")
    return clndr


@router.delete("/{calendar_id}")
async def delete_calendar(
    calendar_id: str,
    telegram_id: int = Header(..., alias="X-Telegram-Id"),
):
    """Удалить календарь по его ID и принадлежности к telegram ID."""
    await require_calendar_access(calendar_id, telegram_id)
    success = await db.delete_calendar(calendar_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete calendar")
    return {"success": True, "message": f"Calendar '{calendar_id}' deleted successfully"}




@router.post("/create_user")
async def create_calendar_user(user: CreateUser):
    created_user = await db.create_calendar_user(user.telegram_id, user.username, user.full_name)
    return created_user


@router.post("/calendar_members")
async def create_calendar_member(user: CalendarMembers):
    resp = await db.add_member(user.calendar_id, user.telegram_id, user.role)
    return resp


@router.post("/{calendar_id}/migrate-google")
async def migrate_from_google(
    calendar_id: str,
    body: MigrateGoogleCalendarRequest,
    telegram_id: int = Header(..., alias="X-Telegram-Id"),
):
    """
    Миграция событий из Google Calendar в указанный календарь нашей БД.
    Период: с сегодняшнего дня по конец следующего месяца.
    """
    await require_calendar_access(calendar_id, telegram_id)

    try:
        service = get_service()
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка инициализации сервиса Google: {e}")

    try:
        result = await run_google_migration(
            service=service,
            g_cal=body.google_calendar_id,
            db_cal=calendar_id,
            created_by=telegram_id,
        )
        return result
    except Exception as e:
        logger.exception("Migration failed: calendar_id=%s, google_cal=%s", calendar_id, body.google_calendar_id)
        raise HTTPException(status_code=500, detail=f"Ошибка при миграции: {e}")


