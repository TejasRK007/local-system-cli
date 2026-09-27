from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

KNOWN_DIRECTORIES = {
    "downloads": Path.home() / "Downloads",
    "documents": Path.home() / "Documents",
    "desktop": Path.home() / "Desktop",
}


def _get_file_creation_time(file: Path) -> datetime:
    """Return file creation time cross-platform.

    macOS exposes st_birthtime (true creation time).
    Linux only has st_ctime (inode change time) as the closest equivalent.
    """
    stat = file.stat()
    timestamp = getattr(stat, "st_birthtime", None) or stat.st_ctime
    return datetime.fromtimestamp(timestamp)  # noqa: DTZ006


@tool
def search_files(
    directory: str,
    extension: str,
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """Search files by extension and creation date.

directory can be Downloads, Documents, Desktop, or a full path.

If the user does not specify a directory for a file-search request,
use Downloads.

start_date and end_date use YYYY-MM-DD format.

If both dates are empty, search all matching files.
"""

    directory_key = directory.strip().lower()

    if directory_key in KNOWN_DIRECTORIES:
        folder = KNOWN_DIRECTORIES[directory_key]
    else:
        folder = Path(directory).expanduser()

    if not folder.exists():
        return {
            "found": False,
            "files": [],
            "message": f"Directory does not exist: {folder}",
        }

    start = None
    end = None

    if start_date:
        start = datetime.strptime(start_date, "%Y-%m-%d")  # noqa: DTZ007

    if end_date:
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(  # noqa: DTZ007
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )

    results = []

    for file in folder.rglob(f"*{extension}"):
        if not file.is_file():
            continue

        created_time = _get_file_creation_time(file)

        if start and created_time < start:
            continue

        if end and created_time > end:
            continue

        results.append({
            "path": str(file),
            "created": created_time.strftime("%Y-%m-%d %H:%M:%S"),
        })

    return {
        "found": len(results) > 0,
        "count": len(results),
        "directory": str(folder),
        "extension": extension,
        "start_date": start_date,
        "end_date": end_date,
        "files": results,
    }
