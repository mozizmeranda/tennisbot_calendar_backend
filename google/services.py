# google/calendar/services.py
import httpx
import jwt
import time as t
from config.config import CALENDAR_ID, courts
from .google_config import GoogleConfig, get_google_config
from datetime import datetime, timedelta, timezone, time, date
from database.database import db
from utils import notify_admin
# from datetime import datetime


SCOPES = "https://www.googleapis.com/auth/calendar"
CALENDAR_BASE_URL = "https://www.googleapis.com/calendar/v3"


async def get_access_token(client: httpx.AsyncClient, gc: GoogleConfig) -> str:
    """Быстрый асинхронный метод получения токена с проверкой кэша."""
    now = t.time()

    # Если токен валиден еще хотя бы 5 минут — отдаем из памяти
    if gc.cached_token and (gc.token_expires_at - now) > 300:
        return gc.cached_token

    # Если токен устарел — генерируем новый (sa_data уже считан в lifespan)
    sa_data = gc.sa_data

    private_key = sa_data["private_key"]
    client_email = sa_data["client_email"]
    token_uri = sa_data.get("token_uri", "https://oauth2.googleapis.com/token")

    payload = {
        "iss": client_email,
        "scope": SCOPES,
        "aud": token_uri,
        "exp": int(now) + 3600,
        "iat": int(now),
    }

    assertion = jwt.encode(payload, private_key, algorithm="RS256")

    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }

    response = await client.post(token_uri, data=data)
    response.raise_for_status()

    result = response.json()

    # Обновляем кэш в нашем едином объекте gc
    gc.cached_token = result["access_token"]
    gc.token_expires_at = now + result.get("expires_in", 3600)

    return gc.cached_token


# =====================================================================
# 2. ДРУГИЕ ФУНКЦИИ (Используют функцию выше)
# =====================================================================

async def list_calendar_events(
        client: httpx.AsyncClient, gc: GoogleConfig, calendar_id: str = "primary", max_results: int = 10
) -> dict:
    """Получить список событий (вызывает get_access_token внутри)."""
    # Вызываем вашу функцию, передавая клиент и конфиг
    token = await get_access_token(client, gc)

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"maxResults": max_results, "singleEvents": "true", "orderBy": "startTime"}

    url = f"{CALENDAR_BASE_URL}/calendars/{calendar_id}/events"
    response = await client.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


async def create_calendar_event(
        client: httpx.AsyncClient,
        gc: GoogleConfig,
        summary: str,
        start_time: str,
        end_time: str,
        calendar_id: str = "primary"
) -> dict:
    """Создать новое событие в календаре."""
    # Снова вызываем вашу функцию. Если прошлый вызов был недавно — токен возьмется из кэша gc!
    token = await get_access_token(client, gc)

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    event_body = {
        "summary": summary,
        "start": {"dateTime": start_time, "timeZone": "UTC"},
        "end": {"dateTime": end_time, "timeZone": "UTC"},
    }

    url = f"{CALENDAR_BASE_URL}/calendars/{calendar_id}/events"
    response = await client.post(url, headers=headers, json=event_body)
    response.raise_for_status()
    return response.json()


