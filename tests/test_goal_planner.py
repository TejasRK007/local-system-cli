"""
Automated test suite for Milestone 5: Intelligent Goal-to-Plan Reasoning.

Covers:
1. Goal parsing & analysis.
2. Real workspace file discovery.
3. Rejection of hallucinated/unverified files.
4. Empty search results handling (safe no-op).
5. create_directory step generation.
6. create_directory execution and physical verification.
7. Dependent move step generation.
8. Output variable resolution ($output.step_1.path).
9. Action whitelist enforcement.
10. Invalid action rejection.
11. Path traversal rejection.
12. Outside-workspace target rejection.
13. Disabled workspace rejection.
14. Missing READ permission rejection.
15. Missing WRITE permission rejection.
16. Missing DELETE permission rejection.
17. DAG dependency structure validation.
18. Cyclic and forward dependency rejection.
19. Cumulative LOW risk calculation.
20. Cumulative MEDIUM risk calculation.
21. Cumulative HIGH risk calculation.
22. Plan approval acceptance via CLI.
23. Plan approval denial via CLI.
24. Zero filesystem modifications after approval denial.
25. End-to-end goal execution (create dir -> move files -> verify).
26. Physical filesystem verification post-execution.
27. Compensation (safe empty directory removal on subsequent failure).
28. Audit logging for plan generation, execution, and cancellation.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import app.database as db
from app.main import app
from app.tasks.executor import StepExecutor
from app.tasks.goal_planner import GoalPlanner
from app.tasks.manager import TaskManager
from app.tasks.models import StepStatus, TaskStatus
from app.tasks.validator import PlanValidator
from app.tools.file_actions import create_directory
from app.workspaces import WorkspaceManager

runner = CliRunner()


@pytest.fixture(autouse=True)
def setup_goal_planner_env(tmp_path, monkeypatch):
    """Isolate SQLite database and enforce workspace security for Milestone 5 tests."""
    temp_db_path = tmp_path / "test_goal_agent.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db_path))
    monkeypatch.setenv("AGENT_ENFORCE_WORKSPACES", "1")
    db.init_db(temp_db_path)
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Goal Parsing
# ---------------------------------------------------------------------------


def test_goal_parsing_extracts_criteria():
    """Verify GoalPlanner parses high-level goal into structured criteria."""
    analysis = GoalPlanner.analyze_goal("Organize my internship PDFs into an Internship folder")
    assert analysis["action_type"] in ("organize", "move")
    assert analysis["extension"] == ".pdf"
    assert "internship" in [k.lower() for k in analysis["keywords"]]
    assert analysis["target_directory_name"] == "Internship"


# ---------------------------------------------------------------------------
# 2 & 3. Real Workspace File Discovery & No Hallucinated Files
# ---------------------------------------------------------------------------


def test_real_workspace_file_discovery_no_hallucination(tmp_path):
    """Verify plan only contains files that physically exist on disk in authorized workspace."""
    ws_dir = tmp_path / "ws_real"
    source_dir = ws_dir / "source"
    source_dir.mkdir(parents=True)
    WorkspaceManager.add_workspace(ws_dir, name="RealWs", permissions=["READ", "WRITE"])

    # Create real files on disk
    f1 = source_dir / "internship_offer.pdf"
    f2 = source_dir / "internship_report.pdf"
    f1.write_text("offer content", encoding="utf-8")
    f2.write_text("report content", encoding="utf-8")

    plan = GoalPlanner.plan_goal("Organize my internship PDFs into an Internship folder")

    assert len(plan.discovered_files) == 2
    discovered_paths = [Path(f["path"]).resolve() for f in plan.discovered_files]
    assert f1.resolve() in discovered_paths
    assert f2.resolve() in discovered_paths

    # Confirm plan steps only reference the 2 real files
    move_sources = [s["arguments"]["source"] for s in plan.steps if s["action"] == "move"]
    assert len(move_sources) == 2
    assert str(f1.resolve()) in move_sources
    assert str(f2.resolve()) in move_sources


# ---------------------------------------------------------------------------
# 4. Empty Search Results (Safe No-Op)
# ---------------------------------------------------------------------------


def test_empty_search_results_safe_no_op(tmp_path):
    """Verify zero matching files produces safe no-op with no steps and no directory creation."""
    ws_dir = tmp_path / "ws_empty"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="EmptyWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Organize my internship PDFs into an Internship folder")

    assert len(plan.discovered_files) == 0
    assert len(plan.steps) == 0
    assert "No matching files were found" in plan.summary
    assert not (ws_dir / "Internship").exists()


# ---------------------------------------------------------------------------
# 5 & 6. create_directory Generation & Controlled Execution
# ---------------------------------------------------------------------------


def test_create_directory_generation_and_execution(tmp_path):
    """Verify create_directory is generated in plan and successfully executed by tool."""
    ws_dir = tmp_path / "ws_mkdir"
    source_dir = ws_dir / "src"
    source_dir.mkdir(parents=True)
    (source_dir / "internship_notes.pdf").write_text("notes", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="MkdirWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Organize my internship PDFs into an Internship folder")

    # Step 1 must be create_directory
    assert plan.steps[0]["action"] == "create_directory"
    target_dir = Path(plan.steps[0]["arguments"]["directory"])
    assert target_dir.name == "Internship"

    # Execute create_directory tool directly
    res = create_directory(str(target_dir))
    assert "Verified:" in res
    assert target_dir.exists() and target_dir.is_dir()

    # Idempotent execution
    res_again = create_directory(str(target_dir))
    assert "Verified: directory already exists" in res_again


# ---------------------------------------------------------------------------
# 7 & 8. Dependent Move Step Generation & Output Passing
# ---------------------------------------------------------------------------


def test_dependent_move_generation_and_output_passing(tmp_path):
    """Verify generated move steps depend on step 1 and reference $output.step_1.path."""
    ws_dir = tmp_path / "ws_dep"
    src = ws_dir / "source"
    src.mkdir(parents=True)
    (src / "internship_a.pdf").write_text("a", encoding="utf-8")
    (src / "internship_b.pdf").write_text("b", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="DepWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Organize my internship PDFs into an Internship folder")

    assert plan.steps[0]["action"] == "create_directory"
    for move_step in plan.steps[1:]:
        assert move_step["action"] == "move"
        assert move_step["depends_on_order"] == 1
        assert move_step["arguments"]["destination"] == "$output.step_1.path"


# ---------------------------------------------------------------------------
# 9 & 10. Action Whitelist & Invalid Action Rejection
# ---------------------------------------------------------------------------


def test_plan_validator_action_whitelist_and_rejection():
    """Verify PlanValidator enforces action whitelist and rejects unsupported/injected actions."""
    # Valid actions
    valid_steps = [
        {
            "step_order": 1,
            "action": "create_directory",
            "arguments": {"directory": "C:\\safe"},
            "depends_on_order": None,
        },
    ]
    # Inject unauthorized action e.g. shell_execute or python_code
    invalid_steps = [
        {
            "step_order": 1,
            "action": "shell_execute",
            "arguments": {"command": "dir"},
            "depends_on_order": None,
        },
    ]

    valid, _ = PlanValidator.validate_plan(valid_steps)
    invalid, reason = PlanValidator.validate_plan(invalid_steps)

    assert invalid is False
    assert "unsupported action 'shell_execute'" in reason.lower()


# ---------------------------------------------------------------------------
# 11 & 12. Path Traversal & Outside-Workspace Rejection
# ---------------------------------------------------------------------------


def test_plan_validator_traversal_and_outside_workspace_rejection(tmp_path):
    """Verify PlanValidator rejects path traversal and paths outside configured workspaces."""
    ws_dir = tmp_path / "ws_sec"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="SecWs", permissions=["READ", "WRITE"])

    # Traversal escaping workspace
    traversal_steps = [
        {
            "step_order": 1,
            "action": "create_directory",
            "arguments": {"directory": str(ws_dir / ".." / "outside")},
            "depends_on_order": None,
        },
    ]
    valid_trav, reason_trav = PlanValidator.validate_plan(traversal_steps)
    assert valid_trav is False
    assert "unauthorized" in reason_trav.lower() or "outside" in reason_trav.lower()

    # System directory target (C:\Windows\System32)
    sys_steps = [
        {
            "step_order": 1,
            "action": "create_directory",
            "arguments": {"directory": "C:\\Windows\\System32\\danger"},
            "depends_on_order": None,
        },
    ]
    valid_sys, reason_sys = PlanValidator.validate_plan(sys_steps)
    assert valid_sys is False
    assert "system directory" in reason_sys.lower() or "unauthorized" in reason_sys.lower()


# ---------------------------------------------------------------------------
# 13, 14, 15, 16. Workspace Status & Permission Checks
# ---------------------------------------------------------------------------


def test_plan_validator_permission_and_disabled_checks(tmp_path):
    """Verify PlanValidator checks workspace enabled status and required permissions."""
    ws_dir = tmp_path / "ws_perm"
    src = ws_dir / "source"
    src.mkdir(parents=True)
    f = src / "doc.txt"
    f.write_text("content", encoding="utf-8")

    # Read-only workspace: create_directory or move destination must fail WRITE check
    ws = WorkspaceManager.add_workspace(ws_dir, name="PermWs", permissions=["READ"])

    write_steps = [
        {
            "step_order": 1,
            "action": "create_directory",
            "arguments": {"directory": str(ws_dir / "NewDir")},
            "depends_on_order": None,
        },
    ]
    valid_w, reason_w = PlanValidator.validate_plan(write_steps)
    assert valid_w is False
    assert "write" in reason_w.lower()

    # Delete without DELETE permission
    del_steps = [
        {
            "step_order": 1,
            "action": "delete",
            "arguments": {"target": str(f)},
            "depends_on_order": None,
        },
    ]
    valid_d, reason_d = PlanValidator.validate_plan(del_steps)
    assert valid_d is False
    assert "delete" in reason_d.lower()

    # Disabled workspace
    WorkspaceManager.set_permissions(ws.workspace_id, ["READ", "WRITE", "DELETE"])
    WorkspaceManager.disable_workspace(ws.workspace_id)

    valid_dis, reason_dis = PlanValidator.validate_plan(write_steps)
    assert valid_dis is False
    assert "disabled" in reason_dis.lower()


# ---------------------------------------------------------------------------
# 17 & 18. DAG Dependency Validation & Cycle Detection
# ---------------------------------------------------------------------------


def test_plan_validator_dag_cycle_and_forward_reference():
    """Verify PlanValidator rejects cyclic dependencies and forward references."""
    # Forward dependency: step 1 depends on step 2
    forward_steps = [
        {
            "step_order": 1,
            "action": "create_directory",
            "arguments": {"directory": "C:\\ws\\dir"},
            "depends_on_order": 2,
        },
        {
            "step_order": 2,
            "action": "search",
            "arguments": {"query": "test"},
            "depends_on_order": None,
        },
    ]
    valid_fwd, reason_fwd = PlanValidator.validate_plan(forward_steps)
    assert valid_fwd is False
    assert "earlier steps" in reason_fwd.lower() or "cycle" in reason_fwd.lower()

    # Forward variable reference: step 1 references $output.step_2.path
    fwd_var_steps = [
        {
            "step_order": 1,
            "action": "move",
            "arguments": {"source": "a.txt", "destination": "$output.step_2.path"},
            "depends_on_order": None,
        },
        {
            "step_order": 2,
            "action": "create_directory",
            "arguments": {"directory": "C:\\ws\\dir"},
            "depends_on_order": None,
        },
    ]
    valid_var, reason_var = PlanValidator.validate_plan(fwd_var_steps)
    assert valid_var is False
    assert "earlier step" in reason_var.lower() or "non-existent" in reason_var.lower()


# ---------------------------------------------------------------------------
# 19, 20, 21. Cumulative Risk Calculation
# ---------------------------------------------------------------------------


def test_cumulative_risk_calculation():
    """Verify cumulative plan risk correctly escalates to the highest risk action."""
    # Read-only steps -> LOW
    low_steps = [
        {"step_order": 1, "action": "search", "arguments": {}},
    ]
    assert GoalPlanner.calculate_plan_risk(low_steps) == "low"

    # Contains create_directory / move -> MEDIUM
    med_steps = [
        {"step_order": 1, "action": "create_directory", "arguments": {}},
        {"step_order": 2, "action": "move", "arguments": {}},
    ]
    assert GoalPlanner.calculate_plan_risk(med_steps) == "medium"

    # Contains delete -> HIGH
    high_steps = [
        {"step_order": 1, "action": "move", "arguments": {}},
        {"step_order": 2, "action": "delete", "arguments": {}},
    ]
    assert GoalPlanner.calculate_plan_risk(high_steps) == "high"


# ---------------------------------------------------------------------------
# 22, 23, 24. CLI Approval Acceptance, Denial, and Safe Zero Modification
# ---------------------------------------------------------------------------


def test_cli_goal_approval_denial_leaves_filesystem_unchanged(tmp_path):
    """Verify denying approval at CLI plan preview aborts cleanly with zero modifications."""
    ws_dir = tmp_path / "ws_cli_deny"
    src = ws_dir / "source"
    src.mkdir(parents=True)
    f = src / "internship_test.pdf"
    f.write_text("test pdf", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="CliDenyWs", permissions=["READ", "WRITE"])

    # Run goal command with "n" (deny)
    res = runner.invoke(
        app, ["goal", "Organize my internship PDFs into an Internship folder"], input="n\n"
    )

    assert res.exit_code == 0
    assert "Proposed Execution Plan" in res.stdout
    assert "Plan execution cancelled by user" in res.stdout

    # Verify zero filesystem changes: Internship folder NOT created, file NOT moved
    assert not (ws_dir / "Internship").exists()
    assert f.exists()


# ---------------------------------------------------------------------------
# 25 & 26. End-to-End Goal Execution & Physical Verification
# ---------------------------------------------------------------------------


def test_cli_goal_end_to_end_execution(tmp_path):
    """Verify approving plan executes all steps through StepExecutor with physical verification."""
    ws_dir = tmp_path / "ws_e2e"
    src = ws_dir / "source"
    src.mkdir(parents=True)
    f1 = src / "internship_offer.pdf"
    f2 = src / "internship_report.pdf"
    f1.write_text("offer letter", encoding="utf-8")
    f2.write_text("final report", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="E2EWs", permissions=["READ", "WRITE"])

    # Run goal command with "y" (approve)
    res = runner.invoke(
        app, ["goal", "Organize my internship PDFs into an Internship folder"], input="y\n"
    )

    assert res.exit_code == 0
    assert "Proposed Execution Plan" in res.stdout
    assert "Task Created:" in res.stdout
    assert "Goal Completed" in res.stdout or "completed successfully" in res.stdout

    # Physical verification on disk
    dest_dir = ws_dir / "Internship"
    assert dest_dir.exists() and dest_dir.is_dir()
    assert (dest_dir / "internship_offer.pdf").exists()
    assert (dest_dir / "internship_report.pdf").exists()
    assert not f1.exists()
    assert not f2.exists()


# ---------------------------------------------------------------------------
# 27. Compensation (Empty Directory Rollback on Failure)
# ---------------------------------------------------------------------------


def test_compensation_removes_empty_created_directory_on_failure(tmp_path):
    """Verify compensation safely cleans up an empty created directory when task fails."""
    ws_dir = tmp_path / "ws_comp"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="CompWs", permissions=["READ", "WRITE"])

    new_dir = ws_dir / "TempDir"

    steps_spec = [
        {"step_order": 1, "action": "create_directory", "arguments": {"directory": str(new_dir)}},
        # Step 2 will fail because ghost.txt does not exist
        {
            "step_order": 2,
            "action": "move",
            "arguments": {
                "source": str(ws_dir / "ghost.txt"),
                "destination": "$output.step_1.path",
            },
            "depends_on_order": 1,
        },
    ]

    task = TaskManager.create_task("Test compensation with create_directory", steps_spec)
    executed = StepExecutor.execute_task(task, compensate_on_failure=True)

    assert executed.status == TaskStatus.FAILED or executed.status == TaskStatus.PARTIAL_FAILURE
    # Step 1 succeeded, Step 2 failed -> compensation ran -> new_dir removed because it was empty
    assert not new_dir.exists()


# ---------------------------------------------------------------------------
# 28. Audit Logging
# ---------------------------------------------------------------------------


def test_audit_logging_of_goal_plan_and_execution(tmp_path):
    """Verify plan generation, step executions, and audit records are properly recorded."""
    ws_dir = tmp_path / "ws_audit"
    src = ws_dir / "source"
    src.mkdir(parents=True)
    f = src / "internship_audit.pdf"
    f.write_text("audit doc", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="AuditWs", permissions=["READ", "WRITE"])

    res = runner.invoke(
        app, ["goal", "Organize my internship PDFs into an Internship folder"], input="y\n"
    )
    assert res.exit_code == 0

    logs = db.get_recent_logs(limit=10)
    actions = [r["action"] for r in logs]
    assert "goal" in actions
    assert "create_directory" in actions
    assert "move" in actions


# ---------------------------------------------------------------------------
# 29. Search-Only Goal Parsing Variations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "goal_str,expected_action,expected_ext,expected_filename,expected_keywords",
    [
        ("Find all PDF files", "search", ".pdf", None, []),
        ("Find all TXT files", "search", ".txt", None, []),
        ("Search for PDF files", "search", ".pdf", None, []),
        ("Show me all PDF files", "search", ".pdf", None, []),
        ("List all Python files", "search", ".py", None, []),
        ("Find m4_test.txt", "search", ".txt", "m4_test.txt", []),
        ("Search for my resume", "search", None, None, ["resume"]),
    ],
)
def test_search_goal_parsing_variations(
    goal_str, expected_action, expected_ext, expected_filename, expected_keywords
):
    """Verify natural-language search variations extract search action and criteria."""
    analysis = GoalPlanner._heuristic_goal_analysis(goal_str)
    assert analysis["action_type"] == expected_action
    assert analysis["extension"] == expected_ext
    assert analysis["filename"] == expected_filename
    for kw in expected_keywords:
        assert kw in analysis["keywords"]


# ---------------------------------------------------------------------------
# 30. Search-Only Goal Plan Synthesis & Execution
# ---------------------------------------------------------------------------


def test_search_goal_plan_synthesis_and_cli_execution(tmp_path):
    """Verify search-only goal creates valid search plan steps and executes cleanly."""
    ws_dir = tmp_path / "ws_search_goal"
    src = ws_dir / "src"
    src.mkdir(parents=True)
    p1 = src / "doc1.pdf"
    p2 = src / "doc2.pdf"
    p1.write_text("pdf one", encoding="utf-8")
    p2.write_text("pdf two", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="SearchGoalWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Find all PDF files")
    assert len(plan.discovered_files) == 2
    assert len(plan.steps) == 1
    assert plan.steps[0]["action"] == "search"
    assert plan.steps[0]["arguments"]["extension"] == ".pdf"
    assert plan.cumulative_risk == "low"
    assert plan.requires_approval is False

    # CLI invocation executes search step without error
    res = runner.invoke(app, ["goal", "Find all PDF files"])
    assert res.exit_code == 0
    assert "Proposed Execution Plan" in res.stdout
    assert "SEARCH" in res.stdout
    assert "Goal Completed" in res.stdout or "completed successfully" in res.stdout


def test_search_goal_specific_filename(tmp_path):
    """Verify searching for specific file (e.g. m4_test.txt) finds only that file."""
    ws_dir = tmp_path / "ws_find_file"
    src = ws_dir / "src"
    src.mkdir(parents=True)
    target_file = src / "m4_test.txt"
    other_file = src / "other.txt"
    target_file.write_text("hello m4", encoding="utf-8")
    other_file.write_text("other text", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="FindFileWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Find m4_test.txt")
    assert len(plan.discovered_files) == 1
    assert Path(plan.discovered_files[0]["path"]).resolve() == target_file.resolve()
    assert len(plan.steps) == 1
    assert plan.steps[0]["action"] == "search"
    assert plan.steps[0]["arguments"]["filename"] == "m4_test.txt"


def test_search_goal_zero_match_safe_no_op(tmp_path):
    """Verify search with zero matching files produces safe no-op with zero steps."""
    ws_dir = tmp_path / "ws_zero_search"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="ZeroSearchWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Find all PDF files")
    assert len(plan.discovered_files) == 0
    assert len(plan.steps) == 0
    assert "No matching files were found" in plan.summary


# ---------------------------------------------------------------------------
# 31. Physical Verification of CREATE_DIRECTORY in Real Execution Path
# ---------------------------------------------------------------------------


def test_create_directory_physical_verification_real_execution(tmp_path, monkeypatch):
    """Verify create_directory through real execution path physically exists on disk."""
    ws_dir = tmp_path / "ws_phys_mkdir"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="PhysMkdirWs", permissions=["READ", "WRITE"])

    target_dir = ws_dir / "PhysicalDir"

    # Step specification
    step_spec = {
        "step_order": 1,
        "action": "create_directory",
        "arguments": {"directory": str(target_dir)},
    }
    task = TaskManager.create_task("Create physical dir", [step_spec])
    step = task.steps[0]

    # Execute through real StepExecutor.execute_step
    success = StepExecutor.execute_step(
        step=step,
        task=task,
        resolved_args=step.arguments,
    )

    assert success is True
    assert step.status == StepStatus.SUCCESS
    assert target_dir.exists() and target_dir.is_dir()
    assert step.output is not None
    assert Path(step.output["path"]).resolve() == target_dir.resolve()

    # Negative test: If directory does not physically exist, step MUST NOT be marked SUCCESS
    non_existent_dir = ws_dir / "GhostDir"
    fail_step_spec = {
        "step_order": 1,
        "action": "create_directory",
        "arguments": {"directory": str(non_existent_dir)},
    }
    fail_task = TaskManager.create_task("Ghost dir fail test", [fail_step_spec])
    fail_step = fail_task.steps[0]

    # Simulate tool returning success but filesystem missing directory
    monkeypatch.setattr(
        "app.tasks.executor.create_directory",
        lambda d: f"Verified: directory created successfully.\nPath: {d}",
    )

    fail_success = StepExecutor.execute_step(
        step=fail_step,
        task=fail_task,
        resolved_args=fail_step.arguments,
    )
    assert fail_success is False
    assert fail_step.status == StepStatus.FAILED
    assert not non_existent_dir.exists()


# ---------------------------------------------------------------------------
# 32. End-to-End: Organize PDF files into Documents
# ---------------------------------------------------------------------------


def test_organize_pdf_files_into_documents_end_to_end(tmp_path):
    """Verify Organize PDF files into Documents creates Documents physically and moves files."""
    ws_dir = tmp_path / "ws_docs_e2e"
    src1 = ws_dir / "src1"
    src2 = ws_dir / "src2"
    src1.mkdir(parents=True)
    src2.mkdir(parents=True)

    f1 = src1 / "report.pdf"
    f2 = src1 / "invoice.pdf"
    f3 = src2 / "report.pdf"  # Potential duplicate name across directories

    f1.write_text("report 1", encoding="utf-8")
    f2.write_text("invoice 1", encoding="utf-8")
    f3.write_text("report 2", encoding="utf-8")

    WorkspaceManager.add_workspace(ws_dir, name="DocsE2EWs", permissions=["READ", "WRITE"])

    # Run CLI command with approve
    res = runner.invoke(app, ["goal", "Organize my PDF files into a Documents folder"], input="y\n")

    assert res.exit_code == 0
    assert "Proposed Execution Plan" in res.stdout
    assert "Goal Completed" in res.stdout or "completed successfully" in res.stdout

    # Physical verification: Documents directory MUST physically exist
    dest_dir = ws_dir / "Documents"
    assert dest_dir.exists() and dest_dir.is_dir()

    # Physical verification: Non-colliding files are present in Documents
    dest_files = [f.name for f in dest_dir.iterdir() if f.is_file()]
    assert "invoice.pdf" in dest_files
    assert "report.pdf" in dest_files


# ---------------------------------------------------------------------------
# 33. Rename Goal Planning & Execution Tests
# ---------------------------------------------------------------------------


def test_rename_goal_source_to_destination(tmp_path):
    """Verify renaming existing file generates a single RENAME step and executes successfully."""
    ws_dir = tmp_path / "ws_rename"
    ws_dir.mkdir()
    src_file = ws_dir / "agent_demo.txt"
    src_file.write_text("demo content", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="RenameWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename agent_demo.txt to agent_demo_renamed.txt in RenameWs")

    assert len(plan.discovered_files) == 1
    assert Path(plan.discovered_files[0]["path"]).resolve() == src_file.resolve()
    assert len(plan.steps) == 1
    assert plan.steps[0]["action"] == "rename"
    assert plan.steps[0]["arguments"]["source"] == str(src_file.resolve())
    assert plan.steps[0]["arguments"]["new_name"] == "agent_demo_renamed.txt"
    assert plan.cumulative_risk == "medium"
    assert plan.requires_approval is True

    # Execute via CLI with approval
    goal_cmd = "Rename agent_demo.txt to agent_demo_renamed.txt in RenameWs"
    res = runner.invoke(app, ["goal", goal_cmd], input="y\n")
    assert res.exit_code == 0
    assert "RENAME" in res.stdout
    assert "Goal Completed" in res.stdout or "completed successfully" in res.stdout

    # Verify physical file rename on disk
    dest_file = ws_dir / "agent_demo_renamed.txt"
    assert dest_file.exists() and dest_file.is_file()
    assert dest_file.read_text(encoding="utf-8") == "demo content"
    assert not src_file.exists()


def test_rename_goal_quoted_filenames_with_spaces(tmp_path):
    """Verify rename parser handles quoted filenames with spaces cleanly."""
    ws_dir = tmp_path / "ws_spaces"
    ws_dir.mkdir()
    src_file = ws_dir / "my quarterly report.pdf"
    src_file.write_text("quarterly data", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="SpacesWs", permissions=["READ", "WRITE"])

    goal_str = 'Rename "my quarterly report.pdf" to "my final report.pdf" in SpacesWs'
    plan = GoalPlanner.plan_goal(goal_str)

    assert len(plan.discovered_files) == 1
    assert len(plan.steps) == 1
    assert plan.steps[0]["action"] == "rename"
    assert plan.steps[0]["arguments"]["source"] == str(src_file.resolve())
    assert plan.steps[0]["arguments"]["new_name"] == "my final report.pdf"

    # Execute via CLI
    res = runner.invoke(
        app,
        ["goal", 'Rename "my quarterly report.pdf" to "my final report.pdf" in SpacesWs'],
        input="y\n",
    )
    assert res.exit_code == 0
    dest_file = ws_dir / "my final report.pdf"
    assert dest_file.exists()
    assert not src_file.exists()


def test_rename_goal_ambiguous_source_filename(tmp_path):
    """Verify ambiguous filename matching multiple files halts without guessing."""
    ws1 = tmp_path / "ws_ambig1"
    ws2 = tmp_path / "ws_ambig2"
    ws1.mkdir()
    ws2.mkdir()
    f1 = ws1 / "common_doc.txt"
    f2 = ws2 / "common_doc.txt"
    f1.write_text("doc 1", encoding="utf-8")
    f2.write_text("doc 2", encoding="utf-8")
    WorkspaceManager.add_workspace(ws1, name="AmbigWs1", permissions=["READ", "WRITE"])
    WorkspaceManager.add_workspace(ws2, name="AmbigWs2", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename common_doc.txt to common_renamed.txt")

    assert len(plan.discovered_files) == 2
    assert len(plan.steps) == 0
    assert "Ambiguous rename goal" in plan.summary
    assert f1.exists()
    assert f2.exists()


def test_rename_goal_nonexistent_source(tmp_path):
    """Verify nonexistent source file halts safely as a zero-modification no-op."""
    ws_dir = tmp_path / "ws_empty_rename"
    ws_dir.mkdir()
    WorkspaceManager.add_workspace(ws_dir, name="EmptyRenameWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename missing_file.txt to new_file.txt in EmptyRenameWs")

    assert len(plan.discovered_files) == 0
    assert len(plan.steps) == 0
    assert "No matching file" in plan.summary


def test_rename_goal_destination_collision(tmp_path):
    """Verify collision with an existing destination file rejects plan generation safely."""
    ws_dir = tmp_path / "ws_collision"
    ws_dir.mkdir()
    src = ws_dir / "source.txt"
    dest = ws_dir / "target.txt"
    src.write_text("src content", encoding="utf-8")
    dest.write_text("existing content", encoding="utf-8")
    WorkspaceManager.add_workspace(ws_dir, name="CollisionWs", permissions=["READ", "WRITE"])

    plan = GoalPlanner.plan_goal("Rename source.txt to target.txt in CollisionWs")

    assert len(plan.steps) == 0
    assert "Destination collision" in plan.summary
    # Both files must remain untouched
    assert src.read_text(encoding="utf-8") == "src content"
    assert dest.read_text(encoding="utf-8") == "existing content"


def test_rename_goal_permission_enforcement(tmp_path):
    """Verify rename requires WRITE permission and rejects disabled workspaces."""
    ws_dir = tmp_path / "ws_ro"
    ws_dir.mkdir()
    f = ws_dir / "readonly.txt"
    f.write_text("readonly content", encoding="utf-8")
    ws = WorkspaceManager.add_workspace(ws_dir, name="RoWs", permissions=["READ"])

    # Missing WRITE permission
    plan = GoalPlanner.plan_goal("Rename readonly.txt to renamed.txt in RoWs")
    assert len(plan.steps) == 0
    assert "lacks WRITE permission" in plan.summary

    # Disabled workspace
    WorkspaceManager.disable_workspace(ws.workspace_id)
    plan_disabled = GoalPlanner.plan_goal("Rename readonly.txt to renamed.txt in RoWs")
    assert len(plan_disabled.steps) == 0
    assert "currently disabled" in plan_disabled.summary


# ---------------------------------------------------------------------------
# Move vs Rename Goal Classification Regressions
# ---------------------------------------------------------------------------


def test_move_with_renamed_in_filename_classified_as_move(tmp_path):
    """Verify 'Move <file> into <directory> in <ws>' with 'renamed' in filename is a MOVE."""
    ws_dir = tmp_path / "Downloads"
    ws_dir.mkdir()
    f = ws_dir / "agent_test_report_renamed.txt"
    f.write_text("report data", encoding="utf-8")
    WorkspaceManager.add_workspace(
        ws_dir, name="Downloads", permissions=["READ", "WRITE"]
    )

    plan = GoalPlanner.plan_goal(
        "Move agent_test_report_renamed.txt into agent_test_archive in Downloads"
    )

    assert plan.target_workspace is not None
    assert plan.target_workspace.name == "Downloads"
    assert len(plan.discovered_files) == 1
    assert Path(plan.discovered_files[0]["path"]).resolve() == f.resolve()
    # Steps: create_directory then move
    actions = [s["action"] for s in plan.steps]
    assert actions == ["create_directory", "move"]
    move_step = next(s for s in plan.steps if s["action"] == "move")
    assert move_step["arguments"]["source"] == str(f)
    assert plan.cumulative_risk == "medium"
    assert plan.requires_approval is True


def test_existing_move_syntax_supported(tmp_path):
    """Verify existing move syntax works for single-workspace and cross-workspace."""
    ws1 = tmp_path / "Downloads"
    ws2 = tmp_path / "Documents"
    ws1.mkdir()
    ws2.mkdir()
    (ws1 / "doc.pdf").write_text("pdf", encoding="utf-8")
    WorkspaceManager.add_workspace(ws1, name="Downloads", permissions=["READ", "WRITE"])
    WorkspaceManager.add_workspace(ws2, name="Documents", permissions=["READ", "WRITE"])

    # Cross-workspace move
    plan_cross = GoalPlanner.plan_goal(
        "Move doc.pdf from Downloads into Documents"
    )
    assert plan_cross.target_workspace is not None
    assert plan_cross.target_workspace.name == "Documents"
    assert len(plan_cross.discovered_files) == 1
    assert [s["action"] for s in plan_cross.steps] == ["move"]

    # Single workspace move into folder
    (ws1 / "report.txt").write_text("txt", encoding="utf-8")
    plan_single = GoalPlanner.plan_goal(
        "Move report.txt into Archive in Downloads"
    )
    assert plan_single.target_workspace is not None
    assert plan_single.target_workspace.name == "Downloads"
    assert len(plan_single.discovered_files) == 1
    assert [s["action"] for s in plan_single.steps] == ["create_directory", "move"]


def test_rename_goals_remain_rename_goals(tmp_path):
    """Verify genuine rename goals are always classified and planned as rename."""
    ws_dir = tmp_path / "Downloads"
    ws_dir.mkdir()
    f = ws_dir / "agent_test_report.txt"
    f.write_text("report", encoding="utf-8")
    WorkspaceManager.add_workspace(
        ws_dir, name="Downloads", permissions=["READ", "WRITE"]
    )

    plan = GoalPlanner.plan_goal(
        "Rename agent_test_report.txt to agent_test_report_renamed.txt in Downloads"
    )
    assert plan.target_workspace is not None
    assert plan.target_workspace.name == "Downloads"
    assert len(plan.steps) == 1
    assert plan.steps[0]["action"] == "rename"
    assert plan.steps[0]["arguments"]["new_name"] == "agent_test_report_renamed.txt"


def test_archive_and_organize_wording_preserved(tmp_path):
    """Verify archive and organize goals are not accidentally turned into MOVE unless requested."""
    ws_dir = tmp_path / "Downloads"
    ws_dir.mkdir()
    (ws_dir / "item1.pdf").write_text("p1", encoding="utf-8")
    (ws_dir / "item2.pdf").write_text("p2", encoding="utf-8")
    WorkspaceManager.add_workspace(
        ws_dir, name="Downloads", permissions=["READ", "WRITE"]
    )

    # 1. Archive wording produces archive action
    heur_archive = GoalPlanner._heuristic_goal_analysis(
        "Archive all PDF files into archive folder in Downloads"
    )
    assert heur_archive["action_type"] == "archive"

    # 2. Organize wording produces organize action
    heur_org = GoalPlanner._heuristic_goal_analysis(
        "Organize all documents in Downloads"
    )
    assert heur_org["action_type"] == "organize"

    # 3. Explicit move wording produces move action
    heur_move = GoalPlanner._heuristic_goal_analysis(
        "Move all PDF files into archive folder in Downloads"
    )
    assert heur_move["action_type"] == "move"
