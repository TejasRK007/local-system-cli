"""
Cross-Platform and Filesystem Edge Cases Regression Suite for M5.

Tests:
1. Windows-style paths, drive letters, and backslashes.
2. Case-insensitive protected path resolution (SystemRoot, ProgramFiles, ProgramData).
3. Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9).
4. macOS-specific paths (/System, /Library, /private/etc, /etc).
5. Filesystem edge cases: Unicode, spaces, parentheses, brackets, nested directories.
6. Path traversal, collisions, source == destination, nonexistent targets.
7. Workspace authorization across platforms and CLI execution without shell dependencies.
"""

import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

import app.database as db
from app.main import app
from app.tasks.goal_planner import GoalPlanner
from app.tasks.validator import PlanValidator
from app.tools.file_actions import create_directory, delete_file, move_file, rename_file
from app.workspaces import WorkspaceManager

runner = CliRunner()


@pytest.fixture(autouse=True)
def setup_isolated_env(tmp_path, monkeypatch):
    """Ensure every test executes against a fresh isolated temporary SQLite database."""
    temp_db_path = tmp_path / "test_cross_platform.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db_path))
    monkeypatch.setenv("GROQ_API_KEY", "dummy_groq_api_key_for_testing")
    db.init_db(temp_db_path)
    yield


# ==============================================================================
# 1. Windows Path & Drive Letter Tests (Cross-Platform via Abstractions)
# ==============================================================================


def test_windows_drive_letter_protection():
    """Verify that any Windows drive root is recognized as protected."""
    assert WorkspaceManager.is_protected_system_path("C:\\") is True
    assert WorkspaceManager.is_protected_system_path("c:\\") is True
    assert WorkspaceManager.is_protected_system_path("D:\\") is True
    assert WorkspaceManager.is_protected_system_path("E:\\") is True
    assert WorkspaceManager.is_protected_system_path("Z:\\") is True


def test_windows_system_directories_on_multiple_drives():
    """Verify system directories are blocked on any drive letter (C:, D:, etc.)."""
    assert WorkspaceManager.is_protected_system_path("C:\\Windows") is True
    assert WorkspaceManager.is_protected_system_path("c:\\windows\\system32") is True
    assert WorkspaceManager.is_protected_system_path("D:\\Windows") is True
    assert WorkspaceManager.is_protected_system_path("D:\\Program Files") is True
    assert WorkspaceManager.is_protected_system_path("d:\\program files (x86)") is True
    assert WorkspaceManager.is_protected_system_path("E:\\ProgramData") is True
    assert WorkspaceManager.is_protected_system_path("C:\\$Recycle.Bin") is True


def test_windows_environment_variable_expansion(monkeypatch):
    """Verify system environment variables (SystemRoot, ProgramFiles, etc.) are protected."""
    monkeypatch.setenv("SystemRoot", "C:\\CustomWin")
    monkeypatch.setenv("ProgramFiles", "D:\\Apps")
    monkeypatch.setenv("ProgramData", "E:\\SysData")

    assert WorkspaceManager.is_protected_system_path("C:\\CustomWin") is True
    assert WorkspaceManager.is_protected_system_path("c:\\customwin\\drivers") is True
    assert WorkspaceManager.is_protected_system_path("D:\\Apps\\Common") is True
    assert WorkspaceManager.is_protected_system_path("E:\\SysData\\Secrets") is True


def test_windows_user_directories_not_blocked():
    """Verify normal user folders on Windows are not falsely classified as protected."""
    assert WorkspaceManager.is_protected_system_path("C:\\Users\\Alice\\Downloads") is False
    assert WorkspaceManager.is_protected_system_path("C:\\Users\\Bob\\Documents") is False
    assert WorkspaceManager.is_protected_system_path("D:\\Projects\\Workspace") is False


def test_windows_reserved_names_in_rename(tmp_path):
    """Verify renaming to Windows reserved device names (CON, NUL, AUX, PRN, COM1) is blocked."""
    ws_dir = tmp_path / "win_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="WinWs", permissions=["READ", "WRITE"])
    src_file = ws_dir / "safe.txt"
    src_file.write_text("hello", encoding="utf-8")

    reserved_names = ["CON", "con.txt", "PRN", "aux.dat", "NUL", "COM1", "lpt1.txt"]
    for reserved in reserved_names:
        # 1. file_actions direct tool
        msg = rename_file(str(src_file), reserved)
        assert "reserved device name" in msg.lower() or "blocked" in msg.lower()

        # 2. PlanValidator
        steps = [
            {
                "step_order": 1,
                "action": "rename",
                "arguments": {"source": str(src_file), "new_name": reserved},
                "depends_on_order": None,
            }
        ]
        valid, reason = PlanValidator.validate_plan(steps)
        assert valid is False
        assert "reserved" in reason.lower()


