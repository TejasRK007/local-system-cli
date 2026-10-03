"""
Automated test suite for Milestone 4:
Persistent Local Agent + Workspace & Permission Management.

Covers:
- A. Workspace creation
- B. Workspace persistence across reloads
- C. Workspace listing
- D. Workspace removal & disable
- E. READ permission enforcement
- F. WRITE permission enforcement
- G. DELETE permission enforcement
- H. Canonical path containment
- I. Path traversal rejection ("../../Windows")
- J. Disabled workspace rejection
- K. Unauthorized workspace rejection
- L. Move requiring source READ + destination WRITE
- M. Rename requiring WRITE
- N. Delete requiring DELETE
- O. Policy integration
- P. Approval integration
- Q. Recovery integration
- R. Multi-step task integration with workspaces
- S. Safe task resumption (preserves completed steps, re-evaluates incomplete steps)
- T. Windows path handling (case-insensitivity, drive letter casing)
- U. Drive root and protected system directory rejection
- V. CLI workspace commands & no-workspace blocking
"""

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

import app.database as db
from app.main import app
from app.tasks.executor import StepExecutor
from app.tasks.manager import TaskManager
from app.tasks.models import StepStatus, TaskStatus
from app.tools.file_actions import delete_file, is_allowed_path, move_file, rename_file
from app.workspaces import Permission, WorkspaceManager

runner = CliRunner()


class MockLLM:
    """Mock LLM response for deterministic testing."""

    def __init__(self, content: str):
        self.content = content

    def invoke(self, prompt):
        class Response:
            pass

        res = Response()
        res.content = self.content
        return res


@pytest.fixture(autouse=True)
def setup_workspace_env(tmp_path, monkeypatch):
    """Isolate SQLite database and enforce workspace security for Milestone 4 tests."""
    temp_db_path = tmp_path / "test_workspace_agent.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db_path))
    monkeypatch.setenv("AGENT_ENFORCE_WORKSPACES", "1")
    db.init_db(temp_db_path)
    return tmp_path


# ---------------------------------------------------------------------------
# A & B. Workspace Creation & Persistence
# ---------------------------------------------------------------------------


def test_workspace_creation_and_persistence(tmp_path):
    """Verify workspace is created with canonical path and persists across DB reloads."""
    ws_dir = tmp_path / "my_docs"
    ws_dir.mkdir()

    ws = WorkspaceManager.add_workspace(
        path=str(ws_dir),
        name="Documents",
        permissions=["READ", "WRITE"],
    )

    assert ws.workspace_id.startswith("ws_")
    assert ws.name == "Documents"
    assert ws.canonical_path == ws_dir.resolve()
    assert ws.enabled is True
    assert ws.permissions == {"READ", "WRITE"}

    # Persistence verification: reload from fresh DB query
    loaded = WorkspaceManager.get_workspace(ws.workspace_id)
    assert loaded is not None
    assert loaded.workspace_id == ws.workspace_id
    assert loaded.canonical_path == ws_dir.resolve()
    assert loaded.permissions == {"READ", "WRITE"}
    assert loaded.enabled is True


# ---------------------------------------------------------------------------
# C & D. Workspace Listing, Disable, Enable & Removal
# ---------------------------------------------------------------------------


def test_workspace_listing_and_lifecycle(tmp_path):
    """Verify listing, enabling, disabling, and removal without affecting tasks."""
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()

    ws1 = WorkspaceManager.add_workspace(dir1, name="DirOne")
    ws2 = WorkspaceManager.add_workspace(dir2, name="DirTwo")

    all_ws = WorkspaceManager.list_workspaces()
    assert len(all_ws) == 2
    assert {w.workspace_id for w in all_ws} == {ws1.workspace_id, ws2.workspace_id}

    # Disable ws1
    WorkspaceManager.disable_workspace(ws1.workspace_id)
    ws1_updated = WorkspaceManager.get_workspace(ws1.workspace_id)
    assert ws1_updated.enabled is False

    enabled_only = WorkspaceManager.list_workspaces(enabled_only=True)
    assert len(enabled_only) == 1
    assert enabled_only[0].workspace_id == ws2.workspace_id

    # Re-enable ws1
    WorkspaceManager.enable_workspace(ws1.workspace_id)
    assert WorkspaceManager.get_workspace(ws1.workspace_id).enabled is True

    # Remove ws2
    removed = WorkspaceManager.remove_workspace(ws2.workspace_id)
    assert removed is True
    assert WorkspaceManager.get_workspace(ws2.workspace_id) is None
    assert WorkspaceManager.count_workspaces() == 1


