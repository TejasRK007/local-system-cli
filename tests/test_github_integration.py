"""
Automated Test Suite for GitHub Integration Module (Milestone 9).

Covers:
1. URL parsing & validation (HTTPS, SSH, owner/repo shorthand, invalid formats)
2. Connection status tracking (disconnected initial state, connected state)
3. OAuth account storage, token security (never leaked in responses), and disconnection
4. Public and private repository tracking via mocked GitHub REST API
5. Local repository listing, search filtering, and sorting
6. Safe repository removal (soft-delete; never deletes from GitHub)
7. Fast-API endpoints (/api/github/auth/..., /api/github/repos/...)
"""

import base64
import json
import sqlite3
from io import BytesIO
from unittest.mock import MagicMock, patch
import urllib.request
import pytest
from fastapi.testclient import TestClient

import app.database as db
from app.server import server_app
from app.tools.github_tools import (
    _ensure_github_tables,
    _parse_github_repo_url,
    github_add_repository,
    github_connection_status,
    github_disconnect_account,
    github_get_connected_account,
    github_get_repo_metadata,
    github_list_connected_repos,
    github_list_user_repos,
    github_remove_repository,
    github_store_account,
)


@pytest.fixture(autouse=True)
def isolate_test_db(tmp_path, monkeypatch):
    """Ensure every test runs in an isolated SQLite database."""
    test_db_file = tmp_path / "test_agent_github.db"
    monkeypatch.setattr(db, "DB_PATH", test_db_file)
    _ensure_github_tables()
    yield test_db_file


@pytest.fixture
def api_client():
    """FastAPI TestClient fixture."""
    return TestClient(server_app)


# -----------------------------------------------------------------------------
# 1. URL Parsing & Validation Tests
# -----------------------------------------------------------------------------

def test_parse_github_repo_url_https():
    assert _parse_github_repo_url("https://github.com/octocat/Hello-World") == "octocat/Hello-World"
    assert _parse_github_repo_url("https://github.com/octocat/Hello-World/") == "octocat/Hello-World"
    assert _parse_github_repo_url("https://github.com/pallets/flask.git") == "pallets/flask"
    assert _parse_github_repo_url("http://github.com/user/repo") == "user/repo"


def test_parse_github_repo_url_ssh():
    assert _parse_github_repo_url("git@github.com:torvalds/linux.git") == "torvalds/linux"
    assert _parse_github_repo_url("git@github.com:facebook/react") == "facebook/react"


def test_parse_github_repo_url_shorthand():
    assert _parse_github_repo_url("fastapi/fastapi") == "fastapi/fastapi"
    assert _parse_github_repo_url("my_org-1/my-repo.v2") == "my_org-1/my-repo.v2"


def test_parse_github_repo_url_invalid():
    assert _parse_github_repo_url("https://gitlab.com/user/repo") is None
    assert _parse_github_repo_url("https://github.com/") is None
    assert _parse_github_repo_url("just-a-name") is None
    assert _parse_github_repo_url("owner/repo/extra/path") is None
    assert _parse_github_repo_url("") is None


# -----------------------------------------------------------------------------
# 2. Account Connection, Status & Token Security Tests
# -----------------------------------------------------------------------------

def test_initial_status_is_disconnected():
    status = github_connection_status()
    assert status["connected"] is False
    assert status["login"] is None
    assert status["total_repos_connected"] == 0
    assert status["public_repos"] == 0
    assert status["private_repos"] == 0
    assert status["recently_accessed"] == []


def test_store_account_and_connection_status():
    result = github_store_account(
        login="testdev",
        name="Test Developer",
        email="testdev@example.com",
        avatar_url="https://github.com/images/error/testdev.gif",
        public_repos=12,
        total_private_repos=4,
        access_token="gho_mock_access_token_12345",
        scope="read:user,repo",
    )
    assert result["success"] is True
    assert result["login"] == "testdev"

    # Verify status
    status = github_connection_status()
    assert status["connected"] is True
    assert status["login"] == "testdev"
    assert status["name"] == "Test Developer"
    assert status["public_repos"] == 12
    assert status["private_repos"] == 4

    # Security verification: access token must NEVER be exposed in returned dict
    assert "access_token" not in status
    account_info = github_get_connected_account()
    assert account_info["connected"] is True
    assert "access_token" not in account_info