def test_windows_invalid_filename_characters(tmp_path):
    """Verify invalid Windows filename characters (< > : " / \\ | ? *) are rejected."""
    ws_dir = tmp_path / "char_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="CharWs", permissions=["READ", "WRITE"])
    src_file = ws_dir / "test.txt"
    src_file.write_text("data", encoding="utf-8")

    invalid_names = [
        "file<1>.txt",
        "file>2.txt",
        "file:3.txt",
        'file"4.txt',
        "file|5.txt",
        "file?6.txt",
    ]
    for bad_name in invalid_names:
        msg = rename_file(str(src_file), bad_name)
        assert "invalid" in msg.lower() or "blocked" in msg.lower()

        steps = [
            {
                "step_order": 1,
                "action": "rename",
                "arguments": {"source": str(src_file), "new_name": bad_name},
                "depends_on_order": None,
            }
        ]
        valid, reason = PlanValidator.validate_plan(steps)
        assert valid is False
        assert "invalid" in reason.lower()


# ==============================================================================
# 2. macOS & POSIX Protected Path Tests
# ==============================================================================


def test_posix_system_directory_protection():
    """Verify Unix and macOS system directories are protected."""
    assert WorkspaceManager.is_protected_system_path("/") is True
    assert WorkspaceManager.is_protected_system_path("/System") is True
    assert WorkspaceManager.is_protected_system_path("/Library") is True
    assert WorkspaceManager.is_protected_system_path("/etc") is True
    assert WorkspaceManager.is_protected_system_path("/private") is True
    assert WorkspaceManager.is_protected_system_path("/private/etc") is True
    assert WorkspaceManager.is_protected_system_path("/bin") is True
    assert WorkspaceManager.is_protected_system_path("/usr") is True
    assert WorkspaceManager.is_protected_system_path("/var/root") is True


def test_posix_user_and_temp_directories_not_blocked(tmp_path):
    """Verify user home folders and temp directories are NOT falsely blocked."""
    assert WorkspaceManager.is_protected_system_path(tmp_path) is False
    assert WorkspaceManager.is_protected_system_path("/Users/tejasrk/Downloads") is False
    assert WorkspaceManager.is_protected_system_path("/home/user/Documents") is False


# ==============================================================================
# 3. Filesystem Edge Cases: Unicode, Spaces, Brackets, Parentheses
# ==============================================================================


def test_unicode_filenames_and_spaces(tmp_path):
    """Verify files with Unicode, accented chars, spaces, and brackets work seamlessly."""
    ws_dir = tmp_path / "Dossier Médical (2026) [Archives]"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(
        ws_dir, name="UnicodeWs", permissions=["READ", "WRITE", "DELETE"]
    )

    unicode_file = ws_dir / "rapport_résumé_2026 — final (v1.0) [confidential].txt"
    unicode_file.write_text("Données sécurisées", encoding="utf-8")
    assert unicode_file.exists()

    # 1. Search via GoalPlanner
    plan = GoalPlanner.plan_goal("Find rapport_résumé in UnicodeWs")
    assert len(plan.discovered_files) == 1

    # 2. Rename with spaces and Unicode
    new_name = "rapport_officiel_2026 (approuvé).txt"
    res = rename_file(str(unicode_file), new_name)
    assert "successfully" in res.lower()
    renamed_file = ws_dir / new_name
    assert renamed_file.exists()

    # 3. Move to nested directory with spaces
    target_subdir = ws_dir / "Sous Répertoire (Niveau 2)"
    create_directory(str(target_subdir))
    assert target_subdir.is_dir()

    res_move = move_file(str(renamed_file), str(target_subdir))
    assert "successfully" in res_move.lower()
    moved_file = target_subdir / new_name
    assert moved_file.exists()
    assert not renamed_file.exists()

    # 4. Delete moved file
    res_del = delete_file(str(moved_file))
    assert "successfully" in res_del.lower()
    assert not moved_file.exists()


def test_deeply_nested_directories(tmp_path):
    """Verify operations across deeply nested subdirectories."""
    ws_dir = tmp_path / "deep_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="DeepWs", permissions=["READ", "WRITE", "DELETE"])

    nested_dir = ws_dir / "lvl1" / "lvl2" / "lvl3" / "lvl4"
    res_dir = create_directory(str(nested_dir))
    assert "successfully" in res_dir.lower() or "exists" in res_dir.lower()
    assert nested_dir.is_dir()

    test_file = nested_dir / "deep_file.txt"
    test_file.write_text("nested data", encoding="utf-8")

    # Search in workspace should locate the nested file
    plan = GoalPlanner.plan_goal("Find deep_file.txt in DeepWs")
    assert len(plan.discovered_files) == 1
    found_path = (
        plan.discovered_files[0]["path"]
        if isinstance(plan.discovered_files[0], dict)
        else plan.discovered_files[0]
    )
    assert Path(found_path).resolve() == test_file.resolve()


def test_duplicate_filenames_in_different_directories(tmp_path):
    """Verify search handles multiple files with the same name across subfolders."""
    ws_dir = tmp_path / "dup_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="DupWs", permissions=["READ", "WRITE"])

    dir_a = ws_dir / "folder_a"
    dir_b = ws_dir / "folder_b"
    dir_a.mkdir()
    dir_b.mkdir()

    file_a = dir_a / "common.log"
    file_b = dir_b / "common.log"
    file_a.write_text("log a", encoding="utf-8")
    file_b.write_text("log b", encoding="utf-8")

    plan = GoalPlanner.plan_goal("Find common.log in DupWs")
    assert len(plan.discovered_files) == 2


