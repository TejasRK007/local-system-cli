"""
Tests for the persistent SQLite audit logging system.

Requirements covered:
  1. Successful search creates an audit entry.
  2. Approved rename creates an audit entry.
  3. Cancelled delete creates an audit entry.
  4. Successful delete creates an audit entry.
  5. Ambiguous request creates an audit entry.
  6. Unsupported request creates an audit entry.
  7. Logs CLI command displays entries in a clean Rich table (including --limit).
  8. Secrets (API keys, tokens, passwords) are never stored or exposed.
  9. Full CLI integration via Typer runner for agent lifecycle flows.
"""

import pytest
from typer.testing import CliRunner

import app.database as db
from app.main import app

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
# 1. Successful search creates audit entry
# ---------------------------------------------------------------------------


def test_successful_search_creates_audit_entry():
    """Verify logging a successful search records the expected row."""
    row_id = db.log_event(
        user_request="Find all PDF files in Downloads",
        action="search",
        risk_level="low",
        approval_required=False,
        approval_result="NOT_REQUIRED",
        execution_status="SUCCESS",
        result_summary="Found 3 matching file(s)",
    )

    assert row_id > 0
    logs = db.get_recent_logs(limit=10)
    assert len(logs) == 1

    entry = logs[0]
    assert entry["id"] == row_id
    assert entry["user_request"] == "Find all PDF files in Downloads"
    assert entry["action"] == "search"
    assert entry["risk_level"] == "low"
    assert entry["approval_required"] == 0
    assert entry["approval_result"] == "NOT_REQUIRED"
    assert entry["execution_status"] == "SUCCESS"
    assert "Found 3 matching file(s)" in entry["result_summary"]
    assert entry["timestamp"]


# ---------------------------------------------------------------------------
# 2. Approved rename creates audit entry
# ---------------------------------------------------------------------------


def test_approved_rename_creates_audit_entry():
    """Verify an approved rename records APPROVED and SUCCESS."""
    row_id = db.log_event(
        user_request="Rename report_draft.txt to report_final.txt",
        action="rename",
        risk_level="medium",
        approval_required=True,
        approval_result="APPROVED",
        execution_status="SUCCESS",
        result_summary="Verified: file renamed successfully",
    )

    assert row_id > 0
    logs = db.get_recent_logs(limit=5)
    assert len(logs) == 1
    entry = logs[0]
    assert entry["action"] == "rename"
    assert entry["risk_level"] == "medium"
    assert entry["approval_required"] == 1
    assert entry["approval_result"] == "APPROVED"
    assert entry["execution_status"] == "SUCCESS"
    assert "Verified" in entry["result_summary"]


# ---------------------------------------------------------------------------
# 3. Cancelled delete creates audit entry
# ---------------------------------------------------------------------------


