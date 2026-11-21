"""
Cloudflare Quick Tunnel Service.
Automates creating zero-config, encrypted public HTTPS tunnels via cloudflared
so external mobile devices can scan QR codes and access attendance/web portals
from outside the local Wi-Fi network (e.g. mobile 4G/5G data).
"""

from __future__ import annotations

import atexit
import logging
import os
import re
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_tunnel_lock = threading.RLock()
_tunnel_proc: Optional[subprocess.Popen] = None
_tunnel_url: Optional[str] = None
_tunnel_thread: Optional[threading.Thread] = None
_url_ready_event = threading.Event()


def find_cloudflared_binary() -> Optional[str]:
    """Locate the cloudflared executable in project directories or system PATH."""
    project_root = Path(__file__).resolve().parent.parent
    local_candidates = [
        project_root / "cloudflared.exe",
        project_root / "cloudflared",
        project_root / "bin" / "cloudflared.exe",
        Path(__file__).resolve().parent / "cloudflared.exe",
    ]
    for cand in local_candidates:
        if cand.is_file() and os.access(str(cand), os.X_OK | os.R_OK):
            return str(cand)

    which_path = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
    if which_path:
        return which_path

    return None


def is_tunnel_running() -> bool:
    """Return True if a Cloudflare tunnel subprocess is currently active."""
    global _tunnel_proc
    return _tunnel_proc is not None and _tunnel_proc.poll() is None


def get_tunnel_url() -> Optional[str]:
    """Return the active public trycloudflare.com URL, or None."""
    global _tunnel_url
    if is_tunnel_running():
        return _tunnel_url
    return None


def get_tunnel_status() -> Dict[str, Any]:
    """Return the current status of the Cloudflare tunnel service."""
    binary = find_cloudflared_binary()
    running = is_tunnel_running()
    url = _tunnel_url if running else None
    return {
        "installed": binary is not None,
        "binary_path": binary,
        "active": running,
        "url": url,
    }


def _read_tunnel_output(proc: subprocess.Popen) -> None:
    """Background reader thread to parse trycloudflare.com URL from cloudflared stderr."""
    global _tunnel_url
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    try:
        if proc.stderr is None:
            return
        for line in iter(proc.stderr.readline, ""):
            if not line:
                break
            line_str = line.strip()
            match = url_pattern.search(line_str)
            if match:
                _tunnel_url = match.group(0)
                _url_ready_event.set()
                logger.info(f"Cloudflare Tunnel active: {_tunnel_url}")
    except Exception as e:
        logger.debug(f"Cloudflare tunnel reader finished: {e}")
    finally:
        _url_ready_event.set()


def start_cloudflare_tunnel(port: int = 8000, timeout: float = 14.0) -> Optional[str]:
    """
    Launch cloudflared quick tunnel to forward traffic to http://127.0.0.1:{port}.
    Blocks until the public trycloudflare.com URL is ready (or timeout is reached).
    """
    global _tunnel_proc, _tunnel_url, _tunnel_thread, _url_ready_event

    with _tunnel_lock:
        if is_tunnel_running() and _tunnel_url:
            return _tunnel_url

        binary = find_cloudflared_binary()
        if not binary:
            logger.warning("cloudflared executable not found.")
            return None

        # Clean up any stale process
        stop_cloudflare_tunnel()

        _tunnel_url = None
        _url_ready_event.clear()

        cmd = [binary, "tunnel", "--url", f"http://127.0.0.1:{port}"]
        try:
            # On Windows, hide command window when spawned as child
            creation_flags = 0
            if os.name == "nt":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

            _tunnel_proc = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                creationflags=creation_flags,
            )

            _tunnel_thread = threading.Thread(
                target=_read_tunnel_output,
                args=(_tunnel_proc,),
                daemon=True,
            )
            _tunnel_thread.start()

        except Exception as exc:
            logger.error(f"Failed to start cloudflared process: {exc}")
            _tunnel_proc = None
            return None

    # Wait outside lock for tunnel URL to arrive
    _url_ready_event.wait(timeout=timeout)

    with _tunnel_lock:
        if _tunnel_url and is_tunnel_running():
            return _tunnel_url
        if not _tunnel_url:
            logger.warning("Cloudflare tunnel started but URL discovery timed out.")
        return _tunnel_url


def stop_cloudflare_tunnel() -> bool:
    """Terminate the active Cloudflare tunnel subprocess."""
    global _tunnel_proc, _tunnel_url

    with _tunnel_lock:
        proc = _tunnel_proc
        _tunnel_proc = None
        _tunnel_url = None

        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
                return True
            except Exception as e:
                logger.warning(f"Error terminating cloudflared: {e}")
                return False
        return False


# Register exit cleanup
atexit.register(stop_cloudflare_tunnel)