def test_source_equals_destination_collision(tmp_path):
    """Verify renaming a file to its own name is rejected as invalid/identical."""
    ws_dir = tmp_path / "same_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="SameWs", permissions=["READ", "WRITE"])

    f = ws_dir / "document.pdf"
    f.write_text("pdf content", encoding="utf-8")

    steps = [
        {
            "step_order": 1,
            "action": "rename",
            "arguments": {"source": str(f), "new_name": "document.pdf"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "identical" in reason.lower() or "collision" in reason.lower()


def test_destination_collision_rejection(tmp_path):
    """Verify moving or renaming to an already existing file is blocked."""
    ws_dir = tmp_path / "coll_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="CollWs", permissions=["READ", "WRITE"])

    f1 = ws_dir / "file1.txt"
    f2 = ws_dir / "file2.txt"
    f1.write_text("f1", encoding="utf-8")
    f2.write_text("f2", encoding="utf-8")

    # Direct rename
    msg = rename_file(str(f1), "file2.txt")
    assert "already exists" in msg.lower() or "blocked" in msg.lower()

    # Plan validation
    steps = [
        {
            "step_order": 1,
            "action": "rename",
            "arguments": {"source": str(f1), "new_name": "file2.txt"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "collision" in reason.lower() or "already exists" in reason.lower()


def test_path_traversal_rejection(tmp_path):
    """Verify path traversal (..) attempting to escape workspace is strictly blocked."""
    ws_dir = tmp_path / "confined_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="ConfinedWs", permissions=["READ", "WRITE"])

    outside = tmp_path / "escaped.txt"
    outside.write_text("outside", encoding="utf-8")

    # Step attempting to rename file outside workspace
    traversal_src = str(ws_dir / ".." / "escaped.txt")
    steps = [
        {
            "step_order": 1,
            "action": "rename",
            "arguments": {"source": traversal_src, "new_name": "hacked.txt"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "unauthorized" in reason.lower() or "outside" in reason.lower()


def test_nonexistent_source_and_destination(tmp_path):
    """Verify operations against nonexistent sources or destinations fail safely."""
    ws_dir = tmp_path / "nonexist_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(
        ws_dir, name="NonExistWs", permissions=["READ", "WRITE", "DELETE"]
    )

    nonexistent_file = str(ws_dir / "ghost.txt")
    assert "does not exist" in delete_file(nonexistent_file).lower()
    assert "does not exist" in rename_file(nonexistent_file, "new.txt").lower()
    assert "does not exist" in move_file(nonexistent_file, str(ws_dir)).lower()

    # Move to nonexistent directory
    real_file = ws_dir / "real.txt"
    real_file.write_text("real", encoding="utf-8")
    assert "does not exist" in move_file(str(real_file), str(ws_dir / "no_folder")).lower()


def test_readonly_file_permission(tmp_path):
    """Verify behavior when encountering a read-only file where OS permits."""
    ws_dir = tmp_path / "ro_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="RoWs", permissions=["READ", "WRITE", "DELETE"])

    f = ws_dir / "readonly.txt"
    f.write_text("protected", encoding="utf-8")

    # Attempt to set read-only permission (remove write bits)
    try:
        os.chmod(str(f), stat.S_IREAD)
        # Verify read operations still succeed
        plan = GoalPlanner.plan_goal("Find readonly.txt in RoWs")
        assert len(plan.discovered_files) == 1
    finally:
        # Restore write permissions so pytest cleanup succeeds on Windows & macOS
        os.chmod(str(f), stat.S_IWRITE | stat.S_IREAD)


# ==============================================================================
# 4. CLI Cross-Platform Execution (No Bash/Grep/Sed Dependencies)
# ==============================================================================


def test_cli_help_is_portable():
    """Verify CLI help command runs cleanly via Python CLI runner."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Local Agentic Automation System" in result.output
    assert "workspace" in result.output
    assert "goal" in result.output


def test_cli_workspace_workflow_portable(tmp_path):
    """Verify full workspace lifecycle through CLI runner without any shell piping."""
    ws_dir = tmp_path / "CliTestWs"
    ws_dir.mkdir()

    # 1. Add workspace
    res_add = runner.invoke(app, ["workspace-add", str(ws_dir), "--name", "CliWs"])
    assert res_add.exit_code == 0
    assert "CliWs" in res_add.output

    # 2. List workspaces
    res_list = runner.invoke(app, ["workspace"])
    assert res_list.exit_code == 0
    assert "CliWs" in res_list.output

    # 3. Disable workspace
    res_dis = runner.invoke(app, ["workspace-disable", "CliWs"])
    assert res_dis.exit_code == 0

    # 4. Enable workspace
    res_en = runner.invoke(app, ["workspace-enable", "CliWs"])
    assert res_en.exit_code == 0

    # 5. Remove workspace
    res_rem = runner.invoke(app, ["workspace-remove", "CliWs"])
    assert res_rem.exit_code == 0
