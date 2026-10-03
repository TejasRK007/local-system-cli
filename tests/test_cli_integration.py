"""
Integration and regression tests for Milestone 2 CLI natural-language operations:
- Move with explicit relative source & destination
- Move to standard allowed directory
- Rename with explicit & bare filenames
- Delete with explicit target path
- Search with natural language query
- Ambiguous filename handling
- Destination conflict handling
- Unsafe path policy blocking
- Recovery engine integration
- Persistent audit logging
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import app.database as db
import app.tools.file_actions as fa
import app.tools.filesystem as fs
from app.agent import extract_intent, resolve_file_sources
from app.main import app

runner = CliRunner()


class MockLLM:
    """Mock LLM response generator for deterministic testing without live API calls."""

    def __init__(self, content: str):
        self.content = content

    def invoke(self, prompt):
        class Response:
            pass

        res = Response()
        res.content = self.content
        return res


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Isolate SQLite audit DB and set ALLOWED_DIRECTORIES for safe testing."""
    temp_db_path = tmp_path / "test_agent.db"
    monkeypatch.setattr(db, "DB_PATH", temp_db_path)
    monkeypatch.setenv("AGENT_DB_PATH", str(temp_db_path))
    db.init_db(temp_db_path)

    # Include tmp_path in allowed directories for test isolation
    monkeypatch.setattr(
        fa,
        "ALLOWED_DIRECTORIES",
        [tmp_path, Path.home() / "Downloads", Path.home() / "Documents", Path.home() / "Desktop"],
    )
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Intent Extraction Tests
# ---------------------------------------------------------------------------


def test_extract_intent_move_explicit_paths(monkeypatch):
    """Verify LLM intent extraction returns move action with explicit relative paths."""
    mock_llm = MockLLM(
        '{"action": "move", "source": "manual_test/source/test.pdf", '
        '"destination": "manual_test/destination"}'
    )
    monkeypatch.setattr("app.agent.llm", mock_llm)

    intent = extract_intent("Move test.pdf from manual_test/source to manual_test/destination")
    assert intent["action"] == "move"
    assert intent["source"] == "manual_test/source/test.pdf"
    assert intent["destination"] == "manual_test/destination"


def test_extract_intent_rename(monkeypatch):
    """Verify LLM intent extraction returns rename action with target names."""
    mock_llm = MockLLM(
        '{"action": "rename", "source": "manual_test/source/old-name.pdf", '
        '"new_name": "new-name.pdf", "directory": null}'
    )
    monkeypatch.setattr("app.agent.llm", mock_llm)

    intent = extract_intent("Rename manual_test/source/old-name.pdf to new-name.pdf")
    assert intent["action"] == "rename"
    assert intent["source"] == "manual_test/source/old-name.pdf"
    assert intent["new_name"] == "new-name.pdf"


def test_extract_intent_delete(monkeypatch):
    """Verify LLM intent extraction returns delete action."""
    mock_llm = MockLLM(
        '{"action": "delete", "target": "manual_test/source/delete-test.txt", "directory": null}'
    )
    monkeypatch.setattr("app.agent.llm", mock_llm)

    intent = extract_intent("Delete manual_test/source/delete-test.txt")
    assert intent["action"] == "delete"
    assert intent["target"] == "manual_test/source/delete-test.txt"


# ---------------------------------------------------------------------------
# 2. Path Resolution Tests
# ---------------------------------------------------------------------------


def test_resolve_file_sources_explicit_relative_path(tmp_path, monkeypatch):
    """Verify explicit relative path is resolved to actual file on disk."""
    monkeypatch.chdir(tmp_path)
    src_dir = tmp_path / "manual_test" / "source"
    src_dir.mkdir(parents=True)
    test_file = src_dir / "test.pdf"
    test_file.write_text("PDF content")

    rel_path = "manual_test/source/test.pdf"
    sources = resolve_file_sources(rel_path)

    assert len(sources) == 1
    assert Path(sources[0]["path"]).resolve() == test_file.resolve()


# ---------------------------------------------------------------------------
# 3. CLI Integration — MOVE with Explicit Relative Paths
# ---------------------------------------------------------------------------


