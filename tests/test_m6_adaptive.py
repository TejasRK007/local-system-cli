"""M6 tests for observation, adaptive replanning, completion, and safety boundaries."""

import pytest

import app.database as db
from app.tasks.adaptive import AdaptiveFilesystemAgent
from app.tasks.goal_planner import GoalPlan
from app.tasks.models import StepStatus, Task, TaskStatus, TaskStep
from app.workspaces import WorkspaceManager


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "m6.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))
    db.init_db(db_path)
    yield


def make_plan(goal, ws, steps, risk="medium"):
    return GoalPlan(
        goal=goal,
        target_workspace=ws,
        discovered_files=[{"path": str(ws.canonical_path / "a.txt")}],
        steps=steps,
        cumulative_risk=risk,
        requires_approval=risk != "low",
        summary=f"Generated {len(steps)} step(s).",
    )


def make_task(task_id="m6_task", status=TaskStatus.COMPLETED, steps=None):
    return Task(
        task_id=task_id,
        user_request="M6 test",
        status=status,
        steps=steps or [],
    )


def test_observation_is_workspace_scoped_and_collects_environment_facts(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "one.pdf").write_text("1", encoding="utf-8")
    (ws / "two.pdf").write_text("2", encoding="utf-8")
    (ws / "note.txt").write_text("n", encoding="utf-8")
    (ws / ".git").mkdir()
    (ws / ".git" / "ignored.txt").write_text("x", encoding="utf-8")
    WorkspaceManager.add_workspace(ws, name="M6Obs", permissions=["READ"])

    observation = AdaptiveFilesystemAgent.observe()
    assert len(observation.workspaces) == 1
    item = observation.workspaces[0]
    assert item.file_count == 3
    assert item.extension_counts[".pdf"] == 2
    assert item.extension_counts[".txt"] == 1
    assert all(".git" not in f.path for f in item.files)


def test_observation_skips_workspace_without_read_permission(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "secret.txt").write_text("secret", encoding="utf-8")
    WorkspaceManager.add_workspace(ws, name="M6NoRead", permissions=["WRITE"])

    observation = AdaptiveFilesystemAgent.observe()
    assert observation.workspaces == []