async def returning_free_slots(
        client: httpx.AsyncClient,
        gc: GoogleConfig,
        location: str,
        year: int,
        month: int,
        day: int
        # db
) -> dict:
    tz = timezone(timedelta(hours=5))
    check_date = date(year, month, day)
    day_start = datetime.combine(check_date, time(6, 0), tzinfo=tz)
    day_end = datetime.combine(check_date + timedelta(days=1), time(0, 0), tzinfo=tz)

    time_min_iso = day_start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    time_max_iso = day_end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    # print("calendarId:", CALENDAR_ID[location])
    # print("timeMin:", time_min_iso)
    # print("timeMax:", time_max_iso)

    busy_events = []

    try:
        # 1. Получаем токен из нашего единого кэша gc
        token = await get_access_token(client, gc)

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        params = {
            "timeMin": time_min_iso,
            "timeMax": time_max_iso,
            "singleEvents": "true",
            "orderBy": "startTime"
        }

        url = f"{CALENDAR_BASE_URL}/calendars/{CALENDAR_ID[location]}/events"

        # 2. Асинхронный запрос к Google Calendar API
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()

        events_result = response.json()
        print("STATUS OK, events:", events_result)
        busy_events = events_result.get('items', [])
        print("BUSY EVENTS:", busy_events)

    except httpx.HTTPStatusError as e:
        # print("GOOGLE API ERROR TYPE:", type(e).__name__)
        # print("ERROR DETAILS:", e.response.text)
        return {}
    except Exception as e:
        # print("ERROR TYPE:", type(e).__name__)
        # print("ERROR:", e)
        return {}

    time_slots = [
        '06:00-07:00', '07:00-08:00', '08:00-09:00', '09:00-10:00',
        '10:00-11:00', '11:00-12:00', '12:00-13:00', '13:00-14:00',
        '14:00-15:00', '15:00-16:00', '16:00-17:00', '17:00-18:00',
        '18:00-19:00', '19:00-20:00', '20:00-21:00', '21:00-22:00',
        '22:00-23:00', '23:00-00:00',
    ]

    month_str = str(month).zfill(2)  # для БД
    day_str = str(day).zfill(2)  # для БД

    result = {}
    for slot in time_slots:
        start_str, end_str = slot.split("-")
        slot_start = datetime.combine(check_date, time(*map(int, start_str.split(":"))), tzinfo=tz)

        if end_str == "00:00":
            slot_end = datetime.combine(check_date + timedelta(days=1), time(0, 0), tzinfo=tz)
        else:
            slot_end = datetime.combine(check_date, time(*map(int, end_str.split(":"))), tzinfo=tz)

        # Высчитываем пересечения с событиями из Google
        overlap_count = 0
        for e in busy_events:
            # Парсим ISO строку от Google (обязательно приводим к нашей таймзоне tz для корректного сравнения)
            event_start = datetime.fromisoformat(e['start'].get('dateTime')).astimezone(tz)
            event_end = datetime.fromisoformat(e['end'].get('dateTime')).astimezone(tz)

            if event_start < slot_end and event_end > slot_start:
                overlap_count += 1

        # 3. Асинхронный вызов к бд (добавлен await, так как в проде БД должна быть асинхронной)
        # Если твоя функция db.pendings всё еще синхронная — убери await
        pending_count = await db.pendings(location, f"{year}-{month_str}-{day_str}", slot)
        overlap_count += pending_count

        result[slot] = 0 if overlap_count >= courts[location] else 1

    return result


async def google_create_booking(
        client: httpx.AsyncClient,
        gc: GoogleConfig,
        location: str,
        booking_date: str,
        time_slot: str,
        number: str,
        name: str,
) -> int:
    """
    Асинхронно создаёт бронирование в Google Calendar.
    Возвращает ссылку на созданное событие.
    """
    try:
        token = await get_access_token(client, gc)
        time_start_str = time_slot.split("-")[0]
        s = f"{booking_date}_{time_start_str}"

        event_start = datetime.strptime(s, "%Y-%m-%d_%H:%M")
        event_end = event_start + timedelta(hours=1)

        event_body = {
            "summary": name,
            "description": number,
            "start": {
                "dateTime": event_start.isoformat(),
                "timeZone": "Asia/Tashkent",
            },
            "end": {
                "dateTime": event_end.isoformat(),
                "timeZone": "Asia/Tashkent",
            },
            "reminders": {"useDefault": True},
        }

        url = f"{CALENDAR_BASE_URL}/calendars/{CALENDAR_ID[location]}/events"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        response = await client.post(url, headers=headers, json=event_body)
        response.raise_for_status()
        created_event = response.json()

        link = created_event.get("htmlLink", "")
        print(f"Событие создано: {link}")
        return 1

    except Exception as exp:
        await notify_admin(client=client, func_name=google_update_booking_text.__name__,
                           error=str(exp), arguments={"location": location, "booking_date": booking_date,
                                                      "time_slot": time_slot, "number": number})
        return -1


async def google_update_booking_text(
        client: httpx.AsyncClient,
        gc: GoogleConfig,
        location: str,
        event_id: str,
        name: str,
        number: str,
) -> int:
    """
    Асинхронно обновляет только имя (summary) и номер (description) события по event_id.
    Возвращает ссылку на обновленное событие.
    """
    try:
        token = await get_access_token(client, gc)

        event_body = {
            "summary": name,
            "description": number,
        }

        url = f"{CALENDAR_BASE_URL}/calendars/{CALENDAR_ID[location]}/events/{event_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # PATCH обновляет только переданные поля (summary и description), не трогая время
        response = await client.patch(url, headers=headers, json=event_body)
        response.raise_for_status()
        updated_event = response.json()

        link = updated_event.get("htmlLink", "")
        return 1

    except Exception as exp:
        await notify_admin(client=client, func_name=google_update_booking_text.__name__,
                           error=str(exp), arguments={"event_id": event_id})
        return -1
