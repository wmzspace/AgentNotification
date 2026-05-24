from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from ._common import InstallResult, InstallStatus, backup_file

CLAUDE_DIR = Path.home() / ".claude"
SETTINGS_PATH = CLAUDE_DIR / "settings.json"


def _agentnotify_bin() -> str:
    """Absolute path to agentnotify (PATH may be stripped in hook subprocesses)."""
    if sys.argv and sys.argv[0]:
        p = Path(sys.argv[0])
        try:
            if p.is_absolute() and p.is_file():
                return str(p)
            cand = shutil.which(p.name)
            if cand:
                return cand
        except OSError:
            pass
    return shutil.which("agentnotify") or "agentnotify"


def _make_entry(suffix: str, bin_path: str) -> dict:
    cmd = f"{bin_path} hook claude-{suffix} 2>/dev/null || true"
    return {
        "matcher": "",
        "hooks": [{"type": "command", "command": cmd, "async": True}],
    }


def _hook_event_has_agentnotify(event_list: list, needle: str) -> bool:
    """True if any nested hook command in `event_list` already mentions `agentnotify`."""
    for matcher in event_list:
        for h in matcher.get("hooks", []) if isinstance(matcher, dict) else []:
            cmd = h.get("command", "") if isinstance(h, dict) else ""
            if "agentnotify" in cmd and needle in cmd:
                return True
    return False


# (suffix used in command, key under "hooks", description fragment)
_HOOK_TARGETS = (
    ("stop", "Stop"),
    ("notification", "Notification"),
    ("permission", "PermissionRequest"),
)


def install_claude() -> InstallResult:
    target = SETTINGS_PATH
    if not CLAUDE_DIR.exists():
        return InstallResult(
            agent="claude",
            status=InstallStatus.NO_AGENT,
            target=target,
            detail="~/.claude/ missing — install Claude Code first",
        )

    data: dict = {}
    if target.exists():
        try:
            data = json.loads(target.read_text())
        except json.JSONDecodeError:
            data = {}

    hooks = data.setdefault("hooks", {})
    bin_path = _agentnotify_bin()

    missing: list[tuple[str, str]] = []
    for suffix, event_key in _HOOK_TARGETS:
        event_list = hooks.setdefault(event_key, [])
        if not _hook_event_has_agentnotify(event_list, f"claude-{suffix}"):
            missing.append((suffix, event_key))

    if not missing:
        return InstallResult(
            agent="claude",
            status=InstallStatus.ALREADY_PRESENT,
            target=target,
        )

    backup = backup_file(target) if target.exists() else None

    for suffix, event_key in missing:
        hooks[event_key].append(_make_entry(suffix, bin_path))

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    detail = f"added: {', '.join(k for _, k in missing)}"
    return InstallResult(
        agent="claude",
        status=InstallStatus.INSTALLED,
        target=target,
        backup=backup,
        detail=detail,
    )
