"""Agent-side hook installers.

Each `install_*` function writes (or refuses to overwrite) one agent's config
file and returns an :class:`InstallResult` describing what happened. They are
idempotent: running `agentnotify init` twice never doubles up a hook, and they
always back the original file up to the *same directory* before mutating.
"""
from __future__ import annotations

from ._common import InstallResult, InstallStatus
from .claude import install_claude
from .codex import install_codex
from .kimi import install_kimi

__all__ = [
    "InstallResult",
    "InstallStatus",
    "install_claude",
    "install_codex",
    "install_kimi",
]
