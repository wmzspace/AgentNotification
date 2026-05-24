from __future__ import annotations

import json
import os
from pathlib import Path

from .notifiers import Notification


# Per-agent notification icons. `Notification.icon` takes precedence over the
# `[bark].icon` default in config.toml (see notifiers/bark.py: `n.icon or
# self.cfg.icon`), so hook builders set this explicitly to keep Codex/Kimi
# pushes from showing the Claude avatar.
CLAUDE_ICON = "https://claude.ai/favicon.ico"
CODEX_ICON = "https://openai.com/favicon.ico"
KIMI_ICON = "https://statics.moonshot.cn/kimi-chat/favicon.ico"


def summarize(text: str, max_len: int = 120) -> str:
    """Truncate to max_len, preferring sentence boundaries then word boundaries.

    Preserves the behavior of the original bark_stop.py — falls back through
    several punctuation marks before resorting to a hard cut at a space.
    """
    text = text.strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    chunk = text[:max_len]
    for punct in ("。", "！", "？", "!", "?", ".", "；", ";"):
        idx = chunk.rfind(punct)
        if idx > 20:
            return chunk[: idx + 1]
    idx = chunk.rfind(" ")
    return (chunk[:idx] if idx > 20 else chunk) + "…"


def last_assistant_message(transcript_path: str) -> str | None:
    """Read a Claude Code JSONL transcript and return the most recent assistant text.

    Claude Code's transcript schema as of 2026:
        {
          "type": "assistant",                  # top-level type
          "message": {"role": "assistant",
                      "content": [
                          {"type": "text",     "text": "..."},
                          {"type": "tool_use", ...},
                          {"type": "thinking", ...},
                      ]},
          ...
        }
    We skip records that aren't `type:"assistant"` and skip assistant
    messages whose content only contains tool_use / thinking (mid-turn),
    walking backward until we find one with actual user-facing text.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return None
    try:
        # Claude Code writes transcripts as UTF-8 JSONL. Without an explicit
        # encoding, Python falls back to the OS locale on Windows (GBK/CP936
        # on zh-CN), and any non-ASCII char in the assistant text raises
        # UnicodeDecodeError — which the outer hook's broad except then
        # swallows, so the notification silently never fires.
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("type") != "assistant":
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            if content.strip():
                return content
            continue
        if isinstance(content, list):
            texts = [
                c.get("text", "")
                for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            ]
            joined = "\n".join(t for t in texts if t).strip()
            if joined:
                return joined
            # All blocks were tool_use / thinking — keep walking back.
            continue
    return None


def claude_stop(stdin_text: str) -> Notification | None:
    """Build a notification for Claude Code's Stop hook payload."""
    try:
        d = json.loads(stdin_text)
    except json.JSONDecodeError:
        d = {}
    body = "回答完成"
    msg = last_assistant_message(d.get("transcript_path", ""))
    if msg:
        body = summarize(msg)
    return Notification(title="Claude Code 回答完成", body=body, url="claude://", icon=CLAUDE_ICON)


# Substrings (lowercased) that indicate a "waiting for input" notification.
# We let the Stop hook own that case so we don't double-fire.
_SKIP_KEYWORDS = (
    "waiting for your input",
    "waiting for input",
    "等待输入",
    "等待你的",
)


def claude_notification(stdin_text: str) -> Notification | None:
    """Build a notification for Claude Code's Notification hook payload.

    Claude Code 2026 multiplexes many event types through `Notification`:
    `permission_prompt`, `idle_prompt`, `auth_success`, `elicitation_dialog`,
    etc. We let the dedicated `PermissionRequest` hook handle permission
    events (richer payload with tool_name + tool_input), and surface the
    other notification types here.

    Returns None when the event should be skipped (empty message, a
    'waiting for input' event already covered by the Stop hook, or a
    permission_prompt about to be re-fired by claude-permission).
    """
    try:
        d = json.loads(stdin_text)
    except json.JSONDecodeError:
        return None
    message = (d.get("message") or "").strip()
    if not message:
        return None
    lowered = message.lower()
    if any(kw in lowered for kw in _SKIP_KEYWORDS):
        return None
    # PermissionRequest hook covers this in richer detail — drop the duplicate.
    matcher = (d.get("matcher") or "").strip().lower()
    notif_type = (d.get("notification_type") or "").strip().lower()
    if matcher == "permission_prompt" or notif_type == "permission_prompt":
        return None
    if "permission" in lowered:
        return None
    raw_title = (d.get("title") or "").strip()
    title = f"Claude Code · {raw_title}" if raw_title else "Claude Code 需要操作"
    return Notification(
        title=title,
        body=summarize(message),
        url="claude://",
        icon=CLAUDE_ICON,
    )


