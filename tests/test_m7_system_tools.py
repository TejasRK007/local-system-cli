"""
Automated test suite for Milestone 7: General Local System Tools.

Verifies:
1. System hardware, OS specification, and resource utilization inspection.
2. Safe process inspection, filtering, and sorting.
3. Cross-platform clipboard reading and writing with approval gating.
4. Archive inspection and safe extraction with strict Zip Slip traversal rejection.
5. Structured file metadata, MIME type detection, and cryptographic checksums.
6. Integration with PlanValidator, StepExecutor, and Typer CLI commands.
"""

import os
import zipfile

import pytest
from typer.testing import CliRunner

import app.database as db
from app.main import app
from app.policy import get_action_risk, requires_approval
from app.tasks.executor import StepExecutor
from app.tasks.models import Task, TaskStep
from app.tasks.validator import PlanValidator
from app.tools.archive_tools import extract_archive, inspect_archive
from app.tools.clipboard import read_clipboard, write_clipboard
from app.tools.metadata_tools import get_file_metadata
from app.tools.system_tools import find_process, get_system_info, list_processes
from app.workspaces import WorkspaceManager

runner = CliRunner()


@pytest.fixture(autouse=True)
def setup_isolated_env(tmp_path, monkeypatch):
    """Ensure tests run against an isolated SQLite DB and temporary directory."""
    temp_db_path = tmp_path / "test_m7.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db_path))
    db.init_db(temp_db_path)
    yield


# ==============================================================================
# 1. System & Resource Tools
# ==============================================================================


def test_get_system_info():
    """Verify system info returns OS, CPU, RAM, and Disk metrics."""
    info = get_system_info()
    assert isinstance(info, dict)
    assert "os" in info
    assert "architecture" in info
    assert "cpu_count" in info
    assert info["cpu_count"] >= 1
    assert "ram_total_gb" in info
    assert "disk_total_gb" in info


def test_list_and_filter_processes():
    """Verify safe process listing with memory/cpu sorting and name filtering."""
    procs = list_processes(limit=5, sort_by="memory")
    assert isinstance(procs, list)
    if procs:
        p0 = procs[0]
        assert "pid" in p0
        assert "name" in p0
        assert "memory_mb" in p0
        assert "cpu_percent" in p0
        assert "status" in p0

    # CPU sorting
    cpu_procs = list_processes(limit=5, sort_by="cpu")
    assert isinstance(cpu_procs, list)

    # Search for own process (python)
    results = find_process("python")
    assert isinstance(results, list)

    # Search by PID
    my_pid = str(os.getpid())
    by_pid = find_process(my_pid)
    assert isinstance(by_pid, list)
    if by_pid:
        assert by_pid[0]["pid"] == os.getpid()


# ==============================================================================
# 2. Clipboard Tools
# ==============================================================================


def test_clipboard_read_write():
    """Verify reading and writing to the clipboard."""
    test_text = "M7-Controlled-Automation-Test-42"
    success = write_clipboard(test_text)
    assert success is True

    read_back = read_clipboard()
    # In headless environments, read_back will either be test_text or fallback buffer
    assert test_text in read_back or read_back == test_text


# ==============================================================================
# 3. Archive Tools & Zip Slip Security
# ==============================================================================


def test_archive_inspection_and_safe_extraction(tmp_path):
    """Verify inspecting archive members and extracting within workspace."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    WorkspaceManager.add_workspace(ws, name="ArchiveWs", permissions=["READ", "WRITE"])

    # Create a test zip file
    zip_path = ws / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("doc1.txt", "First document content")
        zf.writestr("subfolder/doc2.txt", "Second document content")

    # 1. Inspect
    report = inspect_archive(zip_path)
    assert report["total_files"] == 2
    assert report["archive_type"] == "zip"
    assert any(m["filename"] == "doc1.txt" for m in report["members"])

    # 2. Extract into authorized target directory
    extract_target = ws / "extracted"
    extract_res = extract_archive(zip_path, extract_target)
    assert extract_res["extracted_count"] == 2

    # Physical verification
    assert (extract_target / "doc1.txt").exists()
    assert (extract_target / "doc1.txt").read_text() == "First document content"
    assert (extract_target / "subfolder" / "doc2.txt").exists()


def test_archive_zip_slip_rejection(tmp_path):
    """Verify that malicious archives attempting directory traversal are blocked."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Create an archive with a traversal payload
    bad_zip = ws / "malicious.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("../../pwned.txt", "Malicious escape attempt")

    extract_dest = ws / "safe_dir"
    with pytest.raises(PermissionError, match="Zip Slip attack detected"):
        extract_archive(bad_zip, extract_dest)

    # Verify no escape file was created
    assert not (tmp_path / "pwned.txt").exists()


