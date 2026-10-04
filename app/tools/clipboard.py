"""
Clipboard inspection and modification tools for Milestone 7.

Provides controlled, cross-platform clipboard reading and writing with graceful
fallback support for headless or container environments.
"""

from __future__ import annotations

import subprocess
import sys

_IN_MEMORY_CLIPBOARD: str = ""

try:
    import pyperclip
except ImportError:  # pragma: no cover
    pyperclip = None  # type: ignore[assignment]


def read_clipboard() -> str:
    """
    Read the current text from the system clipboard.

    Returns:
        str: Current clipboard text, or empty string if clipboard cannot be accessed.
    """
    if pyperclip is not None:
        try:
            val = pyperclip.paste()
            if isinstance(val, str):
                return val
        except Exception:
            pass

    # Platform native fallbacks
    if sys.platform == "win32":
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0:
                return res.stdout.rstrip("\r\n")
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                return res.stdout
        except Exception:
            pass

    return _IN_MEMORY_CLIPBOARD


def write_clipboard(text: str) -> bool:
    """
    Write text to the system clipboard.

    Args:
        text: String content to write.

    Returns:
        bool: True if writing succeeded or fallback was stored.
    """
    global _IN_MEMORY_CLIPBOARD
    _IN_MEMORY_CLIPBOARD = str(text)

    if pyperclip is not None:
        try:
            pyperclip.copy(str(text))
            return True
        except Exception:
            pass

    if sys.platform == "win32":
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
                input=str(text),
                text=True,
                timeout=3,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            res = subprocess.run(["pbcopy"], input=str(text), text=True, timeout=3)
            if res.returncode == 0:
                return True
        except Exception:
            pass

    return True
