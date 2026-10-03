"""
M5 Test Matrix: Section I (Execution / Verification) and Section J (Persistence).

Covers all 12 Execution/Verification test cases and all 9 Persistence test cases.
"""

import pytest
from typer.testing import CliRunner

import app.database as db
from app.main import app
from app.recovery import (
    FailureCategory,
    classify_failure,
    execute_action_with_recovery,
)
from app.tasks.executor import StepExecutor
from app.tasks.manager import TaskManager
from app.tasks.models import StepStatus, TaskStatus
from app.workspaces import WorkspaceManager

runner = CliRunner()


@pytest.fixture(autouse=True)
def setup_isolated_env(tmp_path, monkeypatch):
    """Ensure every test executes against a fresh isolated temporary SQLite database."""
    temp_db_path = tmp_path / "test_m5_exec_persist.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db_path))
    monkeypatch.setenv("GROQ_API_KEY", "dummy_groq_api_key_for_testing")
    db.init_db(temp_db_path)
    yield


# ==============================================================================
# SECTION I: EXECUTION AND VERIFICATION
# ==============================================================================


def test_exec_i1_i2_i3_successful_execution_and_physical_observation(tmp_path):
    """I.1, I.2, I.3: Successful execution verifies physical destination exists."""
    ws_dir = tmp_path / "ws_exec_success"
    ws_dir.mkdir()
    src = ws_dir / "item.txt"
    src.write_text("success", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="ExecSuccessWs", permissions=["READ", "WRITE"])

    steps = [
        {
            "step_order": 1,
            "action": "rename",
            "arguments": {"source": str(src), "new_name": "item_done.txt"},
            "depends_on_order": None,
        }
    ]
    task = TaskManager.create_task("Rename Task", steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)

    assert executed.status == TaskStatus.COMPLETED
    assert executed.steps[0].status == StepStatus.SUCCESS
    assert not src.exists()
    assert (ws_dir / "item_done.txt").exists()


def test_exec_i4_executor_failure(tmp_path):
    """I.4: Executor failure when underlying OS operation fails."""
    ws_dir = tmp_path / "ws_exec_fail"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="ExecFailWs", permissions=["READ", "WRITE"])

    # Attempt to move non-existent source
    steps = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {
                "source": str(ws_dir / "missing.txt"),
                "destination": str(ws_dir),
            },
            "depends_on_order": None,
        }
    ]
    task = TaskManager.create_task("Move Fail", steps)
    executed = StepExecutor.execute_task(task)
    assert executed.status == TaskStatus.FAILED
    assert executed.steps[0].status == StepStatus.FAILED


def test_exec_i5_verification_failure(tmp_path):
    """I.5: Verification failure if physical observation fails."""
    ws_dir = tmp_path / "ws_verif_fail"
    ws_dir.mkdir()
    f = ws_dir / "phantom.txt"
    # Do not write file physically

    # Classification test for verification failure
    msg = "Verified: phantom.txt was deleted successfully."
    res = classify_failure("delete", msg, source_path=f)
    assert res.category in (
        FailureCategory.EXECUTION_FAILURE,
        FailureCategory.VERIFICATION_FAILURE,
    )


