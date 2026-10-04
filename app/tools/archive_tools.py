"""
Archive inspection and safe extraction tools for Milestone 7.

Provides controlled archive inspection and extraction with strict Zip Slip
path-traversal protection.
"""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path
from typing import Any


def _is_zip_file(path: Path) -> bool:
    return path.suffix.lower() == ".zip" or zipfile.is_zipfile(path)


def _is_tar_file(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(ext) for ext in [".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2"])


def inspect_archive(archive_path: str | Path) -> dict[str, Any]:
    """
    Inspect an archive file and list its members without extracting.

    Args:
        archive_path: Path to archive file (.zip, .tar, .tar.gz).

    Returns:
        dict: Archive details (type, total_files, total_uncompressed_bytes, members).
    """
    path = Path(archive_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Archive file not found: {path}")

    members = []
    total_uncompressed = 0

    if _is_zip_file(path):
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                is_dir = info.is_dir()
                members.append(
                    {
                        "filename": info.filename,
                        "size_bytes": info.file_size,
                        "compressed_bytes": info.compress_size,
                        "is_dir": is_dir,
                    }
                )
                if not is_dir:
                    total_uncompressed += info.file_size
        archive_type = "zip"
    elif _is_tar_file(path) or tarfile.is_tarfile(path):
        with tarfile.open(path, "r:*") as tf:
            for m in tf.getmembers():
                is_dir = m.isdir()
                members.append(
                    {
                        "filename": m.name,
                        "size_bytes": m.size,
                        "compressed_bytes": m.size,
                        "is_dir": is_dir,
                    }
                )
                if not is_dir:
                    total_uncompressed += m.size
        archive_type = "tar"
    else:
        raise ValueError(f"Unsupported archive format: {path.name}")

    return {
        "archive_path": str(path),
        "archive_type": archive_type,
        "total_members": len(members),
        "total_files": len([m for m in members if not m["is_dir"]]),
        "total_uncompressed_bytes": total_uncompressed,
        "members": members,
    }


def extract_archive(archive_path: str | Path, target_dir: str | Path) -> dict[str, Any]:
    """
    Safely extract an archive into target_dir with strict Zip Slip protection.

    Args:
        archive_path: Path to archive.
        target_dir: Destination directory.

    Returns:
        dict: Extraction report with extracted file paths.
    """
    src = Path(archive_path).expanduser().resolve()
    dest = Path(target_dir).expanduser().resolve()

    if not src.exists():
        raise FileNotFoundError(f"Archive not found: {src}")

    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()

    extracted_files: list[str] = []

    if _is_zip_file(src):
        with zipfile.ZipFile(src, "r") as zf:
            # 1. Validation phase (Zip Slip check)
            for member_name in zf.namelist():
                target_path = (dest / member_name).resolve()
                try:
                    target_path.relative_to(dest_resolved)
                except ValueError:
                    raise PermissionError(
                        f"Zip Slip attack detected in member '{member_name}': "
                        f"targets outside {dest_resolved}"
                    )

            # 2. Safe extraction phase
            for member_info in zf.infolist():
                target_path = (dest / member_info.filename).resolve()
                if member_info.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member_info) as source, open(target_path, "wb") as target:
                        target.write(source.read())
                    extracted_files.append(str(target_path))

    elif _is_tar_file(src) or tarfile.is_tarfile(src):
        with tarfile.open(src, "r:*") as tf:
            for tar_m in tf.getmembers():
                target_path = (dest / tar_m.name).resolve()
                try:
                    target_path.relative_to(dest_resolved)
                except ValueError:
                    raise PermissionError(
                        f"Zip Slip attack detected in member '{tar_m.name}': "
                        f"targets outside {dest_resolved}"
                    )

            for tar_m in tf.getmembers():
                target_path = (dest / tar_m.name).resolve()
                if tar_m.isdir():
                    target_path.mkdir(parents=True, exist_ok=True)
                elif tar_m.isfile():
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    fobj = tf.extractfile(tar_m)
                    if fobj:
                        with open(target_path, "wb") as target:
                            target.write(fobj.read())
                        extracted_files.append(str(target_path))
    else:
        raise ValueError(f"Unsupported archive format: {src.name}")

    # Physical verification
    verified = [f for f in extracted_files if Path(f).exists()]

    return {
        "archive_path": str(src),
        "target_directory": str(dest_resolved),
        "extracted_count": len(verified),
        "extracted_files": verified,
    }
