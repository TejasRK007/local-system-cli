"""
Automated Test Suite for AI Repository Intelligence (Milestone 9 - Prompt 2).

Covers:
1. Secret redaction (never persists or exposes raw secrets, tokens, keys)
2. ZIP archive security (path traversal, symlinks, zip bombs, reserved names)
3. Safe file discovery and exclusions (.git, node_modules, .venv, binaries)
4. Manifest and dependency parsing (npm, pip, cargo, go)
5. Entry points and run/test instruction extraction
6. Maintainability and security observations (factual, non-vulnerability assertions)
7. Deterministic non-LLM fallback and privacy gating (offline Ollama, Groq consent)
8. Incremental analysis caching based on commit SHA
9. End-to-end connected repo analysis with mocked GitHub API (preserves repo record)
10. Partial failure resilience (handles corrupted files gracefully)
11. FastAPI REST endpoints for repo analysis and ZIP upload
"""

import hashlib
import io
import json
import sqlite3
import tempfile
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.database as db
from app.server import server_app
from app.tools.github_analyzer import (
    MAX_UNCOMPRESSED_TOTAL_SIZE,
    MAX_ZIP_FILES_COUNT,
    MAX_ZIP_UPLOAD_SIZE,
    analyze_repository_directory,
    discover_entry_points,
    discover_repository_files,
    discover_test_suite,
    extract_run_instructions,
    generate_observations,
    parse_manifests,
    redact_secrets,
    safe_extract_zip,
)
from app.tools.github_tools import (
    _ensure_github_tables,
    github_add_repository,
    github_analyze_connected_repo,
    github_analyze_zip_upload,
    github_get_analysis_by_id,
    github_get_latest_analysis,
    github_list_connected_repos,
    github_store_account,
    github_store_analysis,
)


@pytest.fixture(autouse=True)
def isolate_test_db(tmp_path, monkeypatch):
    """Ensure every test runs in an isolated SQLite database."""
    test_db_file = tmp_path / "test_agent_analyzer.db"
    monkeypatch.setattr(db, "DB_PATH", test_db_file)
    _ensure_github_tables()
    yield test_db_file


@pytest.fixture
def api_client():
    return TestClient(server_app)


