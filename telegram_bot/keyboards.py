from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="🎾 Открыть приложение", web_app=WebAppInfo(url="https://tennisplus.uz/v2.html"))
    ]
])


def offer_confirm_kb(lang: str) -> InlineKeyboardMarkup:
    texts = {
        "en": {
            "accept": "I agree"
        },
        "ru": {
            "accept": "Я согласен"
        },
        "uz": {
            "accept": "Roziman"
        },
        "uz-cyr": {
            "accept": "Розиман"
        }
    }

    t = texts.get(lang, texts["en"])

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t["accept"],
                    callback_data=f"offer_accept:{lang}"
                )
            ]
        ]
    )


def get_registration_keyboard(lang: str) -> ReplyKeyboardMarkup:
    texts = {
        "ru": "Отправить номер 📱",
        "en": "Send phone number 📱",
        "uz": "Telefon raqamni yuborish 📱",
        "uz-cyr": "Телефон рақамни юбориш 📱"
    }

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=texts.get(lang, texts["ru"]),
                    request_contact=True
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


rs_confirm_keys = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Подвтертдить", callback_data="rs_confirm"),
            InlineKeyboardButton(text="Отменить", callback_data="rs_cancel")
        ]
    ]
)


languages = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🇬🇧 English", callback_data="l_en"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="l_ru"),
            InlineKeyboardButton(text="🇺🇿 O'zbek tili", callback_data="l_uz"),
            InlineKeyboardButton(text="🇺🇿 Узбек тили", callback_data="l_uz-cyr")
        ]
    ]
)
