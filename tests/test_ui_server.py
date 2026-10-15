"""Tests for the Local Agent Web UI FastAPI server endpoints."""

from fastapi.testclient import TestClient

from app.server import app
from app.workspaces import WorkspaceManager

client = TestClient(app)


def test_ui_index_html() -> None:
    """Ensure the static frontend root returns the dashboard HTML."""
    response = client.get("/")
    assert response.status_code == 200
    assert "AI Manager" in response.text
    assert "Ask AI" in response.text


def test_api_status() -> None:
    """Ensure /api/status returns model, provider, workspaces, and system metrics."""
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "llm_provider" in data
    assert "llm_model" in data
    assert "workspaces_count" in data


def test_api_workspaces() -> None:
    """Ensure /api/workspaces returns list of registered workspaces."""
    response = client.get("/api/workspaces")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_api_audit_log() -> None:
    """Ensure /api/audit returns the recent log entries."""
    response = client.get("/api/audit?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_api_tasks_plan() -> None:
    """Ensure /api/tasks/plan generates a validated task execution plan."""
    response = client.post("/api/tasks/plan", json={"goal": "organize files in sandbox"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "task_id" in data
    assert "steps" in data
    assert isinstance(data["steps"], list)


def test_api_chat_plan() -> None:
    """Ensure /api/chat synthesizes a plan for actionable goals."""
    response = client.post("/api/chat", json={"message": "organize files in sandbox"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["type"] == "plan"
    assert "steps" in data


def test_api_chat_conversation() -> None:
    """Ensure /api/chat returns conversational assistance for general messages."""
    response = client.post("/api/chat", json={"message": "hello, what are your capabilities?"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["type"] == "conversation"
    assert "message" in data


def test_api_document_read_safe(tmp_path) -> None:
    """Ensure /api/docs/read endpoint correctly handles safe read."""
    from app.workspaces import WorkspaceManager

    ws_dir = tmp_path / "DocsWs"
    ws_dir.mkdir(exist_ok=True)
    WorkspaceManager.add_workspace(ws_dir, name="DocsWs", permissions=["READ"])

    sample_doc = ws_dir / "sample.md"
    sample_doc.write_text("# Test Document\n\nSafe read content.", encoding="utf-8")

    response = client.post(
        "/api/docs/read",
        json={"path": str(sample_doc), "max_chars": 4000},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "content" in data
    assert "Safe read content" in data["content"]


def test_api_browser_fetch() -> None:
    """Ensure /api/browser/fetch validates and executes URL extraction safely."""
    response = client.post(
        "/api/browser/fetch",
        json={"url": "https://example.com", "max_chars": 1000},
    )
    assert response.status_code == 200
    data = response.json()
    assert "success" in data


def test_api_email_endpoints() -> None:
    """Ensure all email endpoints for inbox, summarize, reply, and account work."""
    # 1. Account get
    acc_res = client.get("/api/email/account")
    assert acc_res.status_code == 200
    assert acc_res.json()["success"] is True

    # 2. Sync
    sync_res = client.post("/api/email/sync")
    assert sync_res.status_code == 200
    assert sync_res.json()["success"] is True

    # 3. Inbox
    inbox_res = client.get("/api/email/inbox")
    assert inbox_res.status_code == 200
    inbox_data = inbox_res.json()
    assert inbox_data["success"] is True
    assert len(inbox_data["messages"]) > 0
    test_msg_id = inbox_data["messages"][0]["id"]

    # 4. Read
    read_res = client.get(f"/api/email/read?id={test_msg_id}")
    assert read_res.status_code == 200
    assert read_res.json()["success"] is True

    # 5. Summarize
    sum_res = client.post("/api/email/summarize", json={"message_id": test_msg_id})
    assert sum_res.status_code == 200
    assert sum_res.json()["success"] is True
    assert "summary" in sum_res.json()

    # 6. Generate reply
    reply_res = client.post(
        "/api/email/generate_reply",
        json={"message_id": test_msg_id, "tone": "professional", "user_notes": "We are aligned."},
    )
    assert reply_res.status_code == 200
    reply_data = reply_res.json()
    assert reply_data["success"] is True
    assert "body" in reply_data
    assert "to" in reply_data


def test_api_chat_device_storage() -> None:
    """Ensure /api/chat accurately inspects device storage."""
    response = client.post("/api/chat", json={"message": "can you see my device storage"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Device & System Metrics" in data["message"]
    assert "Free Space" in data["message"]


def test_api_chat_check_mails() -> None:
    """Ensure /api/chat inspects email inbox status."""
    response = client.post("/api/chat", json={"message": "can you check any new mails"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Email Inbox Status" in data["message"]


def test_api_chat_with_attachment() -> None:
    """Ensure /api/chat analyzes attached documents."""
    import base64

    fake_txt = (
        "Local Agentic System\nDeveloper handover roadmap from M1 to M10.\n"
        "Purpose and operating principle."
    )
    b64_content = base64.b64encode(fake_txt.encode("utf-8")).decode("utf-8")
    payload = {
        "message": "what is this",
        "attachments": [
            {
                "name": "sample_handover.txt",
                "data": f"data:text/plain;base64,{b64_content}",
            }
        ],
    }
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Document Analysis" in data["message"]
    assert "sample_handover.txt" in data["message"]


def test_api_chat_morning_briefing() -> None:
    """Ensure /api/chat synthesizes an executive morning briefing without emojis."""
    import re

    response = client.post("/api/chat", json={"message": "Give me today's morning briefing"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    msg = data["message"]
    assert "Executive Briefing" in msg
    assert "Actionable Communications" in msg
    # Verify no emojis exist in the response
    emoji_pattern = re.compile(r"[\U00010000-\U0010ffff\u2600-\u27bf]")
    assert not emoji_pattern.search(msg), f"Emojis found in morning briefing: {msg}"


def test_api_email_read_raw_html() -> None:
    """Ensure /api/email/read returns raw_html alongside sanitized body."""
    inbox_res = client.get("/api/email/inbox")
    assert inbox_res.status_code == 200
    inbox_data = inbox_res.json()
    assert len(inbox_data.get("messages", [])) > 0
    test_id = inbox_data["messages"][0]["id"]

    response = client.get(f"/api/email/read?id={test_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    msg = data["message"]
    assert "body" in msg
    assert "raw_html" in msg
    assert isinstance(msg["body"], str)


def test_api_chat_tasks_today() -> None:
    """Ensure conversational queries about tasks for today return agenda and events."""
    response = client.post("/api/chat", json={"message": "hey, what are the tasks for today"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data.get("type") == "conversation"
    msg = data["message"]
    assert "Agenda & Tasks" in msg
    assert "Scheduled Calendar Events" in msg
    assert "Action Items from Communications" in msg
    # Verify no emojis exist
    import re

    emoji_pattern = re.compile(r"[\U00010000-\U0010ffff\u2600-\u27bf]")
    assert not emoji_pattern.search(msg), f"Emojis found: {msg}"


def test_api_attendance_workflow() -> None:
    """Ensure attendance session creation, rotation, checkin, validation, and CSV export work."""
    # 1. Start a session
    start_res = client.post(
        "/api/attendance/session/start",
        json={"course": "CS-101", "section": "Room A", "rotation_interval": 15},
    )
    assert start_res.status_code == 200
    start_data = start_res.json()
    assert start_data["success"] is True
    session_id = start_data["session_id"]
    active_token = start_data["current_token"]
    assert "svg" in start_data["qr_svg"]
    assert len(active_token) > 0

    # 2. Get active session
    active_res = client.get("/api/attendance/session/active")
    assert active_res.status_code == 200
    active_data = active_res.json()
    assert active_data["success"] is True
    assert active_data["session_id"] == session_id

    # 3. Successful student check-in
    checkin_res = client.post(
        "/api/attendance/checkin",
        json={
            "session_id": session_id,
            "token": active_token,
            "student_id": "STU-9901",
            "student_name": "Alice Tester",
            "device_info": "TestDevice 1.0",
            "device_id": "DEV-TEST-PHONE-1",
        },
    )
    assert checkin_res.status_code == 200
    checkin_data = checkin_res.json()
    assert checkin_data["success"] is True
    assert "checked_in_at" in checkin_data["record"]

    # 4. Duplicate check-in rejection (same student)
    dup_res = client.post(
        "/api/attendance/checkin",
        json={
            "session_id": session_id,
            "token": active_token,
            "student_id": "STU-9901",
            "student_name": "Alice Tester",
            "device_info": "TestDevice 1.0",
            "device_id": "DEV-TEST-PHONE-1",
        },
    )
    assert dup_res.status_code == 200
    dup_data = dup_res.json()
    assert dup_data["success"] is False
    assert "already checked in" in dup_data["error"].lower()

    # 4b. Device duplicate rejection (different student on same phone)
    dev_dup_res = client.post(
        "/api/attendance/checkin",
        json={
            "session_id": session_id,
            "token": active_token,
            "student_id": "STU-9902",
            "student_name": "Bob Proxy",
            "device_info": "TestDevice 1.0",
            "device_id": "DEV-TEST-PHONE-1",
        },
    )
    assert dev_dup_res.status_code == 200
    dev_dup_data = dev_dup_res.json()
    assert dev_dup_data["success"] is False
    assert "device has already checked in" in dev_dup_data["error"].lower()

    # 5. Invalid / expired token rejection
    invalid_res = client.post(
        "/api/attendance/checkin",
        json={
            "session_id": session_id,
            "token": "fake_expired_token_12345",
            "student_id": "STU-9902",
            "student_name": "Bob Tester",
            "device_info": "TestDevice 2.0",
        },
    )
    assert invalid_res.status_code == 200
    invalid_data = invalid_res.json()
    assert invalid_data["success"] is False
    assert "expired" in invalid_data["error"].lower() or "invalid" in invalid_data["error"].lower()

    # 6. Rotate token
    rotate_res = client.post(
        "/api/attendance/session/rotate",
        json={"session_id": session_id},
    )
    assert rotate_res.status_code == 200
    rotate_data = rotate_res.json()
    assert rotate_data["success"] is True
    new_token = rotate_data["new_token"]
    assert new_token != active_token

    # 7. Student portal HTML page & Mobile Scanner Portal
    portal_res = client.get(f"/attendance/checkin?session_id={session_id}&token={new_token}")
    assert portal_res.status_code == 200
    assert "Live Class Attendance Check-in" in portal_res.text
    assert "student-id" in portal_res.text

    # 7b. Dedicated Student Mobile Scanner Portal
    scanner_res = client.get("/attendance/student")
    assert scanner_res.status_code == 200
    assert "Live Attendance Scan" in scanner_res.text
    assert "Open Camera to Scan QR Code" in scanner_res.text

    scan_alias_res = client.get("/attendance/scan")
    assert scan_alias_res.status_code == 200
    assert "Live Attendance Scan" in scan_alias_res.text

    # 8. Simulate scan helper endpoint
    sim_res = client.post(
        "/api/attendance/simulate_scan",
        json={"session_id": session_id, "student_name": "Charlie Tester", "student_id": "STU-9903"},
    )
    assert sim_res.status_code == 200
    assert sim_res.json()["success"] is True

    # 9. Export CSV
    export_res = client.get(f"/api/attendance/export?session_id={session_id}")
    assert export_res.status_code == 200
    assert "text/csv" in export_res.headers.get("content-type", "")
    assert "STU-9901" in export_res.text
    assert "Alice Tester" in export_res.text
    assert "Charlie Tester" in export_res.text

    # 10. End session
    end_res = client.post(
        "/api/attendance/session/end",
        json={"session_id": session_id},
    )
    assert end_res.status_code == 200
    assert end_res.json()["success"] is True

    # 11. Active session is now null
    active_after = client.get("/api/attendance/session/active").json()
    assert active_after.get("active") is False


def test_api_workspace_presets_and_management(tmp_path):
    # Presets
    presets_res = client.get("/api/workspaces/presets")
    assert presets_res.status_code == 200
    data = presets_res.json()
    assert "downloads" in data
    assert "documents" in data
    assert "desktop" in data
    assert "project" in data

    # Add workspace
    custom_ws = tmp_path / "MySpecialWs"
    custom_ws.mkdir()
    add_res = client.post(
        "/api/workspaces",
        json={"name": "MySpecialWs", "path": str(custom_ws), "permissions": ["READ", "WRITE"]},
    )
    assert add_res.status_code == 200
    ws_obj = add_res.json()["workspace"]
    ws_id = ws_obj["workspace_id"]

    # Toggle workspace
    toggle_res = client.patch(f"/api/workspaces/{ws_id}/toggle")
    assert toggle_res.status_code == 200
    assert toggle_res.json()["workspace"]["enabled"] is False

    # Delete workspace
    del_res = client.delete(f"/api/workspaces/{ws_id}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True


def test_api_google_calendar_sync():
    from unittest.mock import MagicMock, patch

    ics_content = (
        "BEGIN:VCALENDAR\n"
        "BEGIN:VEVENT\n"
        "SUMMARY:Executive Review\n"
        "DTSTART:20261015T110000Z\n"
        "DTEND:20261015T120000Z\n"
        "DESCRIPTION:Quarterly goals\n"
        "END:VEVENT\n"
        "END:VCALENDAR"
    )
    mock_resp = MagicMock()
    mock_resp.read.return_value = ics_content.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.post(
            "/api/calendar/google/sync",
            json={"calendar_id_or_url": "https://calendar.google.com/calendar/ical/test/basic.ics"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["synced_count"] == 1
        assert data["events"][0]["title"] == "Executive Review"


def test_unregistered_workspace_chat_guidance():
    # Ensure sandbox isolation is active for this test
    client.post("/api/system/access_mode", json={"all_files_mode": False})
    ws_dl = WorkspaceManager.get_workspace_by_name("Downloads")
    if ws_dl:
        WorkspaceManager.remove_workspace(ws_dl.workspace_id)
    try:
        res = client.post(
            "/api/chat",
            json={"message": "list the files in downloads", "llm_enabled": False},
        )
        assert res.status_code == 200
        msg = res.json().get("message", "")
        assert "Downloads" in msg
        assert "Workspaces tab" in msg or "authorized" in msg
    finally:
        if ws_dl:
            WorkspaceManager.add_workspace(
                ws_dl.path, name=ws_dl.name, permissions=list(ws_dl.permissions)
            )


def test_all_files_access_mode_toggle_and_direct_listing():
    res = client.post("/api/system/access_mode", json={"all_files_mode": True})
    assert res.status_code == 200
    assert res.json()["all_files_mode"] is True

    res_get = client.get("/api/system/access_mode")
    assert res_get.status_code == 200
    assert res_get.json()["all_files_mode"] is True

    # In all files mode, asking for downloads directly inspects the directory
    res_chat = client.post(
        "/api/chat",
        json={"message": "list the files in downloads", "llm_enabled": False},
    )
    assert res_chat.status_code == 200
    msg = res_chat.json().get("message", "")
    assert "Downloads" in msg

    # Reset state to default for other test modules
    from app.workspaces import WorkspaceManager
    WorkspaceManager.reset_all_files_mode()


def test_llm_status_and_config_endpoints():
    res = client.get("/api/llm/status")
    assert res.status_code == 200
    data = res.json()
    assert "provider" in data
    assert "ollama_online" in data
    assert "llm_available" in data

    # Test config update
    cfg_res = client.post(
        "/api/llm/config",
        json={"provider": "ollama", "ollama_model": "qwen2.5:3b"},
    )
    assert cfg_res.status_code == 200
    assert cfg_res.json()["success"] is True


def test_api_tunnel_endpoints():
    """Ensure Cloudflare tunnel status, start, and stop endpoints return proper schema."""
    res = client.get("/api/tunnel/status")
    assert res.status_code == 200
    data = res.json()
    assert "installed" in data
    assert "active" in data
    assert "url" in data

    stop_res = client.post("/api/tunnel/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["success"] is True


def test_external_student_route_restrictions():
    """Ensure external students are blocked from dashboard and restricted to attendance portal."""
    external_headers = {"Host": "quick-sample.trycloudflare.com"}

    # 1. Visiting root dashboard redirects directly to student scanner
    root_res = client.get("/", headers=external_headers, follow_redirects=False)
    assert root_res.status_code in (307, 302, 301)
    assert root_res.headers.get("location") == "/attendance/student"

    # 2. Administrative and chat APIs are blocked with 403 Forbidden
    blocked_chat = client.post("/api/chat", json={"message": "hello"}, headers=external_headers)
    assert blocked_chat.status_code == 403
    assert "restricted" in blocked_chat.json().get("detail", "").lower()

    blocked_workspaces = client.get("/api/workspaces", headers=external_headers)
    assert blocked_workspaces.status_code == 403

    blocked_start = client.post("/api/attendance/session/start", json={"course": "CS101"}, headers=external_headers)
    assert blocked_start.status_code == 403

    blocked_export = client.get("/api/attendance/export?session_id=fake", headers=external_headers)
    assert blocked_export.status_code == 403

    # 3. Allowed attendance portals and static files pass through
    checkin_page = client.get("/attendance/checkin?session_id=1&token=2", headers=external_headers)
    assert checkin_page.status_code == 200

    student_page = client.get("/attendance/student", headers=external_headers)
    assert student_page.status_code == 200

    scan_alias = client.get("/attendance/scan", headers=external_headers)
    assert scan_alias.status_code == 200

