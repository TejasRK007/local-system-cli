"""
Automated Test Suite for AI Repository Chat & Grounded Code Retrieval (Milestone 9 - Prompt 3).

Covers:
1. File chunking with line range metadata and secret redaction
2. SQLite FTS5 indexing of text files with exclusion rules and idempotency
3. Repository and commit isolation (cross-repo / cross-commit leakage prevention)
4. Source citations formatting (file path, line ranges, code snippets)
5. Anti-hallucination and insufficient evidence honest fallback
6. Stale commit SHA detection and warning generation
7. Repository-scoped chat history, session creation, and history clearing
8. Privacy gating (cloud consent, local preference, deterministic fallback on LLM failure)
9. Repository list for chat with index status
10. FastAPI REST endpoints for repository chat
"""

import json
import sqlite3
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch
import zipfile

import pytest
from fastapi.testclient import TestClient

import app.database as db
from app.server import server_app
from app.tools.github_chat import (
    CHUNK_LINES_OVERLAP,
    CHUNK_LINES_SIZE,
    _ensure_chat_tables,
    check_repository_stale,
    chunk_text_content,
    clear_chat_history,
    create_chat_session,
    execute_repository_chat,
    get_chat_history,
    index_repository_text_files,
    list_analyzed_repos_for_chat,
    retrieve_relevant_chunks,
)
from app.tools.github_tools import (
    _ensure_github_tables,
    github_add_repository,
    github_store_account,
    github_store_analysis,
)


@pytest.fixture(autouse=True)
def isolate_test_db(tmp_path, monkeypatch):
    """Ensure every test runs in an isolated SQLite database."""
    test_db_file = tmp_path / "test_github_chat.db"
    monkeypatch.setattr(db, "DB_PATH", test_db_file)
    _ensure_github_tables()
    _ensure_chat_tables()
    yield test_db_file


@pytest.fixture
def api_client():
    return TestClient(server_app)


# -----------------------------------------------------------------------------
# 1. Chunking & Line Range Metadata Tests
# -----------------------------------------------------------------------------
def test_chunk_text_content_metadata():
    """Verify that chunks have correct 1-indexed line numbers and overlap."""
    lines = [f"line {i}" for i in range(1, 151)]
    text = "\n".join(lines)

    chunks = chunk_text_content(text, "src/index.ts", max_lines=50, overlap=10)
    assert len(chunks) > 1

    first = chunks[0]
    assert first["file_path"] == "src/index.ts"
    assert first["start_line"] == 1
    assert first["end_line"] == 50
    assert "line 1" in first["content"]
    assert "line 50" in first["content"]

    second = chunks[1]
    assert second["start_line"] == 41  # 50 - 10 + 1 = 41
    assert second["end_line"] == 90

    # Ensure empty string returns empty chunk list
    assert chunk_text_content("", "empty.py") == []


def test_chunk_text_redacts_secrets_prior_to_chunking():
    """Verify raw secrets are purged before chunk generation."""
    code_with_token = (
        "def connect():\n"
        "    token = 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456'\n"
        "    api_key = 'sk-12345678901234567890123456789012'\n"
        "    return token, api_key\n"
    )
    chunks = chunk_text_content(code_with_token, "config.py")
    assert len(chunks) == 1
    content = chunks[0]["content"]

    assert "ghp_ABC" not in content
    assert "sk-123456789" not in content
    assert "[REDACTED]" in content


