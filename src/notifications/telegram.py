"""Telegram Bot API notification implementation."""

import logging
from typing import Any

import httpx

from src.notifications.base import Notifier
from src.config import get_settings

logger = logging.getLogger(__name__)


class TelegramNotifier(Notifier):
    """Send notifications via Telegram Bot API."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._api_url = (
            f"https://api.telegram.org/bot{self._settings.telegram_bot_token}"
        )
        self._timeout = httpx.Timeout(10.0)

    async def send(
        self, message: str, *, title: str | None = None, **kwargs: Any
    ) -> bool:
        """Send message to configured Telegram chat."""

        if not self._settings.telegram_bot_token:
            logger.warning("Telegram bot token not configured, skipping notification")
            return False

        if not self._settings.telegram_chat_id:
            logger.warning("Telegram chat ID not configured, skipping notification")
            return False

        # Build message with title if provided
        full_message = f"🔔 *{title}*\n\n{message}" if title else message

        payload = {
            "chat_id": self._settings.telegram_chat_id,
            "text": full_message,
            "parse_mode": "Markdown",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._api_url}/sendMessage", json=payload
                )
                response.raise_for_status()

                result = response.json()
                if result.get("ok"):
                    logger.info(
                        f"Telegram notification sent: {title or 'Notification'}"
                    )
                    return True
                else:
                    logger.error(
                        f"Telegram API error: {result.get('description', 'Unknown')}"
                    )
                    return False

        except httpx.HTTPStatusError as e:
            logger.error(f"Telegram HTTP error: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Telegram notification failed: {str(e)}")
            return False