# ---------------------------------------------------------------------------
# E, F, G. Granular Permissions (READ, WRITE, DELETE)
# ---------------------------------------------------------------------------


def test_permission_enforcement_read_write_delete(tmp_path):
    """Verify granular permission authorization for READ, WRITE, and DELETE."""
    read_only_dir = tmp_path / "readonly"
    read_only_dir.mkdir()
    ws = WorkspaceManager.add_workspace(read_only_dir, name="ReadOnly", permissions=["READ"])

    test_file = read_only_dir / "file.txt"
    test_file.write_text("content", encoding="utf-8")

    # READ should be allowed
    ok_read, _, _ = WorkspaceManager.check_workspace_authorization(test_file, Permission.READ.value)
    assert ok_read is True

    # WRITE and DELETE should be blocked
    ok_write, reason_w, _ = WorkspaceManager.check_workspace_authorization(
        test_file, Permission.WRITE.value
    )
    assert ok_write is False
    assert "WRITE" in reason_w

    ok_del, reason_d, _ = WorkspaceManager.check_workspace_authorization(
        test_file, Permission.DELETE.value
    )
    assert ok_del is False
    assert "DELETE" in reason_d

    # Now grant WRITE and DELETE
    WorkspaceManager.set_permissions(ws.workspace_id, ["READ", "WRITE", "DELETE"])
    ok_write2, _, _ = WorkspaceManager.check_workspace_authorization(
        test_file, Permission.WRITE.value
    )
    ok_del2, _, _ = WorkspaceManager.check_workspace_authorization(
        test_file, Permission.DELETE.value
    )
    assert ok_write2 is True
    assert ok_del2 is True


# ---------------------------------------------------------------------------
# H & I. Canonical Path Containment & Traversal Rejection
# ---------------------------------------------------------------------------


def test_path_containment_and_traversal_rejection(tmp_path):
    """Verify robust canonical containment and rejection of '..' traversal."""
    ws_dir = tmp_path / "safe_zone"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="SafeZone")

    valid_subfile = ws_dir / "nested" / "doc.txt"
    assert is_allowed_path(valid_subfile, permission=Permission.READ.value) is True

    # Traversal escaping outside safe_zone
    traversal_path = ws_dir / ".." / "outside.txt"
    assert is_allowed_path(traversal_path, permission=Permission.READ.value) is False

    # Deep traversal attempting to reach system dirs
    sys_traversal = ws_dir / ".." / ".." / "Windows" / "System32"
    assert is_allowed_path(sys_traversal, permission=Permission.READ.value) is False


# ---------------------------------------------------------------------------
# J & K. Disabled & Unauthorized Workspace Rejection
# ---------------------------------------------------------------------------


def test_disabled_and_unauthorized_workspace_rejection(tmp_path):
    """Verify operations in disabled or unconfigured workspaces are rejected."""
    ws_dir = tmp_path / "toggle_zone"
    ws_dir.mkdir()
    ws = WorkspaceManager.add_workspace(ws_dir, name="ToggleZone")

    f = ws_dir / "test.txt"
    f.write_text("data", encoding="utf-8")

    # When enabled -> authorized
    ok, _, _ = WorkspaceManager.check_workspace_authorization(f, Permission.READ.value)
    assert ok is True

    # When disabled -> rejected
    WorkspaceManager.disable_workspace(ws.workspace_id)
    ok_dis, reason, _ = WorkspaceManager.check_workspace_authorization(f, Permission.READ.value)
    assert ok_dis is False
    assert "disabled" in reason.lower()

    # Completely unauthorized directory
    other_dir = tmp_path / "unconfigured"
    other_dir.mkdir()
    ok_unauth, reason_unauth, _ = WorkspaceManager.check_workspace_authorization(
        other_dir / "secret.txt", Permission.READ.value
    )
    assert ok_unauth is False
    assert "outside configured workspaces" in reason_unauth.lower()


# ---------------------------------------------------------------------------
# L, M, N. Multi-permission Actions (Move, Rename, Delete)
# ---------------------------------------------------------------------------


