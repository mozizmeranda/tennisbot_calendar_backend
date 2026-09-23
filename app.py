# app.py
from aiogram.enums import revenue_withdrawal_state_type
import logging
import traceback
import secrets

from config import config, models

from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi import FastAPI, status, Body, Depends, Request, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import JSONResponse

from contextlib import asynccontextmanager

import json
import uvicorn
from network.client import manager
import httpx

from payment.router import router as payment_router
from profile.profile_endpoint import profile_router
from datetime import datetime, timedelta, timezone

from telegram_bot.bot_app import dp, bot, bot_router
from database.database import db
from typing import Dict, Any
from utils import notify_admin, nanoid_generate

from calendar_api.calendar import router as calendar_router
from calendar_api.event import router as event_router

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from config.config import courts



@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- КОД ВЫПОЛНЯЕТСЯ РОВНО ОДИН РАЗ ПРИ СТАРТЕ СЕРВЕРА ----
    manager.api_client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
    )
    logger.info("Запуск приложения...")
    await db.connect()

    if config.WEBHOOK_URL:
        # Устанавливаем URL и секретный токен
        await bot.set_webhook(
            url=config.WEBHOOK_URL,
            secret_token=config.WEBHOOK_SECRET,
            drop_pending_updates=True  # Сбрасывает зависшие апдейты, накопленные во время оффлайна
        )
        logging.info(f"Вебхук успешно установлен на {config.WEBHOOK_URL}")

    yield

    try:
        await bot.delete_webhook()
        logger.info("Вебхук успешно удален.")
    except Exception as e:
        await notify_admin("Lifespan", str(traceback.format_exc()), arguments={})
        logger.info(f"Ошибка при удалении вебхука: {e}")

        # Закрываем сессию бота
    await bot.session.close()

    if manager.api_client:
        await manager.api_client.aclose()
        logger.info("HTTP-клиент успешно закрыт.")

    if db:
        await db.close()
        logger.info("Соединение с базой данных успешно закрыто.")

    logger.info("Остановка приложения...")


limiter = Limiter(key_func=get_remote_address)
app = FastAPI(lifespan=lifespan, root_path="/bot_app", docs_url=None, redoc_url=None, openapi_url=None)
# app.include_router(router)
# app.post("/send-photo", tags=["Payments"])(send_photo_payment)
app.include_router(payment_router)
app.include_router(profile_router)
app.include_router(bot_router)
app.include_router(calendar_router)
app.include_router(event_router)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # ОБЯЗАТЕЛЬНО добавить эту строку
)

app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler
)

app.add_middleware(SlowAPIMiddleware)

@app.middleware("http")
async def ip_or_auth_middleware(request: Request, call_next):
    # Webhook endpoint is exempted
    if request.url.path.startswith("/webhook"):
        return await call_next(request)

    if request.url.path.startswith("/docs") or request.url.path.startswith("/openapi.json"):
        return await call_next(request)

    if config.WHITE_IPS[0] == "*":
        return await call_next(request)
        
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
        
    if client_ip in config.WHITE_IPS:
        return await call_next(request)
        
    # Check AUTH_KEY
    auth_key = request.headers.get("AUTH_KEY")
    if auth_key and auth_key == config.AUTH_KEY:
        return await call_next(request)
        
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": "Access forbidden"}
    )

logger = logging.getLogger(__name__)
logger.info("Логгер успешно запущен")


security = HTTPBasic()


def check_admin(credentials: HTTPBasicCredentials = Depends(security)):
    correct_user = secrets.compare_digest(credentials.username, config.ADMIN_USERNAME)
    correct_pass = secrets.compare_digest(credentials.password, config.ADMIN_PASSWORD)

    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Basic"},
        )


# OpenAPI спецификация (учитывает root_path автоматически)
@app.get("/openapi.json", include_in_schema=True)
def get_open_api_endpoint():
    return app.openapi()


# Страница Swagger UI (передаем относительный путь к openapi.json)
@app.get("/docs", include_in_schema=True)
def get_documentation():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Docs"
    )


