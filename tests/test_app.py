import pytest
from httpx import AsyncClient
from database.database import db

pytestmark = pytest.mark.asyncio

async def test_free_slots_empty(client: AsyncClient):
    payload = {
        "location": "Test 2",
        "year": 2026,
        "month": 11,
        "day": 10
    }
    response = await client.post("/free-slots", json=payload)
    assert response.status_code == 200
    data = response.json()
    # Test 2 has 2 courts available according to env override
    assert data["10:00-11:00"] == 2

async def test_get_full_price_and_free_slots(client: AsyncClient):
    # 1. Capture a slot via get-full-price
    payload = {
        "location": "Test 2",
        "day": "2026-11-10",
        "telegram_id": 123,
        "time_slots": ["10:00-11:00"],
        "free_courts_quantity": 2
    }
    response = await client.post("/get-full-price", json=payload)
    assert response.status_code == 200
    data = response.json()
    order_id = data["temprary_order_id"]
    
    # 2. Check free-slots, should be reduced by 1
    fs_payload = {
        "location": "Test 2",
        "year": 2026,
        "month": 11,
        "day": 10
    }
    fs_resp = await client.post("/free-slots", json=fs_payload)
    assert fs_resp.status_code == 200
    fs_data = fs_resp.json()
    assert fs_data["10:00-11:00"] == 1
    
    # 3. Move it to pending_bookings (simulate send-photo)
    # The actual bot uses db.create_pending_booking and db.cancel_pending_by_order_id
    await db.create_pending_booking("booking-1", "Test 2", "2026-11-10", "10:00-11:00", 123)
    await db.cancel_pending_by_order_id(order_id)
    
    # 4. Check free-slots again, should still be 1 (because pending_bookings counts too)
    fs_resp2 = await client.post("/free-slots", json=fs_payload)
    assert fs_resp2.status_code == 200
    fs_data2 = fs_resp2.json()
    assert fs_data2["10:00-11:00"] == 1
    
async def test_get_full_price_collision(client: AsyncClient):
    # Test 1 has 1 court
    # 1. Capture the slot
    payload = {
        "location": "Test 1",
        "day": "2026-11-11",
        "telegram_id": 123,
        "time_slots": ["14:00-15:00"],
        "free_courts_quantity": 1
    }
    response = await client.post("/get-full-price", json=payload)
    assert response.status_code == 200
    
    # 2. Try to capture the same slot again
    response2 = await client.post("/get-full-price", json=payload)
    assert response2.status_code == 409
    assert "уже успели занять" in response2.json()["message"]
