import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

async def test_create_single_event_success(client: AsyncClient):
    payload = {
        "title": "Test Event",
        "start_datetime": "2026-10-10T10:00:00Z",
        "end_datetime": "2026-10-10T11:00:00Z",
        "status": "confirmed"
    }
    response = await client.post(
        "/v1/calendars/Test 1/single-events",
        json=payload,
        headers={"X-Telegram-Id": "123"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Event"
    assert data["calendar_id"] == "Test 1"
    
async def test_create_single_event_limit_exceeded(client: AsyncClient):
    # Test 1 max_events_per_hour = 1
    # We already created one at 10:00. Creating another one at the same time should fail.
    payload = {
        "title": "Conflict Event",
        "start_datetime": "2026-10-10T10:00:00Z",
        "end_datetime": "2026-10-10T11:00:00Z",
        "status": "confirmed"
    }
    response = await client.post(
        "/v1/calendars/Test 1/single-events",
        json=payload,
        headers={"X-Telegram-Id": "123"}
    )
    assert response.status_code == 400
    assert "Limit reached" in response.json()["detail"]
    
async def test_create_single_event_midnight(client: AsyncClient):
    payload = {
        "title": "Midnight Event",
        "start_datetime": "2026-10-10T23:00:00Z",
        "end_datetime": "2026-10-11T00:00:00Z", # Next day midnight
        "status": "confirmed"
    }
    response = await client.post(
        "/v1/calendars/Test 1/single-events",
        json=payload,
        headers={"X-Telegram-Id": "123"}
    )
    assert response.status_code == 201
    
async def test_recurring_event_success_and_conflict(client: AsyncClient):
    # Create recurring event for Monday (day 1) 12:00-13:00
    payload = {
        "title": "Recurring Mon",
        "days_of_week": [1],
        "start_time": "12:00:00Z",
        "end_time": "13:00:00Z"
    }
    response = await client.post(
        "/v1/calendars/Test 1/recurring-events",
        json=payload,
        headers={"X-Telegram-Id": "123"}
    )
    assert response.status_code == 201
    
    # Try to create another recurring event at the same time (Test 1 has capacity 1)
    response2 = await client.post(
        "/v1/calendars/Test 1/recurring-events",
        json=payload,
        headers={"X-Telegram-Id": "123"}
    )
    assert response2.status_code == 400
    
async def test_stats_permissions(client: AsyncClient):
    # User 999 is not a member of Test 1
    response = await client.get(
        "/v1/calendars/Test 1/stats?from_date=2026-09-01&to_date=2026-09-30",
        headers={"X-Telegram-Id": "999"}
    )
    assert response.status_code == 403
    
    # Create user 999 first to satisfy foreign key constraint
    from database.database import db
    await db.connection.execute("INSERT OR IGNORE INTO calendar_users (telegram_id, username, full_name) VALUES (999, 'trainer999', 'Trainer')")
    await db.connection.commit()

    # Add user 999 as trainer
    await client.post(
        "/v1/calendars/calendar_members",
        json={"calendar_id": "Test 1", "telegram_id": 999, "role": "trainer"}
    )
    
    # Trainer should not see stats
    response = await client.get(
        "/v1/calendars/Test 1/stats?from_date=2026-09-01&to_date=2026-09-30",
        headers={"X-Telegram-Id": "999"}
    )
    assert response.status_code == 403
    
    # Add user 999 as admin
    await client.post(
        "/v1/calendars/calendar_members",
        json={"calendar_id": "Test 1", "telegram_id": 999, "role": "admin"}
    )
    
    # Admin should see stats
    response = await client.get(
        "/v1/calendars/Test 1/stats?from_date=2026-09-01&to_date=2026-09-30",
        headers={"X-Telegram-Id": "999"}
    )
    assert response.status_code == 200
    assert "total_earned" in response.json()


# ─── новые функции календаря ─────────────────────────────────────────────────
from datetime import date as _date, timedelta as _td

H = {"X-Telegram-Id": "123"}


def _next_weekday(wd: int, min_days: int = 1) -> _date:
    d = _date.today() + _td(days=min_days)
    while d.weekday() != wd:
        d += _td(days=1)
    return d


async def test_reservation_creates_single_events_for_period(client: AsyncClient):
    start = _next_weekday(2, 100)  # среда, далеко в будущем
    payload = {"title": "Ivan", "days_of_week": [2], "start_time": "07:00:00", "end_time": "08:00:00",
               "start_date": start.isoformat(), "months": 1}
    r = await client.post("/v1/calendars/Test 1/reservations", json=payload, headers=H)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["created_count"] >= 4
    assert all(e["recurring_event_id"] is None for e in data["created"])
    # повтор — конфликт, ничего не создаётся
    r = await client.post("/v1/calendars/Test 1/reservations", json=payload, headers=H)
    assert r.status_code == 400
    # skip_conflicts
    r = await client.post("/v1/calendars/Test 1/reservations", json={**payload, "skip_conflicts": True}, headers=H)
    assert r.status_code == 201
    assert r.json()["created_count"] == 0 and r.json()["skipped_count"] >= 4


async def test_recurring_with_start_date_ignores_earlier_conflict(client: AsyncClient):
    sunday = _next_weekday(6, 1)
    single = {"title": "Busy", "status": "confirmed",
              "start_datetime": f"{sunday}T12:00:00", "end_datetime": f"{sunday}T13:00:00"}
    assert (await client.post("/v1/calendars/Test 1/single-events", json=single, headers=H)).status_code == 201
    rec = {"title": "Perm", "days_of_week": [6], "start_time": "12:00:00", "end_time": "13:00:00"}
    # без start_date — конфликт с ближайшим воскресеньем
    assert (await client.post("/v1/calendars/Test 1/recurring-events", json=rec, headers=H)).status_code == 400
    # со start_date на следующее воскресенье — ок
    rec["start_date"] = (sunday + _td(days=7)).isoformat()
    r = await client.post("/v1/calendars/Test 1/recurring-events", json=rec, headers=H)
    assert r.status_code == 201, r.text
    rec_id = r.json()[0]["id"]

    grid = (await client.get("/v1/calendars/Test 1/events",
                             params={"from_date": sunday.isoformat(), "to_date": (sunday + _td(days=14)).isoformat()},
                             headers=H)).json()
    inst = [e for e in grid if e["type"] == "recurring_instance" and e["recurring_event_id"] == rec_id]
    assert all(e["start_datetime"][:10] >= rec["start_date"] for e in inst) and len(inst) == 2

    # переименование одного слота
    target = sunday + _td(days=14)
    r = await client.patch(f"/v1/recurring-events/{rec_id}/instance-title",
                           json={"date": target.isoformat(), "title": "Andrey (absent)"}, headers=H)
    assert r.status_code == 200, r.text
    grid = (await client.get("/v1/calendars/Test 1/events",
                             params={"from_date": sunday.isoformat(), "to_date": target.isoformat()},
                             headers=H)).json()
    titles = {e["start_datetime"][:10]: e["title"] for e in grid if e["recurring_event_id"] == rec_id}
    assert titles[target.isoformat()] == "Andrey (absent)"
    assert titles[(sunday + _td(days=7)).isoformat()] == "Perm"
    # сброс
    assert (await client.delete(f"/v1/recurring-events/{rec_id}/instance-title",
                                params={"date": target.isoformat()}, headers=H)).status_code == 200
    # неверный день недели
    r = await client.patch(f"/v1/recurring-events/{rec_id}/instance-title",
                           json={"date": (target + _td(days=1)).isoformat(), "title": "x"}, headers=H)
    assert r.status_code == 400
