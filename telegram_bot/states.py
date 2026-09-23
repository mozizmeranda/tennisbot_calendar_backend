from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    OffertaOk = State()
    language = State()
    phone_number = State()


class Mailing(StatesGroup):
    get_text = State()
    confirm_mailing = State()