def test_disconnect_account():
    github_store_account(
        login="tempuser",
        name="Temp",
        email="temp@example.com",
        avatar_url="",
        public_repos=1,
        total_private_repos=0,
        access_token="gho_temp_token",
        scope="read:user",
    )
    assert github_connection_status()["connected"] is True

    disc = github_disconnect_account()
    assert disc["success"] is True
    assert github_connection_status()["connected"] is False


# -----------------------------------------------------------------------------
# 3. Repository Tracking & Management Tests (Mocked GitHub REST API)
# -----------------------------------------------------------------------------

def _make_mock_response(data: dict):
    """Helper to mock urllib.request.urlopen returning JSON."""
    raw = json.dumps(data).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_resp.__enter__.return_value = mock_resp
    return mock_resp


def test_add_public_repository():
    mock_repo_data = {
        "id": 1001,
        "name": "fastapi",
        "full_name": "fastapi/fastapi",
        "owner": {"login": "fastapi"},
        "description": "FastAPI framework, high performance, easy to learn.",
        "private": False,
        "language": "Python",
        "default_branch": "master",
        "stargazers_count": 75000,
        "fork": False,
        "html_url": "https://github.com/fastapi/fastapi",
    }

    with patch.object(urllib.request, "urlopen", return_value=_make_mock_response(mock_repo_data)):
        res = github_add_repository("https://github.com/fastapi/fastapi")

    assert res["success"] is True
    assert res["status"] == "ADDED"
    assert res["full_name"] == "fastapi/fastapi"
    assert res["private"] is False
    assert res["stars"] == 75000

    # Verify present in list
    repos = github_list_connected_repos()["repos"]
    assert len(repos) == 1
    assert repos[0]["full_name"] == "fastapi/fastapi"
    assert repos[0]["private"] is False


def test_add_private_repository():
    mock_repo_data = {
        "id": 2002,
        "name": "internal-tool",
        "full_name": "mycompany/internal-tool",
        "owner": {"login": "mycompany"},
        "description": "Internal developer tooling.",
        "private": True,
        "language": "TypeScript",
        "default_branch": "main",
        "stargazers_count": 5,
        "fork": False,
        "html_url": "https://github.com/mycompany/internal-tool",
    }

    with patch.object(urllib.request, "urlopen", return_value=_make_mock_response(mock_repo_data)):
        res = github_add_repository("mycompany/internal-tool")

    assert res["success"] is True
    assert res["private"] is True

    repos = github_list_connected_repos()["repos"]
    assert len(repos) == 1
    assert repos[0]["private"] is True
    assert repos[0]["language"] == "TypeScript"


def test_add_invalid_url_rejected():
    res = github_add_repository("https://invalid-domain.com/some/path")
    assert res["success"] is False
    assert res["status"] == "VALIDATION_FAILURE"


def test_add_duplicate_repo_is_idempotent():
    mock_repo_data = {
        "id": 3003,
        "name": "idempotent-repo",
        "full_name": "org/idempotent-repo",
        "owner": {"login": "org"},
        "description": "Version 1",
        "private": False,
        "language": "Go",
        "default_branch": "main",
        "stargazers_count": 10,
        "fork": False,
        "html_url": "https://github.com/org/idempotent-repo",
    }

    with patch.object(urllib.request, "urlopen", return_value=_make_mock_response(mock_repo_data)):
        res1 = github_add_repository("org/idempotent-repo")
        assert res1["success"] is True

    # Update description & stars in second call
    mock_repo_data["description"] = "Version 2 with updates"
    mock_repo_data["stargazers_count"] = 25
    with patch.object(urllib.request, "urlopen", return_value=_make_mock_response(mock_repo_data)):
        res2 = github_add_repository("org/idempotent-repo")
        assert res2["success"] is True

    repos = github_list_connected_repos()["repos"]
    assert len(repos) == 1
    assert repos[0]["description"] == "Version 2 with updates"
    assert repos[0]["stars"] == 25