def test_exec_i6_partial_failure(tmp_path):
    """I.6: Partial failure correctly sets task state."""
    ws_dir = tmp_path / "ws_exec_part"
    ws_dir.mkdir()
    f1 = ws_dir / "f1.txt"
    f1.write_text("1", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="PartWs", permissions=["READ", "WRITE", "DELETE"])

    steps = [
        {
            "step_order": 1,
            "action": "delete",
            "arguments": {"target": str(f1)},
            "depends_on_order": None,
        },
        {
            "step_order": 2,
            "action": "delete",
            "arguments": {"target": str(ws_dir / "ghost.txt")},
            "depends_on_order": None,
        },
    ]
    task = TaskManager.create_task("Partial Task", steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.PARTIAL_FAILURE
    assert executed.steps[0].status == StepStatus.SUCCESS
    assert executed.steps[1].status == StepStatus.FAILED


def test_exec_i7_retryable_failure():
    """I.7: Transient failure classified as RETRYABLE."""
    res = classify_failure("move", "Error: resource temporarily unavailable")
    assert res.category == FailureCategory.RETRYABLE
    assert res.retryable is True


def test_exec_i8_conflict():
    """I.8: Destination conflict classified as CONFLICT."""
    conflict_msg = "Move blocked: a file with the same name already exists at target"
    res = classify_failure("move", conflict_msg)
    assert res.category == FailureCategory.CONFLICT
    assert res.retryable is False


def test_exec_i9_policy_violation(tmp_path):
    """I.9: Policy violation rejects execution and updates state."""
    ws_dir = tmp_path / "ws_policy"
    ws_dir.mkdir()
    f = ws_dir / "test.txt"
    f.write_text("test", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="PolicyWs", permissions=["READ"])  # Read only

    # Try delete without permission
    steps = [
        {
            "step_order": 1,
            "action": "delete",
            "arguments": {"target": str(f)},
            "depends_on_order": None,
        }
    ]
    task = TaskManager.create_task("Policy Task", steps)
    executed = StepExecutor.execute_task(task)
    assert executed.status == TaskStatus.FAILED
    err = executed.steps[0].error_info.lower()
    assert "policy" in err or "violation" in err


def test_exec_i10_recovery_mechanism():
    """I.10: execute_action_with_recovery executes with bounded retries."""
    attempt_count = 0

    def mock_transient_action(path):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 2:
            return "Error: resource temporarily unavailable"
        return "Verified: success"

    res = execute_action_with_recovery(
        action="search",
        action_func=mock_transient_action,
        func_args=("/dummy",),
        max_retries=2,
    )
    assert res["status"] == "SUCCESS"
    assert res["attempts"] == 2


def test_exec_i11_i12_no_false_success_state(tmp_path):
    """I.11 & I.12: A failed task never reports COMPLETED or Goal Completed."""
    ws_dir = tmp_path / "ws_false_success"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="FalseSuccessWs", permissions=["READ", "WRITE"])

    steps = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {
                "source": str(ws_dir / "phantom.txt"),
                "destination": str(ws_dir),
            },
            "depends_on_order": None,
        }
    ]
    task = TaskManager.create_task("Failing Task", steps)
    executed = StepExecutor.execute_task(task)
    assert executed.status != TaskStatus.COMPLETED
    assert executed.status == TaskStatus.FAILED


# ==============================================================================
# SECTION J: PERSISTENCE
# ==============================================================================


def test_persist_j1_j2_task_and_steps_written_to_sqlite(tmp_path):
    """J.1 & J.2: Task and steps are persisted in SQLite."""
    steps = [
        {
            "step_order": 1,
            "action": "search",
            "arguments": {"directory": "/tmp"},
            "depends_on_order": None,
        },
        {
            "step_order": 2,
            "action": "search",
            "arguments": {"directory": "/tmp"},
            "depends_on_order": 1,
        },
    ]
    task = TaskManager.create_task("Persist Goal", steps)
    retrieved = TaskManager.get_task(task.task_id)
    assert retrieved is not None
    assert retrieved.task_id == task.task_id
    assert len(retrieved.steps) == 2
    assert retrieved.steps[0].action == "search"
    assert retrieved.steps[1].depends_on_step_id == retrieved.steps[0].step_id


def test_persist_j3_status_changes_correctly(tmp_path):
    """J.3: Task status changes are persisted in SQLite."""
    steps = [
        {"step_order": 1, "action": "search", "arguments": {}, "depends_on_order": None}
    ]
    task = TaskManager.create_task("Status Goal", steps)
    assert task.status == TaskStatus.PENDING

    TaskManager.update_task_state(task, TaskStatus.RUNNING)
    reloaded = TaskManager.get_task(task.task_id)
    assert reloaded.status == TaskStatus.RUNNING

    TaskManager.update_task_state(task, TaskStatus.COMPLETED)
    reloaded2 = TaskManager.get_task(task.task_id)
    assert reloaded2.status == TaskStatus.COMPLETED


