"""
M5 Test Matrix: Section G (Plan Validation) and Section H (Approval).

Covers all 17 Plan Validation test cases and all 7 Approval test cases.
"""

import pytest
from typer.testing import CliRunner

import app.database as db
from app.main import app
from app.policy import get_action_risk, requires_approval
from app.tasks.goal_planner import GoalPlanner
from app.tasks.validator import PlanValidator
from app.workspaces import WorkspaceManager

runner = CliRunner()


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Isolate SQLite database and enforce workspace security."""
    temp_db_path = tmp_path / "test_matrix_g_h.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db_path))
    monkeypatch.setenv("AGENT_ENFORCE_WORKSPACES", "1")
    db.init_db(temp_db_path)


# ==============================================================================
# SECTION G: PLAN VALIDATION
# ==============================================================================


def test_val_g1_unsupported_action():
    """G.1: Unsupported action rejected."""
    steps = [
        {"step_order": 1, "action": "curl_download", "arguments": {}, "depends_on_order": None}
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "unsupported action" in reason.lower()


def test_val_g2_invalid_action_arguments():
    """G.2: Invalid action arguments rejected (e.g. not a dictionary)."""
    steps = [
        {"step_order": 1, "action": "search", "arguments": "invalid", "depends_on_order": None}
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "must be a dictionary" in reason.lower()


def test_val_g3_invalid_source():
    """G.3: Missing or empty source rejected."""
    steps = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": "", "destination": "/tmp"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "missing required 'source'" in reason.lower()


def test_val_g4_invalid_destination():
    """G.4: Missing or empty destination rejected."""
    steps = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": "/tmp/a", "destination": ""},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "missing required 'destination'" in reason.lower()


def test_val_g5_workspace_does_not_exist(tmp_path):
    """G.5: Target in non-configured workspace rejected."""
    ws_dir = tmp_path / "ws_val_configured"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="ConfWs", permissions=["READ", "WRITE"])

    outside = tmp_path / "outside_unconfigured" / "file.txt"
    outside.parent.mkdir()
    outside.write_text("outside", encoding="utf-8")

    steps = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(outside), "destination": str(ws_dir)},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "unauthorized" in reason.lower() or "outside" in reason.lower()


def test_val_g6_workspace_disabled(tmp_path):
    """G.6: Operation in disabled workspace rejected."""
    ws_dir = tmp_path / "ws_val_dis"
    ws_dir.mkdir()
    f = ws_dir / "file.txt"
    f.write_text("content", encoding="utf-8")
    ws = WorkspaceManager.add_workspace(
        ws_dir, name="ValDisWs", permissions=["READ", "WRITE", "DELETE"]
    )
    WorkspaceManager.disable_workspace(ws.workspace_id)

    steps = [
        {
            "step_order": 1,
            "action": "delete",
            "arguments": {"target": str(f)},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "disabled" in reason.lower()


def test_val_g7_required_permission_missing(tmp_path):
    """G.7: Operation missing required permission rejected."""
    ws_dir = tmp_path / "ws_val_perm"
    ws_dir.mkdir()
    f = ws_dir / "file.txt"
    f.write_text("content", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="ValPermWs", permissions=["READ"])

    # Attempt delete without DELETE permission
    steps = [
        {
            "step_order": 1,
            "action": "delete",
            "arguments": {"target": str(f)},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "delete" in reason.lower()


def test_val_g8_protected_path():
    """G.8: Protected system path rejected."""
    steps = [
        {
            "step_order": 1,
            "action": "delete",
            "arguments": {"target": "/etc/passwd"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    reason_low = reason.lower()
    assert "protected" in reason_low or "unsafe" in reason_low or "unauthorized" in reason_low


def test_val_g9_path_traversal(tmp_path):
    """G.9: Path traversal rejected."""
    ws_dir = tmp_path / "ws_val_trav"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="ValTravWs", permissions=["READ", "WRITE"])

    steps = [
        {
            "step_order": 1,
            "action": "create_directory",
            "arguments": {"directory": str(ws_dir / ".." / "escaped")},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "outside" in reason.lower() or "unauthorized" in reason.lower()


def test_val_g10_source_file_does_not_physically_exist(tmp_path):
    """G.10: Source file that does not physically exist rejected."""
    ws_dir = tmp_path / "ws_val_ghost"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="GhostWs", permissions=["READ", "WRITE"])

    steps = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {
                "source": str(ws_dir / "ghost.txt"),
                "destination": str(ws_dir),
            },
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "does not exist on disk" in reason.lower()


def test_val_g11_destination_collision(tmp_path):
    """G.11: Destination collision rejected during plan validation."""
    ws_dir = tmp_path / "ws_val_col"
    ws_dir.mkdir()
    f1 = ws_dir / "source.txt"
    f2 = ws_dir / "existing.txt"
    f1.write_text("1", encoding="utf-8")
    f2.write_text("2", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="ColWs", permissions=["READ", "WRITE"])

    steps = [
        {
            "step_order": 1,
            "action": "rename",
            "arguments": {"source": str(f1), "new_name": "existing.txt"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "collision" in reason.lower() or "already exists" in reason.lower()


def test_val_g12_invalid_dependency():
    """G.12: Dependency pointing to non-existent step order rejected."""
    steps = [
        {"step_order": 1, "action": "search", "arguments": {}, "depends_on_order": 99}
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "non-existent step #99" in reason.lower() or "invalid dependency" in reason.lower()


def test_val_g13_forward_dependency():
    """G.13: Forward reference dependency rejected."""
    steps = [
        {"step_order": 1, "action": "search", "arguments": {}, "depends_on_order": 2},
        {"step_order": 2, "action": "search", "arguments": {}, "depends_on_order": None},
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    reason_low = reason.lower()
    assert (
        "forward reference" in reason_low
        or "cycle" in reason_low
        or "non-existent" in reason_low
    )


def test_val_g14_cyclic_dependency():
    """G.14: Cyclic dependency rejected."""
    steps = [
        {"step_order": 1, "action": "search", "arguments": {}, "depends_on_order": 1}
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "cycle" in reason.lower() or "invalid dependency" in reason.lower()


def test_val_g15_conflicting_steps(tmp_path):
    """G.15: Conflicting steps within the same plan rejected."""
    ws_dir = tmp_path / "ws_val_conflict"
    ws_dir.mkdir()
    f1 = ws_dir / "f1.txt"
    f2 = ws_dir / "f2.txt"
    f1.write_text("1", encoding="utf-8")
    f2.write_text("2", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="ConfWs", permissions=["READ", "WRITE", "DELETE"])

    # Step 1 renames f1 to dest.txt, Step 2 renames f2 to same dest.txt
    steps = [
        {
            "step_order": 1,
            "action": "rename",
            "arguments": {"source": str(f1), "new_name": "dest.txt"},
            "depends_on_order": None,
        },
        {
            "step_order": 2,
            "action": "rename",
            "arguments": {"source": str(f2), "new_name": "dest.txt"},
            "depends_on_order": None,
        },
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "conflicting steps" in reason.lower() or "collision" in reason.lower()


def test_val_g16_risk_state_calculation():
    """G.16: Cumulative risk correctly calculated."""
    # Read-only search: LOW
    search_steps = [{"step_order": 1, "action": "search", "arguments": {}}]
    assert GoalPlanner.calculate_plan_risk(search_steps) == "low"

    # Move / Rename / Create directory: MEDIUM
    move_steps = [{"step_order": 1, "action": "move", "arguments": {}}]
    assert GoalPlanner.calculate_plan_risk(move_steps) == "medium"

    # Delete: HIGH
    delete_steps = [
        {"step_order": 1, "action": "search", "arguments": {}},
        {"step_order": 2, "action": "delete", "arguments": {}},
    ]
    assert GoalPlanner.calculate_plan_risk(delete_steps) == "high"


def test_val_g17_unauthorized_step_injected_manually():
    """G.17: Manually injected unauthorized action into a plan is rejected."""
    injected_steps = [
        {
            "step_order": 1,
            "action": "exec_python",
            "arguments": {"code": "import os; os.system('ls')"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(injected_steps)
    assert valid is False
    assert "unsupported action" in reason.lower()


# ==============================================================================
# SECTION H: APPROVAL
# ==============================================================================


def test_approval_h1_low_risk_does_not_require_approval():
    """H.1: Low-risk read-only actions do not require approval."""
    assert requires_approval("low") is False
    assert get_action_risk("search") == "low"


def test_approval_h2_medium_and_high_risk_require_approval():
    """H.2: Medium and High risk actions require approval."""
    assert requires_approval("medium") is True
    assert requires_approval("high") is True
    assert get_action_risk("move") == "medium"
    assert get_action_risk("rename") == "medium"
    assert get_action_risk("create_directory") == "medium"
    assert get_action_risk("delete") == "high"


def test_approval_h3_user_denial_cancels_execution(tmp_path):
    """H.3: User saying 'n' cancels execution and executes zero steps."""
    ws_dir = tmp_path / "ws_appr_no"
    ws_dir.mkdir()
    f = ws_dir / "keep.txt"
    f.write_text("safe", encoding="utf-8")
    WorkspaceManager.add_workspace(
        ws_dir, name="ApprNoWs", permissions=["READ", "WRITE", "DELETE"]
    )

    res = runner.invoke(app, ["goal", "Delete keep.txt in ApprNoWs"], input="n\n")
    assert "cancelled" in res.output.lower() or "denied" in res.output.lower()
    assert f.exists()


def test_approval_h4_user_approval_proceeds(tmp_path):
    """H.4: User saying 'y' proceeds with execution."""
    ws_dir = tmp_path / "ws_appr_yes"
    ws_dir.mkdir()
    f = ws_dir / "delete.txt"
    f.write_text("safe", encoding="utf-8")
    WorkspaceManager.add_workspace(
        ws_dir, name="ApprYesWs", permissions=["READ", "WRITE", "DELETE"]
    )

    res = runner.invoke(app, ["goal", "Delete delete.txt in ApprYesWs"], input="y\n")
    assert "completed" in res.output.lower() or "success" in res.output.lower()
    assert not f.exists()


def test_approval_h5_invalid_input_does_not_execute(tmp_path):
    """H.5: Invalid input defaults to denial and does not execute."""
    ws_dir = tmp_path / "ws_appr_invalid"
    ws_dir.mkdir()
    f = ws_dir / "keep.txt"
    f.write_text("safe", encoding="utf-8")
    WorkspaceManager.add_workspace(
        ws_dir, name="ApprInvWs", permissions=["READ", "WRITE", "DELETE"]
    )

    runner.invoke(app, ["goal", "Delete keep.txt in ApprInvWs"], input="invalid_answer\n")
    # File must NOT be deleted
    assert f.exists()
