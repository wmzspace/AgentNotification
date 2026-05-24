from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from ._common import InstallResult, InstallStatus, backup_file

CODEX_DIR = Path.home() / ".codex"
CONFIG_PATH = CODEX_DIR / "config.toml"


def _agentnotify_bin() -> str:
    """Absolute path to the agentnotify executable.

    Codex spawns hook subprocesses with a stripped PATH (no conda/pyenv
    activation), so bare `agentnotify` may not resolve. Prefer the binary we
    were invoked through, then fall back to a PATH lookup, then to the bare
    name as a last resort.
    """
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


def _toml_basic_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _stop_block(bin_path: str) -> str:
    bin_esc = _toml_basic_escape(bin_path)
    return f"""\
[[hooks.Stop]]

[[hooks.Stop.hooks]]
type = "command"
command = "{bin_esc} hook codex-stop 2>/dev/null || true"
timeout = 30
"""


def _perm_block(bin_path: str) -> str:
    bin_esc = _toml_basic_escape(bin_path)
    return f"""\
[[hooks.PermissionRequest]]

[[hooks.PermissionRequest.hooks]]
type = "command"
command = "{bin_esc} hook codex-permission 2>/dev/null || true"
timeout = 30
"""


_FEATURES_HEADER_RE = re.compile(r"^\[features\]\s*$", re.MULTILINE)
_CODEX_HOOKS_LINE_RE = re.compile(r"^codex_hooks\s*=.*$", re.MULTILINE)
_HOOKS_LINE_RE = re.compile(r"^hooks\s*=.*$", re.MULTILINE)


def _ensure_features_hooks(text: str) -> tuple[str, str]:
    """Force `[features].hooks = true` (drop the deprecated `codex_hooks` alias).

    Codex 0.133+ honors only `[features].hooks`; older `codex_hooks = true`
    silently does nothing, so hook tables are scanned (and even trust-hashed
    in `[hooks.state]`) but events never route to them. This is the line
    between "installer wrote the table" and "hook actually fires".

    Returns (new_text, note). `note` is the empty string when nothing changed.
    """
    notes: list[str] = []

    if _CODEX_HOOKS_LINE_RE.search(text):
        text = _CODEX_HOOKS_LINE_RE.sub("", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        notes.append("removed deprecated [features].codex_hooks")

    m = _HOOKS_LINE_RE.search(text)
    if m:
        if not re.search(r"=\s*true\b", m.group(0)):
            text = _HOOKS_LINE_RE.sub("hooks = true", text, count=1)
            notes.append("forced [features].hooks = true")
    else:
        if _FEATURES_HEADER_RE.search(text):
            text = _FEATURES_HEADER_RE.sub("[features]\nhooks = true", text, count=1)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += "\n[features]\nhooks = true\n"
        notes.append("enabled [features].hooks = true")

    return text, "; ".join(notes)


def _repath_command(text: str, suffix: str, bin_path: str) -> tuple[str, bool]:
    """Rewrite any `command = "<x> hook <suffix> …"` line to use bin_path.

    Returns (new_text, changed). Only changes lines whose binary doesn't already
    match bin_path, so this is safely idempotent.
    """
    bin_esc = _toml_basic_escape(bin_path)
    correct = f'command = "{bin_esc} hook {suffix} 2>/dev/null || true"'
    pattern = re.compile(
        r'^command\s*=\s*"[^"]*hook ' + re.escape(suffix) + r'[^"]*"\s*$',
        re.MULTILINE,
    )

    changed = False

    def _sub(m: re.Match) -> str:
        nonlocal changed
        if m.group(0).strip() == correct:
            return m.group(0)
        changed = True
        return correct

    new = pattern.sub(_sub, text)
    return new, changed


def install_codex() -> InstallResult:
    target = CONFIG_PATH
    if not CODEX_DIR.exists():
        return InstallResult(
            agent="codex",
            status=InstallStatus.NO_AGENT,
            target=target,
            detail="~/.codex/ missing — install Codex CLI first",
        )

    bin_path = _agentnotify_bin()
    existing = target.read_text() if target.exists() else ""

    has_stop = "hook codex-stop" in existing
    has_perm = "hook codex-permission" in existing

    fixed_text, features_note = _ensure_features_hooks(existing)

    notes: list[str] = []
    if features_note:
        notes.append(features_note)

    # Rewrite any already-injected command lines whose binary path is stale
    # (most often: bare `agentnotify` from an earlier version of this tool,
    # which Codex's stripped-PATH subprocess can't actually find).
    if has_stop:
        fixed_text, repathed = _repath_command(fixed_text, "codex-stop", bin_path)
        if repathed:
            notes.append("rewrote codex-stop command to absolute path")
    if has_perm:
        fixed_text, repathed = _repath_command(fixed_text, "codex-permission", bin_path)
        if repathed:
            notes.append("rewrote codex-permission command to absolute path")

    needs_inject = (not has_stop) or (not has_perm)
    anything_changed = needs_inject or bool(notes)

    if not anything_changed:
        return InstallResult(
            agent="codex",
            status=InstallStatus.ALREADY_PRESENT,
            target=target,
        )

    backup = backup_file(target) if target.exists() else None

    blocks: list[str] = []
    if not has_stop:
        blocks.append(_stop_block(bin_path).rstrip())
    if not has_perm:
        blocks.append(_perm_block(bin_path).rstrip())

    body = fixed_text.rstrip()
    if blocks:
        if body:
            body += "\n\n"
        body += "# Added by agentnotify init\n"
        body += "\n\n".join(blocks)
    body = body.rstrip() + "\n"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)

    return InstallResult(
        agent="codex",
        status=InstallStatus.INSTALLED,
        target=target,
        backup=backup,
        detail="; ".join(notes),
    )