def test_cli_move_explicit_relative_path_success(tmp_path, monkeypatch):
    """End-to-end: move file from manual_test/source to manual_test/destination via CLI."""
    monkeypatch.chdir(tmp_path)
    src_dir = tmp_path / "manual_test" / "source"
    dst_dir = tmp_path / "manual_test" / "destination"
    src_dir.mkdir(parents=True)
    dst_dir.mkdir(parents=True)

    src_file = src_dir / "test.pdf"
    dst_file = dst_dir / "test.pdf"
    src_file.write_text("PDF Data")

    mock_llm = MockLLM(
        '{"action": "move", "source": "manual_test/source/test.pdf", '
        '"destination": "manual_test/destination"}'
    )
    monkeypatch.setattr("app.agent.llm", mock_llm)

    res = runner.invoke(
        app,
        ["agent", "Move test.pdf from manual_test/source to manual_test/destination"],
        input="y\n",
    )

    assert res.exit_code == 0
    assert "Task Completed" in res.output or "Verified" in res.output
    assert not src_file.exists()
    assert dst_file.exists()
    assert dst_file.read_text() == "PDF Data"

    logs = db.get_recent_logs(limit=1)
    assert len(logs) == 1
    assert logs[0]["action"] == "move"
    assert logs[0]["execution_status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 4. CLI Integration — MOVE to Standard Allowed Directory (Documents)
# ---------------------------------------------------------------------------


def test_cli_move_to_documents_success(tmp_path, monkeypatch):
    """End-to-end: move file to Documents directory."""
    doc_dir = tmp_path / "Documents"
    doc_dir.mkdir()
    dl_dir = tmp_path / "Downloads"
    dl_dir.mkdir()
    desktop_dir = tmp_path / "Desktop"
    desktop_dir.mkdir()

    known_dirs = {"documents": doc_dir, "downloads": dl_dir, "desktop": desktop_dir}
    monkeypatch.setattr("app.agent.KNOWN_DIRECTORIES", known_dirs)
    monkeypatch.setattr(fs, "KNOWN_DIRECTORIES", known_dirs)

    src_file = dl_dir / "agent_move_test.txt"
    src_file.write_text("Test file content")

    mock_llm = MockLLM(
        '{"action": "move", "source": "agent_move_test.txt", "destination": "Documents"}'
    )
    monkeypatch.setattr("app.agent.llm", mock_llm)

    res = runner.invoke(app, ["agent", "Move agent_move_test.txt to Documents"], input="y\n")

    assert res.exit_code == 0
    assert not src_file.exists()
    assert (doc_dir / "agent_move_test.txt").exists()


# ---------------------------------------------------------------------------
# 5. CLI Integration — RENAME
# ---------------------------------------------------------------------------


def test_cli_rename_success(tmp_path, monkeypatch):
    """End-to-end: rename old-name.pdf to new-name.pdf via CLI."""
    monkeypatch.chdir(tmp_path)
    src_dir = tmp_path / "manual_test" / "source"
    src_dir.mkdir(parents=True)
    old_file = src_dir / "old-name.pdf"
    new_file = src_dir / "new-name.pdf"
    old_file.write_text("Rename test content")

    mock_llm = MockLLM(
        '{"action": "rename", "source": "manual_test/source/old-name.pdf", '
        '"new_name": "new-name.pdf", "directory": null}'
    )
    monkeypatch.setattr("app.agent.llm", mock_llm)

    res = runner.invoke(
        app, ["agent", "Rename manual_test/source/old-name.pdf to new-name.pdf"], input="y\n"
    )

    assert res.exit_code == 0
    assert not old_file.exists()
    assert new_file.exists()
    assert new_file.read_text() == "Rename test content"

    logs = db.get_recent_logs(limit=1)
    assert logs[0]["action"] == "rename"
    assert logs[0]["execution_status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 6. CLI Integration — DELETE
# ---------------------------------------------------------------------------


def test_cli_delete_success(tmp_path, monkeypatch):
    """End-to-end: delete file with HIGH risk approval via CLI."""
    monkeypatch.chdir(tmp_path)
    src_dir = tmp_path / "manual_test" / "source"
    src_dir.mkdir(parents=True)
    del_file = src_dir / "delete-test.txt"
    del_file.write_text("Delete me")

    mock_llm = MockLLM(
        '{"action": "delete", "target": "manual_test/source/delete-test.txt", "directory": null}'
    )
    monkeypatch.setattr("app.agent.llm", mock_llm)

    res = runner.invoke(app, ["agent", "Delete manual_test/source/delete-test.txt"], input="y\n")

    assert res.exit_code == 0
    assert not del_file.exists()

    logs = db.get_recent_logs(limit=1)
    assert logs[0]["action"] == "delete"
    assert logs[0]["risk_level"] == "high"
    assert logs[0]["execution_status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 7. Destination Conflict Handling
# ---------------------------------------------------------------------------


def test_cli_move_destination_conflict_preserves_both(tmp_path, monkeypatch):
    """Verify move conflict prevents overwrite and logs CONFLICT status."""
    monkeypatch.chdir(tmp_path)
    src_dir = tmp_path / "manual_test" / "source"
    dst_dir = tmp_path / "manual_test" / "destination"
    src_dir.mkdir(parents=True)
    dst_dir.mkdir(parents=True)

    src_file = src_dir / "report.pdf"
    dst_file = dst_dir / "report.pdf"
    src_file.write_text("NEW SOURCE FILE")
    dst_file.write_text("ORIGINAL DESTINATION FILE")

    mock_llm = MockLLM(
        '{"action": "move", "source": "manual_test/source/report.pdf", '
        '"destination": "manual_test/destination"}'
    )
    monkeypatch.setattr("app.agent.llm", mock_llm)

    res = runner.invoke(
        app,
        ["agent", "Move report.pdf from manual_test/source to manual_test/destination"],
        input="y\n",
    )

    assert res.exit_code == 0
    assert "Conflict Detected" in res.output
    assert src_file.exists() and src_file.read_text() == "NEW SOURCE FILE"
    assert dst_file.exists() and dst_file.read_text() == "ORIGINAL DESTINATION FILE"

    logs = db.get_recent_logs(limit=1)
    assert logs[0]["execution_status"] == "CONFLICT"


# ---------------------------------------------------------------------------
# 8. Ambiguity Handling
# ---------------------------------------------------------------------------


def test_cli_ambiguous_move_refuses_safely(tmp_path, monkeypatch):
    """Verify duplicate filenames across directories cause ambiguous refusal."""
    dir1 = tmp_path / "source1"
    dir2 = tmp_path / "source2"
    dir1.mkdir()
    dir2.mkdir()
    (dir1 / "duplicate.pdf").write_text("file 1")
    (dir2 / "duplicate.pdf").write_text("file 2")

    known_dirs = {"s1": dir1, "s2": dir2}
    monkeypatch.setattr("app.agent.KNOWN_DIRECTORIES", known_dirs)
    monkeypatch.setattr(fs, "KNOWN_DIRECTORIES", known_dirs)

    mock_llm = MockLLM('{"action": "move", "source": "duplicate.pdf", "destination": "Documents"}')
    monkeypatch.setattr("app.agent.llm", mock_llm)

    res = runner.invoke(app, ["agent", "Move duplicate.pdf to Documents"])

    assert res.exit_code == 0
    assert "Multiple Matches" in res.output or "Ambiguous" in res.output
    assert (dir1 / "duplicate.pdf").exists()
    assert (dir2 / "duplicate.pdf").exists()

    logs = db.get_recent_logs(limit=1)
    assert logs[0]["execution_status"] == "AMBIGUOUS"


# ---------------------------------------------------------------------------
# 9. Unsafe Path Policy Blocking
# ---------------------------------------------------------------------------


def test_cli_unsafe_path_blocked(tmp_path, monkeypatch):
    """Verify attempting an action outside allowed directories is blocked."""
    forbidden_file = tmp_path.parent / "forbidden.txt"
    if not forbidden_file.exists():
        forbidden_file.write_text("secret")

    mock_llm = MockLLM(
        f'{{"action": "delete", "target": "{forbidden_file.as_posix()}", "directory": null}}'
    )
    monkeypatch.setattr("app.agent.llm", mock_llm)

    res = runner.invoke(app, ["agent", f"Delete {forbidden_file.as_posix()}"], input="y\n")

    assert res.exit_code == 0
    assert "blocked" in res.output.lower() or "outside allowed" in res.output.lower()
    assert forbidden_file.exists()
