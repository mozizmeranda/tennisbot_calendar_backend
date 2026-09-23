import json
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from database.database import db
from telegram_bot.bot_app import bot
from config import config
from utils import nanoid_generate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Payment's router"])


@router.post("/send-photo")
async def send_photo_payment(
    photo: UploadFile = File(...),
    booking_id: Optional[str] = Form(None),
    id: Optional[int] = Form(None),
    telegram_id: Optional[int] = Form(None),
    date: str = Form(...),
    location: Optional[str] = Form(None),
    location_id: Optional[str] = Form(None),
    price: Optional[str] = Form(None),
    time_slots: str = Form(...),
):
    """
    Эндпоинт для отправки чека оплаты на карту.
    Создает записи в pending_bookings и отправляет фото админу в Telegram.
    """
    user_id = telegram_id or id
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user telegram id")

    loc = location_id or location
    if not loc:
        raise HTTPException(status_code=400, detail="Missing location")
 
    if not booking_id:
        raise HTTPException(status_code=400, detail="Missing booking id")

    try:
        if isinstance(time_slots, str):
            try:
                parsed_slots = json.loads(time_slots)
            except Exception:
                parsed_slots = [s.strip() for s in time_slots.split(",") if s.strip()]
        else:
            parsed_slots = time_slots

        if isinstance(parsed_slots, str):
            parsed_slots = [parsed_slots]

        logger.info(
            "=== /send-photo request === telegram_id=%s, date=%s, location=%s, time_slots=%s, booking_id=%s",
            user_id, date, loc, parsed_slots, booking_id
        )

        user_info = await db.get_user_data_by_id(user_id)
        phone, name = ("Неизвестно", "Неизвестно") if not user_info else (user_info[0], user_info[1])

        caption = (
            f"<b>Booking ID</b>: {booking_id}\n"
            f"📋 <b>ID</b> #{user_id}\n"
            f"👤 <b>Имя</b>: {name}\n"
            f"📞 <b>Номер</b>: {phone}\n"
            f"📍 <b>Локация</b>: {loc}\n"
            f"📅 <b>Дата</b>: {date}\n"
            f"⏰ Слот: {parsed_slots}\n"
            f"Цена: {price or 'Не указана'}"
        )

        for time_slot in parsed_slots:
            await db.create_pending_booking(booking_id, loc, date, time_slot, user_id)

        reply_markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adm_ok_{booking_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"adm_no_{booking_id}")
        ]])

        photo_bytes = await photo.read()
        filename = photo.filename or "receipt.jpg"
        input_file = BufferedInputFile(photo_bytes, filename=filename)

        admin_chat_id = config.ADMIN_ID
        await bot.send_photo(
            chat_id=admin_chat_id,
            photo=input_file,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )

        logger.info("Pending booking created and photo sent to admin for booking_id=%s", booking_id)
        return {"success": True, "message": "Фото принято и обрабатывается"}

    except Exception as e:
        logger.exception("Error in /send-photo for user %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail=str(e))




