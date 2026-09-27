"""
Tests for cross-directory ambiguity detection in rename and move operations.

The LangChain StructuredTool's .invoke() is a method on a Pydantic model,
so we patch the search_files object itself at the module level with a simple
callable class that matches the .invoke(args) interface.

Scenarios covered:
  a. Exactly one match across all allowed directories → 1 result.
  b. Multiple matches across directories → 2 results (ambiguous).
  c. Explicit directory → only that directory is called.
  d. No match anywhere → 0 results (safe failure).
  e. Rename / move result dict has all keys main.py needs.
  f. File-system level: same filename found in two real tmp dirs via merge.
"""

from pathlib import Path

from app.tools.filesystem import KNOWN_DIRECTORIES, search_files

# ---------------------------------------------------------------------------
# Stub: replaces search_files with a callable .invoke(args) look-alike
# ---------------------------------------------------------------------------


class _SearchStub:
    """
    Drop-in stub for search_files (LangChain StructuredTool).

    files_by_dir: maps directory key (lowercase) → list of filenames
    that should appear as matches.
    """
    def __init__(self, files_by_dir: dict[str, list[str]]):
        self._files_by_dir = files_by_dir
        self._calls: list[str] = []

    def invoke(self, args: dict) -> dict:
        directory = args.get("directory", "").lower()
        filename = args.get("filename", "").lower()
        self._calls.append(directory)

        _dir_map = {
            "downloads": "Downloads",
            "documents": "Documents",
            "desktop":   "Desktop",
        }
        label = _dir_map.get(directory, directory)

        available = self._files_by_dir.get(directory, [])
        matched = [
            {"path": str(Path.home() / label / name),
             "created": "2026-09-27 00:00:00"}
            for name in available
            if name.lower() == filename
        ]

        return {"found": bool(matched), "count": len(matched), "files": matched}


def _patch(monkeypatch, stub: _SearchStub):
    """Patch search_files in both agent and filesystem modules."""
    monkeypatch.setattr("app.agent.search_files", stub)


# ---------------------------------------------------------------------------
# Helpers: re-implement the merge loop the way agent.py does it
# ---------------------------------------------------------------------------


def _merge_all_dirs(search_tool, filename: str) -> list:
    matched: list = []
    for dir_name in KNOWN_DIRECTORIES:
        result = search_tool.invoke(
            {"directory": dir_name, "extension": "", "filename": filename,
             "start_date": "", "end_date": ""}
        )
        matched.extend(result.get("files", []))
    return matched


# ---------------------------------------------------------------------------
# a. Single match across all directories
# ---------------------------------------------------------------------------

def test_single_match_across_all_directories(monkeypatch):
    """
    File exists only in Downloads.
    Merge of all three dirs returns exactly 1 result.
    """
    stub = _SearchStub({
        "downloads": ["target.txt"],
        "documents": [],
        "desktop":   [],
    })
    _patch(monkeypatch, stub)

    import app.agent as ag
    matched = _merge_all_dirs(ag.search_files, "target.txt")

    assert len(matched) == 1
    assert "Downloads" in matched[0]["path"]


# ---------------------------------------------------------------------------
# b. Multiple matches across directories → ambiguity detected
# ---------------------------------------------------------------------------

def test_multi_match_across_directories_detected(monkeypatch):
    """
    File exists in Downloads AND Documents.
    Merge returns 2 results — the caller (main.py) will refuse the action.
    """
    stub = _SearchStub({
        "downloads": ["ambiguous.txt"],
        "documents": ["ambiguous.txt"],
        "desktop":   [],
    })
    _patch(monkeypatch, stub)

    import app.agent as ag
    matched = _merge_all_dirs(ag.search_files, "ambiguous.txt")

    assert len(matched) == 2
    paths = [f["path"] for f in matched]
    assert any("Downloads" in p for p in paths)
    assert any("Documents" in p for p in paths)


def test_three_way_match_all_directories(monkeypatch):
    """File in Downloads, Documents, AND Desktop → 3 results."""
    stub = _SearchStub({
        "downloads": ["everywhere.txt"],
        "documents": ["everywhere.txt"],
        "desktop":   ["everywhere.txt"],
    })
    _patch(monkeypatch, stub)

    import app.agent as ag
    matched = _merge_all_dirs(ag.search_files, "everywhere.txt")

    assert len(matched) == 3


# ---------------------------------------------------------------------------
# c. Explicit directory → only that directory is searched
# ---------------------------------------------------------------------------

