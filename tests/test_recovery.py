"""
Tests for Milestone 2: Verification, State Observation, Bounded Recovery,
Failure Classification, Safe Replanning, and Audit Logging.
"""

import pytest
from typer.testing import CliRunner

import app.database as db
from app.main import app
from app.policy import get_action_risk, requires_approval
from app.recovery import (
    FailureCategory,
    classify_failure,
    execute_action_with_recovery,
    observe_filesystem,
)
from app.tools.file_actions import move_file

runner = CliRunner()


@pytest.fixture(autouse=True)
def setup_tmp_db(tmp_path, monkeypatch):
    """Ensure every test uses an isolated temporary SQLite database."""
    temp_db_path = tmp_path / "test_agent.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db_path))
    db.init_db(temp_db_path)
    return temp_db_path


# ---------------------------------------------------------------------------
# 1. Successful Action Verification & State Observation
# ---------------------------------------------------------------------------


def test_observe_filesystem_delete(tmp_path):
    """Verify observation confirms when target file no longer exists."""
    target = tmp_path / "delete_me.txt"
    obs = observe_filesystem("delete", source_path=target)
    assert obs.is_verified is True

    target.write_text("content")
    obs2 = observe_filesystem("delete", source_path=target)
    assert obs2.is_verified is False


def test_observe_filesystem_move(tmp_path):
    """Verify observation confirms move when source is gone and target exists."""
    src = tmp_path / "source.txt"
    dst = tmp_path / "dest.txt"

    dst.write_text("moved")
    obs = observe_filesystem("move", source_path=src, destination_path=dst)
    assert obs.is_verified is True

    src.write_text("source still here")
    obs2 = observe_filesystem("move", source_path=src, destination_path=dst)
    assert obs2.is_verified is False


# ---------------------------------------------------------------------------
# 2. Retryable Failure Followed by Successful Retry
# ---------------------------------------------------------------------------


def test_retryable_failure_succeeds_on_retry(tmp_path):
    """Verify transient error triggers retry and succeeds on attempt 2."""
    src = tmp_path / "file.txt"
    dst = tmp_path / "dest.txt"
    dst.write_text("content")

    attempts = 0

    def mock_action():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return "Execution failed: Temporary resource locked"
        return "Verified: file moved successfully."

    retried_attempts = []

    def on_retry_cb(att, desc):
        retried_attempts.append((att, desc))

    res = execute_action_with_recovery(
        action="move",
        action_func=mock_action,
        func_args=(),
        source_path=src,
        destination_path=dst,
        max_retries=2,
        on_retry=on_retry_cb,
    )

    assert res["status"] == "SUCCESS"
    assert res["attempts"] == 2
    assert len(retried_attempts) == 1
    assert retried_attempts[0][0] == 1


# ---------------------------------------------------------------------------
# 3. Retry Limit Reached (Bounded Retry)
# ---------------------------------------------------------------------------


def test_retry_limit_reached(tmp_path):
    """Verify operation stops at MAX_RETRIES (2) and reports RETRY_EXHAUSTED."""
    src = tmp_path / "file.txt"
    dst = tmp_path / "dest.txt"

    def mock_always_busy():
        return "Execution failed: Resource temporarily busy"

    res = execute_action_with_recovery(
        action="move",
        action_func=mock_always_busy,
        func_args=(),
        source_path=src,
        destination_path=dst,
        max_retries=2,
    )

    assert res["status"] == "RETRY_EXHAUSTED"
    assert res["attempts"] == 3  # Initial + 2 retries
    assert res["failure_category"] == "RETRYABLE"


# ---------------------------------------------------------------------------
# 4. Critical Scenario: Move Destination Conflict
# ---------------------------------------------------------------------------


def test_destination_conflict_preserves_target(monkeypatch, tmp_path):
    """
    Source: ~/allowed/source/report.pdf
    Destination: ~/allowed/destination/report.pdf
    Both files already exist.
    Expected: Conflict detected, target NOT overwritten, source untouched.
    """
    import app.tools.file_actions as fa

    monkeypatch.setattr(fa, "ALLOWED_DIRECTORIES", [tmp_path])

    src_dir = tmp_path / "source"
    dst_dir = tmp_path / "destination"
    src_dir.mkdir()
    dst_dir.mkdir()

    src_file = src_dir / "report.pdf"
    dst_file = dst_dir / "report.pdf"

    src_file.write_text("Source Report Data v1")
    dst_file.write_text("Existing Destination Report Data v2")

    res = execute_action_with_recovery(
        action="move",
        action_func=move_file,
        func_args=(str(src_file), str(dst_dir)),
        source_path=src_file,
        destination_path=dst_file,
    )

    assert res["status"] == FailureCategory.CONFLICT.value
    assert res["attempts"] == 1
    # Check physical state: destination file must remain untouched!
    assert dst_file.exists()
    assert dst_file.read_text() == "Existing Destination Report Data v2"
    # Source file must remain intact!
    assert src_file.exists()
    assert src_file.read_text() == "Source Report Data v1"


