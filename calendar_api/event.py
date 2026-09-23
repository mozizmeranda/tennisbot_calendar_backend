# routers/events.py
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from database.database import db
from calendar_api.helpers import require_calendar_access, _check_capacity
from config.event import CancelInstanceRequest, SingleEventUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Events"])


# ─── endpoints ────────────────────────────────────────────────────────────────

@router.delete("/single-events/{id}")
async def delete_single_event(
    id: int,
    telegram_id: int = Header(..., alias="X-Telegram-Id"),
):
    """Удалить одиночное событие."""
    event = await db.get_single_event(id)
    if not event:
        raise HTTPException(status_code=404, detail="Single event not found")

    deleted = await db.delete_single_event(id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete event")

    return {"message": "Single event successfully deleted", "id": id}


@router.patch("/single-events/{id}")
async def update_single_event(
    id: int,
    event_update: SingleEventUpdate,
    telegram_id: int = Header(..., alias="X-Telegram-Id"),
):
    """Обновить время одиночного события."""
    event = await db.get_single_event(id)
    if not event:
        raise HTTPException(status_code=404, detail="Single event not found")

    calendar = await require_calendar_access(event["calendar_id"], telegram_id)

    start_str = event_update.start_datetime.strftime("%Y-%m-%d %H:%M:%S")
    end_str = event_update.end_datetime.strftime("%Y-%m-%d %H:%M:%S")

    await _check_capacity(
        event["calendar_id"], start_str, end_str,
        calendar["max_events_per_hour"], exclude_event_id=id
    )

    updated = await db.update_single_event(id, start_str, end_str, event_update.title)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update event")

    return updated


@router.delete("/recurring-events/{id}")
async def delete_recurring_event(
    id: int,
    telegram_id: int = Header(..., alias="X-Telegram-Id"),
):
    """Удалить повторяющееся событие (и все его связанные экземпляры)."""
    event = await db.get_recurring_event(id)
    if not event:
        raise HTTPException(status_code=404, detail="Recurring event not found")

    deleted = await db.delete_recurring_event(id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete recurring event")

    return {"message": "Recurring event series successfully deleted", "id": id}


@router.post("/recurring-events/{id}/cancel-instance")
async def cancel_recurring_instance(
    id: int,
    request: CancelInstanceRequest,
    telegram_id: int = Header(..., alias="X-Telegram-Id"),
):
    """Отменить конкретный экземпляр повторяющегося события."""
    rec_event = await db.get_recurring_event(id)
    if not rec_event:
        raise HTTPException(status_code=404, detail="Recurring event not found")

    cancel_date_str = request.date.strftime("%Y-%m-%d")

    result = await db.cancel_recurring_instance(
        recurring_event_id=id,
        cancel_date=cancel_date_str,
        created_by=telegram_id,
    )
    if result is None:
        raise HTTPException(
            status_code=400,
            detail=f"Date {request.date} does not match the recurring event's day of the week"
        )

    return {
        "message": f"Event instance successfully cancelled for {request.date}",
        "recurring_event_id": id,
        "cancelled_date": request.date.isoformat(),
    }