def test_list_connected_repos_filtering_and_search():
    # Insert 3 repos directly for test
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        conn.execute("""
            INSERT INTO github_repositories
            (owner, name, full_name, description, private, language, default_branch, stars, fork, html_url, added_at, is_active)
            VALUES
            ('alice', 'ai-agent', 'alice/ai-agent', 'Smart agent in Python', 0, 'Python', 'main', 100, 0, 'url1', '2026-01-01', 1),
            ('alice', 'secret-vault', 'alice/secret-vault', 'Encrypted store', 1, 'Rust', 'main', 42, 0, 'url2', '2026-01-02', 1),
            ('bob', 'web-app', 'bob/web-app', 'Frontend application', 0, 'JavaScript', 'main', 15, 0, 'url3', '2026-01-03', 1)
        """)
        conn.commit()
    finally:
        conn.close()

    # All
    all_res = github_list_connected_repos(filter_visibility="all")
    assert all_res["count"] == 3

    # Public filter
    pub_res = github_list_connected_repos(filter_visibility="public")
    assert pub_res["count"] == 2
    assert all(r["private"] is False for r in pub_res["repos"])

    # Private filter
    priv_res = github_list_connected_repos(filter_visibility="private")
    assert priv_res["count"] == 1
    assert priv_res["repos"][0]["full_name"] == "alice/secret-vault"
    assert priv_res["repos"][0]["private"] is True

    # Search filter
    search_res = github_list_connected_repos(search="agent")
    assert search_res["count"] == 1
    assert search_res["repos"][0]["full_name"] == "alice/ai-agent"


def test_remove_repository_soft_delete():
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        cur = conn.execute("""
            INSERT INTO github_repositories
            (owner, name, full_name, private, language, added_at, is_active)
            VALUES ('demo', 'removable-repo', 'demo/removable-repo', 0, 'Go', '2026-01-01', 1)
        """)
        repo_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    assert len(github_list_connected_repos()["repos"]) == 1

    rem = github_remove_repository(repo_id)
    assert rem["success"] is True
    assert rem["status"] == "REMOVED"

    # Repos list is now empty
    assert len(github_list_connected_repos()["repos"]) == 0

    # Verify it is still in DB as is_active=0 (safe soft-delete)
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        row = conn.execute("SELECT is_active FROM github_repositories WHERE id = ?", (repo_id,)).fetchone()
        assert row[0] == 0
    finally:
        conn.close()


def test_remove_nonexistent_repo():
    res = github_remove_repository(99999)
    assert res["success"] is False
    assert "not found" in res["error"]


# -----------------------------------------------------------------------------
# 4. FastAPI REST Endpoints Tests
# -----------------------------------------------------------------------------

def test_api_github_auth_status(api_client):
    res = api_client.get("/api/github/auth/status")
    assert res.status_code == 200
    data = res.json()
    assert "connected" in data
    assert "total_repos_connected" in data


def test_api_github_auth_login_redirect(api_client, monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test_client_id_123")
    res = api_client.get("/api/github/auth/login", follow_redirects=False)
    assert res.status_code == 302
    assert "github.com/login/oauth/authorize" in res.headers["location"]
    assert "test_client_id_123" in res.headers["location"]


def test_api_github_auth_callback_error(api_client):
    res = api_client.get("/api/github/auth/callback?error=access_denied", follow_redirects=False)
    assert res.status_code == 302
    assert "github_error=access_denied" in res.headers["location"]


def test_api_github_repos_connected_endpoint(api_client):
    res = api_client.get("/api/github/repos/connected")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert isinstance(data["repos"], list)


def test_api_github_repos_add_endpoint(api_client):
    mock_data = {
        "id": 5555,
        "name": "sample-repo",
        "full_name": "tester/sample-repo",
        "owner": {"login": "tester"},
        "description": "API added repo",
        "private": False,
        "language": "Python",
        "default_branch": "main",
        "stargazers_count": 100,
        "fork": False,
        "html_url": "https://github.com/tester/sample-repo",
    }
    with patch.object(urllib.request, "urlopen", return_value=_make_mock_response(mock_data)):
        res = api_client.post("/api/github/repos/add", json={"repo": "tester/sample-repo"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["full_name"] == "tester/sample-repo"


def test_api_github_repos_remove_endpoint(api_client):
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        cur = conn.execute("""
            INSERT INTO github_repositories (owner, name, full_name, added_at, is_active)
            VALUES ('api-test', 'repo-to-del', 'api-test/repo-to-del', '2026-01-01', 1)
        """)
        repo_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    res = api_client.delete(f"/api/github/repos/{repo_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["status"] == "REMOVED"
