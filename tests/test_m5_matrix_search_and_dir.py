"""
M5 Test Matrix: Section A (Search) and Section E (Controlled Directory Creation).

Covers all 12 Search test cases and all 9 Directory Creation test cases.
"""

from pathlib import Path

import pytest

import app.database as db
from app.tasks.executor import StepExecutor
from app.tasks.goal_planner import GoalPlanner
from app.tasks.manager import TaskManager
from app.tasks.models import TaskStatus
from app.tasks.validator import PlanValidator
from app.workspaces import WorkspaceManager


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Isolate SQLite database and enforce workspace security."""
    temp_db_path = tmp_path / "test_matrix_a_e.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db_path))
    monkeypatch.setenv("AGENT_ENFORCE_WORKSPACES", "1")
    db.init_db(temp_db_path)


# ==============================================================================
# SECTION A: SEARCH
# ==============================================================================


def test_search_a1_find_matching_files(tmp_path):
    """A.1: Find matching files in an authorized workspace."""
    ws_dir = tmp_path / "ws_search_1"
    ws_dir.mkdir()
    (ws_dir / "target.txt").write_text("hello", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="SearchWs", permissions=["READ"])

    plan = GoalPlanner.plan_goal("Find target.txt in SearchWs")
    assert len(plan.discovered_files) == 1
    assert Path(plan.discovered_files[0]["path"]).name == "target.txt"
    assert len(plan.steps) == 1
    assert plan.steps[0]["action"] == "search"
    assert plan.cumulative_risk == "low"
    assert plan.requires_approval is False


def test_search_a2_find_files_across_multiple_authorized_workspaces(tmp_path):
    """A.2: Find files across multiple authorized workspaces."""
    ws1 = tmp_path / "ws_multi_1"
    ws1.mkdir()
    (ws1 / "doc1.pdf").write_text("pdf 1", encoding="utf-8")
    WorkspaceManager.add_workspace(ws1, name="MultiOne", permissions=["READ"])

    ws2 = tmp_path / "ws_multi_2"
    ws2.mkdir()
    (ws2 / "doc2.pdf").write_text("pdf 2", encoding="utf-8")
    WorkspaceManager.add_workspace(ws2, name="MultiTwo", permissions=["READ"])

    # Search goal across both workspaces
    plan = GoalPlanner.plan_goal("Find all PDFs in MultiOne and MultiTwo")
    assert len(plan.discovered_files) == 2
    assert len(plan.steps) == 2
    paths = {Path(f["path"]).name for f in plan.discovered_files}
    assert paths == {"doc1.pdf", "doc2.pdf"}


def test_search_a3_no_matching_files(tmp_path):
    """A.3: No matching files found -> deterministic safe no-op."""
    ws_dir = tmp_path / "ws_search_empty_res"
    ws_dir.mkdir()
    (ws_dir / "other.docx").write_text("word", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="SearchNoMatch", permissions=["READ"])

    plan = GoalPlanner.plan_goal("Find all PDFs in SearchNoMatch")
    assert len(plan.discovered_files) == 0
    assert len(plan.steps) == 0
    assert "no matching files" in plan.summary.lower()


def test_search_a4_empty_workspace(tmp_path):
    """A.4: Empty workspace produces 0 steps and safe summary."""
    ws_dir = tmp_path / "ws_empty"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="EmptyWs", permissions=["READ"])

    plan = GoalPlanner.plan_goal("Find files in EmptyWs")
    assert len(plan.discovered_files) == 0
    assert len(plan.steps) == 0
    assert "no matching files" in plan.summary.lower()


def test_search_a5_multiple_matching_files(tmp_path):
    """A.5: Multiple matching files in a search goal are discovered."""
    ws_dir = tmp_path / "ws_multi_match"
    ws_dir.mkdir()
    for i in range(5):
        (ws_dir / f"note_{i}.txt").write_text("note", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="MultiMatchWs", permissions=["READ"])

    plan = GoalPlanner.plan_goal("Find all txt files in MultiMatchWs")
    assert len(plan.discovered_files) == 5
    assert len(plan.steps) == 1
    assert plan.steps[0]["arguments"]["extension"] == ".txt"


def test_search_a6_extension_filtering(tmp_path):
    """A.6: Extension filtering discovers only requested extension."""
    ws_dir = tmp_path / "ws_ext"
    ws_dir.mkdir()
    (ws_dir / "file.pdf").write_text("pdf", encoding="utf-8")
    (ws_dir / "file.txt").write_text("txt", encoding="utf-8")
    (ws_dir / "file.png").write_text("png", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="ExtWs", permissions=["READ"])

    plan = GoalPlanner.plan_goal("Find all pdf files in ExtWs")
    assert len(plan.discovered_files) == 1
    assert plan.discovered_files[0]["path"].endswith(".pdf")


def test_search_a7_directory_filtering(tmp_path):
    """A.7: Directory filtering discovers files in specific folder."""
    ws_dir = tmp_path / "ws_dir_filter"
    sub1 = ws_dir / "reports"
    sub2 = ws_dir / "archive"
    sub1.mkdir(parents=True)
    sub2.mkdir(parents=True)
    (sub1 / "target.txt").write_text("report", encoding="utf-8")
    (sub2 / "other.txt").write_text("archived", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="DirFilterWs", permissions=["READ"])

    plan = GoalPlanner.plan_goal("Find target.txt in DirFilterWs")
    assert len(plan.discovered_files) == 1
    assert "reports" in plan.discovered_files[0]["path"]


def test_search_a8_disabled_workspace(tmp_path):
    """A.8: Disabled workspace rejected with informative message."""
    ws_dir = tmp_path / "ws_disabled"
    ws_dir.mkdir()
    (ws_dir / "file.txt").write_text("text", encoding="utf-8")
    ws = WorkspaceManager.add_workspace(ws_dir, name="DisabledWs", permissions=["READ"])
    WorkspaceManager.disable_workspace(ws.workspace_id)

    plan = GoalPlanner.plan_goal("Find file.txt in DisabledWs")
    assert len(plan.steps) == 0
    assert "disabled" in plan.summary.lower()


def test_search_a9_unauthorized_workspace(tmp_path):
    """A.9: Unauthorized / unknown workspace rejected without silent fallback."""
    ws_dir = tmp_path / "ws_known"
    ws_dir.mkdir()
    (ws_dir / "file.txt").write_text("text", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="KnownWs", permissions=["READ"])

    # Search targeting non-existent / unauthorized workspace
    plan = GoalPlanner.plan_goal("Find file.txt in SecretWs")
    assert len(plan.steps) == 0
    assert "secretws" in plan.summary.lower()
    assert "not configured" in plan.summary.lower() or "unauthorized" in plan.summary.lower()


def test_search_a10_protected_system_path():
    """A.10: Search targeting protected/system path rejected by validator."""
    steps = [
        {
            "step_order": 1,
            "action": "search",
            "arguments": {"directory": "/etc"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    reason_low = reason.lower()
    assert "protected" in reason_low or "unsafe" in reason_low or "unauthorized" in reason_low


def test_search_a11_path_traversal_attempt(tmp_path):
    """A.11: Path traversal rejected by validator."""
    ws_dir = tmp_path / "ws_trav"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="TravWs", permissions=["READ"])

    steps = [
        {
            "step_order": 1,
            "action": "search",
            "arguments": {"directory": str(ws_dir / ".." / "outside")},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    reason_low = reason.lower()
    assert "outside" in reason_low or "unauthorized" in reason_low or "unsafe" in reason_low


def test_search_a12_ambiguous_workspace_selection():
    """A.12: When no workspaces are configured, safe rejection."""
    # Ensure zero workspaces
    assert WorkspaceManager.count_workspaces() == 0
    plan = GoalPlanner.plan_goal("Find all PDFs")
    assert len(plan.steps) == 0
    assert "no workspaces configured" in plan.summary.lower()


# ==============================================================================
# SECTION E: CONTROLLED DIRECTORY CREATION
# ==============================================================================


def test_dir_e1_create_valid_directory_inside_workspace(tmp_path):
    """E.1 & E.9: Create valid directory inside authorized workspace.
    Verify physical existence.
    """
    ws_dir = tmp_path / "ws_dir_create"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="CreateWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Create a folder called Reports in CreateWs")
    assert len(plan.steps) == 1
    assert plan.steps[0]["action"] == "create_directory"
    assert "reports" in plan.steps[0]["arguments"]["directory"].lower()
    assert plan.cumulative_risk == "medium"
    assert plan.requires_approval is True

    # Execute and verify physical creation
    task = TaskManager.create_task(plan.goal, plan.steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.COMPLETED
    assert (ws_dir / "Reports").exists()
    assert (ws_dir / "Reports").is_dir()


def test_dir_e2_create_nested_directory_where_allowed(tmp_path):
    """E.2: Create nested directory inside authorized workspace."""
    ws_dir = tmp_path / "ws_nested"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="NestedWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Create a folder called 2026/Q1 in NestedWs")
    assert len(plan.steps) == 1
    assert plan.steps[0]["action"] == "create_directory"

    task = TaskManager.create_task(plan.goal, plan.steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.COMPLETED
    assert (ws_dir / "2026" / "Q1").is_dir()


def test_dir_e3_attempt_creation_outside_workspace(tmp_path):
    """E.3: Attempt creation outside workspace rejected."""
    ws_dir = tmp_path / "ws_bound"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="BoundWs", permissions=["READ", "WRITE"])

    outside = tmp_path / "outside_dir"
    steps = [
        {
            "step_order": 1,
            "action": "create_directory",
            "arguments": {"directory": str(outside)},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "unauthorized" in reason.lower() or "outside" in reason.lower()


def test_dir_e4_attempt_protected_system_directory_creation():
    """E.4: Attempt protected/system directory creation rejected."""
    steps = [
        {
            "step_order": 1,
            "action": "create_directory",
            "arguments": {"directory": "/etc/new_folder"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    reason_low = reason.lower()
    assert "protected" in reason_low or "unsafe" in reason_low or "unauthorized" in reason_low


def test_dir_e5_attempt_traversal(tmp_path):
    """E.5: Attempt directory creation with traversal rejected."""
    ws_dir = tmp_path / "ws_trav_create"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="TravCreateWs", permissions=["READ", "WRITE"])

    steps = [
        {
            "step_order": 1,
            "action": "create_directory",
            "arguments": {"directory": str(ws_dir / ".." / "evil_dir")},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "unauthorized" in reason.lower() or "outside" in reason.lower()


def test_dir_e6_attempt_creation_without_write_permission(tmp_path):
    """E.6: Attempt directory creation without WRITE permission rejected."""
    ws_dir = tmp_path / "ws_ro_create"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="RoWs", permissions=["READ"])

    plan = GoalPlanner.plan_goal("Create a folder called Invoices in RoWs")
    assert len(plan.steps) == 0
    assert "write" in plan.summary.lower()


def test_dir_e7_attempt_creation_in_disabled_workspace(tmp_path):
    """E.7: Attempt directory creation in disabled workspace rejected."""
    ws_dir = tmp_path / "ws_dis_create"
    ws_dir.mkdir()
    ws = WorkspaceManager.add_workspace(ws_dir, name="DisWs", permissions=["READ", "WRITE"])
    WorkspaceManager.disable_workspace(ws.workspace_id)

    plan = GoalPlanner.plan_goal("Create a folder called Archive in DisWs")
    assert len(plan.steps) == 0
    assert "disabled" in plan.summary.lower()


def test_dir_e8_existing_directory_behavior(tmp_path):
    """E.8: Creating an already existing directory is idempotent and safe."""
    ws_dir = tmp_path / "ws_exists"
    ws_dir.mkdir()
    (ws_dir / "ExistingDir").mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="ExistsWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Create a folder called ExistingDir in ExistsWs")
    assert len(plan.steps) == 1

    task = TaskManager.create_task(plan.goal, plan.steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.COMPLETED
    assert (ws_dir / "ExistingDir").is_dir()