# ==============================================================================
# 4. File Metadata Tools
# ==============================================================================


def test_file_metadata_inspection(tmp_path):
    """Verify structured metadata extraction: MIME, timestamps, SHA-256."""
    test_file = tmp_path / "example.json"
    test_file.write_text('{"project": "local-system-cli", "milestone": 7}\n', encoding="utf-8")

    meta = get_file_metadata(test_file)
    assert meta["name"] == "example.json"
    assert meta["extension"] == ".json"
    assert meta["is_file"] is True
    assert meta["is_dir"] is False
    assert meta["size_bytes"] > 0
    assert "human_size" in meta
    assert meta["mime_type"] == "application/json"
    assert len(meta["sha256"]) == 64
    assert len(meta["md5"]) == 32
    assert meta["line_count"] == 1


# ==============================================================================
# 5. Policy, Validator, and StepExecutor Integration
# ==============================================================================


def test_m7_policy_risks():
    """Verify M7 actions match the defined risk tiers."""
    assert get_action_risk("get_system_info") == "low"
    assert get_action_risk("list_processes") == "low"
    assert get_action_risk("read_clipboard") == "low"
    assert get_action_risk("inspect_archive") == "low"
    assert get_action_risk("get_file_metadata") == "low"

    # Modifying actions require approval
    assert get_action_risk("write_clipboard") == "medium"
    assert requires_approval("medium") is True
    assert get_action_risk("extract_archive") == "medium"
    assert requires_approval(get_action_risk("extract_archive")) is True


def test_m7_plan_validation_and_execution(tmp_path):
    """Verify PlanValidator accepts M7 actions and StepExecutor runs them."""
    ws = tmp_path / "test_ws"
    ws.mkdir()
    WorkspaceManager.add_workspace(ws, name="TestWs", permissions=["READ", "WRITE"])

    sample_file = ws / "hello.txt"
    sample_file.write_text("Hello world", encoding="utf-8")

    steps = [
        {"step_order": 1, "action": "get_system_info", "arguments": {}, "depends_on_order": None},
        {"step_order": 2, "action": "read_clipboard", "arguments": {}, "depends_on_order": None},
        {
            "step_order": 3,
            "action": "get_file_metadata",
            "arguments": {"file_path": str(sample_file)},
            "depends_on_order": None,
        },
    ]

    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is True, reason

    # Execute step 1 via StepExecutor
    task = Task(task_id="m7_test_task", user_request="M7 test")
    step1 = TaskStep(
        step_id="step_1",
        task_id="m7_test_task",
        step_order=1,
        action="get_system_info",
        arguments={},
    )
    ok1 = StepExecutor.execute_step(step1, task, {})
    assert ok1 is True

    # Execute metadata step
    step3 = TaskStep(
        step_id="step_3",
        task_id="m7_test_task",
        step_order=3,
        action="get_file_metadata",
        arguments={"file_path": str(sample_file)},
    )
    ok3 = StepExecutor.execute_step(step3, task, {"file_path": str(sample_file)})
    assert ok3 is True


# ==============================================================================
# 6. Typer CLI Commands
# ==============================================================================


def test_cli_sys_info_command():
    """Verify 'sys-info' CLI command executes cleanly."""
    res = runner.invoke(app, ["sys-info"])
    assert res.exit_code == 0
    assert "System & Resource Information" in res.stdout


def test_cli_ps_command():
    """Verify 'ps' CLI command executes cleanly."""
    res = runner.invoke(app, ["ps", "--limit", "5"])
    assert res.exit_code == 0
    assert "Processes" in res.stdout


def test_cli_clipboard_command():
    """Verify 'clipboard' CLI command reads cleanly."""
    res = runner.invoke(app, ["clipboard"])
    assert res.exit_code == 0
    assert "Clipboard Content" in res.stdout


def test_cli_metadata_command(tmp_path):
    """Verify 'metadata' CLI command displays file metadata."""
    f = tmp_path / "meta_test.txt"
    f.write_text("Data for metadata", encoding="utf-8")

    res = runner.invoke(app, ["metadata", str(f)])
    assert res.exit_code == 0
    assert "meta_test.txt" in res.stdout
    assert "File Size" in res.stdout
