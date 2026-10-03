from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

from app.workspaces import Permission, WorkspaceManager

KNOWN_DIRECTORIES = {
    "downloads": Path.home() / "Downloads",
    "documents": Path.home() / "Documents",
    "desktop": Path.home() / "Desktop",
}

# -------------------------------------------------------------
# SEARCH EXCLUSIONS
# -------------------------------------------------------------
# Directory names that are always skipped during rglob.
# This prevents noise from version-control internals,
# Python virtual environments, macOS app bundles, etc.

EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        ".env",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
    }
)


def _should_skip_path(path: Path) -> bool:
    """
    Return True if a file path falls inside a directory that
    should be excluded from search results.

    Excluded:
    - Directories listed in EXCLUDED_DIR_NAMES.
    - macOS application bundles (any directory ending in '.app').
    """
    for part in path.parts:
        if part in EXCLUDED_DIR_NAMES:
            return True
        if part.endswith(".app"):
            return True
    return False


@tool
def search_files(
    directory: str,
    extension: str = "",
    filename: str = "",
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """Search files by filename, extension, and creation date.

    directory can be Downloads, Documents, Desktop, or a full path.

    filename is optional. If provided, search for that specific filename.

    extension is optional. Examples: .pdf, .txt, .docx.

    start_date and end_date use YYYY-MM-DD format.

    If both dates are empty, search all matching files.
    """

    directory_key = directory.strip().lower()

    ws = WorkspaceManager.get_workspace_by_name(directory_key)
    if ws:
        folder = ws.canonical_path
    elif directory_key in KNOWN_DIRECTORIES:
        folder = KNOWN_DIRECTORIES[directory_key]
    else:
        folder = Path(directory).expanduser()

    if not folder.exists():
        return {
            "found": False,
            "files": [],
            "count": 0,
            "directory": str(folder),
            "filename": filename,
            "extension": extension,
            "start_date": start_date,
            "end_date": end_date,
            "message": f"Directory does not exist: {folder}",
        }

    # Verify workspace READ permission when workspaces are configured
    if WorkspaceManager.count_workspaces() > 0:
        ok, reason, _ = WorkspaceManager.check_workspace_authorization(
            folder, Permission.READ.value
        )
        if not ok:
            return {
                "found": False,
                "files": [],
                "count": 0,
                "directory": str(folder),
                "filename": filename,
                "extension": extension,
                "start_date": start_date,
                "end_date": end_date,
                "message": f"Search blocked: {reason}",
            }

    start = None
    end = None

    if start_date:
        start = datetime.strptime(
            start_date,
            "%Y-%m-%d",
        )

    if end_date:
        end = datetime.strptime(
            end_date,
            "%Y-%m-%d",
        ).replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )

    results = []

    requested_filename = filename.strip().lower()
    requested_extension = extension.strip().lower()

    for file in folder.rglob("*"):
        if not file.is_file():
            continue

        # -------------------------------------------------
        # EXCLUSION FILTER
        # -------------------------------------------------

        if _should_skip_path(file):
            continue

        # -----------------------------------------------------
        # FILENAME FILTER
        # -----------------------------------------------------

        if requested_filename:
            if file.name.lower() != requested_filename:
                continue

        # -----------------------------------------------------
        # EXTENSION FILTER
        # -----------------------------------------------------

        if requested_extension:
            if file.suffix.lower() != requested_extension:
                continue

        # -----------------------------------------------------
        # DATE FILTER
        # -----------------------------------------------------

        stat = file.stat()
        birthtime = getattr(stat, "st_birthtime", None)
        timestamp = birthtime if birthtime is not None else stat.st_ctime
        created_time = datetime.fromtimestamp(timestamp)

        if start and created_time < start:
            continue

        if end and created_time > end:
            continue

        results.append(
            {
                "path": str(file),
                "created": created_time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    return {
        "found": len(results) > 0,
        "count": len(results),
        "directory": str(folder),
        "filename": filename,
        "extension": extension,
        "start_date": start_date,
        "end_date": end_date,
        "files": results,
    }
