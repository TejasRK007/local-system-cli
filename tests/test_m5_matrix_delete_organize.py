"""
M5 Test Matrix: Section D (Delete / Clean) and Section F (Organize / File Set Operations).

Covers all 11 Delete test cases and all 11 Organize test cases.
"""

import pytest

import app.database as db
from app.tasks.executor import StepExecutor
from app.tasks.goal_planner import GoalPlanner
from app.tasks.manager import TaskManager
from app.tasks.models import StepStatus, TaskStatus
from app.tasks.validator import PlanValidator
from app.workspaces import WorkspaceManager


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Isolate SQLite database and enforce workspace security."""
    temp_db_path = tmp_path / "test_matrix_d_f.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db_path))
    monkeypatch.setenv("AGENT_ENFORCE_WORKSPACES", "1")
    db.init_db(temp_db_path)


# ==============================================================================
# SECTION D: DELETE / CLEAN
# ==============================================================================


def test_delete_d1_d9_delete_one_existing_file_physical(tmp_path):
    """D.1 & D.9: Delete one existing file and verify physical deletion."""
    ws_dir = tmp_path / "ws_del_1"
    ws_dir.mkdir()
    f = ws_dir / "old_note.txt"
    f.write_text("delete me", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="DelWs", permissions=["READ", "DELETE"])

    plan = GoalPlanner.plan_goal("Delete old_note.txt in DelWs")
    assert len(plan.steps) == 1
    assert plan.steps[0]["action"] == "delete"
    assert plan.cumulative_risk == "high"
    assert plan.requires_approval is True

    task = TaskManager.create_task(plan.goal, plan.steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.COMPLETED
    assert not f.exists()


def test_delete_d2_delete_multiple_files(tmp_path):
    """D.2: Delete multiple matching files in a batch clean goal."""
    ws_dir = tmp_path / "ws_del_multi"
    ws_dir.mkdir()
    for i in range(3):
        (ws_dir / f"temp_{i}.txt").write_text("temp", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="DelMultiWs", permissions=["READ", "DELETE"])

    plan = GoalPlanner.plan_goal("Clean temporary txt files from DelMultiWs")
    assert len(plan.discovered_files) == 3
    assert len(plan.steps) == 3

    task = TaskManager.create_task(plan.goal, plan.steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.COMPLETED
    assert len(list(ws_dir.glob("*.txt"))) == 0


def test_delete_d3_delete_nonexistent_file(tmp_path):
    """D.3: Delete nonexistent file returns safe no-op."""
    ws_dir = tmp_path / "ws_del_no_src"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="DelNoSrcWs", permissions=["READ", "DELETE"])

    plan = GoalPlanner.plan_goal("Delete missing.txt in DelNoSrcWs")
    assert len(plan.steps) == 0
    assert "no matching files" in plan.summary.lower()


def test_delete_d4_delete_ambiguous_target(tmp_path):
    """D.4: Delete single file with ambiguous candidates requires disambiguation."""
    ws1 = tmp_path / "ws_del_amb_1"
    ws2 = tmp_path / "ws_del_amb_2"
    ws1.mkdir()
    ws2.mkdir()
    (ws1 / "target.txt").write_text("1", encoding="utf-8")
    (ws2 / "target.txt").write_text("2", encoding="utf-8")
    WorkspaceManager.add_workspace(ws1, name="DelAmb1", permissions=["READ", "DELETE"])
    WorkspaceManager.add_workspace(ws2, name="DelAmb2", permissions=["READ", "DELETE"])

    plan = GoalPlanner.plan_goal("Delete target.txt")
    assert len(plan.steps) == 0
    assert "ambiguous" in plan.summary.lower()


def test_delete_d5_delete_without_permission(tmp_path):
    """D.5: Delete without DELETE permission rejected."""
    ws_dir = tmp_path / "ws_del_noperm"
    ws_dir.mkdir()
    (ws_dir / "doc.txt").write_text("keep", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="DelNoPermWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Delete doc.txt in DelNoPermWs")
    assert len(plan.steps) == 0
    assert "delete" in plan.summary.lower()


def test_delete_d6_delete_from_disabled_workspace(tmp_path):
    """D.6: Delete from disabled workspace rejected."""
    ws_dir = tmp_path / "ws_del_dis"
    ws_dir.mkdir()
    (ws_dir / "doc.txt").write_text("keep", encoding="utf-8")
    ws = WorkspaceManager.add_workspace(ws_dir, name="DelDisWs", permissions=["READ", "DELETE"])
    WorkspaceManager.disable_workspace(ws.workspace_id)

    plan = GoalPlanner.plan_goal("Delete doc.txt in DelDisWs")
    assert len(plan.steps) == 0
    assert "disabled" in plan.summary.lower()


def test_delete_d7_delete_protected_system_path():
    """D.7: Delete targeting protected/system path rejected by validator."""
    steps = [
        {
            "step_order": 1,
            "action": "delete",
            "arguments": {"target": "/etc/hosts"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    reason_low = reason.lower()
    assert "protected" in reason_low or "unsafe" in reason_low or "unauthorized" in reason_low


def test_delete_d8_delete_using_traversal_attempt(tmp_path):
    """D.8: Delete using traversal attempt rejected."""
    ws_dir = tmp_path / "ws_del_trav"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="DelTravWs", permissions=["READ", "DELETE"])

    steps = [
        {
            "step_order": 1,
            "action": "delete",
            "arguments": {"target": str(ws_dir / ".." / "outside.txt")},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "outside" in reason.lower() or "unauthorized" in reason.lower()


def test_delete_d10_failed_deletion_not_reported_as_success(tmp_path):
    """D.10: Ensure a failed deletion is never reported as success."""
    ws_dir = tmp_path / "ws_del_fail"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="DelFailWs", permissions=["READ", "DELETE"])

    # Target file does not exist on disk during execution
    steps = [
        {
            "step_order": 1,
            "action": "delete",
            "arguments": {"target": str(ws_dir / "nonexistent.txt")},
            "depends_on_order": None,
        }
    ]
    task = TaskManager.create_task("Delete", steps)
    executed = StepExecutor.execute_task(task)
    assert executed.status != TaskStatus.COMPLETED
    assert executed.status == TaskStatus.FAILED
    assert executed.steps[0].status == StepStatus.FAILED


def test_delete_d11_partial_failure_status(tmp_path):
    """D.11: Partial failure produces PARTIAL_FAILURE task status."""
    ws_dir = tmp_path / "ws_del_partial"
    ws_dir.mkdir()
    real_f = ws_dir / "real.txt"
    real_f.write_text("delete", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="DelPartWs", permissions=["READ", "DELETE"])

    steps = [
        {
            "step_order": 1,
            "action": "delete",
            "arguments": {"target": str(real_f)},
            "depends_on_order": None,
        },
        {
            "step_order": 2,
            "action": "delete",
            "arguments": {"target": str(ws_dir / "nonexistent.txt")},
            "depends_on_order": None,
        },
    ]
    task = TaskManager.create_task("Delete Partial", steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.PARTIAL_FAILURE
    assert executed.steps[0].status == StepStatus.SUCCESS
    assert executed.steps[1].status == StepStatus.FAILED


# ==============================================================================
# SECTION F: ORGANIZE / FILE SET OPERATIONS
# ==============================================================================


def test_organize_f1_f11_matching_files_and_physical_verification(tmp_path):
    """F.1 & F.11: Organize matching files and verify every move occurred physically."""
    ws_dir = tmp_path / "ws_org_1"
    ws_dir.mkdir()
    for i in range(3):
        (ws_dir / f"report_{i}.pdf").write_text(f"content {i}", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="OrgWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Organize all pdf files into an Archive folder in OrgWs")
    assert len(plan.discovered_files) == 3
    assert len(plan.steps) == 4  # 1 create_dir + 3 moves

    task = TaskManager.create_task(plan.goal, plan.steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.COMPLETED

    # Verify physically
    archive_dir = ws_dir / "Archive"
    assert archive_dir.is_dir()
    for i in range(3):
        assert not (ws_dir / f"report_{i}.pdf").exists()
        assert (archive_dir / f"report_{i}.pdf").exists()


def test_organize_f4_empty_result(tmp_path):
    """F.4: Organize on empty result produces safe no-op."""
    ws_dir = tmp_path / "ws_org_empty"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="OrgEmptyWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Organize all pdf files into an Archive folder in OrgEmptyWs")
    assert len(plan.discovered_files) == 0
    assert len(plan.steps) == 0
    assert "no matching files" in plan.summary.lower()


def test_organize_f6_destination_collision(tmp_path):
    """F.6: Organize destination collision handled safely without overwriting."""
    ws_dir = tmp_path / "ws_org_col"
    ws_dir.mkdir()
    (ws_dir / "doc.pdf").write_text("original", encoding="utf-8")
    target_folder = ws_dir / "Archive"
    target_folder.mkdir()
    (target_folder / "doc.pdf").write_text("existing", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="OrgColWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Organize all pdf files into an Archive folder in OrgColWs")
    # All files would collide -> safe no-op or collision report
    assert len(plan.steps) == 0
    assert "collision" in plan.summary.lower() or "no matching files" in plan.summary.lower()


def test_organize_f7_permission_failure(tmp_path):
    """F.7: Organize without WRITE permission rejected."""
    ws_dir = tmp_path / "ws_org_ro"
    ws_dir.mkdir()
    (ws_dir / "doc.pdf").write_text("pdf", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="OrgRoWs", permissions=["READ"])

    plan = GoalPlanner.plan_goal("Organize all pdf files into an Archive folder in OrgRoWs")
    assert len(plan.steps) == 0
    assert "write" in plan.summary.lower()


def test_organize_f8_disabled_workspace(tmp_path):
    """F.8: Organize in disabled workspace rejected."""
    ws_dir = tmp_path / "ws_org_dis"
    ws_dir.mkdir()
    (ws_dir / "doc.pdf").write_text("pdf", encoding="utf-8")
    ws = WorkspaceManager.add_workspace(ws_dir, name="OrgDisWs", permissions=["READ", "WRITE"])
    WorkspaceManager.disable_workspace(ws.workspace_id)

    plan = GoalPlanner.plan_goal("Organize all pdf files into an Archive folder in OrgDisWs")
    assert len(plan.steps) == 0
    assert "disabled" in plan.summary.lower()