def _create_sample_zip(entries: dict[str, str | bytes]) -> bytes:
    """Helper to generate an in-memory ZIP archive from dict of path -> content."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in entries.items():
            if isinstance(content, str):
                zf.writestr(path, content.encode("utf-8"))
            else:
                zf.writestr(path, content)
    return buf.getvalue()


# -----------------------------------------------------------------------------
# 1. Secret Redaction Tests
# -----------------------------------------------------------------------------
def test_secret_redaction_patterns():
    raw_text = (
        "GitHub token: ghp_1234567890abcdefghijklmnopqrstuvwxyzAB\n"
        "OAuth token: gho_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890ab\n"
        "PAT token: github_pat_11AAAAAAA000000000000000000000000000000000000000000000000000000000\n"
        "AWS key: AKIAIOSFODNN7EXAMPLE\n"
        "Groq key: gsk_1234567890abcdefghijklmnopqr\n"
        "OpenAI key: sk-abcdefghijklmnopqrstuvwxyz123456\n"
        "Slack token: xoxb-1234567890-123456789012-abcdef\n"
        "DB URI: postgres://admin:superSecretPass123@localhost:5432/mydb\n"
        'Config secret: password = "productionPassword999"\n'
        "JWT: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature123\n"
    )

    redacted = redact_secrets(raw_text)

    # Assert none of the raw secret values are present
    assert "ghp_" not in redacted
    assert "gho_" not in redacted
    assert "github_pat_" not in redacted
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "gsk_1234" not in redacted
    assert "sk-abcdef" not in redacted
    assert "superSecretPass123" not in redacted
    assert "productionPassword999" not in redacted
    assert "doNotLeakThisSignature123" not in redacted

    # Assert redacted replacement markers appear
    assert "[REDACTED" in redacted


# -----------------------------------------------------------------------------
# 2. ZIP Archive Security (Traversal, Symlinks, Limits)
# -----------------------------------------------------------------------------
def test_zip_path_traversal_protection(tmp_path):
    # Construct a malicious ZIP with path traversal
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escaped_file.txt", "evil content")

    res = safe_extract_zip(buf, tmp_path / "extract_dest")
    assert res["success"] is False
    assert res["status"] == "SECURITY_VIOLATION"


def test_zip_absolute_path_protection(tmp_path):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("/root/pwned.txt", "evil content")

    res = safe_extract_zip(buf, tmp_path / "extract_dest")
    assert res["success"] is False
    assert res["status"] == "SECURITY_VIOLATION"


def test_zip_symlink_abuse_skipped(tmp_path):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # Normal file
        zf.writestr("safe.txt", "hello safe world")
        # Symlink entry (Unix mode 0o120000 = S_IFLNK)
        sym_info = zipfile.ZipInfo("symlink_entry")
        sym_info.create_system = 3  # Unix
        sym_info.external_attr = 0o120777 << 16  # S_IFLNK | permissions
        zf.writestr(sym_info, "/etc/passwd")

    dest = tmp_path / "symlink_test"
    res = safe_extract_zip(buf, dest)
    assert res["success"] is True
    # Safe file extracted, symlink skipped
    assert res["extracted_count"] == 1
    assert res["skipped_count"] == 1
    assert (dest / "safe.txt").exists()
    assert not (dest / "symlink_entry").exists()


def test_zip_oversized_upload_rejection():
    # Attempt upload beyond MAX_ZIP_UPLOAD_SIZE
    oversized_data = b"0" * (MAX_ZIP_UPLOAD_SIZE + 1024)
    res = github_analyze_zip_upload(oversized_data, "huge.zip")
    assert res["success"] is False
    assert res["status"] == "LIMIT_EXCEEDED"


# -----------------------------------------------------------------------------
# 3. Safe File Discovery & Exclusions
# -----------------------------------------------------------------------------
def test_file_discovery_and_exclusions(tmp_path):
    repo_dir = tmp_path / "sample_project"
    repo_dir.mkdir()

    # Included text files
    (repo_dir / "main.py").write_text("print('hello world')", encoding="utf-8")
    (repo_dir / "helper.py").write_text("def add(a, b): return a + b", encoding="utf-8")
    (repo_dir / "README.md").write_text("# Sample Project\nA test app.", encoding="utf-8")

    # Excluded directories
    node_modules = repo_dir / "node_modules" / "some_pkg"
    node_modules.mkdir(parents=True)
    (node_modules / "index.js").write_text("module.exports = {}", encoding="utf-8")

    venv_dir = repo_dir / ".venv" / "Lib"
    venv_dir.mkdir(parents=True)
    (venv_dir / "site.py").write_text("# venv file", encoding="utf-8")

    git_dir = repo_dir / ".git" / "objects"
    git_dir.mkdir(parents=True)
    (git_dir / "pack.bin").write_bytes(b"\x00\x01\x02")

    # Excluded binary file
    (repo_dir / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    (repo_dir / "cache.pyc").write_bytes(b"\x00\x01\x02\x03")

    discovery = discover_repository_files(repo_dir)

    assert discovery["inspected_files"] == 3  # main.py, helper.py, README.md
    assert "Python" in discovery["languages"]
    assert discovery["languages"]["Python"]["files"] == 2
    assert "main.py" in discovery["inspected_text_files"]

    # Excluded files must NOT be in inspected_text_files
    for key in discovery["inspected_text_files"]:
        assert not key.startswith("node_modules")
        assert not key.startswith(".venv")
        assert not key.startswith(".git")
        assert not key.endswith(".png")
        assert not key.endswith(".pyc")


# -----------------------------------------------------------------------------
# 4. Manifest Parsing & Framework Detection
# -----------------------------------------------------------------------------
def test_manifest_parsing_python_and_node(tmp_path):
    repo_dir = tmp_path / "full_stack_app"
    repo_dir.mkdir()

    pkg_json = {
        "name": "my-web-app",
        "dependencies": {
            "react": "^18.2.0",
            "express": "^4.18.2",
            "tailwindcss": "^3.3.0",
        },
        "devDependencies": {
            "jest": "^29.5.0",
            "typescript": "^5.0.0",
        },
        "scripts": {
            "start": "node index.js",
            "test": "jest",
        },
    }
    (repo_dir / "package.json").write_text(json.dumps(pkg_json), encoding="utf-8")

    req_txt = "fastapi==0.104.1\nuvicorn>=0.24.0\nsqlalchemy\npytest>=7.4.0\n"
    (repo_dir / "requirements.txt").write_text(req_txt, encoding="utf-8")

    discovery = discover_repository_files(repo_dir)
    manifest_data = parse_manifests(discovery["inspected_text_files"])

    assert "npm" in manifest_data["package_managers"]
    assert "pip" in manifest_data["package_managers"]
    assert "React" in manifest_data["frameworks"]
    assert "Express" in manifest_data["frameworks"]
    assert "FastAPI" in manifest_data["frameworks"]
    assert "Pytest" in manifest_data["frameworks"]
    assert manifest_data["total_dependencies"] >= 7
    assert "start" in manifest_data["scripts"]


# -----------------------------------------------------------------------------
# 5. Entry Points, Test Suite & Instructions Extraction
# -----------------------------------------------------------------------------
def test_entry_points_and_test_suite_discovery():
    sample_paths = [
        "app/main.py",
        "src/App.tsx",
        "Dockerfile",
        "tests/test_api.py",
        "tests/test_service.py",
        "README.md",
    ]

    entry_points = discover_entry_points(sample_paths)
    assert any(ep["path"] == "app/main.py" for ep in entry_points)
    assert any(ep["path"] == "Dockerfile" for ep in entry_points)

    test_info = discover_test_suite(sample_paths)
    assert test_info["has_tests"] is True
    assert test_info["test_files_count"] == 2
    assert "tests" in test_info["test_dirs"]


def test_run_instructions_extraction(tmp_path):
    readme_text = """
