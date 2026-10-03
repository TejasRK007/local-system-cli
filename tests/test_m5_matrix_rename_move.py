"""
M5 Test Matrix: Section B (Rename) and Section C (Move).

Covers all 17 Rename test cases and all 14 Move test cases.
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
    temp_db_path = tmp_path / "test_matrix_b_c.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db_path))
    monkeypatch.setenv("AGENT_ENFORCE_WORKSPACES", "1")
    db.init_db(temp_db_path)


# ==============================================================================
# SECTION B: RENAME
# ==============================================================================


def test_rename_b1_b14_existing_file_and_physical_verification(tmp_path):
    """B.1: Rename existing file and verify physical existence and old disappearance."""
    ws_dir = tmp_path / "ws_rn_1"
    ws_dir.mkdir()
    f = ws_dir / "agent_demo.txt"
    f.write_text("content", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="RnWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename agent_demo.txt to agent_demo_renamed.txt in RnWs")
    assert len(plan.steps) == 1
    assert plan.steps[0]["action"] == "rename"

    task = TaskManager.create_task(plan.goal, plan.steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.COMPLETED
    assert not (ws_dir / "agent_demo.txt").exists()
    assert (ws_dir / "agent_demo_renamed.txt").exists()


def test_rename_b2_nonexistent_source(tmp_path):
    """B.2: Rename nonexistent source returns safe no-op."""
    ws_dir = tmp_path / "ws_rn_no_src"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="NoSrcWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename ghost.txt to real.txt in NoSrcWs")
    assert len(plan.steps) == 0
    assert "no matching file" in plan.summary.lower()


def test_rename_b3_b16_multiple_ambiguous_matching_sources(tmp_path):
    """B.3 & B.16: Rename multiple matching sources must require disambiguation and never guess."""
    ws1 = tmp_path / "ws_rn_ambig_1"
    ws2 = tmp_path / "ws_rn_ambig_2"
    ws1.mkdir()
    ws2.mkdir()
    (ws1 / "shared.txt").write_text("one", encoding="utf-8")
    (ws2 / "shared.txt").write_text("two", encoding="utf-8")
    WorkspaceManager.add_workspace(ws1, name="AmbigOne", permissions=["READ", "WRITE"])
    WorkspaceManager.add_workspace(ws2, name="AmbigTwo", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename shared.txt to new.txt")
    assert len(plan.steps) == 0
    assert "ambiguous" in plan.summary.lower()


def test_rename_b4_file_with_spaces(tmp_path):
    """B.4: Rename file with spaces in name."""
    ws_dir = tmp_path / "ws_spaces"
    ws_dir.mkdir()
    (ws_dir / "my report.txt").write_text("spaces", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="SpaceWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename 'my report.txt' to 'final report.txt' in SpaceWs")
    assert len(plan.steps) == 1
    assert plan.steps[0]["arguments"]["new_name"] == "final report.txt"

    task = TaskManager.create_task(plan.goal, plan.steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.COMPLETED
    assert not (ws_dir / "my report.txt").exists()
    assert (ws_dir / "final report.txt").exists()


def test_rename_b5_quoted_names(tmp_path):
    """B.5: Rename using double and single quoted names."""
    ws_dir = tmp_path / "ws_quotes"
    ws_dir.mkdir()
    (ws_dir / "old_doc.txt").write_text("doc", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="QuoteWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename \"old_doc.txt\" to \"new_doc.txt\" in QuoteWs")
    assert len(plan.steps) == 1
    assert plan.steps[0]["arguments"]["new_name"] == "new_doc.txt"


def test_rename_b6_to_existing_filename_collision(tmp_path):
    """B.6: Rename to an existing filename rejected as collision."""
    ws_dir = tmp_path / "ws_collision"
    ws_dir.mkdir()
    (ws_dir / "first.txt").write_text("1", encoding="utf-8")
    (ws_dir / "second.txt").write_text("2", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="CollisionWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename first.txt to second.txt in CollisionWs")
    assert len(plan.steps) == 0
    assert "collision" in plan.summary.lower()


def test_rename_b7_outside_workspace(tmp_path):
    """B.7: Rename outside workspace rejected."""
    ws_dir = tmp_path / "ws_rn_in"
    ws_dir.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("out", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="InWs", permissions=["READ", "WRITE"])

    steps = [
        {
            "step_order": 1,
            "action": "rename",
            "arguments": {"source": str(outside_file), "new_name": "renamed.txt"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "outside" in reason.lower() or "unauthorized" in reason.lower()


def test_rename_b8_into_disabled_workspace(tmp_path):
    """B.8: Rename in disabled workspace rejected."""
    ws_dir = tmp_path / "ws_rn_dis"
    ws_dir.mkdir()
    (ws_dir / "doc.txt").write_text("content", encoding="utf-8")
    ws = WorkspaceManager.add_workspace(ws_dir, name="DisRnWs", permissions=["READ", "WRITE"])
    WorkspaceManager.disable_workspace(ws.workspace_id)

    plan = GoalPlanner.plan_goal("Rename doc.txt to doc_new.txt in DisRnWs")
    assert len(plan.steps) == 0
    assert "disabled" in plan.summary.lower()


def test_rename_b9_without_write_permission(tmp_path):
    """B.9: Rename without WRITE permission rejected."""
    ws_dir = tmp_path / "ws_rn_ro"
    ws_dir.mkdir()
    (ws_dir / "read_only.txt").write_text("ro", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="RoRnWs", permissions=["READ"])

    plan = GoalPlanner.plan_goal("Rename read_only.txt to writable.txt in RoRnWs")
    assert len(plan.steps) == 0
    assert "write" in plan.summary.lower()


def test_rename_b10_protected_system_file():
    """B.10: Rename protected/system file rejected."""
    steps = [
        {
            "step_order": 1,
            "action": "rename",
            "arguments": {"source": "/etc/hosts", "new_name": "hosts.bak"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    reason_low = reason.lower()
    assert "protected" in reason_low or "unsafe" in reason_low or "unauthorized" in reason_low


def test_rename_b11_with_path_traversal(tmp_path):
    """B.11: Rename with path separators or traversal in new_name rejected."""
    ws_dir = tmp_path / "ws_rn_trav"
    ws_dir.mkdir()
    (ws_dir / "target.txt").write_text("content", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="TravRnWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename target.txt to ../escaped.txt in TravRnWs")
    assert len(plan.steps) == 0
    summary_low = plan.summary.lower()
    assert "separators" in summary_low or "unsafe" in summary_low or "invalid" in summary_low


def test_rename_b12_absolute_destination(tmp_path):
    """B.12: Rename with path separators in destination name rejected."""
    ws_dir = tmp_path / "ws_rn_abs"
    ws_dir.mkdir()
    (ws_dir / "file.txt").write_text("text", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="AbsRnWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename file.txt to /tmp/abs.txt in AbsRnWs")
    assert len(plan.steps) == 0
    assert "separators" in plan.summary.lower()


def test_rename_b13_invalid_empty_destination(tmp_path):
    """B.13: Rename with invalid/empty destination name rejected."""
    steps = [
        {
            "step_order": 1,
            "action": "rename",
            "arguments": {"source": str(tmp_path / "any.txt"), "new_name": ""},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "missing" in reason.lower() or "invalid" in reason.lower()


def test_rename_b14_source_and_destination_identical(tmp_path):
    """B.14: Rename where source and destination are effectively identical rejected."""
    ws_dir = tmp_path / "ws_rn_ident"
    ws_dir.mkdir()
    (ws_dir / "same.txt").write_text("identical", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="IdentWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename same.txt to same.txt in IdentWs")
    assert len(plan.steps) == 0
    assert "identical" in plan.summary.lower()


def test_rename_b15_destination_directory_does_not_exist(tmp_path):
    """B.15: Rename where source file or destination parent does not exist rejected."""
    steps = [
        {
            "step_order": 1,
            "action": "rename",
            "arguments": {
                "source": str(tmp_path / "nonexistent" / "file.txt"),
                "new_name": "new.txt",
            },
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "not exist" in reason.lower()


def test_rename_b17_destination_not_treated_as_source_search(tmp_path):
    """B.17: Ensure destination filename is not incorrectly treated as source-search target."""
    ws_dir = tmp_path / "ws_rn_src_dest"
    ws_dir.mkdir()
    (ws_dir / "agent_demo.txt").write_text("hello", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="SrcDestWs", permissions=["READ", "WRITE"])

    # Destination filename "agent_demo_renamed.txt" does not exist yet.
    # The planner must find "agent_demo.txt", not search for "agent_demo_renamed.txt".
    plan = GoalPlanner.plan_goal("Rename agent_demo.txt to agent_demo_renamed.txt in SrcDestWs")
    assert len(plan.discovered_files) == 1
    assert Path(plan.discovered_files[0]["path"]).name == "agent_demo.txt"
    assert len(plan.steps) == 1
    assert plan.steps[0]["arguments"]["new_name"] == "agent_demo_renamed.txt"


# ==============================================================================
# SECTION C: MOVE
# ==============================================================================


def test_move_c1_c4_c14_existing_file_and_physical_verification(tmp_path):
    """C.1, C.4, C.14: Move existing file to valid destination and verify physical result."""
    ws_dir = tmp_path / "ws_mv_1"
    ws_dir.mkdir()
    src = ws_dir / "doc.txt"
    src.write_text("moving file", encoding="utf-8")
    dest_folder = ws_dir / "Archive"
    WorkspaceManager.add_workspace(ws_dir, name="MoveWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Move doc.txt into an Archive folder in MoveWs")
    assert len(plan.steps) == 2  # create_directory + move
    assert plan.steps[0]["action"] == "create_directory"
    assert plan.steps[1]["action"] == "move"

    task = TaskManager.create_task(plan.goal, plan.steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.COMPLETED
    assert not src.exists()
    assert (dest_folder / "doc.txt").exists()


def test_move_c2_nonexistent_source(tmp_path):
    """C.2: Move nonexistent source returns safe no-op."""
    ws_dir = tmp_path / "ws_mv_nosrc"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="MvNoSrcWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Move phantom.pdf into Archive in MvNoSrcWs")
    assert len(plan.steps) == 0
    assert "no matching files" in plan.summary.lower()


def test_move_c3_ambiguous_source(tmp_path):
    """C.3: Move ambiguous single source requires disambiguation."""
    ws1 = tmp_path / "ws_mv_amb1"
    ws2 = tmp_path / "ws_mv_amb2"
    ws1.mkdir()
    ws2.mkdir()
    (ws1 / "report.pdf").write_text("rep 1", encoding="utf-8")
    (ws2 / "report.pdf").write_text("rep 2", encoding="utf-8")
    WorkspaceManager.add_workspace(ws1, name="MvAmb1", permissions=["READ", "WRITE"])
    WorkspaceManager.add_workspace(ws2, name="MvAmb2", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Move report.pdf into Archive")
    assert len(plan.steps) == 0
    assert "ambiguous" in plan.summary.lower()


def test_move_c5_move_to_another_authorized_workspace(tmp_path):
    """C.5: Move from one authorized workspace into another without creating nested folder."""
    ws_src = tmp_path / "ws_downloads"
    ws_dst = tmp_path / "ws_documents"
    ws_src.mkdir()
    ws_dst.mkdir()
    (ws_src / "report.pdf").write_text("pdf content", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_src, name="Downloads", permissions=["READ"])
    WorkspaceManager.add_workspace(ws_dst, name="Documents", permissions=["WRITE"])

    plan = GoalPlanner.plan_goal("Move the PDF files from Downloads into Documents")
    assert len(plan.discovered_files) == 1
    assert len(plan.steps) == 1  # Directly moves to Documents, no subfolder created!
    assert plan.steps[0]["action"] == "move"
    assert plan.steps[0]["arguments"]["destination"] == str(ws_dst.resolve())

    task = TaskManager.create_task(plan.goal, plan.steps)
    executed = StepExecutor.execute_task(task, confirm_callback=lambda act, prompt, details: True)
    assert executed.status == TaskStatus.COMPLETED
    assert not (ws_src / "report.pdf").exists()
    assert (ws_dst / "report.pdf").exists()


def test_move_c6_move_to_unauthorized_workspace(tmp_path):
    """C.6: Move to unauthorized workspace rejected."""
    ws_src = tmp_path / "ws_src_auth"
    ws_src.mkdir()
    (ws_src / "data.csv").write_text("data", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_src, name="SrcAuthWs", permissions=["READ"])

    plan = GoalPlanner.plan_goal("Move data.csv from SrcAuthWs to UnknownWs")
    assert len(plan.steps) == 0
    assert "not configured" in plan.summary.lower() or "unauthorized" in plan.summary.lower()


def test_move_c7_move_into_disabled_workspace(tmp_path):
    """C.7: Move into disabled workspace rejected."""
    ws_src = tmp_path / "ws_src_en"
    ws_dst = tmp_path / "ws_dst_dis"
    ws_src.mkdir()
    ws_dst.mkdir()
    (ws_src / "data.csv").write_text("data", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_src, name="SrcEnWs", permissions=["READ"])
    ws2 = WorkspaceManager.add_workspace(ws_dst, name="DstDisWs", permissions=["WRITE"])
    WorkspaceManager.disable_workspace(ws2.workspace_id)

    plan = GoalPlanner.plan_goal("Move data.csv from SrcEnWs to DstDisWs")
    assert len(plan.steps) == 0
    assert "disabled" in plan.summary.lower()


def test_move_c8_move_without_source_read_permission(tmp_path):
    """C.8: Move without source READ permission rejected."""
    ws_src = tmp_path / "ws_src_nor"
    ws_dst = tmp_path / "ws_dst_w"
    ws_src.mkdir()
    ws_dst.mkdir()
    (ws_src / "file.txt").write_text("text", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_src, name="SrcNoR", permissions=["WRITE"])
    WorkspaceManager.add_workspace(ws_dst, name="DstW", permissions=["WRITE"])

    plan = GoalPlanner.plan_goal("Move file.txt from SrcNoR to DstW")
    assert len(plan.steps) == 0
    assert "read" in plan.summary.lower()


def test_move_c9_move_without_destination_write_permission(tmp_path):
    """C.9: Move without destination WRITE permission rejected."""
    ws_src = tmp_path / "ws_src_r"
    ws_dst = tmp_path / "ws_dst_now"
    ws_src.mkdir()
    ws_dst.mkdir()
    (ws_src / "file.txt").write_text("text", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_src, name="SrcR", permissions=["READ"])
    WorkspaceManager.add_workspace(ws_dst, name="DstNoW", permissions=["READ"])

    plan = GoalPlanner.plan_goal("Move file.txt from SrcR to DstNoW")
    assert len(plan.steps) == 0
    assert "write" in plan.summary.lower()


def test_move_c10_move_into_protected_system_path(tmp_path):
    """C.10: Move into protected system path rejected by validator."""
    ws_dir = tmp_path / "ws_mv_sys"
    ws_dir.mkdir()
    src = ws_dir / "data.txt"
    src.write_text("data", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="MvSysWs", permissions=["READ", "WRITE"])

    steps = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(src), "destination": "/etc"},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    reason_low = reason.lower()
    assert "protected" in reason_low or "unsafe" in reason_low or "unauthorized" in reason_low


def test_move_c11_move_with_traversal(tmp_path):
    """C.11: Move with traversal rejected by validator."""
    ws_dir = tmp_path / "ws_mv_trav"
    ws_dir.mkdir()
    src = ws_dir / "data.txt"
    src.write_text("data", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="MvTravWs", permissions=["READ", "WRITE"])

    steps = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(src), "destination": str(ws_dir / ".." / "outside")},
            "depends_on_order": None,
        }
    ]
    valid, reason = PlanValidator.validate_plan(steps)
    assert valid is False
    assert "outside" in reason.lower() or "unauthorized" in reason.lower()


def test_move_c12_move_destination_collision(tmp_path):
    """C.12: Move when destination already contains the file rejected."""
    ws_dir = tmp_path / "ws_mv_col"
    ws_dir.mkdir()
    src = ws_dir / "doc.txt"
    src.write_text("source", encoding="utf-8")
    dest_dir = ws_dir / "TargetDir"
    dest_dir.mkdir()
    (dest_dir / "doc.txt").write_text("already exists", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="MvColWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Move doc.txt into TargetDir in MvColWs")
    assert len(plan.steps) == 0
    assert "collision" in plan.summary.lower()


def test_move_c13_move_to_nonexistent_destination(tmp_path):
    """C.13: Move to nonexistent destination rejected."""
    ws_dir = tmp_path / "ws_mv_nodest"
    ws_dir.mkdir()
    src = ws_dir / "doc.txt"
    src.write_text("source", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="NoDestWs", permissions=["READ", "WRITE"])

    steps = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": str(src), "destination": str(ws_dir / "NonExistentFolder")},
            "depends_on_order": None,
        }
    ]
    task = TaskManager.create_task("Move", steps)
    executed = StepExecutor.execute_task(task)
    assert executed.status == TaskStatus.FAILED
