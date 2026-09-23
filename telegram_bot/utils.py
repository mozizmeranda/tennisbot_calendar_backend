import re



def is_valid_phone(phone):
    pattern = r'^\+[1-9]\d{7,14}$'
    return bool(re.match(pattern, phone))
    
offer_message = {
    "ru": "Перед бронированием, пожалуйста, ознакомьтесь с <a href=\"https://telegra.ph/PUBLICHNAYA-OFERTA-04-12-4\">условиями публичной оферты</a>.\n\nПродолжая, вы подтверждаете согласие с условиями.",
    "en": "Before booking, please review the <a href=\"https://telegra.ph/PUBLIC-OFFER-04-12\">public offer terms</a>.\n\nBy continuing, you agree to the terms.",
    "uz": "Bron qilishdan oldin, iltimos, <a href=\"https://telegra.ph/OMMAVIY-OFERTA-04-12\">ommaviy oferta shartlari</a> bilan tanishing.\n\nDavom etish orqali siz shartlarga rozilik bildirasiz.",
    "uz-cyr": "Брон қилишдан олдин, илтимос, <a href=\"https://telegra.ph/OMMAVIJ-OFERTA-04-12\">оммавий оферта шартлари</a> билан танишинг.\n\nДавом этиш орқали сиз шартларга розилик билдирасиз."
}


offer_accepted_and_phone = {
    "ru": "Оферта принята. Можете продолжить бронирование.\n\nПожалуйста, отправьте номер телефона, нажав на кнопку ниже ⬇️ или напишите текстом (в формате +998XXXXXXXXX)",
    "en": "Offer accepted. You can continue booking.\n\nPlease send your phone number by pressing the button below ⬇️ or type it manually (in the format +998XXXXXXXXX)",
    "uz": "Oferta qabul qilindi. Bron qilishni davom ettirishingiz mumkin.\n\nIltimos, telefon raqamingizni quyidagi tugmani bosib ⬇️ yoki matn orqali yozing (formatda +998XXXXXXXXX)",
    "uz-cyr": "Оферта қабул қилинди. Брон қилишни давом эттиришингиз мумкин.\n\nИлтимос, телефон рақамингизни қуйидаги тугмани босиб ⬇️ ёки матн орқали ёзинг (форматда +998XXXXXXXXX)"
}


asking_for_number = {
    "ru": "Пожалуйста, отправьте номер телефона, нажав на кнопку ниже ⬇️ или напишите текстом (в формате +998XXXXXXXXX)",
    "en": "Please send your phone number by pressing the button below ⬇️ or type it manually (in the format +998XXXXXXXXX)",
    "uz": "Iltimos, telefon raqamingizni quyidagi tugmani bosib ⬇️ yoki matn orqali yozing (formatda +998XXXXXXXXX)",
    "uz-cyr": "Илтимос, телефон рақамингизни қуйидаги тугмани босиб ⬇️ ёки матн орқали ёзинг (форматда +998XXXXXXXXX)"
}

texts = {
    "phone_error": {
        "ru": "Номер телефона должен быть в формате +998XXXXXXXXX!",
        "en": "Phone number must be in the format +998XXXXXXXXX!",
        "uz": "Telefon raqam +998XXXXXXXXX formatida bo‘lishi kerak!",
        "uz-cyr": "Телефон рақам +998XXXXXXXXX форматда бўлиши керак!"
    },
    "wrong_input": {
        "ru": "Я же написал, номер телефона!",
        "en": "Please send your phone number!",
        "uz": "Iltimos, telefon raqamingizni yuboring!",
        "uz-cyr": "Илтимос, телефон рақамингизни юборинг!"
    },
    "greeting": {
        "ru": """🎾 Добро пожаловать в систему бронирования теннисных кортов!

Здесь вы можете забронировать корт на удобное время.
У нас доступно 5 кортов в 2 локациях.""",

        "en": """🎾 Welcome to the tennis court booking system!

Here you can book a court at a convenient time.
We have 5 courts available in 2 locations.""",

        "uz": """🎾 Tennis kortlarini bron qilish tizimiga xush kelibsiz!

Bu yerda siz o'zingizga qulay vaqtda kort bron qilishingiz mumkin.
Bizda 2 ta lokatsiyada 5 ta kort mavjud.""",

        "uz-cyr": """🎾 Теннис кортларини брон қилиш тизимига хуш келибсиз!

Бу ерда сиз ўзингизга қулай вақтда корт брон қилишингиз мумкин.
Бизда 2 та локацияда 5 та корт мавжуд."""
    }
}


number_got = {
    "ru": "Номер телефона получен ✅",
    "en": "Phone number received ✅",
    "uz": "Telefon raqam qabul qilindi ✅",
    "uz-cyr": "Телефон рақам қабул қилинди ✅"
}