def test_move_action_requires_read_and_write(tmp_path):
    """Verify Move requires READ on source and WRITE on destination."""
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    # src has only READ, dst has only READ (lacks WRITE)
    WorkspaceManager.add_workspace(src_dir, name="Src", permissions=["READ"])
    ws_dst = WorkspaceManager.add_workspace(dst_dir, name="Dst", permissions=["READ"])

    f = src_dir / "file.txt"
    f.write_text("hello", encoding="utf-8")

    auth_ok, reason = WorkspaceManager.authorize_action(
        "move", source_path=f, destination_path=dst_dir
    )
    assert auth_ok is False
    assert "destination unauthorized" in reason.lower()

    # Add WRITE to dst
    WorkspaceManager.set_permissions(ws_dst.workspace_id, ["READ", "WRITE"])
    auth_ok2, _ = WorkspaceManager.authorize_action("move", source_path=f, destination_path=dst_dir)
    assert auth_ok2 is True

    # Now execute move_file
    res = move_file(str(f), str(dst_dir))
    assert "Verified: file moved successfully" in res
    assert not f.exists()
    assert (dst_dir / "file.txt").exists()


def test_rename_action_requires_write(tmp_path):
    """Verify Rename requires WRITE permission."""
    ws_dir = tmp_path / "rename_zone"
    ws_dir.mkdir()
    ws = WorkspaceManager.add_workspace(ws_dir, name="RenameZone", permissions=["READ"])

    f = ws_dir / "old.txt"
    f.write_text("text", encoding="utf-8")

    # Rename with only READ should fail
    auth_ok, reason = WorkspaceManager.authorize_action("rename", target_path=f)
    assert auth_ok is False
    assert "WRITE" in reason

    res = rename_file(str(f), "new.txt")
    assert "Rename blocked" in res

    # Grant WRITE and rename
    WorkspaceManager.set_permissions(ws.workspace_id, ["READ", "WRITE"])
    auth_ok2, _ = WorkspaceManager.authorize_action("rename", target_path=f)
    assert auth_ok2 is True

    res2 = rename_file(str(f), "new.txt")
    assert "Verified: file renamed successfully" in res2
    assert (ws_dir / "new.txt").exists()
    assert not f.exists()


def test_delete_action_requires_delete_permission(tmp_path):
    """Verify Delete requires explicit DELETE permission."""
    ws_dir = tmp_path / "del_zone"
    ws_dir.mkdir()
    ws = WorkspaceManager.add_workspace(ws_dir, name="DelZone", permissions=["READ", "WRITE"])

    f = ws_dir / "obsolete.txt"
    f.write_text("delete me", encoding="utf-8")

    # Delete blocked without DELETE permission
    auth_ok, reason = WorkspaceManager.authorize_action("delete", target_path=f)
    assert auth_ok is False
    assert "DELETE" in reason

    res = delete_file(str(f))
    assert "Deletion blocked" in res
    assert f.exists()

    # Grant DELETE permission
    WorkspaceManager.set_permissions(ws.workspace_id, ["READ", "WRITE", "DELETE"])
    res2 = delete_file(str(f))
    assert "Verified:" in res2 and "deleted successfully" in res2
    assert not f.exists()


# ---------------------------------------------------------------------------
# O, P, Q, R. Multi-step Task Integration with Workspace Authorization
# ---------------------------------------------------------------------------


def test_task_execution_with_workspaces(tmp_path):
    """Verify multi-step task execution strictly respects workspace authorization."""
    ws_dir = tmp_path / "task_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="TaskWs", permissions=["READ", "WRITE"])

    f = ws_dir / "doc.txt"
    f.write_text("step task content", encoding="utf-8")

    dst_dir = ws_dir / "subfolder"
    dst_dir.mkdir()

    steps_spec = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(f), "destination": str(dst_dir)},
        },
        {
            "step_order": 2,
            "action": "rename",
            "arguments": {"source": "$output.step_1.path", "new_name": "renamed.txt"},
            "depends_on_order": 1,
        },
    ]

    task = TaskManager.create_task(
        "Move doc.txt to subfolder and rename to renamed.txt", steps_spec
    )
    executed = StepExecutor.execute_task(task, confirm_callback=lambda a, p, d: True)

    assert executed.status == TaskStatus.COMPLETED
    assert executed.steps[0].status == StepStatus.SUCCESS
    assert executed.steps[1].status == StepStatus.SUCCESS
    assert (dst_dir / "renamed.txt").exists()


