"""
Automated test suite for Milestone 3: Stateful Multi-Step Task Execution.

Covers:
- A. Task creation & persistence
- B. Single-step task
- C. Two-step sequential task
- D. Dependency enforcement
- E. Successful output passing between steps
- F. Step approval
- G. Step denial
- H. Step failure
- I. Dependent step skipped after failure
- J. Partial failure
- K. Retry through existing recovery engine
- L. Persistent task state
- M. Task status retrieval
- N. Safe MOVE/RENAME compensation
- O. DELETE is never blindly rolled back
- P. Full regression baseline
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import app.database as db
import app.tools.file_actions as fa
from app.main import app
from app.tasks.executor import StepExecutor
from app.tasks.manager import TaskManager
from app.tasks.models import StepStatus, TaskStatus

runner = CliRunner()


class MockLLM:
    """Mock LLM response generator for planner and agent."""

    def __init__(self, content: str):
        self.content = content

    def invoke(self, prompt):
        class Response:
            pass

        res = Response()
        res.content = self.content
        return res


@pytest.fixture(autouse=True)
def setup_task_env(tmp_path, monkeypatch):
    """Ensure isolated SQLite DB and temporary allowed directories."""
    temp_db_path = tmp_path / "test_agent.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db_path))
    db.init_db(temp_db_path)

    # Set ALLOWED_DIRECTORIES to include tmp_path
    monkeypatch.setattr(
        fa,
        "ALLOWED_DIRECTORIES",
        [tmp_path, Path.home() / "Downloads", Path.home() / "Documents", Path.home() / "Desktop"],
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# A. Task Creation & Persistence
# ---------------------------------------------------------------------------


def test_task_creation_and_persistence():
    """Verify task and steps are properly instantiated and persisted to SQLite."""
    steps_spec = [
        {"step_order": 1, "action": "move", "arguments": {"source": "a.txt", "destination": "dst"}},
        {
            "step_order": 2,
            "action": "rename",
            "arguments": {"source": "$output.step_1.path", "new_name": "b.txt"},
            "depends_on_order": 1,
        },
    ]
    task = TaskManager.create_task("Move a.txt to dst and rename to b.txt", steps_spec)

    assert task.task_id.startswith("task_")
    assert task.status == TaskStatus.PENDING
    assert len(task.steps) == 2
    assert task.steps[0].step_order == 1
    assert task.steps[1].depends_on_step_id == task.steps[0].step_id

    # Retrieve from DB
    loaded = TaskManager.get_task(task.task_id)
    assert loaded is not None
    assert loaded.task_id == task.task_id
    assert loaded.status == TaskStatus.PENDING
    assert len(loaded.steps) == 2
    assert loaded.steps[1].depends_on_step_id == loaded.steps[0].step_id


# ---------------------------------------------------------------------------
# B. Single-Step Task Execution
# ---------------------------------------------------------------------------


def test_single_step_task_execution(tmp_path):
    """Verify single-step task runs to completion and updates SQLite status."""
    src = tmp_path / "doc.txt"
    dst = tmp_path / "target_dir"
    src.write_text("Hello World")
    dst.mkdir()

    steps_spec = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(src), "destination": str(dst)},
        }
    ]
    task = TaskManager.create_task("Move doc.txt", steps_spec)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, det: True)

    assert executed.status == TaskStatus.COMPLETED
    assert executed.steps[0].status == StepStatus.SUCCESS
    assert not src.exists()
    assert (dst / "doc.txt").exists()


# ---------------------------------------------------------------------------
# C. Two-Step Sequential Task & E. Output Passing
# ---------------------------------------------------------------------------


def test_two_step_sequential_task_with_output_passing(tmp_path):
    """
    Step 1: Move report.pdf to destination.
    Step 2: Rename moved report.pdf to final_report.pdf using verified output from Step 1.
    """
    src_dir = tmp_path / "source"
    dst_dir = tmp_path / "destination"
    src_dir.mkdir()
    dst_dir.mkdir()

    report_file = src_dir / "report.pdf"
    report_file.write_text("Report content v1")

    steps_spec = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(report_file), "destination": str(dst_dir)},
            "depends_on_order": None,
        },
        {
            "step_order": 2,
            "action": "rename",
            "arguments": {"source": "$output.step_1.path", "new_name": "final_report.pdf"},
            "depends_on_order": 1,
        },
    ]

    task = TaskManager.create_task("Move and rename report", steps_spec)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, det: True)

    assert executed.status == TaskStatus.COMPLETED
    assert executed.steps[0].status == StepStatus.SUCCESS
    assert executed.steps[1].status == StepStatus.SUCCESS

    # Verify physical filesystem state
    assert not (src_dir / "report.pdf").exists()
    assert not (dst_dir / "report.pdf").exists()
    final_file = dst_dir / "final_report.pdf"
    assert final_file.exists()
    assert final_file.read_text() == "Report content v1"


# ---------------------------------------------------------------------------
# D. Dependency Enforcement & I. Dependent Step Skipped After Failure
# ---------------------------------------------------------------------------


def test_dependency_enforcement_skips_subsequent_step(tmp_path):
    """If Step 1 fails, Step 2 (dependent) must be marked SKIPPED, not FAILED or SUCCESS."""
    dst_dir = tmp_path / "destination"
    dst_dir.mkdir()

    # Source file intentionally does NOT exist -> Step 1 fails
    non_existent = tmp_path / "ghost.pdf"

    steps_spec = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(non_existent), "destination": str(dst_dir)},
            "depends_on_order": None,
        },
        {
            "step_order": 2,
            "action": "rename",
            "arguments": {"source": "$output.step_1.path", "new_name": "final.pdf"},
            "depends_on_order": 1,
        },
    ]

    task = TaskManager.create_task("Move ghost and rename", steps_spec)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, det: True)

    assert executed.status == TaskStatus.FAILED
    assert executed.steps[0].status == StepStatus.FAILED
    assert executed.steps[1].status == StepStatus.SKIPPED
    assert "Skipped" in str(executed.steps[1].error_info)


# ---------------------------------------------------------------------------
# F. Step Approval & G. Step Denial
# ---------------------------------------------------------------------------


def test_step_denial_halts_task_and_skips_dependencies(tmp_path):
    """Denying approval on Step 1 must halt execution, fail Step 1, skip Step 2, and cancel task."""
    src = tmp_path / "file.txt"
    dst = tmp_path / "destination"
    src.write_text("data")
    dst.mkdir()

    steps_spec = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(src), "destination": str(dst)},
        },
        {
            "step_order": 2,
            "action": "rename",
            "arguments": {"source": "$output.step_1.path", "new_name": "new.txt"},
            "depends_on_order": 1,
        },
    ]

    task = TaskManager.create_task("Move and rename", steps_spec)

    # Deny approval when callback is invoked
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, det: False)

    assert executed.status == TaskStatus.CANCELLED
    assert executed.steps[0].status == StepStatus.FAILED
    assert "denied" in str(executed.steps[0].error_info).lower()
    assert executed.steps[1].status == StepStatus.SKIPPED
    # Physical file remained untouched
    assert src.exists()


# ---------------------------------------------------------------------------
# H. Step Failure & J. Partial Failure
# ---------------------------------------------------------------------------


def test_partial_failure_status(tmp_path):
    """When Step 1 succeeds and Step 2 fails, task status must be PARTIAL_FAILURE."""
    src_dir = tmp_path / "source"
    dst_dir = tmp_path / "destination"
    src_dir.mkdir()
    dst_dir.mkdir()

    file_a = src_dir / "data.txt"
    file_a.write_text("Hello")

    # Destination already has conflicting file for Step 2 rename
    (dst_dir / "already_exists.txt").write_text("Conflict")

    steps_spec = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(file_a), "destination": str(dst_dir)},
        },
        # Renaming to 'already_exists.txt' will fail due to conflict!
        {
            "step_order": 2,
            "action": "rename",
            "arguments": {"source": "$output.step_1.path", "new_name": "already_exists.txt"},
            "depends_on_order": 1,
        },
    ]

    task = TaskManager.create_task("Move and conflicting rename", steps_spec)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, det: True)

    assert executed.status == TaskStatus.PARTIAL_FAILURE
    assert executed.steps[0].status == StepStatus.SUCCESS
    assert executed.steps[1].status == StepStatus.FAILED
    assert "Conflict" in str(executed.steps[1].error_info) or "already exists" in str(
        executed.steps[1].error_info
    )


# ---------------------------------------------------------------------------
# K. Retry Integration via Recovery Engine
# ---------------------------------------------------------------------------


def test_step_retry_integration(monkeypatch, tmp_path):
    """Verify transient error in step execution triggers retry mechanism."""
    src = tmp_path / "file.txt"
    dst = tmp_path / "destination"
    src.write_text("data")
    dst.mkdir()

    attempts = 0

    def mock_move(s, d):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return "Move failed: Temporary resource locked"
        s_path = Path(s)
        d_path = Path(d) / s_path.name
        d_path.write_text(s_path.read_text())
        s_path.unlink()
        return "Verified: file moved successfully."

    monkeypatch.setattr("app.tasks.executor.move_file", mock_move)

    steps_spec = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(src), "destination": str(dst)},
        }
    ]
    task = TaskManager.create_task("Move with retry", steps_spec)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, det: True)

    assert executed.status == TaskStatus.COMPLETED
    assert executed.steps[0].status == StepStatus.SUCCESS
    assert executed.steps[0].attempts == 2


# ---------------------------------------------------------------------------
# L. Persistent Task State & M. Task Status Retrieval via CLI
# ---------------------------------------------------------------------------


def test_task_cli_commands(tmp_path):
    """Test `tasks` and `task-status` CLI commands."""
    src = tmp_path / "file.txt"
    dst = tmp_path / "destination"
    src.write_text("test")
    dst.mkdir()

    steps_spec = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(src), "destination": str(dst)},
        }
    ]
    task = TaskManager.create_task("Test CLI Task", steps_spec)
    StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, det: True)

    # 1. Test `tasks` listing command
    res_list = runner.invoke(app, ["tasks"])
    assert res_list.exit_code == 0
    assert task.task_id in res_list.output
    assert "COMPLETED" in res_list.output

    # 2. Test `task-status` command
    res_status = runner.invoke(app, ["task-status", task.task_id])
    assert res_status.exit_code == 0
    assert task.task_id in res_status.output
    assert "COMPLETED" in res_status.output
    assert "SUCCESS" in res_status.output


# ---------------------------------------------------------------------------
# N. Safe Compensation / Rollback
# ---------------------------------------------------------------------------


def test_safe_compensation_rolls_back_completed_steps(tmp_path):
    """Verify compensation reverses prior move when step 2 fails and compensation is requested."""
    src_dir = tmp_path / "source"
    dst_dir = tmp_path / "destination"
    src_dir.mkdir()
    dst_dir.mkdir()

    src_file = src_dir / "item.txt"
    src_file.write_text("Rollback content")

    # Create destination file to force step 2 failure
    (dst_dir / "target.txt").write_text("Blocked")

    steps_spec = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(src_file), "destination": str(dst_dir)},
        },
        {
            "step_order": 2,
            "action": "rename",
            "arguments": {"source": "$output.step_1.path", "new_name": "target.txt"},
            "depends_on_order": 1,
        },
    ]

    task = TaskManager.create_task("Move and fail rename", steps_spec)
    executed = StepExecutor.execute_task(
        task,
        confirm_callback=lambda act, prompt, det: True,
        compensate_on_failure=True,
    )

    assert executed.status == TaskStatus.PARTIAL_FAILURE
    assert executed.steps[0].status == StepStatus.SUCCESS
    assert executed.steps[1].status == StepStatus.FAILED

    # Check physical state: Step 1 (move) was compensated! The file is moved back to src_dir!
    assert src_file.exists()
    assert src_file.read_text() == "Rollback content"
    assert not (dst_dir / "item.txt").exists()


# ---------------------------------------------------------------------------
# O. DELETE is Never Blindly Rolled Back
# ---------------------------------------------------------------------------


def test_delete_is_never_rolled_back(tmp_path):
    """Verify compensation explicitly refuses to fake-restore deleted files."""
    test_file = tmp_path / "del.txt"
    test_file.write_text("Permanently gone")

    steps_spec = [
        {"step_order": 1, "action": "delete", "arguments": {"target": str(test_file)}},
    ]
    task = TaskManager.create_task("Delete file", steps_spec)
    StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, det: True)

    assert not test_file.exists()

    # Attempt compensation
    results = TaskManager.compensate_task(task)
    assert len(results) == 1
    assert results[0]["action"] == "rollback_delete"
    assert results[0]["status"] == "NOT_SUPPORTED"
    assert "permanent" in results[0]["summary"].lower()


# ---------------------------------------------------------------------------
# End-to-End Task CLI Execution with Planner
# ---------------------------------------------------------------------------


def test_cli_task_command_end_to_end(monkeypatch, tmp_path):
    """End-to-end execution of `task` CLI command with planner mock."""
    src_dir = tmp_path / "source"
    dst_dir = tmp_path / "destination"
    src_dir.mkdir()
    dst_dir.mkdir()

    file_a = src_dir / "report.pdf"
    file_a.write_text("PDF report")

    mock_planner_output = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(file_a), "destination": str(dst_dir)},
            "depends_on_order": None,
        },
        {
            "step_order": 2,
            "action": "rename",
            "arguments": {"source": "$output.step_1.path", "new_name": "final_report.pdf"},
            "depends_on_order": 1,
        },
    ]

    monkeypatch.setattr("app.main.plan_task_steps", lambda req: mock_planner_output)

    # Approve both steps with 'y\ny\n'
    res = runner.invoke(
        app, ["task", "Move report.pdf and rename to final_report.pdf"], input="y\ny\n"
    )

    assert res.exit_code == 0
    assert "Task Created:" in res.output
    assert "Task Completed" in res.output

    # Check physical state
    assert not file_a.exists()
    assert not (dst_dir / "report.pdf").exists()
    final_pdf = dst_dir / "final_report.pdf"
    assert final_pdf.exists()
    assert final_pdf.read_text() == "PDF report"

    # Verify task in DB
    tasks = db.list_task_records()
    assert len(tasks) > 0
    latest_task = tasks[0]
    assert latest_task["status"] == "COMPLETED"

    # Verify task steps in DB
    steps = db.get_task_steps_records(latest_task["task_id"])
    assert len(steps) == 2
    assert all(s["status"] == "SUCCESS" for s in steps)

    # Verify audit records exist
    audit_logs = db.get_recent_logs(limit=10)
    assert len(audit_logs) >= 2
    actions = [log_item["action"] for log_item in audit_logs]
    assert "move" in actions
    assert "rename" in actions
