from pathlib import Path


ALLOWED_DIRECTORIES = [
    Path.home() / "Downloads",
    Path.home() / "Documents",
    Path.home() / "Desktop",
]


def is_allowed_path(file_path: Path) -> bool:
    """Check that the file is inside an allowed directory."""

    try:
        resolved_path = file_path.resolve()

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

    if not is_allowed_path(path):
        return f"Deletion blocked: file is outside allowed directories: {path}"

    path.unlink()

    if path.exists():
        return f"Deletion failed: {path} still exists."

    return f"Verified: {path} was deleted successfully."