def test_task_blocked_when_destination_workspace_disabled(tmp_path):
    """Verify step execution is blocked with POLICY_VIOLATION when workspace is disabled."""
    src_dir = tmp_path / "tsrc"
    dst_dir = tmp_path / "tdst"
    src_dir.mkdir()
    dst_dir.mkdir()

    WorkspaceManager.add_workspace(src_dir, name="Src")
    ws_dst = WorkspaceManager.add_workspace(dst_dir, name="Dst")
    WorkspaceManager.disable_workspace(ws_dst.workspace_id)

    f = src_dir / "blocked.txt"
    f.write_text("blocked", encoding="utf-8")

    steps_spec = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(f), "destination": str(dst_dir)},
        },
    ]

    task = TaskManager.create_task("Move blocked.txt to tdst", steps_spec)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda a, p, d: True)

    assert executed.status == TaskStatus.FAILED
    assert executed.steps[0].status == StepStatus.FAILED
    assert "disabled" in executed.steps[0].error_info.lower()


# ---------------------------------------------------------------------------
# S. Safe Task Resume
# ---------------------------------------------------------------------------


def test_safe_task_resume(tmp_path):
    """
    Verify task-resume:
    1. Step 1 succeeds.
    2. Step 2 initially fails due to destination conflict.
    3. Conflict is resolved.
    4. Resume skips step 1 and successfully runs step 2.
    """
    ws_dir = tmp_path / "resume_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="ResumeWs", permissions=["READ", "WRITE"])

    src_file = ws_dir / "data.txt"
    src_file.write_text("original content", encoding="utf-8")

    dst_dir = ws_dir / "output"
    dst_dir.mkdir()

    # Pre-create conflict file at destination for step 2
    conflict_file = dst_dir / "final_report.txt"
    conflict_file.write_text("pre-existing conflict", encoding="utf-8")

    steps_spec = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(src_file), "destination": str(dst_dir)},
        },
        {
            "step_order": 2,
            "action": "rename",
            "arguments": {"source": "$output.step_1.path", "new_name": "final_report.txt"},
            "depends_on_order": 1,
        },
    ]

    task = TaskManager.create_task("Move and rename report", steps_spec)
    executed_1 = StepExecutor.execute_task(task, confirm_callback=lambda a, p, d: True)

    # Step 1 succeeded, Step 2 failed due to conflict
    assert executed_1.steps[0].status == StepStatus.SUCCESS
    assert executed_1.steps[1].status == StepStatus.FAILED
    assert executed_1.status == TaskStatus.PARTIAL_FAILURE

    # Resolve conflict by deleting the conflicting target
    conflict_file.unlink()

    # Simulate task-resume via CLI command with user confirmation
    res = runner.invoke(app, ["task-resume", task.task_id], input="y\n")
    assert res.exit_code == 0
    assert "Resuming From Step : #2" in res.stdout
    assert "resumed and completed successfully" in res.stdout

    # Verify task state in SQLite
    reloaded_task = TaskManager.get_task(task.task_id)
    assert reloaded_task.status == TaskStatus.COMPLETED
    assert reloaded_task.steps[0].status == StepStatus.SUCCESS
    assert reloaded_task.steps[1].status == StepStatus.SUCCESS
    assert (dst_dir / "final_report.txt").exists()


# ---------------------------------------------------------------------------
# T & U. Windows Path Handling & Drive Root / System Path Protection
# ---------------------------------------------------------------------------


def test_drive_root_and_system_path_rejection(monkeypatch):
    """Verify adding drive roots and system folders is explicitly rejected (platform-aware)."""
    import sys

    if sys.platform == "win32":
        # --- Windows: original behaviour ---
        with pytest.raises(ValueError, match="drive root"):
            WorkspaceManager.add_workspace("C:\\")

        windows_dir = os.environ.get("SystemRoot", "C:\\Windows")
        with pytest.raises(PermissionError, match="protected system directory"):
            WorkspaceManager.add_workspace(windows_dir)
    else:
        # --- Linux / macOS: use platform-appropriate equivalents ---
        # The filesystem root "/" is the Unix equivalent of a drive root.
        with pytest.raises(ValueError, match="drive root"):
            WorkspaceManager.add_workspace("/")

        # Patch SystemRoot to point to a real directory that always exists on
        # POSIX systems (/etc) so the production PermissionError guard fires.
        monkeypatch.setenv("SystemRoot", "/etc")
        with pytest.raises(PermissionError, match="protected system directory"):
            WorkspaceManager.add_workspace("/etc")