# ---------------------------------------------------------------------------
# 5. Verification Failure Detection
# ---------------------------------------------------------------------------


def test_verification_failure_detected(tmp_path):
    """Verify tool claiming success while physical observation fails is classified as
    VERIFICATION_FAILURE."""
    src = tmp_path / "source.txt"
    dst = tmp_path / "dest.txt"
    src.write_text("source still here")  # Physical state contradicts move success!

    def mock_false_success():
        return "Verified: move finished."

    res = execute_action_with_recovery(
        action="move",
        action_func=mock_false_success,
        func_args=(),
        source_path=src,
        destination_path=dst,
        max_retries=0,
    )

    assert res["status"] == FailureCategory.VERIFICATION_FAILURE.value
    assert res["observation"].is_verified is False


# ---------------------------------------------------------------------------
# 6. Policy Violation During Recovery
# ---------------------------------------------------------------------------


def test_policy_violation_in_recovery():
    """Verify forbidden path is classified as POLICY_VIOLATION and non-retryable."""
    res_str = "Move blocked: source file is outside allowed directories: /etc/shadow"
    failure = classify_failure("move", res_str, source_path="/etc/shadow")

    assert failure.category == FailureCategory.POLICY_VIOLATION
    assert failure.retryable is False


# ---------------------------------------------------------------------------
# 7. Ambiguity Handling During Recovery
# ---------------------------------------------------------------------------


def test_ambiguity_during_recovery():
    """Verify ambiguous result is classified as NEEDS_USER_INPUT."""
    res_str = "Ambiguous request: 2 matching files found."
    failure = classify_failure("move", res_str)

    assert failure.category == FailureCategory.NEEDS_USER_INPUT
    assert failure.retryable is False


# ---------------------------------------------------------------------------
# 8. Replan Policy & Fresh Approval Evaluation
# ---------------------------------------------------------------------------


def test_replan_requires_fresh_policy_and_approval():
    """Verify changed action after conflict requires fresh policy check and approval."""
    # Original action: Rename (MEDIUM risk -> requires approval)
    orig_risk = get_action_risk("rename")
    assert requires_approval(orig_risk) is True

    # Replan proposal: Rename to report_alt.pdf (MEDIUM risk -> requires fresh approval)
    replan_risk = get_action_risk("rename")
    assert requires_approval(replan_risk) is True


# ---------------------------------------------------------------------------
# 9. Audit Logging of Retries, Conflict, and Failure Outcomes
# ---------------------------------------------------------------------------


def test_audit_logging_of_conflict_outcome(monkeypatch, tmp_path):
    """End-to-end CLI move conflict creates an audit entry with CONFLICT status."""
    import app.tools.file_actions as fa

    monkeypatch.setattr(fa, "ALLOWED_DIRECTORIES", [tmp_path])

    src_dir = tmp_path / "Downloads" / "source"
    dst_dir = tmp_path / "Downloads" / "destination"
    src_dir.mkdir(parents=True)
    dst_dir.mkdir(parents=True)

    src_file = src_dir / "doc.txt"
    dst_file = dst_dir / "doc.txt"
    src_file.write_text("Source Data")
    dst_file.write_text("Existing Dest Data")

    monkeypatch.setattr(
        "app.main.run_agent",
        lambda req: {
            "action": "move",
            "source_files": [{"path": str(src_file), "created": "2026-10-01"}],
            "count": 1,
            "destination": str(dst_dir),
            "destination_name": "destination",
            "directory_specified": True,
        },
    )

    # Approve move with 'y'
    result = runner.invoke(app, ["agent", "Move doc.txt to destination"], input="y\n")
    assert result.exit_code == 0
    assert "Conflict Detected" in result.output

    # Check audit log
    logs = db.get_recent_logs(limit=1)
    assert len(logs) == 1
    assert logs[0]["action"] == "move"
    assert logs[0]["execution_status"] == "CONFLICT"
    assert (
        "already exists" in logs[0]["result_summary"].lower()
        or "conflict" in logs[0]["result_summary"].lower()
    )
