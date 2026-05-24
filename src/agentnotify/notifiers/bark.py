from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .base import Notification, NotifierError


def normalize_bark_key(s: str) -> str:
    """Accept either a raw device key or a full Bark URL and return the key.

    Bark's iOS app shows users a URL like `https://api.day.app/<KEY>/` and
    it's easy to paste the whole thing as the device_key — the server then
    HTTP 400s with no clue why. Strip http(s):// and any trailing path/slash.
    """
    s = (s or "").strip()
    if s.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(s)
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            return parts[-1]
    return s.rstrip("/")


class BarkNotifier:
    name = "bark"

    def __init__(self, cfg) -> None:
        self.cfg = cfg

    def send(self, n: Notification, *, dry_run: bool = False) -> str:
        payload: dict[str, object] = {
            "title": n.title,
            "body": n.body,
            "device_key": normalize_bark_key(self.cfg.device_key),
            "autoBadge": "+1",
        }
        icon = n.icon or self.cfg.icon
        if icon:
            payload["icon"] = icon
        if n.url:
            payload["url"] = n.url
        if n.group or self.cfg.group:
            payload["group"] = n.group or self.cfg.group
        if self.cfg.sound:
            payload["sound"] = self.cfg.sound

        url = f"{self.cfg.server.rstrip('/')}/push"
        body = json.dumps(payload).encode()

        if dry_run:
            return f"POST {url} {payload}"

        req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return f"bark {resp.status}"
        except urllib.error.HTTPError as e:
            raise NotifierError(f"bark HTTP {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise NotifierError(f"bark network error: {e.reason}") from e
