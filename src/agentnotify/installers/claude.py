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
    # Wrap bin_path in double quotes — works in cmd / PowerShell / bash /
    # zsh and protects against spaces (e.g. C:\Program Files\...). No shell
    # tail (`2>/dev/null || true`) because `cmd_hook` itself is bulletproof
    # now, and POSIX-only tails would explode on Windows cmd.
    cmd = f'"{bin_path}" hook claude-{suffix}'
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


def _repath_event(event_list: list, suffix: str, bin_path: str) -> bool:
    """In-place upgrade any `<x> hook claude-<suffix>` command in event_list
    to use bin_path. Returns True if any command string changed.

    Claude's hook subprocess doesn't inherit conda/pyenv activation either, so
    bare `agentnotify hook ...` injected by older versions silently fails
    (swallowed by `|| true`). We rewrite to the absolute path.
    """
    needle = f"hook claude-{suffix}"
    correct = f'"{bin_path}" hook claude-{suffix}'
    changed = False
    for matcher in event_list:
        if not isinstance(matcher, dict):
            continue
        for h in matcher.get("hooks", []):
            if not isinstance(h, dict):
                continue
            cmd = h.get("command", "")
            if needle in cmd and cmd != correct:
                h["command"] = correct
                changed = True
    return changed


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
            data = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}

    hooks = data.setdefault("hooks", {})
    bin_path = _agentnotify_bin()

    missing: list[tuple[str, str]] = []
    repathed: list[str] = []
    for suffix, event_key in _HOOK_TARGETS:
        event_list = hooks.setdefault(event_key, [])
        if not _hook_event_has_agentnotify(event_list, f"claude-{suffix}"):
            missing.append((suffix, event_key))
            continue
        if _repath_event(event_list, suffix, bin_path):
            repathed.append(event_key)

    if not missing and not repathed:
        return InstallResult(
            agent="claude",
            status=InstallStatus.ALREADY_PRESENT,
            target=target,
        )

    backup = backup_file(target) if target.exists() else None

    for suffix, event_key in missing:
        hooks[event_key].append(_make_entry(suffix, bin_path))

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    notes: list[str] = []
    if missing:
        notes.append(f"added: {', '.join(k for _, k in missing)}")
    if repathed:
        notes.append(f"rewrote {', '.join(repathed)} command to absolute path")
    return InstallResult(
        agent="claude",
        status=InstallStatus.INSTALLED,
        target=target,
        backup=backup,
        detail="; ".join(notes),
    )