@app.post("/free-slots")
@limiter.limit("5/minute")
async def free_slots_endpoint(request: Request, body: models.FreeSlotsBody):
    """
    Возвращает свободные слоты для бронирования корта на указанную дату.

    Данные берутся из БД (single_events + pending_table), без Google Calendar.

    Ответ: объект `{ "HH:MM-HH:MM": 0|1, ... }` где 1 = свободен, 0 = занят.
    """
    logger.info(
        "free-slots: location=%s date=%d-%02d-%02d",
        body.location, body.year, body.month, body.day,
    )

    # calendar_id = await db.get_calendar_id(body.location)
    # if not calendar_id:
    #     return JSONResponse(
    #         status_code=status.HTTP_400_BAD_REQUEST,
    #         content={"message": f"Неизвестная локация: {body.location}"}
    #     )

    try:
        result = await _get_free_slots_from_db(body.location, body.year, body.month, body.day)
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    except Exception as e:
        logger.error("free_slots_endpoint error: %s", e)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Внутренняя ошибка сервера: {str(e)}"}
        )


async def _get_free_slots_from_db(location: str, year: int, month: int, day: int) -> dict:
    """
    Собирает свободные слоты из БД без обращения к Google Calendar.

    Алгоритм:
        - Берём все забронированные слоты из таблицы bookings
        - Добавляем временные холды из pending_table (через db.pendings)
        - Сравниваем с количеством кортов на локации
        - Слот свободен (1) если занятых < courts[location]
    """
    tz = timezone(timedelta(hours=5))
    month_str = str(month).zfill(2)
    day_str = str(day).zfill(2)
    date_str = f"{year}-{month_str}-{day_str}"

    # Получаем список занятых слотов из bookings
    data = await db.get_booked_slots(location, date_str)
    booked = data["slots"]
    max_quantity = data["max_quantity"]

    result = {}
    for slot in config.TIME_SLOTS:
        # Считаем бронирования из таблицы bookings
        booked_count = booked.count(slot)

        # Считаем временные холды из pending_table
        pending_count = await db.pendings(location, date_str, slot)

        total_occupied = booked_count + pending_count
        result[slot] = 0 if total_occupied >= max_quantity else max_quantity - total_occupied

    return result


@app.post("/language")
async def get_language_handler(data: Dict[str, Any] = Body(...)):
    if not data or 'id' not in data:
        return JSONResponse(status_code=400, content={"error": "id is required"})

    user_id = data['id']
    lang = await db.get_user_language(user_id)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"id": user_id, "language": lang}
    )


@app.post("/get-price")
async def get_price_handler(data: Dict[str, Any] = Body(...)):
    try:
        if not data or 'location' not in data or 'time_slot' not in data:
            return JSONResponse(status_code=400, content={"error": "location and time_slot required"})

        location = data['location']
        time_slot = data['time_slot']

        price = await db.get_price(location, time_slot)

        if price is None:
            return JSONResponse(status_code=404, content={"error": "price not found"})

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "location": location,
                "time_slot": time_slot,
                "price": price
            }
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/update-price")
async def update_price_handler(data: Dict[str, Any] = Body(...)):
    try:
        if not data or 'location' not in data or 'time_slot' not in data or 'price' not in data:
            return JSONResponse(status_code=400, content={"error": "location, time_slot and price required"})

        location = data['location']
        time_slot = data['time_slot']
        price = data['price']

        await db.update_price(location, time_slot, price)

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "updated",
                "location": location,
                "time_slot": time_slot,
                "price": price
            }
        )
    except Exception as e:
        logger.exception("Error while changing price: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/change-language")
