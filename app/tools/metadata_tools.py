"""
Structured file metadata inspection tools for Milestone 7.

Provides detailed, controlled file inspection including MIME type detection,
cryptographic hashes (SHA-256, MD5), filesystem timestamps, and permissions.
"""

from __future__ import annotations

import datetime
import hashlib
import mimetypes
import stat
from pathlib import Path
from typing import Any


def _format_size(size_bytes: int) -> str:
    """Format bytes into human-readable representation."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / (1024**2):.2f} MB"
    else:
        return f"{size_bytes / (1024**3):.2f} GB"


def get_file_metadata(file_path: str | Path, compute_hashes: bool = True) -> dict[str, Any]:
    """
    Retrieve rich structured metadata for a file.

    Args:
        file_path: Path to target file.
        compute_hashes: Whether to compute SHA-256 and MD5 checksums.

    Returns:
        dict: Metadata dictionary.
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    st = path.stat()
    mime_type, encoding = mimetypes.guess_type(str(path))

    sha256_hash = ""
    md5_hash = ""
    line_count = None

    if path.is_file() and compute_hashes:
        sha256 = hashlib.sha256()
        md5 = hashlib.md5()
        try:
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    sha256.update(chunk)
                    md5.update(chunk)
            sha256_hash = sha256.hexdigest()
            md5_hash = md5.hexdigest()
        except Exception:
            pass

        # If text-based file, attempt to count lines
        is_text_type = mime_type and (
            "text" in mime_type or mime_type in ("application/json", "application/javascript")
        )
        if is_text_type:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    line_count = sum(1 for _ in f)
            except Exception:
                pass

    created_iso = datetime.datetime.fromtimestamp(st.st_ctime, tz=datetime.timezone.utc).isoformat()
    modified_iso = datetime.datetime.fromtimestamp(
        st.st_mtime, tz=datetime.timezone.utc
    ).isoformat()
    accessed_iso = datetime.datetime.fromtimestamp(
        st.st_atime, tz=datetime.timezone.utc
    ).isoformat()

    return {
        "path": str(path),
        "name": path.name,
        "extension": path.suffix.lower(),
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
        "is_symlink": path.is_symlink(),
        "size_bytes": st.st_size,
        "human_size": _format_size(st.st_size),
        "mime_type": mime_type or "application/octet-stream",
        "encoding": encoding,
        "created_at": created_iso,
        "modified_at": modified_iso,
        "accessed_at": accessed_iso,
        "permissions_octal": oct(stat.S_IMODE(st.st_mode)),
        "sha256": sha256_hash,
        "md5": md5_hash,
        "line_count": line_count,
    }