def test_windows_casing_insensitivity(tmp_path):
    """Verify path containment handles Windows path casing differences."""
    ws_dir = tmp_path / "CaseFolder"
    ws_dir.mkdir()
    ws = WorkspaceManager.add_workspace(ws_dir, name="CaseFolder")

    # Subpath with lowercase variation
    sub_path = Path(str(ws_dir).lower()) / "sub" / "file.txt"
    assert WorkspaceManager._is_subpath(sub_path, ws.canonical_path) is True


# ---------------------------------------------------------------------------
# V. CLI Workspace Commands & Safety Guards
# ---------------------------------------------------------------------------


def test_cli_workspace_commands(tmp_path):
    """Verify CLI commands: workspace, workspace-add, disable, enable, remove."""
    # 1. Listing with no workspaces configured
    res_empty = runner.invoke(app, ["workspace"])
    assert res_empty.exit_code == 0
    assert "No workspaces configured" in res_empty.stdout

    # 2. Add workspace
    ws_dir = tmp_path / "cli_workspace"
    ws_dir.mkdir()
    res_add = runner.invoke(app, ["workspace-add", str(ws_dir), "--name", "TestCliWs"])
    assert res_add.exit_code == 0
    assert "Workspace authorized successfully" in res_add.stdout
    assert "TestCliWs" in res_add.stdout

    # 3. List workspace
    res_list = runner.invoke(app, ["workspace"])
    assert res_list.exit_code == 0
    assert "TestCliWs" in res_list.stdout
    assert "ENABLED" in res_list.stdout

    ws = WorkspaceManager.get_workspace_by_name("TestCliWs")
    assert ws is not None

    # 4. Disable workspace
    res_dis = runner.invoke(app, ["workspace-disable", ws.workspace_id])
    assert res_dis.exit_code == 0
    assert "DISABLED" in res_dis.stdout

    # 5. Enable workspace
    res_en = runner.invoke(app, ["workspace-enable", ws.workspace_id])
    assert res_en.exit_code == 0
    assert "ENABLED" in res_en.stdout

    # 6. Update permissions
    res_perm = runner.invoke(app, ["workspace-permissions", ws.workspace_id, "READ,WRITE"])
    assert res_perm.exit_code == 0
    assert "READ, WRITE" in res_perm.stdout

    # 7. Remove workspace
    res_rm = runner.invoke(app, ["workspace-remove", ws.workspace_id])
    assert res_rm.exit_code == 0
    assert "removed successfully" in res_rm.stdout
    assert WorkspaceManager.get_workspace(ws.workspace_id) is None


def test_cli_blocks_when_no_workspaces_configured(tmp_path, monkeypatch):
    """Verify CLI commands block and explain that workspace must be added when none exist."""
    # Ensure 0 workspaces and force workspace enforcement
    assert WorkspaceManager.count_workspaces() == 0
    monkeypatch.setenv("AGENT_ENFORCE_WORKSPACES", "1")

    res_agent = runner.invoke(app, ["agent", "Move file.txt to Documents"])
    assert res_agent.exit_code == 0
    assert "Workspace Required" in res_agent.stdout

    res_task = runner.invoke(app, ["task", "Move a.txt to b and rename to c.txt"])
    assert res_task.exit_code == 0
    assert "Workspace Required" in res_task.stdout

    res_delete = runner.invoke(app, ["delete", "C:\\some\\file.txt"])
    assert res_delete.exit_code == 0
    assert "Workspace Required" in res_delete.stdout


# ---------------------------------------------------------------------------
# W. Workspace-aware Search Bug Fix Regression Tests
#    Covers all 7 cases from the bug report.
# ---------------------------------------------------------------------------


def test_search_uses_configured_workspaces_when_no_location_given(tmp_path, monkeypatch):
    """
    Case 1 (Bug 1): run_agent search with no directory specified must search
    enabled READ workspaces, NOT fall back to Downloads or any legacy dir.
    """
    from app.agent import run_agent

    monkeypatch.setattr("app.agent.extract_intent", lambda _: {
        "action": "search", "filename": "needle.txt",
        "extension": None, "directory": None,
    })

    ws_dir = tmp_path / "ws_search"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(
        ws_dir, name="SearchWs",
        permissions=["READ", "WRITE", "DELETE"],
    )

    target = ws_dir / "needle.txt"
    target.write_text("find me", encoding="utf-8")

    result = run_agent("Find needle.txt")

    assert isinstance(result, dict), f"Expected dict, got: {result!r}"
    assert result.get("found") is True, f"File not found. Result: {result}"
    found_paths = [f["path"] for f in result.get("files", [])]
    assert any("needle.txt" in p for p in found_paths), f"needle.txt not in results: {found_paths}"
    # Must NOT have searched Downloads
    assert not any("Downloads" in p for p in found_paths), (
        f"Unexpectedly searched Downloads: {found_paths}"
    )


