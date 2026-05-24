from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class NotifierError(Exception):
    pass


@dataclass
class Notification:
    title: str
    body: str = ""
    url: str | None = None
    icon: str | None = None
    group: str | None = None
    priority: int | None = None
    tags: list[str] = field(default_factory=list)


class Notifier(Protocol):
    name: str

    def send(self, n: Notification, *, dry_run: bool = False) -> str:
        """Send the notification. Returns a short human-readable status line.

        Raises NotifierError on failure. `dry_run=True` must not perform any
        network I/O — return the would-be request as the status line instead.
        """
