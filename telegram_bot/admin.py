import logging
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from .keyboards import keyboard, rs_confirm_keys
from config.config import ADMIN_TG_USERNAME, LOCATIONS_YANDEX_MAPS
from states import Mailing

from database.database import db

logger = logging.getLogger(__name__)

router = Router()

texts = {
    "approved_admin": {
        "ru": "Подтверждено✅",
        "en": "Approved by admin✅",
        "uz": "Admin tomonidan tasdiqlandi✅",
        "uz-cyr": "Админ томонидан тасдиқланди✅"
    },
    "payment_confirmed": {
        "ru": "Платеж подтвержден администратором✅.",
        "en": "Payment confirmed by admin✅.",
        "uz": "To‘lov admin tomonidan tasdiqlandi✅.",
        "uz-cyr": "Тўлов админ томонидан тасдиқланди✅."
    },
    "wait_us": {
        "ru": "Ждем вас у нас.😇",
        "en": "We are waiting for you.😇",
        "uz": "Sizni kutamiz.😇",
        "uz-cyr": "Сизни кутамиз.😇"
    },
    "phone_number": {
        "ru": "Номер телефона",
        "en": "Phone number",
        "uz": "Telefon raqam",
        "uz-cyr": "Телефон рақам"
    },
    "rejected": {
        "ru": "Отказано",
        "en": "Rejected",
        "uz": "Rad etildi",
        "uz-cyr": "Рад этилди"
    },
    "payment_rejected": {
        "ru": "Платеж не был подтвержден администратором.",
        "en": "Payment was not approved by admin.",
        "uz": "To‘lov admin tomonidan tasdiqlanmadi.",
        "uz-cyr": "Тўлов админ томонидан тасдиқланмади."
    },
    "contact_admin": {
        "ru": "В случае ошибок, обратитесь к админу",
        "en": "If you have issues, contact admin",
        "uz": "Xatolik bo‘lsa, admin bilan bog‘laning",
        "uz-cyr": "Хатолик бўлса, админ билан боғланинг"
    }
}

yandex_maps = {
    "ru": "📍 Локация на Яндекс Картах:",
    "en": "📍 Location on Yandex Maps:",
    "uz": "📍 Yandex Xaritada joylashuv:",
    "uz-cyr": "📍 Яндекс Харитада жойлашув:"
}

def get_yandex_maps_loc(language, location):
    t = f"{yandex_maps[language]} {LOCATIONS_YANDEX_MAPS[location]}"
    return t


def t(key: str, lang: str) -> str:
    return texts.get(key, {}).get(lang, texts.get(key, {}).get("ru", ""))


@router.callback_query(F.data.startswith("adm_ok_"))
async def admin_confirm(call: CallbackQuery, bot: Bot):
    try:
        screenshot = call.message.photo[-1].file_id if call.message.photo else ""
        text = call.message.caption or ""
        lst = call.data.split("_")

        booking_id = lst[2]
        booking_data = await db.get_by_booking_id(booking_id)
        if not booking_data:
            await call.answer("Бронь не найдена или уже обработана!", show_alert=True)
            return

        tg_id = int(booking_data[0][4])
        location = booking_data[0][1]
        date_str = booking_data[0][2]

        lang = await db.get_lang(tg_id) or "ru"
        user_info = await db.get_user_data_by_id(tg_id)
        number, name = (user_info[0], user_info[1]) if user_info else ("Неизвестно", "Неизвестно")

        await call.message.edit_caption(
            caption=f"{text}\n\n----\n\n{t('approved_admin', lang)}"
        )

        try:
            await bot.send_message(
                chat_id=tg_id,
                text=f"{text}\n\n{t('payment_confirmed', lang)}\n{t('wait_us', lang)}\n{get_yandex_maps_loc(lang, location)}",
                reply_markup=keyboard,
                link_preview_options={"is_disabled": True}
            )
        except Exception as e:
            logger.warning("Failed to send notification to user %s: %s", tg_id, e)

        await db.kill_from_pending_bookings(booking_id)

        for rec in booking_data:
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

                title = f"{name} | {number}" if (name != "Неизвестно" or number != "Неизвестно") else f"Booking #{tg_id}"
                await db.create_single_event(
                    calendar_id=location,
                    created_by=tg_id,
                    title=title,
                    start_datetime=start_dt,
                    end_datetime=end_dt,
                    status="confirmed",
                )

            await db.create_booking(
                telegram_id=tg_id,
                location=location,
                booking_date=date_str,
                time_slot=slot_time,
                screenshot_path=screenshot,
                price=await db.get_price(location, slot_time) or 0.0
            )

        await call.answer("Бронь успешно подтверждена!")
    except Exception as e:
        logger.exception("Error in admin_confirm: %s", e)
        await call.answer(f"Ошибка при подтверждении: {e}", show_alert=True)


@router.callback_query(F.data.startswith("adm_no_"))
async def admin_reject(call: CallbackQuery, bot: Bot):
    try:
        text = call.message.caption or ""
        lst = call.data.split("_")

        booking_id = lst[2]
        booking_data = await db.get_by_booking_id(booking_id)
        if not booking_data:
            await call.answer("Бронь не найдена или уже обработана!", show_alert=True)
            return

        tg_id = int(booking_data[0][4])
        lang = await db.get_lang(tg_id) or "ru"
        number = await db.get_number_by_id(tg_id) or "Неизвестно"

        await db.kill_from_pending_bookings(booking_id)

        await call.message.edit_caption(
            caption=f"{text}\n\n----\n\n{t('phone_number', lang)}: {number}\n\n{t('rejected', lang)}❌"
        )

        try:

            await bot.send_message(
                chat_id=tg_id,
                text=(
                    f"{text}\n\n"
                    f"{t('payment_rejected', lang)}❌\n"
                    f"{t('contact_admin', lang)}: <b>@{ADMIN_TG_USERNAME}</b>"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning("Failed to send rejection notification to user %s: %s", tg_id, e)

        await call.answer("Бронь отклонена.")
    except Exception as e:
        logger.exception("Error in admin_reject: %s", e)
        await call.answer(f"Ошибка при отклонении: {e}", show_alert=True)




@router.message(Command("rs"))
async def rs_command(message: Message, state: FSMContext):
    await message.answer("Отправьте текст для рассылки")
    await state.set_state(Mailing.get_text)


@router.message(Mailing.get_text)
async def get_text_state(message: Message, state: FSMContext):
    await message.answer(f"Ваш текст: {message.html_text}", parse_mode="HTML", reply_markup=rs_confirm_keys)
    await state.set_state(Mailing.confirm_mailing)
    await state.update_data(selected_text=message.html_text)


@router.callback_query(F.data == "rs_confirm", Mailing.confirm_mailing)
async def rs_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
    users = db.get_all_users()
    await call.answer("Рассылка началась", show_alert=True)
    selected_text = await state.get_value("selected_text")
    for user in users:
        await bot.send_message(chat_id=user[0], text=selected_text, parse_mode="HTML")


@router.callback_query(F.data == "rs_cancel", Mailing.confirm_mailing)
async def rs_cancel(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("Чтобы снова сделать рассылку, вызовите команду /rs")
    await state.clear()


