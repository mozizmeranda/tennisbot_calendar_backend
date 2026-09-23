import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from .keyboards import get_registration_keyboard, keyboard, languages, offer_confirm_kb
from aiogram.types import ReplyKeyboardRemove
from .states import Registration
from database.database import db
from config.config import TELEGRAM_TOKEN
from .admin import router as admin_router
from config import config
from fastapi import APIRouter, Header, Request, status, HTTPException
import traceback
import os
from aiogram_sqlite_storage.sqlitestore import SQLStorage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

bot_router = APIRouter(prefix="/webhook", tags=["Bot webhook endpoint"])
bot = Bot(token=TELEGRAM_TOKEN)
storage = SQLStorage(os.path.join(BASE_DIR, "fsm_storage.db"))
dp = Dispatcher(storage=storage)
dp.include_router(admin_router)



# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)


async def on_startup():
    await db.create_tables()
    logger.info("Database tables created / checked.")


# --- /start handler ---
@dp.message(Command("start"))
async def start_func(message: types.Message, state: FSMContext):
    await state.set_state(Registration.language)
    logger.info(
        "Start command | user_id=%s | username=%s",
        message.from_user.id,
        message.from_user.username
    )
    await message.answer(
        "Пожалуйста, выберите язык\n"
        "Please choose your language\n"
        "Iltimos, tilni tanlang",
        reply_markup=languages
    )


@dp.callback_query(F.data.startswith("l_"), Registration.language)
async def choice_language(call: types.CallbackQuery, state: FSMContext):
    lang = call.data.split("_")
    await state.update_data(language=lang[1])
    logger.info(
        "Language chosen | user_id=%s | username=%s | lang=%s",
        call.from_user.id,
        call.from_user.username,
        lang[1]
    )
    await call.message.answer(text=offer_message[lang[1]], reply_markup=offer_confirm_kb(lang[1]), parse_mode="HTML")
    await state.set_state(Registration.OffertaOk)
    await call.answer()


@dp.callback_query(F.data.startswith("offer_accept"), Registration.OffertaOk)
async def accept_offer(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split(":")[1]

    await callback.message.answer(
        text=offer_accepted_and_phone[lang],
        reply_markup=get_registration_keyboard(lang)
    )

    await state.set_state(Registration.phone_number)
    logger.info(
        "Offer accepted | user_id=%s | username=%s | lang=%s",
        callback.from_user.id,
        callback.from_user.username,
        lang
    )
    await callback.answer()


# --- Phone number input ---
@dp.message(Registration.phone_number)
async def get_number(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    lang = user_data.get("language", "ru")

    # Log full user object for debugging
    logger.info("Phone input received | user=%s", vars(message.from_user))

    if message.text or message.contact:
        number = message.text or message.contact.phone_number

        if message.text and not is_valid_phone(message.text):
            logger.warning(
                "Invalid phone number | user_id=%s | username=%s | text=%s",
                message.from_user.id,
                message.from_user.username,
                message.text
            )
            await message.answer(texts["phone_error"][lang])
            return

        # Insert into DB
        logger.info(
            "Saving user to DB | user_id=%s | username=%s | full_name=%s | phone=%s | lang=%s",
            message.from_user.id,
            message.from_user.username,
            message.from_user.full_name,
            number,
            lang
        )
        await db.insert_into(
            message.from_user.id,
            message.from_user.full_name,
            message.from_user.username,
            number,
            lang
        )

        await message.reply(
            number_got[lang],
            reply_markup=ReplyKeyboardRemove()
        )

        await message.answer(
            texts["greeting"][lang],
            reply_markup=keyboard
        )
        await state.clear()
    else:
        logger.warning(
            "Wrong input received | user_id=%s | username=%s | text=%s",
            message.from_user.id,
            message.from_user.username,
            message.text
        )
        await message.answer(texts["wrong_input"][lang])
        

@dp.callback_query(F.data.startswith("rs_offer_accept"))
async def accept_offer(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split(":")[1]

    await state.set_state(Registration.phone_number)
    logger.info(
        "RS Offer accepted | user_id=%s | username=%s | lang=%s",
        callback.from_user.id,
        callback.from_user.username,
        lang
    )

    await callback.message.answer(
        texts["greeting"][lang],
        reply_markup=keyboard
    )
    await callback.answer()


@bot_router.post("", status_code=status.HTTP_200_OK)
async def telegram_webhook(
        request: Request,
        # FastAPI автоматически сопоставит этот параметр с заголовком X-Telegram-Bot-Api-Secret-Token
        x_telegram_bot_api_secret_token: str | None = Header(default=None)
):
    """Эндпоинт, куда Telegram шлет POST-запросы"""

    # 1. ПРОВЕРКА БЕЗОПАСНОСТИ:
    # Если заголовок не совпадает с секретом из config.py — сбрасываем фейковый запрос с кодом 403
    if x_telegram_bot_api_secret_token != config.WEBHOOK_SECRET:
        logger.warning("Попытка доступа с неверным секретным токеном!")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid secret token"
        )

    # 2. ОБРАБОТКА АПДЕЙТА:
    try:
        update_json = await request.json()
        update = types.Update(**update_json)

        # Передаем обновление в диспетчер aiogram
        await dp.feed_update(bot=bot, update=update)

    except Exception as e:
        # Логируем ошибку со стектрейсом у себя в консоли/файле
        logger.exception("Ошибка при обработке вебхука Telegram: %s", e)
        await bot.send_message(chat_id=config.ADMIN_ID, text=f"Error in webhookhandler\n\n{traceback.format_exc()}")


# --- Main ---
# async def main():
#     await dp.start_polling(bot)
#
# if __name__ == "__main__":
#     import asyncio
#     asyncio.run(main())