def test_search_with_explicit_workspace_name(tmp_path, monkeypatch):
    """
    Case 2 (Bug 2): run_agent "Find file.txt in <workspace_name>" must resolve
    the workspace name and search within that workspace.
    """
    from app.agent import run_agent

    monkeypatch.setattr("app.agent.extract_intent", lambda _: {
        "action": "search", "filename": "report.txt",
        "extension": None, "directory": "NamedWs",
    })

    ws_dir = tmp_path / "named_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(
        ws_dir, name="NamedWs", permissions=["READ"],
    )

    target = ws_dir / "report.txt"
    target.write_text("contents", encoding="utf-8")

    result = run_agent("Find report.txt in NamedWs")

    assert isinstance(result, dict), f"Expected dict, got: {result!r}"
    assert result.get("found") is True, (
        f"File not found. Result: {result}"
    )
    found_paths = [f["path"] for f in result.get("files", [])]
    assert any(
        "report.txt" in p for p in found_paths
    ), f"report.txt not in results: {found_paths}"


def test_search_blocked_when_workspace_disabled(
    tmp_path, monkeypatch,
):
    """
    Case 3: Searching within a disabled workspace must be blocked (not searched).
    """
    from app.agent import run_agent

    monkeypatch.setattr("app.agent.extract_intent", lambda _: {
        "action": "search", "filename": "hidden.txt",
        "extension": None, "directory": "DisabledWs",
    })

    ws_dir = tmp_path / "disabled_ws"
    ws_dir.mkdir()
    ws = WorkspaceManager.add_workspace(
        ws_dir, name="DisabledWs", permissions=["READ"],
    )
    WorkspaceManager.disable_workspace(ws.workspace_id)

    target = ws_dir / "hidden.txt"
    target.write_text("should not be found", encoding="utf-8")

    # Search by name — should be blocked because workspace is disabled
    result = run_agent("Find hidden.txt in DisabledWs")

    # Either a "Search blocked"/"disabled" message or found=False
    if isinstance(result, dict):
        msg = result.get("message", "").lower()
        files = result.get("files", [])
        assert (
            result.get("found") is False
            or "disabled" in msg
            or "blocked" in msg
            or len(files) == 0
        ), (
            f"Disabled workspace should not be searchable."
            f" Result: {result}"
        )
    else:
        # UNSUPPORTED_REQUEST or string message also acceptable
        assert isinstance(result, str)


def test_search_blocked_when_workspace_lacks_read_permission(
    tmp_path, monkeypatch,
):
    """
    Case 4: Workspace with WRITE+DELETE but NOT READ must not be searchable.
    """
    from app.agent import run_agent

    monkeypatch.setattr("app.agent.extract_intent", lambda _: {
        "action": "search", "filename": "private.txt",
        "extension": None, "directory": "NoReadWs",
    })

    ws_dir = tmp_path / "no_read_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(
        ws_dir, name="NoReadWs",
        permissions=["WRITE", "DELETE"],
    )

    target = ws_dir / "private.txt"
    target.write_text("private", encoding="utf-8")

    # Searching by name in NoReadWs — no READ permission
    result = run_agent("Find private.txt in NoReadWs")

    if isinstance(result, dict):
        msg = result.get("message", "").lower()
        files = result.get("files", [])
        # Should be blocked or return no files
        assert (
            result.get("found") is False
            or "blocked" in msg
            or len(files) == 0
        ), (
            "Non-READ workspace should not be searchable."
            f" Result: {result}"
        )


def test_search_blocked_for_unconfigured_directory(
    tmp_path, monkeypatch,
):
    """
    Case 5: Searching a directory that is NOT in any configured workspace must
    be rejected — not silently searched.
    """
    from app.agent import run_agent

    ws_dir = tmp_path / "auth_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(
        ws_dir, name="AuthWs", permissions=["READ"],
    )

    # This directory is NOT a configured workspace
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text(
        "secret", encoding="utf-8",
    )

    monkeypatch.setattr("app.agent.extract_intent", lambda _: {
        "action": "search", "filename": "secret.txt",
        "extension": None, "directory": str(outside_dir),
    })

    result = run_agent(f"Find secret.txt in {outside_dir}")

    if isinstance(result, dict):
        msg = result.get("message", "").lower()
        files = result.get("files", [])
        assert (
            result.get("found") is False
            or "blocked" in msg
            or len(files) == 0
        ), (
            "Unconfigured dir should not be searchable."
            f" Result: {result}"
        )


