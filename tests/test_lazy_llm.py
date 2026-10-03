"""
Focused regression tests for lazy LLM initialization and credential independence.

Verifies:
a. app.agent, app.tasks.goal_planner, and app.tasks.planner import without GROQ_API_KEY.
b. Deterministic filesystem/task tests run without GROQ_API_KEY.
c. Actual LLM operations require GROQ_API_KEY and fail with clear configuration errors if missing.
d. Existing LLM behavior remains intact when configured or mocked.
"""

import importlib
from unittest.mock import MagicMock

import pytest

import app.agent
import app.database as db
import app.tasks.goal_planner
import app.tasks.planner
from app.tasks.goal_planner import GoalPlanner
from app.workspaces import WorkspaceManager


@pytest.fixture(autouse=True)
def isolate_environment(tmp_path, monkeypatch):
    """Ensure tests run against an isolated SQLite DB and clean environment."""
    test_db = tmp_path / "test_lazy_llm.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    monkeypatch.setenv("AGENT_DB_PATH", str(test_db))
    db.init_db(test_db)
    yield


def test_modules_import_without_groq_api_key(monkeypatch):
    """Verify modules can be imported without GROQ_API_KEY and without raising GroqError."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)

    # Reset module state
    app.agent.llm = None
    app.agent.llm_with_tools = None
    app.tasks.goal_planner.llm = None
    app.tasks.planner.llm = None

    # Reload modules without GROQ_API_KEY
    reloaded_agent = importlib.reload(app.agent)
    reloaded_goal_planner = importlib.reload(app.tasks.goal_planner)
    reloaded_planner = importlib.reload(app.tasks.planner)

    assert reloaded_agent.llm is None
    assert reloaded_agent.llm_with_tools is None
    assert reloaded_goal_planner.llm is None
    assert reloaded_planner.llm is None


def test_deterministic_goal_planning_without_groq_api_key(tmp_path, monkeypatch):
    """Verify deterministic planning runs fully offline without GROQ_API_KEY."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)

    app.tasks.goal_planner.llm = None

    ws_dir = tmp_path / "OfflineWs"
    ws_dir.mkdir()
    test_file = ws_dir / "invoice.pdf"
    test_file.write_text("dummy invoice content", encoding="utf-8")

    WorkspaceManager.add_workspace(
        ws_dir, name="OfflineWs", permissions=["READ", "WRITE"]
    )

    plan = GoalPlanner.plan_goal("Find invoice.pdf in OfflineWs")

    assert plan.target_workspace is not None
    assert plan.target_workspace.name == "OfflineWs"
    assert len(plan.discovered_files) == 1
    assert "invoice.pdf" in plan.discovered_files[0]["path"]


def test_actual_llm_invocation_without_groq_api_key_raises_error(monkeypatch):
    """Verify invoking actual LLM functionality without GROQ_API_KEY raises a clear error."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)

    app.agent.llm = None
    app.agent.llm_with_tools = None
    app.tasks.planner.llm = None
    app.tasks.goal_planner.llm = None

    # 1. app.agent.get_llm()
    with pytest.raises(ValueError, match="GROQ_API_KEY environment variable is missing"):
        app.agent.get_llm()

    # 2. app.agent.get_llm_with_tools()
    with pytest.raises(ValueError, match="GROQ_API_KEY environment variable is missing"):
        app.agent.get_llm_with_tools()

    # 3. app.agent.extract_intent()
    with pytest.raises(ValueError, match="GROQ_API_KEY environment variable is missing"):
        app.agent.extract_intent("Find files in Downloads")

    # 4. app.agent.run_agent()
    with pytest.raises(ValueError, match="GROQ_API_KEY environment variable is missing"):
        app.agent.run_agent("Find files in Downloads")

    # 5. app.tasks.planner.get_llm()
    with pytest.raises(ValueError, match="GROQ_API_KEY environment variable is missing"):
        app.tasks.planner.get_llm()

    # 6. app.tasks.goal_planner.get_llm()
    with pytest.raises(ValueError, match="GROQ_API_KEY environment variable is missing"):
        app.tasks.goal_planner.get_llm()


def test_existing_llm_behavior_intact_when_configured(monkeypatch):
    """Verify LLM client initializes properly when configured and supports mock overrides."""
    fake_key = "gsk_valid_mock_api_key_test_12345"
    monkeypatch.setenv("GROQ_API_KEY", fake_key)

    app.agent.llm = None
    app.agent.llm_with_tools = None

    # Mock ChatGroq to avoid external network calls while checking initialization
    mock_chat_groq = MagicMock()
    mock_instance = MagicMock()
    mock_chat_groq.return_value = mock_instance
    monkeypatch.setattr("app.agent.ChatGroq", mock_chat_groq)

    client = app.agent.get_llm()
    assert client == mock_instance
    mock_chat_groq.assert_called_once_with(
        model="openai/gpt-oss-20b",
        api_key=fake_key,
        temperature=0,
    )

    # Verify monkeypatch override works for backward compatibility with existing tests
    custom_mock = MagicMock()
    mock_response = MagicMock()
    mock_response.content = '{"action": "search", "filename": "test.txt", "directory": null}'
    custom_mock.invoke.return_value = mock_response

    monkeypatch.setattr("app.agent.llm", custom_mock)
    intent = app.agent.extract_intent("Find test.txt")
    assert intent["action"] == "search"
    assert intent["filename"] == "test.txt"
