import shutil
from pathlib import Path

ALLOWED_DIRECTORIES = [
    Path.home() / "Downloads",
    Path.home() / "Documents",
    Path.home() / "Desktop",
]


def is_allowed_path(file_path: Path) -> bool:
    """Check that a path is inside one of the allowed directories."""
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
        return (
            f"Deletion blocked: file is outside allowed directories: {path}"
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

    if not is_allowed_path(source):
        return (
            f"Move blocked: source file is outside allowed directories: {source}"
        )

    if not destination.exists():
        return f"Destination directory does not exist: {destination}"

    if not destination.is_dir():
        return f"Destination is not a directory: {destination}"

    if not is_allowed_path(destination):
        return (
            f"Move blocked: destination is outside allowed directories: "
            f"{destination}"
        )

    target = destination / source.name

    if target.exists():
        return (
            f"Move blocked: a file with the same name "
            f"already exists at: {target}"
        )

    try:
        shutil.move(str(source), str(target))

    except Exception as error:
        return f"Move failed: {error}"

    if source.exists():
        return (
            f"Move verification failed: source still exists: {source}"
        )

    if not target.exists():
        return (
            f"Move verification failed: destination file "
            f"does not exist: {target}"
        )

    return (
        f"Verified: file moved successfully.\n"
        f"From: {source}\n"
        f"To: {target}"
    )


def rename_file(file_path: str, new_name: str) -> str:
    """Rename one specific file after safety validation."""
    path = Path(file_path).expanduser()

    if not path.exists():
        return f"File does not exist: {path}"

    if not path.is_file():
        return f"Not a file: {path}"

    if not is_allowed_path(path):
        return (
            f"Rename blocked: file is outside allowed directories: {path}"
        )

    new_name = new_name.strip()

    if not new_name:
        return "Rename blocked: new filename cannot be empty."

    if "/" in new_name or "\\" in new_name:
        return "Rename blocked: new name must be a filename only."

    target = path.parent / new_name

    if target.exists():
        return (
            f"Rename blocked: a file with the same name "
            f"already exists at: {target}"
        )

    try:
        path.rename(target)

    except Exception as error:
        return f"Rename failed: {error}"

    if path.exists():
        return (
            f"Rename verification failed: old file still exists: {path}"
        )

    if not target.exists():
        return (
            f"Rename verification failed: new file does not exist: {target}"
        )

    return (
        f"Verified: file renamed successfully.\n"
        f"From: {path.name}\n"
        f"To: {target.name}\n"
        f"Path: {target}"
    )
