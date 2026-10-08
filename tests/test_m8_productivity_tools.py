"""
Comprehensive test suite for Milestone 8: Personal Automation & Productivity Integrations.

Tests:
1. Document Reading & Summarization (safe text/markdown, secret masking, workspace containment)
2. Browser Automation (clean HTML extraction, search structure, workspace-confined download)
3. Email Tools (search, read with redaction, draft staging, outbound dispatch with audit)
4. Calendar Tools (listing, conflict detection, event creation)
5. GitHub Tools (issue query, PR inspection, offline staging)
6. Policy & Approval Gating (LOW auto-approved, MEDIUM/HIGH requiring confirmation)
7. StepExecutor Integration (executing M8 steps through the task pipeline)
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

import app.database as db
from app.policy import get_action_risk, requires_approval
from app.tasks.executor import StepExecutor
from app.tasks.models import StepStatus, Task, TaskStatus, TaskStep
from app.tasks.validator import PlanValidator
from app.tools.browser_tools import browser_download_file, browser_fetch_page, browser_search
from app.tools.calendar_tools import (
    calendar_check_conflict,
    calendar_create_event,
    calendar_list_events,
)
from app.tools.document_tools import read_document, summarize_document
from app.tools.email_tools import email_draft, email_read, email_search, email_send
from app.tools.github_tools import github_create_issue, github_list_issues
from app.workspaces import WorkspaceManager


@pytest.fixture(autouse=True)
def setup_isolated_env(tmp_path, monkeypatch):
    """Isolate SQLite database and workspaces for each test."""
    test_db = tmp_path / "test_m8.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    monkeypatch.setenv("AGENT_DB_PATH", str(test_db))
    db.init_db(test_db)
    yield


# =============================================================================
# 1. DOCUMENT READING & SUMMARIZATION TESTS
# =============================================================================


def test_document_read_success_and_secret_redaction(tmp_path):
    ws_dir = tmp_path / "DocWs"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="DocWs", permissions=["READ", "WRITE"])

    secret_doc = ws_dir / "notes.txt"
    secret_doc.write_text(
        "Project Report:\n"
        "Config details: api_key='gsk_abcdef1234567890abcdef' and token: 'my_secret_token_123'.\n"
        "Database is running smoothly.\n",
        encoding="utf-8",
    )

    res = read_document(str(secret_doc))
    assert res["success"] is True
    assert res["filename"] == "notes.txt"
    assert res["workspace"] == "DocWs"
    assert "[REDACTED" in res["content"]
    assert "gsk_abcdef" not in res["content"]


def test_document_read_unauthorized_outside_workspace(tmp_path):
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("Confidential information", encoding="utf-8")

    res = read_document(str(outside_file))
    assert res["success"] is False
    assert res["status"] == "PERMISSION_DENIED"


def test_document_read_disabled_or_no_read_permission(tmp_path):
    ws_dir = tmp_path / "NoReadWs"
    ws_dir.mkdir()
    ws = WorkspaceManager.add_workspace(ws_dir, name="NoReadWs", permissions=["WRITE"])
    doc = ws_dir / "file.txt"
    doc.write_text("Test", encoding="utf-8")

    # Lacks READ
    res = read_document(str(doc))
    assert res["success"] is False
    assert res["status"] == "PERMISSION_DENIED"

    # Disabled
    WorkspaceManager.set_permissions(ws.workspace_id, ["READ", "WRITE"])
    WorkspaceManager.disable_workspace(ws.workspace_id)
    res_disabled = read_document(str(doc))
    assert res_disabled["success"] is False
    assert res_disabled["status"] == "PERMISSION_DENIED"


def test_document_summarization(tmp_path):
    ws_dir = tmp_path / "SummaryWs"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="SummaryWs", permissions=["READ"])

    report_file = ws_dir / "quarterly.md"
    report_file.write_text(
        "# Quarterly Review\n\n"
        "We achieved all milestone objectives ahead of schedule.\n"
        "System reliability improved to 99.9% uptime.\n"
        "Next quarter will focus on cloud and edge extensions.\n",
        encoding="utf-8",
    )

    summary_res = summarize_document(str(report_file))
    assert summary_res["success"] is True
    assert summary_res["word_count"] > 10
    assert len(summary_res["key_points"]) > 0
    # Original file must remain untouched
    assert report_file.exists()


# =============================================================================
# 2. BROWSER AUTOMATION TESTS
# =============================================================================


def test_browser_fetch_page_clean_html():
    raw_html = (
        "<html><head><title>Test Page</title><style>.hidden{display:none}</style></head>"
        "<body><h1>Header</h1><p>Main content paragraph.</p>"
        "<script>alert(1);</script></body></html>"
    )

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.headers.get_content_type.return_value = "text/html"
        mock_resp.headers.get_content_charset.return_value = "utf-8"
        mock_resp.read.return_value = raw_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = browser_fetch_page("https://example.com/test")
        assert res["success"] is True
        assert res["title"] == "Test Page"
        assert "Main content paragraph." in res["content"]
        assert "alert(1)" not in res["content"]
        assert "display:none" not in res["content"]


def test_browser_fetch_page_invalid_scheme():
    res = browser_fetch_page("file:///etc/passwd")
    assert res["success"] is False
    assert res["status"] == "POLICY_VIOLATION"


def test_browser_search():
    res = browser_search("local agent automation")
    assert res["success"] is True
    assert res["results_count"] >= 1
    assert "local agent automation" in res["results"][0]["title"]


def test_browser_download_file_contained_in_workspace(tmp_path):
    ws_dir = tmp_path / "DownloadsWs"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="DownloadsWs", permissions=["READ", "WRITE"])

    sample_content = b"PDF-1.4 dummy binary content"

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = sample_content
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = browser_download_file(
            url="https://example.com/manual.pdf",
            dest_workspace="DownloadsWs",
            filename="manual.pdf",
        )
        assert res["success"] is True
        assert res["bytes_downloaded"] == len(sample_content)

        downloaded_file = ws_dir / "manual.pdf"
        assert downloaded_file.exists()
        assert downloaded_file.read_bytes() == sample_content


def test_browser_download_file_no_overwrite_conflict(tmp_path):
    ws_dir = tmp_path / "ConflictWs"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="ConflictWs", permissions=["READ", "WRITE"])

    existing = ws_dir / "sample.pdf"
    existing.write_bytes(b"existing content")

    res = browser_download_file(
        url="https://example.com/sample.pdf",
        dest_workspace="ConflictWs",
        filename="sample.pdf",
    )
    assert res["success"] is False
    assert res["status"] == "CONFLICT"


# =============================================================================
# 3. EMAIL AUTOMATION TESTS
# =============================================================================


def test_email_draft_and_send():
    # 1. Draft (MEDIUM risk staging)
    draft_res = email_draft(
        to_address="test@example.com",
        subject="Meeting Followup",
        body="Here are the notes from today's discussion.",
    )
    assert draft_res["success"] is True
    assert draft_res["status"] == "DRAFT_SAVED"
    draft_id = draft_res["draft_id"]

    # 2. Outbound Send (HIGH risk execution)
    send_res = email_send(
        to_address="test@example.com",
        subject="Meeting Followup",
        body="Here are the notes from today's discussion.",
        draft_id=draft_id,
    )
    assert send_res["success"] is True
    assert send_res["status"] == "SENT"


def test_email_search_and_read_with_redaction():
    # Insert test email directly into inbox
    conn = sqlite3.connect(db.DB_PATH)
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS email_inbox (
                id TEXT PRIMARY KEY, sender TEXT, subject TEXT, body TEXT, received_at TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO email_inbox (id, sender, subject, body) VALUES (?, ?, ?, ?)",
            (
                "msg-101",
                "alice@example.com",
                "Project Status Update",
                "Please find the password: 'my_top_secret_pw'",
            ),
        )
    conn.close()

    # Search
    search_res = email_search("Status")
    assert search_res["success"] is True
    assert search_res["count"] == 1
    assert search_res["messages"][0]["id"] == "msg-101"

    # Read with redaction
    read_res = email_read("msg-101")
    assert read_res["success"] is True
    assert "[REDACTED]" in read_res["message"]["body"]
    assert "my_top_secret_pw" not in read_res["message"]["body"]


# =============================================================================
# 4. CALENDAR AUTOMATION TESTS
# =============================================================================


def test_calendar_events_and_conflict_detection():
    # Create event
    ev1 = calendar_create_event(
        title="Sprint Standup",
        start_time="2026-10-08T09:00:00",
        end_time="2026-10-08T09:30:00",
        description="Daily standup",
    )
    assert ev1["success"] is True

    # List events
    events_res = calendar_list_events()
    assert events_res["count"] == 1
    assert events_res["events"][0]["title"] == "Sprint Standup"

    # Detect conflict (overlapping interval: 09:15 to 09:45)
    conflict_res = calendar_check_conflict(
        start_time="2026-10-08T09:15:00",
        end_time="2026-10-08T09:45:00",
    )
    assert conflict_res["has_conflict"] is True
    assert conflict_res["conflicts_count"] == 1

    # Non-conflicting interval (10:00 to 11:00)
    no_conflict = calendar_check_conflict(
        start_time="2026-10-08T10:00:00",
        end_time="2026-10-08T11:00:00",
    )
    assert no_conflict["has_conflict"] is False


# =============================================================================
# 5. GITHUB AUTOMATION TESTS
# =============================================================================


def test_github_tools_offline_and_validation():
    # Invalid repository format rejection
    bad_res = github_list_issues("invalid_format")
    assert bad_res["success"] is False
    assert bad_res["status"] == "VALIDATION_FAILURE"

    # Offline issue creation staging
    staged = github_create_issue(
        repo="TejasRK007/local-system-cli",
        title="Test Issue M8",
        body="Staged issue body",
    )
    assert staged["success"] is True
    assert staged["status"] == "STAGED_OFFLINE"


# =============================================================================
# 6. POLICY RISK CLASSIFICATION & VALIDATOR
# =============================================================================


def test_policy_risk_levels():
    assert get_action_risk("read_document") == "low"
    assert get_action_risk("summarize_document") == "low"
    assert get_action_risk("browser_fetch_page") == "low"
    assert get_action_risk("browser_download_file") == "medium"
    assert get_action_risk("email_draft") == "medium"
    assert get_action_risk("email_send") == "high"
    assert get_action_risk("calendar_create_event") == "medium"
    assert get_action_risk("github_create_issue") == "medium"

    assert requires_approval("low") is False
    assert requires_approval("medium") is True
    assert requires_approval("high") is True


def test_plan_validator_accepts_m8_actions():
    steps = [
        {"step_order": 1, "action": "browser_search", "arguments": {"query": "python"}},
        {"step_order": 2, "action": "calendar_list_events", "arguments": {}},
        {
            "step_order": 3,
            "action": "email_draft",
            "arguments": {"to": "user@example.com", "subject": "Hi", "body": "Hello"},
        },
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is True
    assert "Plan is valid" in reason


# =============================================================================
# 7. STEP EXECUTOR INTEGRATION FOR M8
# =============================================================================


def test_step_executor_m8_flow(tmp_path):
    ws_dir = tmp_path / "TaskWs"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="TaskWs", permissions=["READ", "WRITE"])
    test_doc = ws_dir / "readme.txt"
    test_doc.write_text("Hello from Milestone 8 Task Executor!", encoding="utf-8")

    task = Task(
        task_id="task-m8-001",
        user_request="Read and draft email",
        steps=[
            TaskStep(
                step_id="s1",
                task_id="task-m8-001",
                step_order=1,
                action="read_document",
                arguments={"path": str(test_doc)},
            ),
            TaskStep(
                step_id="s2",
                task_id="task-m8-001",
                step_order=2,
                action="email_draft",
                arguments={
                    "to": "dev@example.com",
                    "subject": "Doc summary",
                    "body": "$output.s1.content",
                },
            ),
        ],
    )

    # Execute task with auto-approval for testing
    executed_task = StepExecutor.execute_task(task, confirm_callback=lambda a, p, d: True)
    assert executed_task.status == TaskStatus.COMPLETED
    assert executed_task.steps[0].status == StepStatus.SUCCESS
    assert executed_task.steps[1].status == StepStatus.SUCCESS