def test_diff_detects_added_removed_and_changed_files(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    WorkspaceManager.add_workspace(ws, name="M6Diff", permissions=["READ"])
    first = ws / "first.txt"
    first.write_text("a", encoding="utf-8")
    before = AdaptiveFilesystemAgent.observe()

    first.write_text("changed", encoding="utf-8")
    second = ws / "second.txt"
    second.write_text("b", encoding="utf-8")
    after = AdaptiveFilesystemAgent.observe()

    diff = AdaptiveFilesystemAgent.diff(before, after)
    assert str(first.resolve()) in diff.changed
    assert str(second.resolve()) in diff.added
    assert diff.changed_anything


def test_m6_denies_modifying_plan_without_explicit_approval(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("a", encoding="utf-8")
    WorkspaceManager.add_workspace(ws, name="M6Approve", permissions=["READ", "WRITE"])

    step = {
        "step_order": 1,
        "action": "rename",
        "arguments": {"source": str(ws / "a.txt"), "new_name": "b.txt"},
        "depends_on_order": None,
    }
    plan = make_plan("rename", WorkspaceManager.get_workspace_by_name("M6Approve"), [step])
    monkeypatch.setattr(AdaptiveFilesystemAgent, "_plan_for_goal", lambda goal: plan)

    called = {"execute": False}
    monkeypatch.setattr(
        "app.tasks.adaptive.StepExecutor.execute_task",
        lambda *args, **kwargs: called.__setitem__("execute", True),
    )

    result = AdaptiveFilesystemAgent.run("rename", max_cycles=1)
    assert result.status == "BLOCKED"
    assert called["execute"] is False
    assert (ws / "a.txt").exists()


def test_m6_replans_after_filesystem_changes(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("a", encoding="utf-8")
    WorkspaceManager.add_workspace(ws, name="M6Replan", permissions=["READ", "WRITE"])
    workspace = WorkspaceManager.get_workspace_by_name("M6Replan")

    first_step = {
        "step_order": 1,
        "action": "rename",
        "arguments": {"source": str(ws / "a.txt"), "new_name": "b.txt"},
        "depends_on_order": None,
    }
    second_step = {
        "step_order": 1,
        "action": "rename",
        "arguments": {"source": str(ws / "c.txt"), "new_name": "d.txt"},
        "depends_on_order": None,
    }
    plan1 = make_plan("adaptive", workspace, [first_step])
    plan2 = make_plan("adaptive", workspace, [second_step])
    plan3 = GoalPlan(
        goal="adaptive",
        target_workspace=workspace,
        discovered_files=[],
        steps=[],
        cumulative_risk="low",
        requires_approval=False,
        summary="No matching files were found in the authorized workspaces. No changes were made.",
    )
    plans = iter([plan1, plan2, plan3])
    monkeypatch.setattr(AdaptiveFilesystemAgent, "_plan_for_goal", lambda goal: next(plans))

    calls = []

    def fake_execute(task, **kwargs):
        calls.append(task.task_id)
        if len(calls) == 1:
            (ws / "c.txt").write_text("new", encoding="utf-8")
        return make_task(task_id=f"m6_{len(calls)}", status=TaskStatus.COMPLETED)

    monkeypatch.setattr("app.tasks.adaptive.StepExecutor.execute_task", fake_execute)

    result = AdaptiveFilesystemAgent.run(
        "adaptive",
        confirm_callback=lambda plan: True,
        max_cycles=3,
    )
    assert result.status == "COMPLETE"
    assert len(result.cycles) == 2
    assert len(calls) == 2
    assert any(str(ws / "c.txt") in path for path in result.observed_changes)


def test_m6_stops_repeated_plan_instead_of_looping(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("a", encoding="utf-8")
    WorkspaceManager.add_workspace(ws, name="M6Loop", permissions=["READ", "WRITE"])
    workspace = WorkspaceManager.get_workspace_by_name("M6Loop")
    step = {
        "step_order": 1,
        "action": "rename",
        "arguments": {"source": str(ws / "a.txt"), "new_name": "b.txt"},
        "depends_on_order": None,
    }
    plan = make_plan("loop", workspace, [step])
    monkeypatch.setattr(AdaptiveFilesystemAgent, "_plan_for_goal", lambda goal: plan)
    monkeypatch.setattr(
        "app.tasks.adaptive.StepExecutor.execute_task",
        lambda task, **kwargs: make_task(status=TaskStatus.PARTIAL_FAILURE),
    )

    result = AdaptiveFilesystemAgent.run(
        "loop",
        confirm_callback=lambda plan: True,
        max_cycles=5,
    )
    assert result.status == "BLOCKED"
    assert len(result.cycles) == 1
    assert "same plan" in result.summary.lower()


def test_m6_marks_failed_execution_partial_when_no_replan_exists(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    WorkspaceManager.add_workspace(ws, name="M6Partial", permissions=["READ", "WRITE"])
    workspace = WorkspaceManager.get_workspace_by_name("M6Partial")
    step = {
        "step_order": 1,
        "action": "rename",
        "arguments": {"source": str(ws / "missing.txt"), "new_name": "new.txt"},
        "depends_on_order": None,
    }
    plan = make_plan("partial", workspace, [step])
    no_plan = GoalPlan(
        goal="partial",
        target_workspace=workspace,
        discovered_files=[],
        steps=[],
        cumulative_risk="low",
        requires_approval=False,
        summary="No matching files were found in the authorized workspaces. No changes were made.",
    )
    plans = iter([plan, no_plan])
    monkeypatch.setattr(AdaptiveFilesystemAgent, "_plan_for_goal", lambda goal: next(plans))
    monkeypatch.setattr(
        "app.tasks.adaptive.StepExecutor.execute_task",
        lambda task, **kwargs: make_task(status=TaskStatus.FAILED),
    )

    result = AdaptiveFilesystemAgent.run(
        "partial", confirm_callback=lambda plan: True, max_cycles=2
    )
    assert result.status == "PARTIAL"


def test_m6_physical_verification_detects_missing_output(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    WorkspaceManager.add_workspace(ws, name="M6Verify", permissions=["READ", "WRITE"])
    source = ws / "source.txt"
    source.write_text("x", encoding="utf-8")
    step = TaskStep(
        step_id="s1",
        task_id="t1",
        step_order=1,
        action="rename",
        arguments={"source": str(source), "new_name": "done.txt"},
        status=StepStatus.SUCCESS,
        output={"path": str(ws / "done.txt")},
    )
    result = AdaptiveFilesystemAgent._verify_task(make_task(steps=[step]))
    assert result["verified"] is False
    assert result["failed_steps"] == 1


def test_m6_search_is_stable_and_does_not_reexecute_forever(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("a", encoding="utf-8")
    WorkspaceManager.add_workspace(ws, name="M6Search", permissions=["READ"])
    workspace = WorkspaceManager.get_workspace_by_name("M6Search")
    step = {
        "step_order": 1,
        "action": "search",
        "arguments": {"directory": str(ws), "extension": ".txt"},
        "depends_on_order": None,
    }
    plan = make_plan("find", workspace, [step], risk="low")
    plan.requires_approval = False
    monkeypatch.setattr(AdaptiveFilesystemAgent, "_plan_for_goal", lambda goal: plan)
    calls = {"count": 0}

    def fake_execute(task, **kwargs):
        calls["count"] += 1
        return make_task(status=TaskStatus.COMPLETED)

    monkeypatch.setattr("app.tasks.adaptive.StepExecutor.execute_task", fake_execute)
    result = AdaptiveFilesystemAgent.run("find", max_cycles=5)
    assert result.status == "COMPLETE"
    assert calls["count"] == 1
