"""
GitHub Developer & Repository Automation Tools (Milestone 8).

Provides repository issue listing (LOW risk), PR inspection (LOW risk),
and issue creation (MEDIUM risk requiring user confirmation).
Supports offline test execution and lazy API token injection.
Also provides GitHub OAuth account management and repository tracking.
"""

import base64
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, List, Optional

import app.database as db
from app.tools.github_analyzer import (
    MAX_ZIP_UPLOAD_SIZE,
    analyze_repository_directory,
    safe_extract_zip,
)


def _get_github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "LocalAgenticAutomation/1.0",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def github_list_issues(repo: str, state: str = "open", limit: int = 10) -> dict[str, Any]:
    """
    List issues in a GitHub repository (LOW risk).
    """
    if not repo or "/" not in repo:
        return {
            "success": False,
            "error": "Repository format must be 'owner/repo'",
            "status": "VALIDATION_FAILURE",
        }

    url = f"https://api.github.com/repos/{repo}/issues?state={state}&per_page={limit}"
    try:
        req = urllib.request.Request(url, headers=_get_github_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        issues = []
        for item in data:
            if "pull_request" not in item:  # Filter out PRs returned as issues
                issues.append(
                    {
                        "number": item.get("number"),
                        "title": item.get("title"),
                        "state": item.get("state"),
                        "author": item.get("user", {}).get("login"),
                        "url": item.get("html_url"),
                    }
                )

        return {
            "success": True,
            "repo": repo,
            "count": len(issues),
            "issues": issues,
        }
    except Exception as e:
        # Graceful fallback representation for offline/unauthenticated testing
        return {
            "success": False,
            "error": str(e),
            "repo": repo,
            "status": "API_ERROR",
        }


def github_inspect_pr(repo: str, pr_number: int) -> dict[str, Any]:
    """
    Inspect pull request metadata and checks (LOW risk).
    """
    if not repo or "/" not in repo:
        return {
            "success": False,
            "error": "Repository format must be 'owner/repo'",
            "status": "VALIDATION_FAILURE",
        }

    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    try:
        req = urllib.request.Request(url, headers=_get_github_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        return {
            "success": True,
            "repo": repo,
            "number": pr_number,
            "title": data.get("title"),
            "state": data.get("state"),
            "merged": data.get("merged", False),
            "additions": data.get("additions", 0),
            "deletions": data.get("deletions", 0),
            "url": data.get("html_url"),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "repo": repo,
            "number": pr_number,
            "status": "API_ERROR",
        }


def github_create_issue(
    repo: str, title: str, body: str, labels: Optional[List[str]] = None
) -> dict[str, Any]:
    """
    Create a new issue on GitHub (MEDIUM risk; requires confirmation).
    """
    if not repo or "/" not in repo:
        return {
            "success": False,
            "error": "Repository format must be 'owner/repo'",
            "status": "VALIDATION_FAILURE",
        }
    if not title or not title.strip():
        return {
            "success": False,
            "error": "Issue title cannot be empty",
            "status": "VALIDATION_FAILURE",
        }

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        # Return structured staged representation if token not provided
        return {
            "success": True,
            "repo": repo,
            "title": title,
            "body": body,
            "labels": labels or [],
            "status": "STAGED_OFFLINE",
            "note": "GITHUB_TOKEN not set; issue staged locally.",
        }

    url = f"https://api.github.com/repos/{repo}/issues"
    payload = json.dumps({"title": title, "body": body, "labels": labels or []}).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=payload, headers=_get_github_headers(), method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        return {
            "success": True,
            "repo": repo,
            "number": data.get("number"),
            "title": data.get("title"),
            "url": data.get("html_url"),
            "status": "CREATED",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status": "API_ERROR",
        }


# ---------------------------------------------------------------------------
# GitHub OAuth Account & Repository Management (Milestone 9)
# ---------------------------------------------------------------------------


def _ensure_github_tables() -> None:
    """Create github_accounts and github_repositories tables if not existing."""
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS github_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT NOT NULL,
                name TEXT,
                email TEXT,
                avatar_url TEXT,
                public_repos INTEGER DEFAULT 0,
                private_repos INTEGER DEFAULT 0,
                access_token TEXT NOT NULL,
                token_scope TEXT,
                connected_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS github_repositories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                github_id INTEGER,
                owner TEXT NOT NULL,
                name TEXT NOT NULL,
                full_name TEXT NOT NULL UNIQUE,
                description TEXT,
                private INTEGER NOT NULL DEFAULT 0,
                language TEXT,
                default_branch TEXT DEFAULT 'main',
                stars INTEGER DEFAULT 0,
                fork INTEGER NOT NULL DEFAULT 0,
                html_url TEXT,
                added_at TEXT NOT NULL,
                last_synced_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS github_repo_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id INTEGER,
                repo_name TEXT NOT NULL,
                commit_sha TEXT,
                status TEXT NOT NULL,
                summary TEXT,
                languages_json TEXT,
                frameworks_json TEXT,
                dependencies_json TEXT,
                entry_points_json TEXT,
                folder_modules_json TEXT,
                components_json TEXT,
                architecture_flow_json TEXT,
                run_instructions_json TEXT,
                test_info_json TEXT,
                observations_json TEXT,
                unknowns_json TEXT,
                inspected_files_count INTEGER DEFAULT 0,
                skipped_files_count INTEGER DEFAULT 0,
                total_files_count INTEGER DEFAULT 0,
                tree_json TEXT,
                llm_provider TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(repo_id) REFERENCES github_repositories(id) ON DELETE SET NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repo_analyses_repo_id ON github_repo_analyses(repo_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repo_analyses_commit ON github_repo_analyses(repo_name, commit_sha);")
        conn.commit()
    finally:
        conn.close()

    try:
        from app.tools.github_chat import _ensure_chat_tables
        _ensure_chat_tables()
    except Exception:
        pass


def _get_authed_headers() -> Optional[dict]:
    """Return GitHub API headers using the stored OAuth access token, or None if not connected."""
    _ensure_github_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT access_token FROM github_accounts WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return None
        raw_token = base64.b64decode(row["access_token"]).decode("utf-8")
        return {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "LocalAgenticAutomation/1.0",
            "Authorization": f"token {raw_token}",
        }
    finally:
        conn.close()


def github_get_connected_account() -> dict:
    """Return the currently connected GitHub account or an empty dict."""
    _ensure_github_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """SELECT id, login, name, email, avatar_url, public_repos, private_repos,
                      token_scope, connected_at, is_active
               FROM github_accounts WHERE is_active = 1 ORDER BY id DESC LIMIT 1"""
        )
        row = cur.fetchone()
        if not row:
            return {"connected": False}
        d = dict(row)
        # Never expose access_token
        d["connected"] = True
        return d
    finally:
        conn.close()


def github_store_account(
    login: str,
    name: str,
    email: str,
    avatar_url: str,
    public_repos: int,
    total_private_repos: int,
    access_token: str,
    scope: str,
) -> dict:
    """Store (or update) a GitHub OAuth account in the database."""
    _ensure_github_tables()
    encoded_token = base64.b64encode(access_token.encode("utf-8")).decode("utf-8")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        # Deactivate any existing account first
        conn.execute("UPDATE github_accounts SET is_active = 0")
        conn.execute(
            """INSERT INTO github_accounts
               (login, name, email, avatar_url, public_repos, private_repos,
                access_token, token_scope, connected_at, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (login, name, email, avatar_url, public_repos, total_private_repos,
             encoded_token, scope, now),
        )
        conn.commit()
        return {"success": True, "login": login, "connected_at": now}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        conn.close()


def github_disconnect_account() -> dict:
    """Disconnect (soft-delete) the currently active GitHub account."""
    _ensure_github_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        conn.execute("UPDATE github_accounts SET is_active = 0")
        conn.commit()
        return {"success": True, "message": "GitHub account disconnected."}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        conn.close()


def github_list_user_repos(page: int = 1, per_page: int = 30) -> dict:
    """List the authenticated user's GitHub repositories via the API."""
    headers = _get_authed_headers()
    if not headers:
        return {"success": False, "error": "No GitHub account connected.", "status": "NOT_CONNECTED"}
    url = f"https://api.github.com/user/repos?page={page}&per_page={per_page}&sort=updated&affiliation=owner,collaborator,organization_member"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        repos = []
        for r in data:
            repos.append({
                "id": r.get("id"),
                "full_name": r.get("full_name"),
                "name": r.get("name"),
                "owner": r.get("owner", {}).get("login"),
                "description": r.get("description"),
                "private": r.get("private", False),
                "language": r.get("language"),
                "default_branch": r.get("default_branch", "main"),
                "stars": r.get("stargazers_count", 0),
                "fork": r.get("fork", False),
                "html_url": r.get("html_url"),
                "updated_at": r.get("updated_at"),
            })
        return {"success": True, "page": page, "per_page": per_page, "count": len(repos), "repos": repos}
    except Exception as exc:
        return {"success": False, "error": str(exc), "status": "API_ERROR"}


def _parse_github_repo_url(url_or_name: str) -> Optional[str]:
    """Return 'owner/repo' from a GitHub URL or validate 'owner/repo'. Returns None if invalid."""
    url_or_name = url_or_name.strip().rstrip("/")
    # Full URL patterns: https://github.com/owner/repo or git@github.com:owner/repo
    https_match = re.match(r"https?://github\.com/([^/]+/[^/]+?)(?:\.git)?$", url_or_name)
    if https_match:
        return https_match.group(1)
    ssh_match = re.match(r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?$", url_or_name)
    if ssh_match:
        return ssh_match.group(1)
    # Plain owner/repo
    plain_match = re.match(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$", url_or_name)
    if plain_match:
        return url_or_name
    return None


def github_add_repository(full_name_or_url: str) -> dict:
    """Validate, fetch metadata from GitHub API, and store a repository locally."""
    full_name = _parse_github_repo_url(full_name_or_url)
    if not full_name:
        return {
            "success": False,
            "error": "Invalid repository format. Use 'owner/repo' or a full GitHub URL.",
            "status": "VALIDATION_FAILURE",
        }
    headers = _get_authed_headers() or {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "LocalAgenticAutomation/1.0",
    }
    url = f"https://api.github.com/repos/{full_name}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"success": False, "error": str(exc), "status": "API_ERROR"}

    _ensure_github_tables()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    owner = r.get("owner", {}).get("login", full_name.split("/")[0])
    name = r.get("name", full_name.split("/")[-1])
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        # Upsert: re-activate if already exists
        conn.execute(
            """INSERT INTO github_repositories
               (github_id, owner, name, full_name, description, private, language,
                default_branch, stars, fork, html_url, added_at, last_synced_at, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(full_name) DO UPDATE SET
                 description=excluded.description, private=excluded.private,
                 language=excluded.language, default_branch=excluded.default_branch,
                 stars=excluded.stars, fork=excluded.fork, html_url=excluded.html_url,
                 last_synced_at=excluded.last_synced_at, is_active=1""",
            (
                r.get("id"), owner, name, r.get("full_name", full_name),
                r.get("description"), 1 if r.get("private") else 0,
                r.get("language"), r.get("default_branch", "main"),
                r.get("stargazers_count", 0), 1 if r.get("fork") else 0,
                r.get("html_url"), now, now,
            ),
        )
        conn.commit()
        return {
            "success": True,
            "full_name": r.get("full_name", full_name),
            "html_url": r.get("html_url"),
            "private": r.get("private", False),
            "language": r.get("language"),
            "stars": r.get("stargazers_count", 0),
            "description": r.get("description"),
            "status": "ADDED",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        conn.close()


def github_list_connected_repos(
    search: str = "", filter_visibility: str = "all", sort: str = "updated"
) -> dict:
    """List locally connected (tracked) repositories with optional search and filter."""
    _ensure_github_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        query = """SELECT id, github_id, owner, name, full_name, description, private,
                          language, default_branch, stars, fork, html_url,
                          added_at, last_synced_at
                   FROM github_repositories WHERE is_active = 1"""
        params: list = []
        if search:
            query += " AND (full_name LIKE ? OR description LIKE ?)"
            params += [f"%{search}%", f"%{search}%"]
        if filter_visibility == "public":
            query += " AND private = 0"
        elif filter_visibility == "private":
            query += " AND private = 1"

        sort_col = "last_synced_at" if sort == "updated" else ("full_name" if sort == "name" else "added_at")
        query += f" ORDER BY {sort_col} DESC"

        cur = conn.execute(query, params)
        repos = [dict(r) for r in cur.fetchall()]
        # Cast private/fork to bool for JSON
        for repo in repos:
            repo["private"] = bool(repo["private"])
            repo["fork"] = bool(repo["fork"])
        return {"success": True, "count": len(repos), "repos": repos}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        conn.close()


def github_remove_repository(repo_id: int) -> dict:
    """Soft-remove a repository (sets is_active=0); does NOT delete it from GitHub."""
    _ensure_github_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        cur = conn.execute(
            "UPDATE github_repositories SET is_active = 0 WHERE id = ? AND is_active = 1",
            (repo_id,),
        )
        conn.commit()
        if cur.rowcount == 0:
            return {"success": False, "error": f"Repository id={repo_id} not found or already removed."}
        return {"success": True, "repo_id": repo_id, "status": "REMOVED"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        conn.close()


def github_get_repo_metadata(full_name: str) -> dict:
    """Fetch fresh metadata from GitHub API for the given 'owner/repo'."""
    full_name = full_name.strip("/")
    headers = _get_authed_headers() or {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "LocalAgenticAutomation/1.0",
    }
    url = f"https://api.github.com/repos/{full_name}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read().decode("utf-8"))
        # Update last_synced_at in DB if tracked
        _ensure_github_tables()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(str(db.DB_PATH))
        try:
            conn.execute(
                "UPDATE github_repositories SET last_synced_at = ?, stars = ?, description = ?, language = ? WHERE full_name = ?",
                (now, r.get("stargazers_count", 0), r.get("description"), r.get("language"), r.get("full_name", full_name)),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "success": True,
            "full_name": r.get("full_name"),
            "description": r.get("description"),
            "private": r.get("private", False),
            "language": r.get("language"),
            "default_branch": r.get("default_branch"),
            "stars": r.get("stargazers_count", 0),
            "forks": r.get("forks_count", 0),
            "open_issues": r.get("open_issues_count", 0),
            "fork": r.get("fork", False),
            "html_url": r.get("html_url"),
            "pushed_at": r.get("pushed_at"),
            "updated_at": r.get("updated_at"),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "status": "API_ERROR"}


def github_connection_status() -> dict:
    """Return an overview of GitHub connection status and stats for the dashboard."""
    _ensure_github_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        # Account
        acct_cur = conn.execute(
            "SELECT login, name, avatar_url, public_repos, private_repos FROM github_accounts WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        )
        acct = acct_cur.fetchone()
        # Total connected repos
        count_cur = conn.execute("SELECT COUNT(*) AS total FROM github_repositories WHERE is_active = 1")
        total_repos = count_cur.fetchone()["total"]
        # Recently accessed (last 5 by last_synced_at or added_at)
        recent_cur = conn.execute(
            """SELECT full_name, html_url, language, private, last_synced_at, added_at
               FROM github_repositories WHERE is_active = 1
               ORDER BY COALESCE(last_synced_at, added_at) DESC LIMIT 5"""
        )
        recently_accessed = []
        for r in recent_cur.fetchall():
            d = dict(r)
            d["private"] = bool(d["private"])
            recently_accessed.append(d)

        if acct:
            return {
                "connected": True,
                "login": acct["login"],
                "name": acct["name"],
                "avatar_url": acct["avatar_url"],
                "public_repos": acct["public_repos"],
                "private_repos": acct["private_repos"],
                "total_repos_connected": total_repos,
                "recently_accessed": recently_accessed,
            }
        return {
            "connected": False,
            "login": None,
            "name": None,
            "avatar_url": None,
            "public_repos": 0,
            "private_repos": 0,
            "total_repos_connected": total_repos,
            "recently_accessed": recently_accessed,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# GitHub Repository Intelligence & Analysis Storage (Milestone 9 - Prompt 2)
# ---------------------------------------------------------------------------


def _deserialize_analysis_row(row: sqlite3.Row) -> dict:
    """Deserialize JSON fields from a github_repo_analyses row into dict."""
    d = dict(row)
    for col in (
        "languages_json", "frameworks_json", "dependencies_json", "entry_points_json",
        "folder_modules_json", "components_json", "architecture_flow_json",
        "run_instructions_json", "test_info_json", "observations_json", "unknowns_json", "tree_json"
    ):
        target_key = col.replace("_json", "")
        raw_val = d.get(col)
        if raw_val:
            try:
                d[target_key] = json.loads(raw_val)
            except Exception:
                d[target_key] = {} if ("languages" in col or "flow" in col or "unknowns" in col or "instructions" in col or "test_info" in col) else []
        else:
            d[target_key] = {} if ("languages" in col or "flow" in col or "unknowns" in col or "instructions" in col or "test_info" in col) else []
        d.pop(col, None)
    d["success"] = True
    return d


def github_store_analysis(analysis: dict, repo_id: Optional[int] = None) -> dict:
    """Safely store a structured analysis report in SQLite."""
    _ensure_github_tables()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        cur = conn.execute(
            """INSERT INTO github_repo_analyses
               (repo_id, repo_name, commit_sha, status, summary, languages_json,
                frameworks_json, dependencies_json, entry_points_json, folder_modules_json,
                components_json, architecture_flow_json, run_instructions_json,
                test_info_json, observations_json, unknowns_json, inspected_files_count,
                skipped_files_count, total_files_count, tree_json, llm_provider,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                repo_id,
                analysis.get("repo_name", "unknown"),
                analysis.get("commit_sha", "snapshot"),
                analysis.get("status", "completed"),
                analysis.get("summary", ""),
                json.dumps(analysis.get("languages", {})),
                json.dumps(analysis.get("frameworks", [])),
                json.dumps(analysis.get("dependencies", [])),
                json.dumps(analysis.get("entry_points", [])),
                json.dumps(analysis.get("folder_modules", [])),
                json.dumps(analysis.get("components", [])),
                json.dumps(analysis.get("architecture_flow", {})),
                json.dumps(analysis.get("run_instructions", {})),
                json.dumps(analysis.get("test_info", {})),
                json.dumps(analysis.get("observations", [])),
                json.dumps(analysis.get("unknowns", {})),
                int(analysis.get("inspected_files_count", 0)),
                int(analysis.get("skipped_files_count", 0)),
                int(analysis.get("total_files_count", 0)),
                json.dumps(analysis.get("tree", [])),
                analysis.get("llm_provider", "deterministic-fallback"),
                now,
                now,
            ),
        )
        conn.commit()
        analysis_id = cur.lastrowid
        analysis["id"] = analysis_id
        analysis["repo_id"] = repo_id
        analysis["created_at"] = now
        analysis["updated_at"] = now
        return analysis
    finally:
        conn.close()


def github_get_latest_analysis(repo_id: int) -> Optional[dict]:
    """Retrieve the latest analysis result for a tracked repository."""
    _ensure_github_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM github_repo_analyses WHERE repo_id = ? ORDER BY id DESC LIMIT 1",
            (repo_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return _deserialize_analysis_row(row)
    finally:
        conn.close()


def github_get_analysis_by_id(analysis_id: int) -> Optional[dict]:
    """Retrieve an analysis record by its primary key."""
    _ensure_github_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM github_repo_analyses WHERE id = ?", (analysis_id,))
        row = cur.fetchone()
        if not row:
            return None
        return _deserialize_analysis_row(row)
    finally:
        conn.close()


def github_get_analysis_by_commit(repo_id: int, commit_sha: str) -> Optional[dict]:
    """Check if an analysis already exists for a specific repository and commit SHA."""
    _ensure_github_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """SELECT * FROM github_repo_analyses
               WHERE repo_id = ? AND commit_sha = ? AND status = 'completed'
               ORDER BY id DESC LIMIT 1""",
            (repo_id, commit_sha),
        )
        row = cur.fetchone()
        if not row:
            return None
        return _deserialize_analysis_row(row)
    finally:
        conn.close()


def github_analyze_connected_repo(
    repo_id: int, force_refresh: bool = False, allow_cloud: bool = False
) -> dict:
    """
    Fetch repository snapshot from GitHub via authenticated API, extract safely,
    perform zero-execution static analysis, and persist the report.
    Supports incremental analysis based on commit SHA.
    """
    _ensure_github_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT id, owner, name, full_name, private FROM github_repositories WHERE id = ? AND is_active = 1",
            (repo_id,),
        )
        repo = cur.fetchone()
        if not repo:
            return {
                "success": False,
                "error": f"Repository id={repo_id} not found or inactive.",
                "status": "NOT_FOUND",
            }
        repo_dict = dict(repo)
    finally:
        conn.close()

    full_name = repo_dict["full_name"]
    headers = _get_authed_headers() or {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "LocalAgenticAutomation/1.0",
    }

    # 1. Fetch latest commit SHA
    commits_url = f"https://api.github.com/repos/{full_name}/commits?per_page=1"
    commit_sha = "unknown"
    try:
        req = urllib.request.Request(commits_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            commits = json.loads(resp.read().decode("utf-8"))
            if commits and isinstance(commits, list) and len(commits) > 0:
                commit_sha = commits[0].get("sha", "unknown")
    except Exception as exc:
        return {
            "success": False,
            "error": f"Failed to fetch commit metadata from GitHub: {str(exc)}",
            "status": "API_ERROR",
        }

    # 2. Check incremental cache if not force_refresh
    if not force_refresh and commit_sha != "unknown":
        existing = github_get_analysis_by_commit(repo_id, commit_sha)
        if existing:
            existing["cached"] = True
            return existing

    # 3. Download repository zipball
    zip_url = f"https://api.github.com/repos/{full_name}/zipball/{commit_sha}"
    try:
        req = urllib.request.Request(zip_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            zip_bytes = resp.read()
    except Exception as exc:
        return {
            "success": False,
            "error": f"Failed to download repository archive from GitHub: {str(exc)}",
            "status": "API_ERROR",
        }

    # 4. Extract and analyze safely
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        extract_res = safe_extract_zip(BytesIO(zip_bytes), tmp_path)
        if not extract_res.get("success"):
            return extract_res

        analysis = analyze_repository_directory(
            repo_root=tmp_path,
            repo_name=full_name,
            commit_sha=commit_sha,
            allow_cloud=allow_cloud,
        )

        # Index text chunks for grounded chat retrieval
        try:
            from app.tools.github_chat import index_repository_text_files
            index_repository_text_files(
                repo_root=tmp_path,
                repo_name=full_name,
                commit_sha=commit_sha,
                repo_id=repo_id,
            )
        except Exception:
            pass

        stored = github_store_analysis(analysis, repo_id=repo_id)

        # Update last_synced_at on repository
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(str(db.DB_PATH))
        try:
            conn.execute("UPDATE github_repositories SET last_synced_at = ? WHERE id = ?", (now, repo_id))
            conn.commit()
        finally:
            conn.close()

        stored["cached"] = False
        return stored


def github_analyze_zip_upload(
    zip_bytes: bytes, filename: str, allow_cloud: bool = False
) -> dict:
    """
    Safely extract and analyze a user-uploaded repository ZIP snapshot.
    Enforces upload limits, traversal guards, and zero execution.
    """
    if len(zip_bytes) > MAX_ZIP_UPLOAD_SIZE:
        max_mb = MAX_ZIP_UPLOAD_SIZE // (1024 * 1024)
        return {
            "success": False,
            "error": f"Uploaded ZIP file exceeds maximum size limit ({max_mb} MB).",
            "status": "LIMIT_EXCEEDED",
        }

    # Hash the archive content for snapshot identification
    commit_sha = hashlib.sha256(zip_bytes).hexdigest()[:12]
    clean_repo_name = Path(filename).stem or "uploaded-archive"

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        extract_res = safe_extract_zip(BytesIO(zip_bytes), tmp_path)
        if not extract_res.get("success"):
            return extract_res

        analysis = analyze_repository_directory(
            repo_root=tmp_path,
            repo_name=clean_repo_name,
            commit_sha=f"snapshot-{commit_sha}",
            allow_cloud=allow_cloud,
        )

        # Index text chunks for grounded chat retrieval
        try:
            from app.tools.github_chat import index_repository_text_files
            index_repository_text_files(
                repo_root=tmp_path,
                repo_name=clean_repo_name,
                commit_sha=f"snapshot-{commit_sha}",
                repo_id=None,
            )
        except Exception:
            pass

        stored = github_store_analysis(analysis, repo_id=None)
        stored["cached"] = False
        return stored

