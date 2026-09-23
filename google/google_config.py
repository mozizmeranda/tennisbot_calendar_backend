# google/calendar/config.py
from pathlib import Path
import json

BASE_DIR = Path(__file__).resolve().parent
SERVICE_ACCOUNT_FILE = BASE_DIR / "credentials.json"


class GoogleConfig:

    def __init__(self):
        self.cached_token: str = None
        self.token_expires_at: float = 0.0
        self.sa_data: dict = None


gc_instance = GoogleConfig()


def load_service_account_data(gc: GoogleConfig):
    if gc.sa_data is None:
        with open(SERVICE_ACCOUNT_FILE, "r") as f:
            gc.sa_data = json.load(f)
    return gc.sa_data


def get_google_config() -> GoogleConfig:
    return gc_instance