async def change_language_handler(data: Dict[str, Any] = Body(...)):
    try:
        if not data or 'id' not in data or 'language' not in data:
            return JSONResponse(status_code=400, content={"error": "id and language are required"})

        user_id = data['id']
        new_language = data['language']

        await db.update_user_language(user_id, new_language)

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "updated",
                "id": user_id,
                "language": new_language
            }
        )
    except Exception as e:
        print("ERROR:", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/get-full-price")
async def get_full_price_handler(body: models.GetFullPriceBody):
    logger.info("[get-full-price] Incoming body: %s", body.model_dump_json(indent=2))
    try:
        free_courts_quantity = body.free_courts_quantity
        location = body.location
        booking_date = body.day
        telegram_id = body.telegram_id
        time_slots = body.time_slots

        if not location or not booking_date or not time_slots:
            return JSONResponse(status_code=400, content={"error": "Missing required fields"})
            
        telegram_id = telegram_id or 0

        first = time_slots[0]
        last = time_slots[-1]
        summary_time_slot = f"{first[:5]}-{last[6:]}"

        prices = await db.get_prices_bulk(location, time_slots)
        total_price = sum(prices)

        expires_at = (datetime.now() + timedelta(minutes=4)).strftime('%Y-%m-%d %H:%M:%S')
        temporary_order_id = nanoid_generate()

        # Атомарно пишем холды по очереди.
        # free_courts_quantity больше не приходит от клиента — берётся из config внутри create_pending.
        created_slots = []
        for slot in time_slots:
            db_resp = await db.create_pending(
                free_courts_quantity, temporary_order_id, location, booking_date, slot, telegram_id, expires_at
            )
            if db_resp == 0:
                # Слот занят — откатываем уже записанные холды по этому order_id
                if created_slots:
                    await db.cancel_pending_by_order_id(temporary_order_id)
                    logger.warning(
                        "Partial rollback: cancelled %d pending(s) for order_id=%s",
                        len(created_slots), temporary_order_id,
                    )

                logger.warning(
                    "Slot occupied: order_id=%s telegram_id=%s slot=%s",
                    temporary_order_id, telegram_id, slot,
                )
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={"message": "Слоты уже успели занять к сожалению...."}
                )
            created_slots.append(slot)

        logger.info("Order created: order_id=%s telegram_id=%s", temporary_order_id, telegram_id)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "temprary_order_id": temporary_order_id,
                "location": location,
                "time_slot": summary_time_slot,
                "price": total_price
            }
        )

    except Exception as e:
        logger.error("get-full-price error: %s", e)
        await notify_admin(get_full_price_handler.__name__, error=str(traceback.format_exc()), arguments=dict(body))
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/cancel-booking", tags=["Booking"])
async def cancel_booking_endpoint(body: models.CancelBookingBody = Body(...)):
    """
    Отмена временной брони (до оплаты).
    Принимает booking_id (он же temporary_order_id), который фронт получил из /get-full-price.
    Удаляет соответствующие записи из pending_table, освобождая слоты для других.
    """
    try:
        await db.cancel_pending_by_order_id(body.booking_id)
        logger.info("Booking %s cancelled successfully", body.booking_id)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "success", "message": "Бронь успешно отменена"}
        )
    except Exception as e:
        logger.error("cancel-booking error: %s", e)
        await notify_admin(cancel_booking_endpoint.__name__, error=str(traceback.format_exc()), arguments=dict(body))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Внутренняя ошибка при отмене брони"}
        )


@app.post("/perform-booking", tags=["Booking"])
async def perform_booking_endpoint(body: models.PerformBookingBody = Body(...)):
    """
    Автоматическое подтверждение брони внешним сервисом (после оплаты).
    Берет данные из pending_table и переводит их в полноценную бронь (bookings + events).
    """
    try:
        # 1. Получаем временную бронь
        data = await db.execute("SELECT * FROM pending_table WHERE temporary_order_id=?", (body.booking_id,), fetchall=True)
        if not data:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "Бронь не найдена или истекло время"}
            )
            
        location = data[0][1]
        date_str = data[0][2]
        
        # 3. Сохраняем слоты
        for rec in data:
            slot_time = rec[3]
            parts = slot_time.split("-")
            if len(parts) == 2:
                start_str, end_str = parts[0], parts[1]
                if end_str == "00:00":
                    dt_obj = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
                    end_dt = f"{dt_obj.strftime('%Y-%m-%d')} 00:00:00"
                else:
                    end_dt = f"{date_str} {end_str}:00"
                start_dt = f"{date_str} {start_str}:00"

                title = f"Бронь {body.number} Play On"
                
                # Создаем событие в календаре
                await db.create_single_event(
                    calendar_id=location,
                    created_by=0,
                    title=title,
                    start_datetime=start_dt,
                    end_datetime=end_dt,
                    status="confirmed",
                )

            # Сохраняем в таблицу bookings
            await db.create_booking(
                telegram_id=0,
                location=location,
                booking_date=date_str,
                time_slot=slot_time,
                screenshot_path="",  # Нет скриншота, так как авто-оплата
                price=await db.get_price(location, slot_time) or 0.0,
                name="Play On",
                number=body.number
            )
            
        # 4. Удаляем из pending_table
        await db.cancel_pending_by_order_id(body.booking_id)
            
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "success", "message": "Бронь успешно подтверждена"})
        
    except Exception as e:
        logger.error("perform-booking error: %s", e)
        await notify_admin(perform_booking_endpoint.__name__, error=str(traceback.format_exc()), arguments=dict(body))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Внутренняя ошибка при подтверждении брони"}
        )



@app.get("/ping")
async def ping_endpoint():
    """
    Простой проверочный эндпоинт (Health Check).
    Используется для проверки работоспособности сервера и мониторинга (например, UptimeRobot).
    """
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "healthy", "message": "pong"}
    )


if __name__ == "__main__":
    uvicorn.run("app:app", host=config.HOST, port=config.PORT, reload=True, log_level="warning")