def test_persist_j4_task_status_command_retrieves_task(tmp_path):
    """J.4: CLI task-status command retrieves the task."""
    steps = [
        {"step_order": 1, "action": "search", "arguments": {}, "depends_on_order": None}
    ]
    task = TaskManager.create_task("CLI Status Goal", steps)
    res = runner.invoke(app, ["task-status", task.task_id])
    assert res.exit_code == 0
    assert task.task_id in res.output


def test_persist_j5_task_history_survives_reconnect(tmp_path):
    """J.5: Task history survives database reconnection."""
    steps = [
        {"step_order": 1, "action": "search", "arguments": {}, "depends_on_order": None}
    ]
    task = TaskManager.create_task("Reconnect Goal", steps)

    # Reload from fresh DB connection
    all_tasks = TaskManager.list_tasks(limit=10)
    assert any(t.task_id == task.task_id for t in all_tasks)


def test_persist_j6_failed_tasks_remain_failed(tmp_path):
    """J.6: Failed tasks remain failed after retrieval."""
    steps = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": "/nonexistent", "destination": "/tmp"},
            "depends_on_order": None,
        }
    ]
    task = TaskManager.create_task("Fail Goal", steps)
    executed = StepExecutor.execute_task(task)
    assert executed.status == TaskStatus.FAILED

    reloaded = TaskManager.get_task(task.task_id)
    assert reloaded.status == TaskStatus.FAILED


def test_persist_j7_successful_tasks_remain_completed(tmp_path):
    """J.7: Completed tasks remain completed after retrieval."""
    ws_dir = tmp_path / "ws_persist_comp"
    ws_dir.mkdir()
    f = ws_dir / "doc.txt"
    f.write_text("doc", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="CompWs", permissions=["READ", "WRITE"])

    steps = [
        {
            "step_order": 1,
            "action": "rename",
            "arguments": {"source": str(f), "new_name": "renamed.txt"},
            "depends_on_order": None,
        }
    ]
    task = TaskManager.create_task("Comp Goal", steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.COMPLETED

    reloaded = TaskManager.get_task(task.task_id)
    assert reloaded.status == TaskStatus.COMPLETED


def test_persist_j8_audit_records_remain_available(tmp_path):
    """J.8: Audit records remain available in database."""
    db.log_event(
        user_request="Test Audit",
        action="search",
        risk_level="low",
        approval_required=False,
        approval_result="NOT_REQUIRED",
        execution_status="SUCCESS",
        result_summary="Audit event logged",
    )
    logs = db.get_recent_logs(limit=10)
    assert any("Test Audit" in log.get("user_request", "") for log in logs)


def test_persist_j9_workspace_removal_does_not_destroy_history(tmp_path):
    """J.9: Workspace removal does not destroy task or audit records."""
    ws_dir = tmp_path / "ws_persist_remove"
    ws_dir.mkdir()
    ws = WorkspaceManager.add_workspace(ws_dir, name="RemoveWs", permissions=["READ"])

    task_steps = [
        {"step_order": 1, "action": "search", "arguments": {}, "depends_on_order": None}
    ]
    task = TaskManager.create_task("Task Before Removal", task_steps)
    db.log_event(
        user_request="Audit Before Removal",
        action="search",
        risk_level="low",
        approval_required=False,
        approval_result="NOT_REQUIRED",
        execution_status="SUCCESS",
        result_summary="Audit logged",
    )

    # Remove workspace
    WorkspaceManager.remove_workspace(ws.workspace_id)

    # Task and audit records must still exist
    reloaded_task = TaskManager.get_task(task.task_id)
    assert reloaded_task is not None
    assert reloaded_task.task_id == task.task_id

    logs = db.get_recent_logs(limit=10)
    assert any("Audit Before Removal" in log.get("user_request", "") for log in logs)
