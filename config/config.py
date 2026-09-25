from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
from environs import Env

# 1. Инициализация environs
env = Env()
env.read_env()  # Загружает переменные из файла .env

# 2. Настройка путей (pathlib вместо os.path)
BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# 3. Базовая настройка логирования
LOG_LEVEL = env.str("LOG_LEVEL", default="INFO").upper()

logging.getLogger("watchfiles").setLevel(logging.WARNING)
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            LOGS_DIR / "app.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
    ]
)

# 4. Telegram & Admin
ADMIN_ID: int = env.int("ADMIN_ID", default=0)
TELEGRAM_TOKEN: str = env.str("TELEGRAM_TOKEN", default="")
ADMIN_BOT_TOKEN: str = env.str("ADMIN_BOT_TOKEN", default="")
WEBHOOK_URL: str = env.str("WEBHOOK_URL")
WEBHOOK_SECRET: str = env.str("WEBHOOK_SECRET")

courts: dict[str, int] = env.json("COURTS")

# 8. Timeout
TIMEOUT_MS: int = env.int("TIMEOUT_MS", default=0)


PAYMENT_CACHE: dict[str, str] = {}

locs = {
    "A": "МГУ",
    "B": "Аджо"
}


ADMIN_USERNAME: str = env.str("ADMIN_USERNAME", default="")
ADMIN_PASSWORD: str = env.str("ADMIN_PASSWORD", default="")

start_h = env.int("SLOT_START_HOUR", default=6)
end_h = env.int("SLOT_END_HOUR", default=24)
step = env.int("SLOT_DURATION_HOURS", default=1)

TIME_SLOTS: list[str] = [
    f"{h:02d}:00-{(h + step) % 24:02d}:00"
    for h in range(start_h, end_h, step)
]


AUTH_KEY: str = env.str("AUTH_KEY")
WHITE_IPS: list[str] = env.list("WHITE_IPS", default=[])

PORT: int = env.int("PORT", default=8080)
HOST: str = env.str("HOST", default="localhost")


ROOT_PATH: str = env.str("ROOT_PATH", default="")

ADMIN_TG_USERNAME: str = env.str("ADMIN_TG_USERNAME", default="")

LOCATIONS_YANDEX_MAPS: dict[str, str] = env.dict("LOCATIONS_YANDEX_MAPS", default={})
