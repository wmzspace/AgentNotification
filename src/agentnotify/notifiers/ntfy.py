from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import Notification, NotifierError


class NtfyNotifier:
    name = "ntfy"

    def __init__(self, cfg) -> None:
        self.cfg = cfg

    def send(self, n: Notification, *, dry_run: bool = False) -> str:
        payload: dict[str, object] = {
            "topic": self.cfg.topic,
            "message": n.body or n.title,
            "title": n.title,
        }
        priority = n.priority if n.priority is not None else self.cfg.priority
        if priority is not None:
            payload["priority"] = priority
        tags = n.tags or self.cfg.tags
        if tags:
            payload["tags"] = list(tags)
        if n.url:
            payload["click"] = n.url
        if n.icon:
            payload["icon"] = n.icon

        url = self.cfg.server.rstrip("/")
        body = json.dumps(payload).encode()

        headers = {"Content-Type": "application/json"}
        if self.cfg.token:
            headers["Authorization"] = f"Bearer {self.cfg.token}"

        if dry_run:
            return f"POST {url} {payload}"

        req = urllib.request.Request(url, body, headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return f"ntfy {resp.status}"
        except urllib.error.HTTPError as e:
            raise NotifierError(f"ntfy HTTP {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise NotifierError(f"ntfy network error: {e.reason}") from e