def claude_permission(stdin_text: str) -> Notification | None:
    """Build a notification for Claude Code's `PermissionRequest` hook payload.

    Payload (Claude Code 2026):
        {session_id, transcript_path, cwd, permission_mode,
         hook_event_name: "PermissionRequest",
         tool_name, tool_input: {<tool-specific fields>}}

    Each tool's `tool_input` differs (Bash → `command`; Edit/Write →
    `file_path`; Read → `file_path`; WebFetch → `url`; …). We surface
    the first useful field we find and prefix it with the tool name.
    """
    try:
        d = json.loads(stdin_text)
    except json.JSONDecodeError:
        return None
    tool = (d.get("tool_name") or "tool").strip()
    body = tool
    tin = d.get("tool_input")
    if isinstance(tin, dict):
        for key in ("command", "file_path", "path", "url", "description"):
            v = tin.get(key)
            if isinstance(v, str) and v.strip():
                body = f"{tool}: {v.strip()}"
                break
    return Notification(
        title="Claude Code · 权限请求",
        body=summarize(body),
        url="claude://",
        icon=CLAUDE_ICON,
    )


def kimi_stop(stdin_text: str) -> Notification | None:
    """Build a notification for Kimi Code CLI's Stop hook.

    Kimi's Stop payload only carries session_id/cwd/hook_event_name — no
    transcript path — so we emit a fixed "完成" title rather than a body
    summary. If a future Kimi version adds last-message metadata, extend here.
    """
    try:
        json.loads(stdin_text)
    except json.JSONDecodeError:
        pass
    return Notification(title="Kimi 完成", body="回答完成", icon=KIMI_ICON)


def kimi_notification(stdin_text: str) -> Notification | None:
    """Build a notification for Kimi Code CLI's Notification hook.

    Payload schema: {sink, notification_type, title, body, severity, ...}.
    We forward title/body verbatim and skip events with no body.
    """
    try:
        d = json.loads(stdin_text)
    except json.JSONDecodeError:
        return None
    body = (d.get("body") or "").strip()
    title = (d.get("title") or "Kimi 需要操作").strip()
    if not body:
        return None
    return Notification(title=title, body=summarize(body), icon=KIMI_ICON)


def codex(payload_arg: str) -> Notification | None:
    """Build a notification for the legacy Codex `notify = [...]` payload.

    Kept for users still on the old top-level `notify` field. New installs go
    through `codex_stop` / `codex_permission` which read the richer hook
    payloads via stdin instead.
    """
    try:
        d = json.loads(payload_arg)
    except json.JSONDecodeError:
        return None
    if d.get("type") != "agent-turn-complete":
        return None
    body = d.get("last-assistant-message") or ""
    if body:
        body = summarize(body)
    else:
        body = "Codex turn complete"
    return Notification(title="Codex 完成", body=body, icon=CODEX_ICON)


def codex_stop(stdin_text: str) -> Notification | None:
    """Build a notification for Codex's `[[hooks.Stop]]` payload (stdin JSON).

    Schema (Codex 8+):
        {session_id, transcript_path, cwd, hook_event_name, model,
         permission_mode, turn_id, stop_hook_active, last_assistant_message}
    """
    try:
        d = json.loads(stdin_text)
    except json.JSONDecodeError:
        d = {}
    msg = (d.get("last_assistant_message") or "").strip()
    body = summarize(msg) if msg else "回答完成"
    return Notification(title="Codex 完成", body=body, icon=CODEX_ICON)


def codex_permission(stdin_text: str) -> Notification | None:
    """Build a notification for Codex's `[[hooks.PermissionRequest]]` payload.

    Schema: {tool_name, tool_input (JSON), ...}. tool_input is a free-form
    value, usually a dict that may carry a 'description' field.
    """
    try:
        d = json.loads(stdin_text)
    except json.JSONDecodeError:
        return None
    tool = (d.get("tool_name") or "tool").strip()
    desc = ""
    tin = d.get("tool_input")
    if isinstance(tin, dict):
        desc = (tin.get("description") or "").strip()
    body = f"{tool}{': ' + desc if desc else ''}"
    return Notification(title="Codex 需要权限", body=summarize(body), icon=CODEX_ICON)