def test_cancelled_delete_creates_audit_entry():
    """Verify user cancellation of a delete records DENIED and CANCELLED."""
    row_id = db.log_event(
        user_request="Delete old_archive.zip in Downloads",
        action="delete",
        risk_level="high",
        approval_required=True,
        approval_result="DENIED",
        execution_status="CANCELLED",
        result_summary="Cancelled deletion of 1 file(s)",
    )

    assert row_id > 0
    logs = db.get_recent_logs(limit=5)
    assert len(logs) == 1
    entry = logs[0]
    assert entry["action"] == "delete"
    assert entry["risk_level"] == "high"
    assert entry["approval_required"] == 1
    assert entry["approval_result"] == "DENIED"
    assert entry["execution_status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# 4. Successful delete creates audit entry
# ---------------------------------------------------------------------------


def test_successful_delete_creates_audit_entry():
    """Verify an approved delete execution records APPROVED and SUCCESS."""
    row_id = db.log_event(
        user_request="Delete temp_debug.log in Downloads",
        action="delete",
        risk_level="high",
        approval_required=True,
        approval_result="APPROVED",
        execution_status="SUCCESS",
        result_summary="Deleted 1 file(s)",
    )

    assert row_id > 0
    logs = db.get_recent_logs(limit=5)
    entry = logs[0]
    assert entry["action"] == "delete"
    assert entry["risk_level"] == "high"
    assert entry["approval_required"] == 1
    assert entry["approval_result"] == "APPROVED"
    assert entry["execution_status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 5. Ambiguous request creates audit entry
# ---------------------------------------------------------------------------


def test_ambiguous_request_creates_audit_entry():
    """Verify an ambiguous request refusal records AMBIGUOUS and NOT_APPLICABLE."""
    row_id = db.log_event(
        user_request="Rename duplicate.txt to new.txt",
        action="ambiguous",
        risk_level="medium",
        approval_required=True,
        approval_result="NOT_APPLICABLE",
        execution_status="AMBIGUOUS",
        result_summary="Ambiguous: 2 matching files found",
    )

    assert row_id > 0
    logs = db.get_recent_logs(limit=5)
    entry = logs[0]
    assert entry["action"] == "ambiguous"
    assert entry["approval_result"] == "NOT_APPLICABLE"
    assert entry["execution_status"] == "AMBIGUOUS"
    assert "Ambiguous" in entry["result_summary"]


# ---------------------------------------------------------------------------
# 6. Unsupported request creates audit entry
# ---------------------------------------------------------------------------


def test_unsupported_request_creates_audit_entry():
    """Verify an unsupported request records NOT_SUPPORTED and NOT_APPLICABLE."""
    row_id = db.log_event(
        user_request="Order a pizza online",
        action="unsupported",
        risk_level="low",
        approval_required=False,
        approval_result="NOT_APPLICABLE",
        execution_status="NOT_SUPPORTED",
        result_summary="Request was not recognized or is unsupported.",
    )

    assert row_id > 0
    logs = db.get_recent_logs(limit=5)
    entry = logs[0]
    assert entry["action"] == "unsupported"
    assert entry["approval_result"] == "NOT_APPLICABLE"
    assert entry["execution_status"] == "NOT_SUPPORTED"


# ---------------------------------------------------------------------------
# 7. Logs command displays entries and respects --limit
# ---------------------------------------------------------------------------


def test_logs_command_displays_entries():
    """Verify python -m app.main logs renders rows and column headers in Rich table."""
    # Seed 3 rows
    db.log_event("Find PDFs", "search", "low", False, "NOT_REQUIRED", "SUCCESS", "Found 2 files")
    db.log_event(
        "Rename a to b", "rename", "medium", True, "APPROVED", "SUCCESS", "Verified rename"
    )
    db.log_event("Delete c", "delete", "high", True, "DENIED", "CANCELLED", "User denied")

    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0
    output = result.output

    # Check table headers
    for header in ["ID", "Timestamp", "Action", "Risk", "Approval", "Status", "Request"]:
        assert header in output

    # Check content values
    assert "search" in output
    assert "rename" in output
    assert "delete" in output
    assert "SUCCESS" in output
    assert "CANCELLED" in output
    assert "APPROVED" in output
    assert "DENIED" in output


def test_logs_command_limit_option():
    """Verify python -m app.main logs --limit restricts displayed count."""
    for i in range(5):
        db.log_event(
            f"Request #{i}", "search", "low", False, "NOT_REQUIRED", "SUCCESS", f"Found {i}"
        )

    result = runner.invoke(app, ["logs", "--limit", "2"])
    assert result.exit_code == 0
    assert "Showing latest 2" in result.output
    # Newest entries (4 and 3) should appear, entry 0 should not
    assert "Request #4" in result.output
    assert "Request #3" in result.output
    assert "Request #0" not in result.output


def test_logs_command_empty_database():
    """Verify python -m app.main logs shows informative message when no logs exist."""
    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0
    assert "No audit log entries found" in result.output


# ---------------------------------------------------------------------------
# 8. Secrets are not stored or exposed
# ---------------------------------------------------------------------------


def test_secrets_are_not_stored_or_exposed(monkeypatch):
    """Verify API keys, tokens, and passwords are sanitized before persistence."""
    fake_groq_key = "gsk_testsecretgroqkey1234567890abcdef"
    fake_openai_key = "sk-testsecretopenaikey1234567890abcdef"
    fake_password = "password=SuperSecretPassword123"

    monkeypatch.setenv("GROQ_API_KEY", fake_groq_key)

    # User mistakenly pastes an API key and password into request and summary
    db.log_event(
        user_request=f"Search files using {fake_groq_key} and {fake_password}",
        action="search",
        risk_level="low",
        approval_required=False,
        approval_result="NOT_REQUIRED",
        execution_status="SUCCESS",
        result_summary=f"Key: {fake_openai_key}",
    )

    logs = db.get_recent_logs(limit=1)
    entry = logs[0]

    # Raw secrets must NOT be in DB
    assert fake_groq_key not in entry["user_request"]
    assert "SuperSecretPassword123" not in entry["user_request"]
    assert fake_openai_key not in entry["result_summary"]

    # Redacted markers should be present
    assert "[REDACTED]" in entry["user_request"]
    assert "[REDACTED]" in entry["result_summary"]

    # Render via CLI command logs to verify output does not leak secrets
    res = runner.invoke(app, ["logs"])
    assert res.exit_code == 0
    assert fake_groq_key not in res.output
    assert "SuperSecretPassword123" not in res.output
    assert fake_openai_key not in res.output


# ---------------------------------------------------------------------------
# 9. CLI End-to-End Integration Tests
# ---------------------------------------------------------------------------


def test_cli_agent_search_creates_audit_entry(monkeypatch):
    """End-to-end: running 'agent <search request>' creates an audit entry."""
    monkeypatch.setattr(
        "app.main.run_agent",
        lambda req: {
            "found": True,
            "count": 2,
            "files": [
                {"path": "/Users/test/Downloads/a.pdf", "created": "2026-09-28 10:00:00"},
                {"path": "/Users/test/Downloads/b.pdf", "created": "2026-09-28 10:01:00"},
            ],
        },
    )

    result = runner.invoke(app, ["agent", "Find all PDF files in Downloads"])
    assert result.exit_code == 0

    logs = db.get_recent_logs(limit=5)
    assert len(logs) == 1
    assert logs[0]["action"] == "search"
    assert logs[0]["risk_level"] == "low"
    assert logs[0]["approval_required"] == 0
    assert logs[0]["approval_result"] == "NOT_REQUIRED"
    assert logs[0]["execution_status"] == "SUCCESS"
    assert "Found 2 matching file(s)" in logs[0]["result_summary"]


def test_cli_agent_unsupported_creates_audit_entry(monkeypatch):
    """End-to-end: unsupported agent request records NOT_SUPPORTED."""
    monkeypatch.setattr("app.main.run_agent", lambda req: "UNSUPPORTED_REQUEST")

    result = runner.invoke(app, ["agent", "Fly me to the moon"])
    assert result.exit_code == 0

    logs = db.get_recent_logs(limit=5)
    assert len(logs) == 1
    assert logs[0]["action"] == "unsupported"
    assert logs[0]["approval_result"] == "NOT_APPLICABLE"
    assert logs[0]["execution_status"] == "NOT_SUPPORTED"


def test_cli_agent_ambiguous_rename_creates_audit_entry(monkeypatch):
    """End-to-end: ambiguous rename request records AMBIGUOUS."""
    monkeypatch.setattr(
        "app.main.run_agent",
        lambda req: {
            "action": "rename",
            "source_files": [
                {"path": "/Users/test/Downloads/dup.txt", "created": "2026-09-28"},
                {"path": "/Users/test/Documents/dup.txt", "created": "2026-09-28"},
            ],
            "new_name": "renamed.txt",
            "directory_specified": False,
        },
    )

    result = runner.invoke(app, ["agent", "Rename dup.txt to renamed.txt"])
    assert result.exit_code == 0

    logs = db.get_recent_logs(limit=5)
    assert len(logs) == 1
    assert logs[0]["action"] == "ambiguous"
    assert logs[0]["approval_result"] == "NOT_APPLICABLE"
    assert logs[0]["execution_status"] == "AMBIGUOUS"


def test_cli_agent_cancelled_rename_creates_audit_entry(monkeypatch):
    """End-to-end: user answering 'n' to rename records CANCELLED."""
    monkeypatch.setattr(
        "app.main.run_agent",
        lambda req: {
            "action": "rename",
            "source_files": [
                {"path": "/Users/test/Downloads/doc.txt", "created": "2026-09-28"},
            ],
            "new_name": "renamed.txt",
            "directory_specified": True,
        },
    )

    # Provide 'n' as input for confirmation prompt
    result = runner.invoke(app, ["agent", "Rename doc.txt to renamed.txt"], input="n\n")
    assert result.exit_code == 0

    logs = db.get_recent_logs(limit=5)
    assert len(logs) == 1
    assert logs[0]["action"] == "rename"
    assert logs[0]["approval_result"] == "DENIED"
    assert logs[0]["execution_status"] == "CANCELLED"


def test_cli_agent_approved_rename_creates_audit_entry(monkeypatch):
    """End-to-end: user answering 'y' to rename records APPROVED and SUCCESS."""
    monkeypatch.setattr(
        "app.main.run_agent",
        lambda req: {
            "action": "rename",
            "source_files": [
                {"path": "/Users/test/Downloads/doc.txt", "created": "2026-09-28"},
            ],
            "new_name": "renamed.txt",
            "directory_specified": True,
        },
    )
    monkeypatch.setattr(
        "app.main.rename_file",
        lambda src, new_name: f"Verified: file successfully renamed to {new_name}",
    )

    result = runner.invoke(app, ["agent", "Rename doc.txt to renamed.txt"], input="y\n")
    assert result.exit_code == 0

    logs = db.get_recent_logs(limit=5)
    assert len(logs) == 1
    assert logs[0]["action"] == "rename"
    assert logs[0]["approval_result"] == "APPROVED"
    assert logs[0]["execution_status"] == "SUCCESS"
    assert "Verified" in logs[0]["result_summary"]


def test_cli_agent_cancelled_delete_creates_audit_entry(monkeypatch):
    """End-to-end: user answering 'n' to delete records CANCELLED."""
    monkeypatch.setattr(
        "app.main.run_agent",
        lambda req: {
            "found": True,
            "count": 1,
            "files": [
                {"path": "/Users/test/Downloads/temp.txt", "created": "2026-09-28"},
            ],
        },
    )

    result = runner.invoke(app, ["agent", "Delete temp.txt in Downloads"], input="n\n")
    assert result.exit_code == 0

    logs = db.get_recent_logs(limit=5)
    assert len(logs) == 1
    assert logs[0]["action"] == "delete"
    assert logs[0]["approval_result"] == "DENIED"
    assert logs[0]["execution_status"] == "CANCELLED"


def test_cli_agent_approved_delete_creates_audit_entry(monkeypatch):
    """End-to-end: user answering 'y' to delete records APPROVED and SUCCESS."""
    monkeypatch.setattr(
        "app.main.run_agent",
        lambda req: {
            "found": True,
            "count": 1,
            "files": [
                {"path": "/Users/test/Downloads/temp.txt", "created": "2026-09-28"},
            ],
        },
    )
    monkeypatch.setattr(
        "app.main.delete_file",
        lambda path: f"Verified: file deleted: {path}",
    )

    result = runner.invoke(app, ["agent", "Delete temp.txt in Downloads"], input="y\n")
    assert result.exit_code == 0

    logs = db.get_recent_logs(limit=5)
    assert len(logs) == 1
    assert logs[0]["action"] == "delete"
    assert logs[0]["approval_result"] == "APPROVED"
    assert logs[0]["execution_status"] == "SUCCESS"


def test_cli_direct_delete_creates_audit_entry(monkeypatch):
    """End-to-end: direct 'delete <path>' command records audit entry."""
    monkeypatch.setattr(
        "app.main.delete_file",
        lambda path: f"Verified: deleted {path}",
    )

    result = runner.invoke(app, ["delete", "/Users/test/Downloads/direct.txt"], input="y\n")
    assert result.exit_code == 0

    logs = db.get_recent_logs(limit=5)
    assert len(logs) == 1
    assert logs[0]["action"] == "delete"
    assert logs[0]["approval_result"] == "APPROVED"
    assert logs[0]["execution_status"] == "SUCCESS"
