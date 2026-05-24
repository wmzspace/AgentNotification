from __future__ import annotations

import re
import shutil
import sys
import tomllib
from pathlib import Path

from ._common import InstallResult, InstallStatus, backup_file

KIMI_DIR = Path.home() / ".kimi"
CONFIG_PATH = KIMI_DIR / "config.toml"


def _agentnotify_bin() -> str:
    """Absolute path to agentnotify; Kimi's hook subprocesses (like Codex's)
    don't inherit conda / pyenv activation."""
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


def _toml_str_esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _find_hooks_array_span(text: str) -> tuple[int, int] | None:
    """Find the textual span of a top-level `hooks = [...]` array literal.

    Returns (start, end) covering the full `hooks = [...]` statement, with
    correct bracket balancing so multi-line arrays are handled. None if no
    such top-level assignment exists or the value isn't a `[` literal.
    """
    m = re.search(r"^hooks\s*=\s*", text, re.MULTILINE)
    if not m:
        return None
    start = m.start()
    i = m.end()
    if i >= len(text) or text[i] != "[":
        return None  # hooks = something-other-than-array; out of scope
    depth = 0
    in_str: str | None = None
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\" and i + 1 < len(text):
                i += 2
                continue
            if c == in_str:
                in_str = None
        else:
            if c in ('"', "'"):
                in_str = c
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return (start, i + 1)
        i += 1
    return None


# Match the broken [[hooks]] blocks our prior installer wrote.
_OLD_HOOKS_BLOCK_RE = re.compile(
    r"\n*\[\[hooks\]\]\s*\n"
    r"(?:[^\[\n]*\n)*?"
    r"command\s*=\s*\"[^\"]*agentnotify hook kimi-[^\"]*\"\s*\n"
    r"(?:[^\[\n]*\n)*",
    re.MULTILINE,
)


def _render_hooks_array(entries: list[dict]) -> str:
    if not entries:
        return "hooks = []"
    lines = ["hooks = ["]
    for ent in entries:
        ev = _toml_str_esc(str(ent.get("event", "")))
        cmd = _toml_str_esc(str(ent.get("command", "")))
        to = ent.get("timeout", 10)
        matcher = ent.get("matcher")
        parts = [f'event = "{ev}"', f'command = "{cmd}"', f'timeout = {to}']
        if matcher:
            parts.insert(1, f'matcher = "{_toml_str_esc(str(matcher))}"')
        lines.append(f'    {{ {", ".join(parts)} }},')
    lines.append("]")
    return "\n".join(lines)


def install_kimi() -> InstallResult:
    target = CONFIG_PATH
    if not KIMI_DIR.exists():
        return InstallResult(
            agent="kimi",
            status=InstallStatus.NO_AGENT,
            target=target,
            detail="~/.kimi/ missing — install Kimi Code CLI first",
        )

    existing = target.read_text(encoding="utf-8") if target.exists() else ""

    # The "broken" state we most need to recover from is the one we ourselves
    # created in an earlier release: a top-level `hooks = []` AND `[[hooks]]`
    # array-of-tables collide and make the whole file invalid TOML. Strip our
    # own [[hooks]] blocks via text-level scan first, then parse.
    has_broken_blocks = bool(_OLD_HOOKS_BLOCK_RE.search(existing))
    pre_clean = existing
    if has_broken_blocks:
        pre_clean = _OLD_HOOKS_BLOCK_RE.sub("\n", pre_clean)
        pre_clean = re.sub(
            r"\n#\s*Added by agentnotify init\s*\n",
            "\n",
            pre_clean,
        )
        pre_clean = re.sub(r"\n{3,}", "\n\n", pre_clean)

    try:
        parsed = tomllib.loads(pre_clean) if pre_clean.strip() else {}
    except tomllib.TOMLDecodeError as e:
        return InstallResult(
            agent="kimi",
            status=InstallStatus.NO_AGENT,
            target=target,
            detail=f"existing config has TOML error we can't auto-fix: {e}",
        )

    current = parsed.get("hooks", [])
    if not isinstance(current, list):
        return InstallResult(
            agent="kimi",
            status=InstallStatus.NO_AGENT,
            target=target,
            detail="`hooks` key exists but isn't a list — clean up ~/.kimi/config.toml manually",
        )

    bin_path = _agentnotify_bin()
    # Quote bin_path so paths with spaces survive shell parsing on every
    # platform. No `2>/dev/null || true` tail — `cmd_hook` already swallows
    # errors and that tail is POSIX-only (Windows cmd has neither).
    stop_cmd = f'"{bin_path}" hook kimi-stop'
    notif_cmd = f'"{bin_path}" hook kimi-notification'

    kept: list[dict] = []
    has_correct_stop = False
    has_correct_notif = False
    for ent in current:
        if not isinstance(ent, dict):
            continue
        cmd = str(ent.get("command", ""))
        if "agentnotify hook kimi-stop" in cmd:
            if cmd == stop_cmd:
                has_correct_stop = True
                kept.append(ent)
            # else: stale path / format, drop and re-add fresh
            continue
        if "agentnotify hook kimi-notification" in cmd:
            if cmd == notif_cmd:
                has_correct_notif = True
                kept.append(ent)
            continue
        kept.append(ent)

    if has_correct_stop and has_correct_notif and not has_broken_blocks:
        return InstallResult(
            agent="kimi",
            status=InstallStatus.ALREADY_PRESENT,
            target=target,
        )

    if not has_correct_stop:
        kept.append({"event": "Stop", "command": stop_cmd, "timeout": 10})
    if not has_correct_notif:
        kept.append({"event": "Notification", "command": notif_cmd, "timeout": 10})

    backup = backup_file(target) if target.exists() else None

    # `pre_clean` already has the broken [[hooks]] blocks stripped (and is
    # known-valid TOML from above), so we can work on it directly.
    new_text = pre_clean

    rendered = _render_hooks_array(kept)

    span = _find_hooks_array_span(new_text)
    if span is not None:
        new_text = new_text[: span[0]] + rendered + new_text[span[1] :]
    else:
        new_text = new_text.rstrip() + "\n\n" + rendered + "\n"

    # Validate before persisting — never leave Kimi with broken TOML.
    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as e:
        return InstallResult(
            agent="kimi",
            status=InstallStatus.NO_AGENT,
            target=target,
            detail=f"refused to write — would produce invalid TOML: {e}",
        )

    if not new_text.endswith("\n"):
        new_text += "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_text, encoding="utf-8")

    notes = ["rewrote top-level `hooks = [...]` (Kimi rejects [[hooks]] when `hooks` is already a scalar)"]
    if has_broken_blocks:
        notes.append("removed earlier broken [[hooks]] blocks")
    return InstallResult(
        agent="kimi",
        status=InstallStatus.INSTALLED,
        target=target,
        backup=backup,
        detail="; ".join(notes),
    )
