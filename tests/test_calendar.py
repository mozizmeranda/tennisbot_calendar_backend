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