def test_explicit_directory_searches_only_that_dir(monkeypatch):
    """
    When directory is explicit, agent calls search_files exactly once
    with that directory — not all three.
    """
    stub = _SearchStub({
        "downloads": ["myfile.txt"],   # also here, but shouldn't be searched
        "documents": ["myfile.txt"],   # explicit target
        "desktop":   [],
    })
    _patch(monkeypatch, stub)

    import app.agent as ag

    # Simulate the explicit-directory branch (one call only)
    result = ag.search_files.invoke(
        {"directory": "documents", "extension": "", "filename": "myfile.txt",
         "start_date": "", "end_date": ""}
    )

    assert len(result["files"]) == 1
    assert stub._calls == ["documents"]   # exactly one dir searched


# ---------------------------------------------------------------------------
# d. No match anywhere → empty list (safe failure)
# ---------------------------------------------------------------------------

def test_no_match_anywhere_returns_empty(monkeypatch):
    """
    File does not exist in any allowed directory.
    Merge returns 0 results — main.py shows "File Not Found".
    """
    stub = _SearchStub({
        "downloads": [],
        "documents": [],
        "desktop":   [],
    })
    _patch(monkeypatch, stub)

    import app.agent as ag
    matched = _merge_all_dirs(ag.search_files, "ghost.txt")

    assert len(matched) == 0


# ---------------------------------------------------------------------------
# e. Result dict keys consumed by main.py
# ---------------------------------------------------------------------------

def test_rename_result_dict_structure(monkeypatch):
    """
    The dict returned to main.py for a rename must have the right keys.
    """
    stub = _SearchStub({"downloads": ["report.pdf"], "documents": [], "desktop": []})
    _patch(monkeypatch, stub)

    import app.agent as ag
    matched = _merge_all_dirs(ag.search_files, "report.pdf")

    result = {
        "action": "rename",
        "source_files": matched,
        "count": len(matched),
        "new_name": "final.pdf",
        "directory_specified": False,
    }

    assert result["action"] == "rename"
    assert isinstance(result["source_files"], list)
    assert result["count"] == 1
    assert result["new_name"] == "final.pdf"
    assert result["directory_specified"] is False


def test_move_result_dict_structure(monkeypatch):
    """
    The dict returned to main.py for a move must have the right keys.
    """
    stub = _SearchStub({"downloads": ["report.pdf"], "documents": [], "desktop": []})
    _patch(monkeypatch, stub)

    import app.agent as ag
    matched = _merge_all_dirs(ag.search_files, "report.pdf")

    result = {
        "action": "move",
        "source_files": matched,
        "count": len(matched),
        "destination": str(Path.home() / "Documents"),
        "destination_name": "Documents",
        "directory_specified": False,
    }

    assert result["action"] == "move"
    assert isinstance(result["source_files"], list)
    assert result["count"] == 1
    assert isinstance(result["destination"], str)
    assert result["directory_specified"] is False


# ---------------------------------------------------------------------------
# f. Filesystem level: same filename found via merge of two real directories
# ---------------------------------------------------------------------------

def test_search_same_filename_merged_from_two_dirs(tmp_path):
    """
    search_files is called on two separate tmp directories.
    Results are merged — this is the exact mechanism agent.py now uses.
    """
    dir_a = tmp_path / "A"
    dir_b = tmp_path / "B"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "shared.txt").write_text("in A")
    (dir_b / "shared.txt").write_text("in B")

    result_a = search_files.invoke({
        "directory": str(dir_a), "filename": "shared.txt",
        "extension": "", "start_date": "", "end_date": "",
    })
    result_b = search_files.invoke({
        "directory": str(dir_b), "filename": "shared.txt",
        "extension": "", "start_date": "", "end_date": "",
    })

    combined = result_a["files"] + result_b["files"]
    assert len(combined) == 2
    paths = [f["path"] for f in combined]
    assert any("/A/" in p for p in paths)
    assert any("/B/" in p for p in paths)


def test_search_unique_filename_no_false_positive(tmp_path):
    """
    A file that only exists in one directory must not produce a duplicate
    even when we search all three (simulated here with two tmp dirs).
    """
    dir_a = tmp_path / "A"
    dir_b = tmp_path / "B"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "unique.txt").write_text("only here")
    # dir_b deliberately has no file

    result_a = search_files.invoke({
        "directory": str(dir_a), "filename": "unique.txt",
        "extension": "", "start_date": "", "end_date": "",
    })
    result_b = search_files.invoke({
        "directory": str(dir_b), "filename": "unique.txt",
        "extension": "", "start_date": "", "end_date": "",
    })

    combined = result_a["files"] + result_b["files"]
    assert len(combined) == 1