def test_search_blocked_for_traversal_attempt(tmp_path):
    """
    Case 6: Path traversal like 'workspace/../outside' must be blocked.
    """
    ws_dir = tmp_path / "safe_ws"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="SafeWs", permissions=["READ"])

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escape.txt").write_text("escaped", encoding="utf-8")

    traversal_path = ws_dir / ".." / "outside"
    ok, reason, _ = WorkspaceManager.check_workspace_authorization(
        traversal_path, Permission.READ.value
    )
    assert ok is False, "Traversal should be blocked"
    assert "outside" in reason.lower() or "configured" in reason.lower()


def test_search_aggregates_multiple_enabled_read_workspaces(
    tmp_path, monkeypatch,
):
    """
    Case 7: When multiple enabled READ workspaces exist and no directory is
    specified, search must aggregate results from ALL of them.
    """
    from app.agent import run_agent

    monkeypatch.setattr("app.agent.extract_intent", lambda _: {
        "action": "search", "filename": "",
        "extension": ".txt", "directory": None,
    })

    ws1_dir = tmp_path / "ws1"
    ws2_dir = tmp_path / "ws2"
    ws1_dir.mkdir()
    ws2_dir.mkdir()
    WorkspaceManager.add_workspace(
        ws1_dir, name="Ws1", permissions=["READ"],
    )
    WorkspaceManager.add_workspace(
        ws2_dir, name="Ws2", permissions=["READ"],
    )

    (ws1_dir / "alpha.txt").write_text(
        "alpha", encoding="utf-8",
    )
    (ws2_dir / "beta.txt").write_text(
        "beta", encoding="utf-8",
    )

    # Search for .txt files across all workspaces
    result = run_agent("Find all .txt files")

    assert isinstance(result, dict), (
        f"Expected dict, got: {result!r}"
    )
    found_paths = [
        f["path"] for f in result.get("files", [])
    ]
    paths_lower = [p.lower() for p in found_paths]
    assert any("alpha.txt" in p for p in paths_lower), (
        f"alpha.txt from ws1 not found: {found_paths}"
    )
    assert any("beta.txt" in p for p in paths_lower), (
        f"beta.txt from ws2 not found: {found_paths}"
    )


# ---------------------------------------------------------------------------
# X. Filename-with-extension normalization regression tests (cases 8-10)
# ---------------------------------------------------------------------------


def test_exact_filename_with_txt_extension(tmp_path, monkeypatch):
    """
    Case 8: 'Find m4_test.txt' — LLM may split into filename='m4_test' +
    extension='.txt'. The search branch must recombine these so that
    search_files receives filename='m4_test.txt' and finds the real file.
    """
    from app.agent import run_agent

    monkeypatch.setattr("app.agent.extract_intent", lambda _: {
        "action": "search", "filename": "m4_test",
        "extension": ".txt", "directory": None,
    })

    ws_dir = tmp_path / "ws_exact"
    ws_dir.mkdir()
    sub = ws_dir / "source"
    sub.mkdir()
    WorkspaceManager.add_workspace(
        ws_dir, name="ExactWs", permissions=["READ"],
    )

    target = sub / "m4_test.txt"
    target.write_text("milestone 4 test", encoding="utf-8")

    result = run_agent("Find m4_test.txt")

    assert isinstance(result, dict), (
        f"Expected dict, got: {result!r}"
    )
    assert result.get("found") is True, (
        f"m4_test.txt not found. Result: {result}"
    )
    found_paths = [
        f["path"] for f in result.get("files", [])
    ]
    assert any(
        "m4_test.txt" in p for p in found_paths
    ), f"m4_test.txt missing from results: {found_paths}"
    assert not any(
        "Downloads" in p for p in found_paths
    ), f"Unexpectedly searched Downloads: {found_paths}"