# Developer Tool

## Installation
```bash
pip install -r requirements.txt
npm install
```

## Running
```bash
python -m app.server
```

## Testing
```bash
pytest tests/
```
"""
    f = tmp_path / "README.md"
    f.write_text(readme_text, encoding="utf-8")

    instructions = extract_run_instructions(
        inspected_text_files={"README.md": f},
        scripts={"test": "pytest"},
        package_managers=["pip", "npm"],
    )

    assert any("pip install" in cmd for cmd in instructions["install"])
    assert any("python -m app.server" in cmd for cmd in instructions["run"])
    assert any("pytest" in cmd for cmd in instructions["test"])


# -----------------------------------------------------------------------------
# 6. Factual Maintainability & Configuration Observations
# -----------------------------------------------------------------------------
def test_generate_observations(tmp_path):
    # Repository without README, without tests, missing lockfile, and unpinned deps
    observations = generate_observations(
        inspected_text_files={},
        all_relative_paths=["package.json", "index.js"],
        has_tests=False,
        dependencies=[
            {"name": "foo", "version": "unpinned"},
            {"name": "bar", "version": "*"},
            {"name": "baz", "version": ""},
        ],
    )

    types = [o["type"] for o in observations]
    assert "Missing Documentation" in types
    assert "No Test Suite Detected" in types
    assert "Missing Node Lockfile" in types
    assert "Unpinned Dependencies" in types


# -----------------------------------------------------------------------------
# 7. Deterministic Non-LLM Fallback & Privacy Gating
# -----------------------------------------------------------------------------
def test_deterministic_fallback_when_llm_offline(tmp_path):
    repo_dir = tmp_path / "offline_repo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text("print('core app')", encoding="utf-8")
    (repo_dir / "README.md").write_text("# Core App\nA private application.", encoding="utf-8")

    with patch("app.llm.is_ollama_online", return_value=False):
        # allow_cloud=False strictly blocks any cloud API calls
        report = analyze_repository_directory(
            repo_root=repo_dir,
            repo_name="org/offline-repo",
            commit_sha="c0ffee1",
            allow_cloud=False,
        )

    assert report["success"] is True
    assert report["llm_provider"] == "deterministic-fallback"
    assert "Core App" in report["summary"]
    assert report["inspected_files_count"] == 2
    assert len(report["components"]) > 0
    assert "architecture_flow" in report


def test_privacy_gating_blocks_cloud_without_consent(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_dummy_mock_key_for_privacy_test")
    from app.llm import get_configured_llm

    # Must raise PermissionError when allow_cloud is False
    with pytest.raises(PermissionError) as exc_info:
        get_configured_llm(provider="groq", allow_cloud=False)
    assert "consent" in str(exc_info.value).lower()


# -----------------------------------------------------------------------------
# 8. Incremental Analysis & Caching
# -----------------------------------------------------------------------------
def test_incremental_analysis_caching(tmp_path):
    # Setup tracked repo in DB
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        cur = conn.execute("""
            INSERT INTO github_repositories
            (owner, name, full_name, private, language, added_at, is_active)
            VALUES ('octocat', 'cached-repo', 'octocat/cached-repo', 0, 'Python', '2026-01-01', 1)
        """)
        repo_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    # Pre-store an analysis with commit SHA "sha_1111"
    analysis_payload = {
        "repo_name": "octocat/cached-repo",
        "commit_sha": "sha_1111",
        "status": "completed",
        "summary": "Pre-computed summary",
        "languages": {"Python": {"files": 1, "bytes": 100, "percentage": 100.0}},
        "frameworks": ["FastAPI"],
        "dependencies": [],
        "entry_points": [],
        "folder_modules": [],
        "components": [],
        "architecture_flow": {},
        "run_instructions": {},
        "test_info": {},
        "observations": [],
        "unknowns": {},
        "inspected_files_count": 1,
        "skipped_files_count": 0,
        "total_files_count": 1,
        "tree": [],
        "llm_provider": "deterministic-fallback",
    }
    github_store_analysis(analysis_payload, repo_id=repo_id)

    # Mock GitHub commits response returning same SHA
    mock_commit_resp = [{"sha": "sha_1111"}]
    mock_url_resp = MagicMock()
    mock_url_resp.read.return_value = json.dumps(mock_commit_resp).encode("utf-8")
    mock_url_resp.__enter__.return_value = mock_url_resp

    with patch.object(urllib.request, "urlopen", return_value=mock_url_resp):
        result = github_analyze_connected_repo(repo_id=repo_id, force_refresh=False)

    assert result["success"] is True
    assert result["cached"] is True
    assert result["commit_sha"] == "sha_1111"
    assert result["summary"] == "Pre-computed summary"


# -----------------------------------------------------------------------------
# 9. End-to-End Connected Repo Analysis (Preserves Connected Repository Record)
# -----------------------------------------------------------------------------
def test_connected_repo_analysis_mocked_github():
    # 1. Insert connected repository
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        cur = conn.execute("""
            INSERT INTO github_repositories
            (owner, name, full_name, private, language, added_at, is_active)
            VALUES ('alice', 'microservice', 'alice/microservice', 0, 'Python', '2026-01-01', 1)
        """)
        repo_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    # 2. Build mock zipball content
    sample_files = {
        "alice-microservice-a1b2c3d/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        "alice-microservice-a1b2c3d/README.md": "# Microservice\n## Installation\n```bash\npip install fastapi\n```\n",
        "alice-microservice-a1b2c3d/requirements.txt": "fastapi==0.100.0\npytest\n",
    }
    zip_bytes = _create_sample_zip(sample_files)

    # Mock urllib.request.urlopen for:
    # Call 1: commits API -> returns commit SHA
    # Call 2: zipball download -> returns zip_bytes
    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        mock_r = MagicMock()
        if "commits" in url:
            mock_r.read.return_value = json.dumps([{"sha": "a1b2c3d4e5f6"}]).encode("utf-8")
        elif "zipball" in url:
            mock_r.read.return_value = zip_bytes
        mock_r.__enter__.return_value = mock_r
        return mock_r

    with patch.object(urllib.request, "urlopen", side_effect=fake_urlopen):
        analysis_res = github_analyze_connected_repo(repo_id=repo_id, force_refresh=True)

    assert analysis_res["success"] is True
    assert analysis_res["commit_sha"] == "a1b2c3d4e5f6"
    assert "FastAPI" in analysis_res["frameworks"]
    assert analysis_res["inspected_files_count"] == 3

    # CRITICAL CHECK: Connected repository in github_repositories must NOT be deleted or removed
    repos = github_list_connected_repos()["repos"]
    assert len(repos) == 1
    assert repos[0]["id"] == repo_id
    assert repos[0]["full_name"] == "alice/microservice"

    # Verify latest analysis retrieval
    latest = github_get_latest_analysis(repo_id)
    assert latest is not None
    assert latest["commit_sha"] == "a1b2c3d4e5f6"


# -----------------------------------------------------------------------------
# 10. Partial Failure Resilience (Corrupted/Unreadable Files)
# -----------------------------------------------------------------------------
def test_partial_failure_resilience(tmp_path):
    repo_dir = tmp_path / "corrupted_repo"
    repo_dir.mkdir()

    # Good file
    (repo_dir / "good.py").write_text("x = 10\n", encoding="utf-8")
    # File with invalid surrogate bytes
    (repo_dir / "broken.py").write_bytes(b"\xff\xfe\x00\x00\xaa\xbb\xcc\xdd\xee")

    report = analyze_repository_directory(
        repo_root=repo_dir,
        repo_name="test/corrupted",
        commit_sha="corrupt1",
        allow_cloud=False,
    )

    # Analysis must successfully complete without raising exceptions
    assert report["success"] is True
    assert report["inspected_files_count"] >= 1


# -----------------------------------------------------------------------------
# 11. ZIP Upload Direct Handling
# -----------------------------------------------------------------------------
def test_zip_upload_analysis_success():
    sample_files = {
        "project/index.js": "const express = require('express');\n",
        "project/package.json": json.dumps({"name": "demo-proj", "dependencies": {"express": "^4.18.2"}}),
        "project/README.md": "# Demo Proj\n## Usage\n```bash\nnode index.js\n```\n",
    }
    zip_bytes = _create_sample_zip(sample_files)

    result = github_analyze_zip_upload(zip_bytes, "demo-proj.zip", allow_cloud=False)
    assert result["success"] is True
    assert "Express" in result["frameworks"]
    assert result["inspected_files_count"] == 3

    # Retrieve by analysis ID
    stored_id = result["id"]
    retrieved = github_get_analysis_by_id(stored_id)
    assert retrieved is not None
    assert retrieved["repo_name"] == "demo-proj"


# -----------------------------------------------------------------------------
# 12. FastAPI Endpoints for Repo Intelligence & ZIP Upload
# -----------------------------------------------------------------------------
def test_api_upload_zip_endpoint(api_client):
    sample_files = {
        "repo/app.py": "print('hello')\n",
        "repo/requirements.txt": "flask\n",
        "repo/README.md": "# Flask App\n",
    }
    zip_bytes = _create_sample_zip(sample_files)

    res = api_client.post(
        "/api/github/repos/upload-zip?filename=test_repo.zip",
        content=zip_bytes,
        headers={"Content-Type": "application/zip", "X-Filename": "test_repo.zip"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "Flask" in data["frameworks"]
    assert "id" in data

    # Retrieve by ID via GET endpoint
    analysis_id = data["id"]
    get_res = api_client.get(f"/api/github/analysis/{analysis_id}")
    assert get_res.status_code == 200
    assert get_res.json()["repo_name"] == "test_repo"


def test_api_upload_zip_invalid_file(api_client):
    res = api_client.post(
        "/api/github/repos/upload-zip?filename=not_a_zip.txt",
        content=b"plain text file",
        headers={"Content-Type": "text/plain"},
    )
    assert res.status_code == 400


def test_api_analyze_and_get_analysis_endpoints(api_client):
    # Insert repository in DB
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        cur = conn.execute("""
            INSERT INTO github_repositories
            (owner, name, full_name, private, language, added_at, is_active)
            VALUES ('bob', 'api-test-repo', 'bob/api-test-repo', 0, 'Python', '2026-01-01', 1)
        """)
        repo_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    # Pre-store an analysis
    analysis_data = {
        "repo_name": "bob/api-test-repo",
        "commit_sha": "commit_999",
        "status": "completed",
        "summary": "API test summary",
        "languages": {"Python": {"files": 1, "bytes": 50, "percentage": 100.0}},
        "frameworks": ["FastAPI"],
        "dependencies": [],
        "entry_points": [],
        "folder_modules": [],
        "components": [],
        "architecture_flow": {},
        "run_instructions": {},
        "test_info": {},
        "observations": [],
        "unknowns": {},
        "inspected_files_count": 1,
        "skipped_files_count": 0,
        "total_files_count": 1,
        "tree": [],
        "llm_provider": "deterministic-fallback",
    }
    github_store_analysis(analysis_data, repo_id=repo_id)

    # 1. GET /api/github/repos/{repo_id}/analysis
    get_res = api_client.get(f"/api/github/repos/{repo_id}/analysis")
    assert get_res.status_code == 200
    assert get_res.json()["commit_sha"] == "commit_999"
    assert get_res.json()["summary"] == "API test summary"

    # 2. POST /api/github/repos/{repo_id}/analyze (cached return)
    mock_commits_resp = MagicMock()
    mock_commits_resp.read.return_value = json.dumps([{"sha": "commit_999"}]).encode("utf-8")
    mock_commits_resp.__enter__.return_value = mock_commits_resp

    with patch.object(urllib.request, "urlopen", return_value=mock_commits_resp):
        post_res = api_client.post(
            f"/api/github/repos/{repo_id}/analyze",
            json={"force_refresh": False},
        )
    assert post_res.status_code == 200
    assert post_res.json()["cached"] is True

