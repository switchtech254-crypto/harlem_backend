"""Telegram Bot API (sendMessage). The bot token is part of the request URL, so it must never reach
logs or error messages: every failure is re-raised with a generic message."""
import html
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)
TIMEOUT = (5, 15)
MAX_LEN = 4000  # Telegram's limit is 4096


class TelegramError(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and chat_ids())


def chat_ids() -> list[str]:
    return [c.strip() for c in settings.TELEGRAM_CHAT_ID.split(",") if c.strip()]


def esc(value) -> str:
    """Customer-provided text goes into an HTML message: escape it."""
    return html.escape(str(value or ""), quote=False)


def send_message(chat_id: str, text: str) -> None:
    url = f"{settings.TELEGRAM_API_BASE.rstrip('/')}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text[:MAX_LEN], "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=TIMEOUT,
        )
        data = r.json()
    except (requests.RequestException, ValueError):
        # Do NOT chain the original exception: its message contains the URL (and the token).
        raise TelegramError("Could not reach Telegram.") from None
    if r.status_code != 200 or not data.get("ok"):
        raise TelegramError(f"Telegram rejected the message: {data.get('description', r.status_code)}")
