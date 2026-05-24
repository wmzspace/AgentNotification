from .base import Notification, Notifier, NotifierError
from .bark import BarkNotifier
from .ntfy import NtfyNotifier

__all__ = [
    "Notification",
    "Notifier",
    "NotifierError",
    "BarkNotifier",
    "NtfyNotifier",
    "build_notifiers",
]


KNOWN_BACKENDS = ("bark", "ntfy")


def build_notifiers(config) -> tuple[list[Notifier], list[str]]:
    """Instantiate the notifiers requested by `config.backends`.

    Returns (notifiers, warnings). Unknown backend names yield a warning string
    rather than raising — hooks must not crash the agent over a typo.
    """
    result: list[Notifier] = []
    warnings: list[str] = []
    for name in config.backends:
        if name == "bark":
            if not config.bark or not config.bark.device_key:
                continue
            result.append(BarkNotifier(config.bark))
        elif name == "ntfy":
            if not config.ntfy or not config.ntfy.topic:
                continue
            result.append(NtfyNotifier(config.ntfy))
        else:
            warnings.append(f"unknown backend {name!r} (known: {', '.join(KNOWN_BACKENDS)})")
    return result, warnings
