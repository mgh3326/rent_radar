"""Notification system for price changes and alerts."""

from abc import ABC, abstractmethod
from typing import Any


class Notifier(ABC):
    """Base protocol for notification services."""

    @abstractmethod
    async def send(
        self, message: str, *, title: str | None = None, **kwargs: Any
    ) -> bool:
        """Send a notification message.

        Args:
            message: The notification body text.
            title: Optional title/header for the notification.
            **kwargs: Additional provider-specific parameters.

        Returns:
            True if sent successfully, False otherwise.
        """
        ...
