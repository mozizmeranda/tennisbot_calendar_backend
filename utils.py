from httpx import AsyncClient
from config.config import *
import base64
from nanoid import generate
import logging
from network.client import get_http_client


logger = logging.getLogger(__name__)


async def send_check_to_admin(client: AsyncClient, photo_bytes, filename, content_type, caption, reply_markup):
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto'
        response = await client.post(
            url,
            data={
                'chat_id': ADMIN_ID,
                'caption': caption,
                'reply_markup': reply_markup
            },
            files={'photo': (filename, photo_bytes, content_type)},
            timeout=60
        )
        response.json()
        return 1

    except Exception as exp:
        print(f"Error while sending photo to admin from\n {caption}")
        return 0


async def notify_admin(func_name: str, error: str, arguments=None):
    if arguments is None:
        arguments = {"00": 00}
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
        text = (f"Func name:\n ```{func_name}``` \n\nError:\n ```{error}```  \n "
                f"Arguments:\n ```{arguments.items() if arguments else "Nothing"}```\n")
        response = await get_http_client().post(
            url,
            data={
                'chat_id': ADMIN_ID,
                'text': text,
                'parse_mode': 'MarkdownV2'
            },
            timeout=60
        )
        response.json()

    except Exception as exp:
        logger.error("Error in notify admin: %s", exp)



alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'


def nanoid_generate():
    return generate(alphabet, 8)