# -----------------------------------------------------------------------------
# 2. SQLite FTS5 Indexing & Exclusion Tests
# -----------------------------------------------------------------------------
def test_index_repository_text_files_and_exclusions(tmp_path):
    """Test text file indexing, excluded folders, and idempotency."""
    repo_dir = tmp_path / "sample_repo"
    repo_dir.mkdir()

    # Included files
    (repo_dir / "main.py").write_text(
        "import auth\ndef main():\n    print('Server starting on port 8080')\n",
        encoding="utf-8",
    )
    (repo_dir / "auth.py").write_text(
        "def authenticate_user(username, password):\n    # Authenticates users\n    return True\n",
        encoding="utf-8",
    )

    # Excluded dirs
    node_dir = repo_dir / "node_modules" / "pkg"
    node_dir.mkdir(parents=True)
    (node_dir / "index.js").write_text("console.log('should be skipped');", encoding="utf-8")

    git_dir = repo_dir / ".git" / "objects"
    git_dir.mkdir(parents=True)
    (git_dir / "blob.txt").write_text("git internal blob", encoding="utf-8")

    # Binary file
    (repo_dir / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

    result = index_repository_text_files(
        repo_root=repo_dir,
        repo_name="acme/service",
        commit_sha="c111222",
        repo_id=1,
    )

    assert result["success"] is True
    assert result["indexed_files"] == 2
    assert result["total_chunks"] >= 2

    # Verify database contents
    conn = sqlite3.connect(str(db.DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT file_path FROM github_repo_file_chunks WHERE repo_name = 'acme/service'")
    indexed_paths = [r[0] for r in cur.fetchall()]
    conn.close()

    assert any(p.endswith("main.py") for p in indexed_paths)
    assert any(p.endswith("auth.py") for p in indexed_paths)
    assert not any("node_modules" in p for p in indexed_paths)
    assert not any(".git" in p for p in indexed_paths)
    assert not any(p.endswith(".png") for p in indexed_paths)

    # Verify idempotency: re-indexing replaces chunks without duplication
    result2 = index_repository_text_files(
        repo_root=repo_dir,
        repo_name="acme/service",
        commit_sha="c111222",
        repo_id=1,
    )
    assert result2["indexed_files"] == 2

    conn = sqlite3.connect(str(db.DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM github_repo_file_chunks WHERE repo_name = 'acme/service'")
    count = cur.fetchone()[0]
    conn.close()
    assert count == result["total_chunks"]


# -----------------------------------------------------------------------------
# 3. Repository & Commit Isolation Tests
# -----------------------------------------------------------------------------
def test_repository_and_commit_isolation(tmp_path):
    """Ensure search queries never leak chunks across repos or different commits."""
    # Repo A (commit A1)
    dir_a = tmp_path / "repo_a"
    dir_a.mkdir()
    (dir_a / "db.py").write_text("def connect_database():\n    return 'DB_CONNECTION_A'\n", encoding="utf-8")
    index_repository_text_files(dir_a, "org/repo-a", "commit-aaa")

    # Repo B (commit B1)
    dir_b = tmp_path / "repo_b"
    dir_b.mkdir()
    (dir_b / "db.py").write_text("def connect_database():\n    return 'DB_CONNECTION_B'\n", encoding="utf-8")
    index_repository_text_files(dir_b, "org/repo-b", "commit-bbb")

    # Query repo-a
    chunks_a = retrieve_relevant_chunks("org/repo-a", "commit-aaa", "connect_database")
    assert len(chunks_a) > 0
    assert all("DB_CONNECTION_A" in c["content"] for c in chunks_a)
    assert not any("DB_CONNECTION_B" in c["content"] for c in chunks_a)

    # Query repo-b
    chunks_b = retrieve_relevant_chunks("org/repo-b", "commit-bbb", "connect_database")
    assert len(chunks_b) > 0
    assert all("DB_CONNECTION_B" in c["content"] for c in chunks_b)
    assert not any("DB_CONNECTION_A" in c["content"] for c in chunks_b)

    # Query repo-a with non-existent or stale commit
    chunks_stale = retrieve_relevant_chunks("org/repo-a", "commit-nonexistent", "connect_database")
    assert chunks_stale == []


# -----------------------------------------------------------------------------
# 4. Citations & Line Range Grounding Tests
# -----------------------------------------------------------------------------
def test_retrieval_citations_formatting(tmp_path):
    """Test citation structure with file_path, start_line, end_line, and code_snippet."""
    dir_x = tmp_path / "repo_x"
    dir_x.mkdir()
    code = (
        "import jwt\n"
        "from fastapi import HTTPException\n"
        "\n"
        "def verify_jwt_token(token: str):\n"
        "    if not token:\n"
        "        raise HTTPException(status_code=401, detail='Token missing')\n"
        "    return jwt.decode(token, 'secret', algorithms=['HS256'])\n"
    )
    (dir_x / "security.py").write_text(code, encoding="utf-8")
    index_repository_text_files(dir_x, "acme/api", "commit-123")

    res = execute_repository_chat(
        repo_name="acme/api",
        commit_sha="commit-123",
        question="Where is verify_jwt_token defined?",
        allow_cloud=False,
    )

    assert res["success"] is True
    sources = res["sources"]
    assert len(sources) > 0
    src = sources[0]
    assert "security.py" in src["file_path"]
    assert src["start_line"] == 1
    assert src["end_line"] >= 7
    assert "verify_jwt_token" in src["code_snippet"]


# -----------------------------------------------------------------------------
# 5. Anti-Hallucination & Insufficient Evidence Tests
# -----------------------------------------------------------------------------
def test_insufficient_evidence_honest_fallback(tmp_path):
    """When queried on topics with zero evidence, the system honestly states insufficient evidence."""
    dir_x = tmp_path / "repo_empty"
    dir_x.mkdir()
    (dir_x / "hello.py").write_text("print('hello world')\n", encoding="utf-8")
    index_repository_text_files(dir_x, "acme/simple", "commit-simple")

    res = execute_repository_chat(
        repo_name="acme/simple",
        commit_sha="commit-simple",
        question="Where is the payment gateway Stripe webhook handler configured?",
        allow_cloud=False,
    )

    assert res["success"] is True
    assert "Insufficient evidence" in res["answer"]
    assert res["sources"] == []


# -----------------------------------------------------------------------------
# 6. Stale Index Detection Tests
# -----------------------------------------------------------------------------
def test_check_repository_stale():
    """Verify stale commit warning when remote commit differs from indexed commit."""
    # Stored account
    github_store_account(
        login="octocat",
        name="The Octocat",
        email="octo@cat.com",
        avatar_url="https://github.com/avatar.png",
        public_repos=10,
        total_private_repos=2,
        access_token="gho_test_token",
        scope="repo",
    )
    conn = sqlite3.connect(str(db.DB_PATH))
    cur = conn.execute(
        """INSERT INTO github_repositories (github_id, owner, name, full_name, is_active, added_at, last_synced_at)
           VALUES (12345, 'octocat', 'Hello-World', 'octocat/Hello-World', 1, '2026-01-01', '2026-01-01')"""
    )
    repo_id = cur.lastrowid
    conn.commit()
    conn.close()

    # 1. Matching commit -> not stale
    mock_resp_match = MagicMock()
    mock_resp_match.read.return_value = json.dumps([{"sha": "abc111"}]).encode("utf-8")
    mock_resp_match.__enter__.return_value = mock_resp_match

    with patch("urllib.request.urlopen", return_value=mock_resp_match):
        is_stale, live_sha = check_repository_stale(repo_id, "abc111")
        assert is_stale is False
        assert live_sha == "abc111"

    # 2. Changed commit -> is stale with warning
    mock_resp_stale = MagicMock()
    mock_resp_stale.read.return_value = json.dumps([{"sha": "def222"}]).encode("utf-8")
    mock_resp_stale.__enter__.return_value = mock_resp_stale

    with patch("urllib.request.urlopen", return_value=mock_resp_stale):
        is_stale, live_sha = check_repository_stale(repo_id, "abc111")
        assert is_stale is True
        assert live_sha == "def222"

    # 3. Snapshot / ZIP repo -> not stale
    is_stale_zip, live_sha_zip = check_repository_stale(None, "snapshot-123")
    assert is_stale_zip is False
    assert live_sha_zip == "snapshot-123"


# -----------------------------------------------------------------------------
# 7. Chat History Isolation & Session Management Tests
# -----------------------------------------------------------------------------
def test_chat_history_isolation_and_clearing(tmp_path):
    """Verify chat sessions and history messages are strictly isolated per repo and clearable."""
    dir_x = tmp_path / "repo_h"
    dir_x.mkdir()
    (dir_x / "app.py").write_text("def ping(): return 'pong'\n", encoding="utf-8")
    index_repository_text_files(dir_x, "org/app-one", "c1")
    index_repository_text_files(dir_x, "org/app-two", "c2")

    # Ask in app-one
    res1 = execute_repository_chat(
        repo_name="org/app-one",
        commit_sha="c1",
        question="What does ping do?",
        allow_cloud=False,
    )
    session_id_1 = res1["session_id"]

    # Ask in app-two
    res2 = execute_repository_chat(
        repo_name="org/app-two",
        commit_sha="c2",
        question="Is ping available?",
        allow_cloud=False,
    )
    session_id_2 = res2["session_id"]

    assert session_id_1 != session_id_2

    # History for app-one
    h1 = get_chat_history("org/app-one")
    assert h1["count"] >= 2  # user + assistant
    assert all("What does ping do?" in m["content"] or "ping" in m["content"] for m in h1["messages"])
    assert not any("Is ping available?" in m["content"] for m in h1["messages"])

    # Clear history for app-one
    clear_res = clear_chat_history("org/app-one")
    assert clear_res["success"] is True

    h1_after = get_chat_history("org/app-one")
    assert h1_after["count"] == 0

    # app-two history remains untouched
    h2 = get_chat_history("org/app-two")
    assert h2["count"] >= 2


def test_create_new_chat_session():
    """Verify explicit session creation."""
    session = create_chat_session("org/my-project", "commit-999", title="Architecture Q&A")
    assert session["success"] is True
    assert session["session_id"] > 0
    assert session["title"] == "Architecture Q&A"


# -----------------------------------------------------------------------------
# 8. Privacy Gating & Mocked LLM Tests
# -----------------------------------------------------------------------------
def test_privacy_gating_blocks_cloud_when_disallowed(tmp_path):
    """When allow_cloud=False, Groq is never invoked and processing stays local."""
    dir_x = tmp_path / "repo_privacy"
    dir_x.mkdir()
    (dir_x / "calc.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    index_repository_text_files(dir_x, "safe/repo", "c1")

    with patch("app.llm.is_ollama_online", return_value=False), \
         patch("app.llm.GroqChatWrapper") as mock_groq:
        res = execute_repository_chat(
            repo_name="safe/repo",
            commit_sha="c1",
            question="Where is add defined?",
            allow_cloud=False,
        )
        # GroqChatWrapper should not be instantiated or called
        mock_groq.assert_not_called()
        assert res["llm_provider"] == "deterministic-fallback"
        assert "safe/repo" in res["answer"]
        assert len(res["sources"]) > 0


def test_mocked_llm_failure_graceful_fallback(tmp_path):
    """If the LLM client throws an exception, system falls back gracefully to code-search answer."""
    dir_x = tmp_path / "repo_err"
    dir_x.mkdir()
    (dir_x / "service.py").write_text("def run_service(): pass\n", encoding="utf-8")
    index_repository_text_files(dir_x, "err/repo", "c1")

    with patch("app.llm.is_ollama_online", return_value=True), \
         patch("app.llm.OllamaChatWrapper.invoke", side_effect=RuntimeError("Ollama timeout")):
        res = execute_repository_chat(
            repo_name="err/repo",
            commit_sha="c1",
            question="Where is run_service defined?",
            allow_cloud=False,
        )
        assert res["success"] is True
        assert res["llm_provider"] == "deterministic-fallback"
        assert "run_service" in res["answer"]


# -----------------------------------------------------------------------------
# 9. List Analyzed Repositories for Chat
# -----------------------------------------------------------------------------
def test_list_analyzed_repos_for_chat(tmp_path):
    """Test discovery of completed analyses for chat dropdown."""
    dir_x = tmp_path / "repo_disc"
    dir_x.mkdir()
    (dir_x / "index.js").write_text("console.log('hello');", encoding="utf-8")
    index_repository_text_files(dir_x, "org/discovered-repo", "c999")

    # Store analysis record
    github_store_analysis(
        analysis={
            "repo_name": "org/discovered-repo",
            "commit_sha": "c999",
            "summary": "A web application",
            "frameworks": ["Express"],
            "languages": {"JavaScript": 100},
            "dependencies": [],
            "entry_points": [],
            "folder_modules": [],
            "components": [],
            "architecture_flow": "",
            "run_instructions": {},
            "test_instructions": {},
            "observations": [],
            "unknowns": {},
            "inspected_files_count": 1,
            "status": "completed",
        }
    )

    data = list_analyzed_repos_for_chat()
    assert data["success"] is True
    repos = data["repositories"]
    assert any(r["repo_name"] == "org/discovered-repo" for r in repos)
    matched = next(r for r in repos if r["repo_name"] == "org/discovered-repo")
    assert matched["is_indexed"] is True
    assert matched["chunks_count"] >= 1
    assert "Express" in matched["frameworks"]


# -----------------------------------------------------------------------------
# 10. FastAPI REST Endpoints Tests
# -----------------------------------------------------------------------------
def test_api_github_chat_endpoints(api_client, tmp_path):
    """Test the 5 REST API routes under /api/github/chat/*."""
    dir_x = tmp_path / "api_repo"
    dir_x.mkdir()
    (dir_x / "api.py").write_text("def ping(): return 'pong'\n", encoding="utf-8")
    index_repository_text_files(dir_x, "test/api-repo", "sha123")

    github_store_analysis(
        analysis={
            "repo_name": "test/api-repo",
            "commit_sha": "sha123",
            "summary": "API Service",
            "frameworks": ["FastAPI"],
            "languages": {"Python": 100},
            "dependencies": [],
            "entry_points": [],
            "folder_modules": [],
            "components": [],
            "architecture_flow": "",
            "run_instructions": {},
            "test_instructions": {},
            "observations": [],
            "unknowns": {},
            "inspected_files_count": 1,
            "status": "completed",
        }
    )

    # 1. GET /api/github/chat/repos
    resp_repos = api_client.get("/api/github/chat/repos")
    assert resp_repos.status_code == 200
    assert any(r["repo_name"] == "test/api-repo" for r in resp_repos.json()["repositories"])

    # 2. POST /api/github/chat/query
    resp_query = api_client.post(
        "/api/github/chat/query",
        json={
            "repo_name": "test/api-repo",
            "commit_sha": "sha123",
            "message": "Where is ping defined?",
        },
    )
    assert resp_query.status_code == 200
    q_data = resp_query.json()
    assert q_data["success"] is True
    assert "ping" in q_data["answer"]
    assert len(q_data["sources"]) > 0

    session_id = q_data["session_id"]

    # 3. GET /api/github/chat/history
    resp_hist = api_client.get(f"/api/github/chat/history?repo_name=test/api-repo&session_id={session_id}")
    assert resp_hist.status_code == 200
    h_data = resp_hist.json()
    assert h_data["count"] >= 2

    # 4. POST /api/github/chat/new
    resp_new = api_client.post(
        "/api/github/chat/new",
        json={"repo_name": "test/api-repo", "commit_sha": "sha123", "title": "New Chat Session"},
    )
    assert resp_new.status_code == 200
    assert resp_new.json()["success"] is True

    # 5. POST /api/github/chat/clear
    resp_clear = api_client.post(
        "/api/github/chat/clear",
        json={"repo_name": "test/api-repo"},
    )
    assert resp_clear.status_code == 200
    assert resp_clear.json()["success"] is True

    # 6. Validation: Empty query message returns 400
    resp_bad = api_client.post(
        "/api/github/chat/query",
        json={"repo_name": "test/api-repo", "message": "   "},
    )
    assert resp_bad.status_code == 400