def test_exact_filename_in_named_workspace(
    tmp_path, monkeypatch,
):
    """
    Case 9: Natural-language 'Find m4_test.txt in ManualTest' — must resolve
    workspace by name, validate READ permission, and return the exact file.
    """
    from app.agent import run_agent

    monkeypatch.setattr("app.agent.extract_intent", lambda _: {
        "action": "search", "filename": "m4_test",
        "extension": ".txt", "directory": "ManualTest",
    })

    ws_dir = tmp_path / "manual_test"
    source_dir = ws_dir / "source"
    source_dir.mkdir(parents=True)
    WorkspaceManager.add_workspace(
        ws_dir, name="ManualTest", permissions=["READ"],
    )

    target = source_dir / "m4_test.txt"
    target.write_text(
        "milestone 4 test file", encoding="utf-8",
    )

    result = run_agent("Find m4_test.txt in ManualTest")

    assert isinstance(result, dict), (
        f"Expected dict, got: {result!r}"
    )
    assert result.get("found") is True, (
        f"m4_test.txt not found in ManualTest."
        f" Result: {result}"
    )
    found_paths = [
        f["path"] for f in result.get("files", [])
    ]
    assert any(
        "m4_test.txt" in p for p in found_paths
    ), f"m4_test.txt missing: {found_paths}"


def test_exact_filename_with_pdf_extension(
    tmp_path, monkeypatch,
):
    """
    Case 10a: 'Find report.pdf' — LLM may extract
    filename='report', extension='.pdf'.
    Normalization must recombine to 'report.pdf'.
    """
    from app.agent import run_agent

    monkeypatch.setattr("app.agent.extract_intent", lambda _: {
        "action": "search", "filename": "report",
        "extension": ".pdf", "directory": None,
    })

    ws_dir = tmp_path / "ws_pdf"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(
        ws_dir, name="PdfWs", permissions=["READ"],
    )

    target = ws_dir / "report.pdf"
    target.write_text("%PDF dummy", encoding="utf-8")

    result = run_agent("Find report.pdf")

    assert isinstance(result, dict), (
        f"Expected dict, got: {result!r}"
    )
    assert result.get("found") is True, (
        f"report.pdf not found. Result: {result}"
    )
    found_paths = [
        f["path"] for f in result.get("files", [])
    ]
    assert any(
        "report.pdf" in p for p in found_paths
    ), f"report.pdf missing: {found_paths}"


def test_exact_filename_with_docx_extension(
    tmp_path, monkeypatch,
):
    """
    Case 10b: 'Find resume.docx' — normalization must
    recombine correctly.
    """
    from app.agent import run_agent

    monkeypatch.setattr("app.agent.extract_intent", lambda _: {
        "action": "search", "filename": "resume",
        "extension": ".docx", "directory": None,
    })

    ws_dir = tmp_path / "ws_docx"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(
        ws_dir, name="DocxWs", permissions=["READ"],
    )

    target = ws_dir / "resume.docx"
    target.write_bytes(b"PK dummy docx content")

    result = run_agent("Find resume.docx")

    assert isinstance(result, dict), (
        f"Expected dict, got: {result!r}"
    )
    assert result.get("found") is True, (
        f"resume.docx not found. Result: {result}"
    )
    found_paths = [
        f["path"] for f in result.get("files", [])
    ]
    assert any(
        "resume.docx" in p for p in found_paths
    ), f"resume.docx missing: {found_paths}"


def test_exact_filename_already_has_extension_not_doubled(
    tmp_path, monkeypatch,
):
    """
    Guard: if the LLM returns filename='my_file.txt' with
    extension='.txt', the normalization must NOT produce
    'my_file.txt.txt'.
    Condition: filename.endswith(extension) → skip recombination.
    """
    from app.agent import run_agent

    monkeypatch.setattr("app.agent.extract_intent", lambda _: {
        "action": "search", "filename": "my_file.txt",
        "extension": ".txt", "directory": None,
    })

    ws_dir = tmp_path / "ws_guard"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(
        ws_dir, name="GuardWs", permissions=["READ"],
    )

    target = ws_dir / "my_file.txt"
    target.write_text("guard test", encoding="utf-8")

    result = run_agent("Find my_file.txt")

    assert isinstance(result, dict), (
        f"Expected dict, got: {result!r}"
    )
    assert result.get("found") is True, (
        f"my_file.txt not found. Result: {result}"
    )
    found_paths = [
        f["path"] for f in result.get("files", [])
    ]
    # File must be found exactly once with correct name
    assert any(
        "my_file.txt" in p for p in found_paths
    ), f"my_file.txt missing: {found_paths}"
    assert not any(
        "my_file.txt.txt" in p for p in found_paths
    ), f"Extension was doubled: {found_paths}"
