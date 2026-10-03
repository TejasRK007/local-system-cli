import shutil
from pathlib import Path
from typing import Optional

from app.workspaces import Permission, WorkspaceManager

ALLOWED_DIRECTORIES = [
    Path.home() / "Downloads",
    Path.home() / "Documents",
    Path.home() / "Desktop",
]


def is_allowed_path(file_path: Path, permission: Optional[str] = None) -> bool:
    """
    Check that a path is inside an authorized workspace with required permission.

    Primary authorization: configured, enabled workspaces in WorkspaceManager.
    Backward compatibility: falls back to ALLOWED_DIRECTORIES only when
    no workspaces are configured in the system.
    """
    try:
        resolved_path = file_path.resolve()

        # Primary authorization: WorkspaceManager
        if WorkspaceManager.count_workspaces() > 0:
            perm = permission if permission is not None else Permission.READ.value
            ok, _, _ = WorkspaceManager.check_workspace_authorization(resolved_path, perm)
            return ok

        # Fallback to ALLOWED_DIRECTORIES only when no workspaces are configured
        for allowed_directory in ALLOWED_DIRECTORIES:
            allowed_path = allowed_directory.resolve()
            if resolved_path.is_relative_to(allowed_path):
                return True

        return False

    except Exception:
        return False


def delete_file(file_path: str) -> str:
    """Delete one specific file after safety validation."""
    path = Path(file_path).expanduser()

    if not path.exists():
        return f"File does not exist: {path}"

    if not path.is_file():
        return f"Not a file: {path}"

    if not is_allowed_path(path, permission=Permission.DELETE.value):
        return (
            f"Deletion blocked: file is outside allowed"
            f" directories or lacks DELETE permission: {path}"
        )

    path.unlink()

    if path.exists():
        return f"Deletion failed: {path} still exists."

    return f"Verified: {path} was deleted successfully."


def move_file(source_path: str, destination_directory: str) -> str:
    """Move one specific file to an allowed destination directory."""
    source = Path(source_path).expanduser()
    destination = Path(destination_directory).expanduser()

    if not source.exists():
        return f"Source file does not exist: {source}"

    if not source.is_file():
        return f"Source path is not a file: {source}"

    if not is_allowed_path(source, permission=Permission.READ.value):
        return (
            f"Move blocked: source file is outside allowed"
            f" directories or lacks READ permission: {source}"
        )

    if not destination.exists():
        return f"Destination directory does not exist: {destination}"

    if not destination.is_dir():
        return f"Destination is not a directory: {destination}"

    if not is_allowed_path(destination, permission=Permission.WRITE.value):
        return (
            f"Move blocked: destination is outside allowed directories or lacks WRITE permission: "
            f"{destination}"
        )

    target = destination / source.name

    if target.exists():
        return f"Move blocked: a file with the same name already exists at: {target}"

    try:
        shutil.move(str(source), str(target))

    except Exception as error:
        return f"Move failed: {error}"

    if source.exists():
        return f"Move verification failed: source still exists: {source}"

    if not target.exists():
        return f"Move verification failed: destination file does not exist: {target}"

    return f"Verified: file moved successfully.\nFrom: {source}\nTo: {target}"


def rename_file(file_path: str, new_name: str) -> str:
    """Rename one specific file after safety validation."""
    path = Path(file_path).expanduser()

    if not path.exists():
        return f"File does not exist: {path}"

    if not path.is_file():
        return f"Not a file: {path}"

    if not is_allowed_path(path, permission=Permission.WRITE.value):
        return (
            f"Rename blocked: file is outside allowed directories or lacks WRITE permission: {path}"
        )

    new_name = new_name.strip()

    if not new_name:
        return "Rename blocked: new filename cannot be empty."

    if "/" in new_name or "\\" in new_name:
        return "Rename blocked: new name must be a filename only."

    target = path.parent / new_name

    if target.exists():
        return f"Rename blocked: a file with the same name already exists at: {target}"

    try:
        path.rename(target)

    except Exception as error:
        return f"Rename failed: {error}"

    if path.exists():
        return f"Rename verification failed: old file still exists: {path}"

    if not target.exists():
        return f"Rename verification failed: new file does not exist: {target}"

    return (
        f"Verified: file renamed successfully.\n"
        f"From: {path.name}\n"
        f"To: {target.name}\n"
        f"Path: {target}"
    )


def create_directory(directory_path: str) -> str:
    """
    Create a directory inside an allowed workspace with WRITE permission.

    Canonicalizes the path, checks workspace containment, enforces WRITE
    permission, rejects traversal and system folders, and physically verifies
    directory creation.
    """
    path = Path(directory_path).expanduser().resolve()

    # Reject entire drive root (e.g. C:\ or /)
    if path == Path(path.anchor) or len(path.parts) <= 1:
        return f"Directory creation blocked: cannot target drive root: {path}"

    # Reject Windows system directories
    import os

    windows_dir = os.environ.get("SystemRoot", "C:\\Windows").lower()
    prog_files = os.environ.get("ProgramFiles", "C:\\Program Files").lower()
    prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)").lower()
    p_str = str(path).lower()
    for sys_path in (windows_dir, prog_files, prog_files_x86):
        if (
            p_str == sys_path
            or p_str.startswith(sys_path + "\\")
            or p_str.startswith(sys_path + "/")
        ):
            return f"Directory creation blocked: cannot target protected system directory: {path}"

    # Verify workspace containment and WRITE permission
    if not is_allowed_path(path, permission=Permission.WRITE.value):
        return (
            f"Directory creation blocked: path is outside allowed directories or lacks WRITE "
            f"permission: {path}"
        )

    # Check if a file (not directory) already exists at path
    if path.exists() and not path.is_dir():
        return f"Directory creation blocked: a file already exists at: {path}"

    # Idempotent: already exists as a directory
    if path.exists() and path.is_dir():
        return f"Verified: directory already exists.\nPath: {path}"

    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as error:
        return f"Directory creation failed: {error}"

    if not path.exists() or not path.is_dir():
        return f"Directory creation verification failed: directory does not exist: {path}"

    return f"Verified: directory created successfully.\nPath: {path}"
