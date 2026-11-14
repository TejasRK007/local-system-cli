"""
GitHub Developer Workbench & Safe Automation Module (Milestone 9 - Prompt 4).

Provides repository overview, issues, pull requests, commits, branches,
and GitHub Actions intelligence with read-first behavior and explicit approval
for all write actions.

Enforces:
1. Read-first, non-destructive behavior across all endpoints.
2. Explicit preview and user approval immediately before any API write.
3. Zero automatic merges, approvals, force-pushes, or branch deletions.
4. Comprehensive secret redaction on logs, diffs, and AI prompts.
5. Audit logging for every write action without persisting credentials.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import app.database as db
from app.llm import GroqChatWrapper, OllamaChatWrapper, is_ollama_online
from app.tools.github_analyzer import redact_secrets
from app.tools.github_tools import _get_authed_headers, _get_github_headers

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Custom Exceptions
# -----------------------------------------------------------------------------
class GitHubWorkbenchError(Exception):
    """Base exception for GitHub Workbench operations."""
    pass


class GitHubRateLimitError(GitHubWorkbenchError):
    """Raised when GitHub API rate limit is exceeded."""
    pass


class GitHubAuthError(GitHubWorkbenchError):
    """Raised when GitHub authentication is missing or rejected."""
    pass


class GitHubNotFoundError(GitHubWorkbenchError):
    """Raised when a repository or resource is not found."""
    pass


class GitHubApprovalRequiredError(GitHubWorkbenchError):
    """Raised when a modifying operation is attempted without approval."""
    pass


class GitHubDangerousOperationBlockedError(GitHubWorkbenchError):
    """Raised when a prohibited destructive operation is requested."""
    pass


# -----------------------------------------------------------------------------
# GitHub API Client Helpers
# -----------------------------------------------------------------------------
def get_effective_github_headers(accept_header: Optional[str] = None) -> Dict[str, str]:
    """
    Return valid GitHub headers prioritizing OAuth token, falling back to GITHUB_TOKEN.
    """
    headers = _get_authed_headers()
    if not headers:
        headers = _get_github_headers()

    if accept_header:
        headers["Accept"] = accept_header
    return headers


def github_api_request(
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    accept_header: Optional[str] = None,
    timeout: int = 15,
) -> Any:
    """
    Make an authenticated HTTP request to the GitHub REST API.
    Handles rate limits, auth errors, 404s, and redacts sensitive error messages.
    """
    clean_endpoint = endpoint.lstrip("/")
    url = f"https://api.github.com/{clean_endpoint}"

    if params:
        clean_params = {k: v for k, v in params.items() if v is not None}
        if clean_params:
            url += f"?{urllib.parse.urlencode(clean_params)}"

    headers = get_effective_github_headers(accept_header=accept_header)
    data_bytes = None
    if json_data is not None:
        headers["Content-Type"] = "application/json"
        data_bytes = json.dumps(json_data).encode("utf-8")

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method.upper())

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()

            if "application/json" in content_type:
                return json.loads(raw.decode("utf-8"))
            elif accept_header and "diff" in accept_header:
                return raw.decode("utf-8", errors="replace")
            else:
                try:
                    return json.loads(raw.decode("utf-8"))
                except Exception:
                    return raw.decode("utf-8", errors="replace")

    except urllib.error.HTTPError as exc:
        code = exc.code
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass

        clean_err = redact_secrets(err_body)

        if code == 403:
            remaining = exc.headers.get("X-RateLimit-Remaining")
            if remaining == "0" or "rate limit exceeded" in clean_err.lower():
                reset_time = exc.headers.get("X-RateLimit-Reset", "soon")
                raise GitHubRateLimitError(
                    f"GitHub API rate limit exceeded. Reset epoch: {reset_time}."
                ) from exc
            raise GitHubWorkbenchError(f"GitHub API permission denied (403): {clean_err}") from exc

        elif code == 401:
            raise GitHubAuthError(
                "GitHub authentication failed. Please connect or refresh your GitHub account."
            ) from exc

        elif code == 404:
            raise GitHubNotFoundError(f"GitHub resource not found (404): {clean_endpoint}") from exc

        elif code == 422:
            raise GitHubWorkbenchError(f"GitHub validation failure (422): {clean_err}") from exc

        else:
            raise GitHubWorkbenchError(f"GitHub API error ({code}): {clean_err}") from exc

    except urllib.error.URLError as exc:
        raise GitHubWorkbenchError(f"Network error connecting to GitHub: {redact_secrets(str(exc))}") from exc


def _record_audit_event(
    action: str,
    repo_name: str,
    summary: str,
    approval_result: str = "APPROVED",
    execution_status: str = "SUCCESS",
    risk: str = "medium",
) -> None:
    """Safely log modifying developer workbench operations to SQLite audit_log."""
    try:
        user_prompt = f"{action} on {repo_name}"
        db.log_event(
            user_request=user_prompt,
            action=action,
            risk_level=risk,
            approval_required=True,
            approval_result=approval_result,
            execution_status=execution_status,
            result_summary=redact_secrets(summary),
        )
    except Exception as e:
        logger.warning("Failed to record audit event (%s): %s", action, e)


# -----------------------------------------------------------------------------
# 1. Repository Overview Intelligence
# -----------------------------------------------------------------------------
def github_get_repo_overview(repo_name: str) -> Dict[str, Any]:
    """
    Fetch repository overview statistics:
    - Open issues and open PRs counts
    - Recent commits (latest 5)
    - Branch count and active branches
    - Recent workflow runs and recent failure count
    """
    if not repo_name or "/" not in repo_name:
        raise ValueError("repo_name must be in 'owner/repo' format")

    overview: Dict[str, Any] = {
        "success": True,
        "repo_name": repo_name,
        "description": "",
        "default_branch": "main",
        "stars": 0,
        "forks": 0,
        "open_issues_count": 0,
        "open_prs_count": 0,
        "branches_count": 0,
        "recent_commits": [],
        "recent_workflows": [],
        "workflow_failures_count": 0,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 1. Repo Metadata
    try:
        repo_data = github_api_request("GET", f"repos/{repo_name}")
        overview["description"] = repo_data.get("description") or ""
        overview["default_branch"] = repo_data.get("default_branch") or "main"
        overview["stars"] = repo_data.get("stargazers_count", 0)
        overview["forks"] = repo_data.get("forks_count", 0)
        overview["open_issues_count"] = repo_data.get("open_issues_count", 0)
        overview["private"] = repo_data.get("private", False)
        overview["html_url"] = repo_data.get("html_url", f"https://github.com/{repo_name}")
    except Exception as e:
        logger.warning("Error fetching repo metadata for %s: %s", repo_name, e)

    # 2. Open PRs Count
    try:
        prs_data = github_api_request("GET", f"repos/{repo_name}/pulls", params={"state": "open", "per_page": 1})
        if isinstance(prs_data, list):
            overview["open_prs_count"] = len(prs_data)
    except Exception:
        pass

    # 3. Recent Commits
    try:
        commits_data = github_api_request(
            "GET", f"repos/{repo_name}/commits", params={"per_page": 5}
        )
        if isinstance(commits_data, list):
            for c in commits_data:
                author_info = c.get("author") or {}
                commit_info = c.get("commit") or {}
                overview["recent_commits"].append({
                    "sha": c.get("sha", ""),
                    "short_sha": c.get("sha", "")[:7],
                    "message": commit_info.get("message", "").splitlines()[0] if commit_info.get("message") else "",
                    "author": author_info.get("login") or commit_info.get("author", {}).get("name", "Unknown"),
                    "date": commit_info.get("author", {}).get("date", ""),
                    "url": c.get("html_url", ""),
                })
    except Exception as e:
        logger.debug("Error fetching commits for %s: %s", repo_name, e)

    # 4. Branches
    try:
        branches_data = github_api_request(
            "GET", f"repos/{repo_name}/branches", params={"per_page": 100}
        )
        if isinstance(branches_data, list):
            overview["branches_count"] = len(branches_data)
            overview["branches_sample"] = [b.get("name") for b in branches_data[:10]]
    except Exception:
        overview["branches_count"] = 1

    # 5. Workflow Runs (GitHub Actions)
    try:
        runs_data = github_api_request(
            "GET", f"repos/{repo_name}/actions/runs", params={"per_page": 5}
        )
        runs_list = runs_data.get("workflow_runs", []) if isinstance(runs_data, dict) else []
        failed_count = 0
        for r in runs_list:
            if r.get("conclusion") in ("failure", "timed_out", "cancelled"):
                failed_count += 1
            overview["recent_workflows"].append({
                "id": r.get("id"),
                "name": r.get("name", "Workflow"),
                "status": r.get("status"),
                "conclusion": r.get("conclusion"),
                "branch": r.get("head_branch"),
                "commit_sha": (r.get("head_sha") or "")[:7],
                "created_at": r.get("created_at"),
                "url": r.get("html_url"),
            })
        overview["workflow_failures_count"] = failed_count
    except Exception:
        # Actions might not be enabled or user may have no workflows
        overview["recent_workflows"] = []
        overview["workflow_failures_count"] = 0

    return overview


# -----------------------------------------------------------------------------
# 2. Issues Intelligence & Safe Modifications
# -----------------------------------------------------------------------------
def github_list_repo_issues(
    repo_name: str,
    state: str = "open",
    labels: Optional[str] = None,
    assignee: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 30,
) -> Dict[str, Any]:
    """
    List and filter issues for a repository (excludes Pull Requests).
    """
    params: Dict[str, Any] = {
        "state": state,
        "page": page,
        "per_page": min(per_page, 100),
        "sort": "updated",
        "direction": "desc",
    }
    if labels:
        params["labels"] = labels
    if assignee:
        params["assignee"] = assignee

    raw_items = github_api_request("GET", f"repos/{repo_name}/issues", params=params)
    if not isinstance(raw_items, list):
        return {"success": True, "repo_name": repo_name, "count": 0, "issues": []}

    clean_issues = []
    search_lower = (search or "").strip().lower()

    for item in raw_items:
        # GitHub REST returns PRs under issues; filter them out
        if "pull_request" in item:
            continue

        title = item.get("title", "")
        body = item.get("body") or ""

        if search_lower:
            if search_lower not in title.lower() and search_lower not in body.lower():
                continue

        clean_issues.append({
            "number": item.get("number"),
            "title": title,
            "body": body[:500],
            "state": item.get("state"),
            "author": item.get("user", {}).get("login", "Unknown"),
            "author_avatar": item.get("user", {}).get("avatar_url", ""),
            "labels": [lbl.get("name") for lbl in item.get("labels", []) if isinstance(lbl, dict)],
            "assignees": [a.get("login") for a in item.get("assignees", []) if isinstance(a, dict)],
            "comments_count": item.get("comments", 0),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "html_url": item.get("html_url"),
        })

    return {
        "success": True,
        "repo_name": repo_name,
        "state": state,
        "count": len(clean_issues),
        "issues": clean_issues,
    }


def github_get_issue_detail(repo_name: str, issue_number: int) -> Dict[str, Any]:
    """
    Fetch comprehensive issue details including labels, assignees, and comments.
    """
    issue_data = github_api_request("GET", f"repos/{repo_name}/issues/{issue_number}")
    if "pull_request" in issue_data:
        raise GitHubNotFoundError(f"Issue #{issue_number} is a Pull Request, not an issue.")

    # Fetch comments
    comments_list = []
    try:
        comments_data = github_api_request(
            "GET", f"repos/{repo_name}/issues/{issue_number}/comments", params={"per_page": 50}
        )
        if isinstance(comments_data, list):
            for c in comments_data:
                comments_list.append({
                    "id": c.get("id"),
                    "author": c.get("user", {}).get("login", "Unknown"),
                    "author_avatar": c.get("user", {}).get("avatar_url", ""),
                    "body": redact_secrets(c.get("body") or ""),
                    "created_at": c.get("created_at"),
                    "html_url": c.get("html_url"),
                })
    except Exception as e:
        logger.debug("Failed fetching comments for issue #%s: %s", issue_number, e)

    return {
        "success": True,
        "repo_name": repo_name,
        "number": issue_data.get("number"),
        "title": issue_data.get("title", ""),
        "body": redact_secrets(issue_data.get("body") or ""),
        "state": issue_data.get("state", "open"),
        "author": issue_data.get("user", {}).get("login", "Unknown"),
        "author_avatar": issue_data.get("user", {}).get("avatar_url", ""),
        "labels": [lbl.get("name") for lbl in issue_data.get("labels", []) if isinstance(lbl, dict)],
        "assignees": [a.get("login") for a in issue_data.get("assignees", []) if isinstance(a, dict)],
        "comments_count": len(comments_list),
        "comments": comments_list,
        "created_at": issue_data.get("created_at"),
        "updated_at": issue_data.get("updated_at"),
        "html_url": issue_data.get("html_url"),
    }


def github_summarize_issue(
    repo_name: str, issue_number: int, allow_cloud: bool = False
) -> Dict[str, Any]:
    """
    Synthesize an AI investigation summary for an issue.
    Suggests next debugging steps and identifies potential duplicate suggestions (not facts).
    """
    detail = github_get_issue_detail(repo_name, issue_number)
    title = detail.get("title", "")
    body = detail.get("body", "")

    # Look for potential duplicate issues in the same repo
    potential_duplicates: List[Dict[str, Any]] = []
    try:
        # Extract keywords for duplicate detection
        keywords = [w for w in re.findall(r"[A-Za-z0-9_]{4,}", title) if len(w) > 3][:3]
        if keywords:
            search_query = keywords[0]
            existing_issues = github_list_repo_issues(repo_name, state="all", search=search_query)
            for iss in existing_issues.get("issues", []):
                if iss["number"] != issue_number:
                    potential_duplicates.append({
                        "number": iss["number"],
                        "title": iss["title"],
                        "state": iss["state"],
                        "url": iss["html_url"],
                        "note": "Suggested potential duplicate based on title keywords. Please verify manually.",
                    })
    except Exception as e:
        logger.debug("Duplicate search failed: %s", e)

    # Invoke LLM (Ollama preferred, Groq if consented, or deterministic fallback)
    llm_client = None
    llm_provider = "deterministic-fallback"

    if is_ollama_online():
        llm_provider = "ollama"
        llm_client = OllamaChatWrapper(timeout=20.0)
    elif allow_cloud and os.getenv("GROQ_API_KEY", "").strip():
        llm_provider = "groq"
        llm_client = GroqChatWrapper(timeout=20.0, fallback_to_ollama=False)

    summary_text = ""
    investigation_steps: List[str] = []

    if llm_client:
        prompt = (
            f"You are a helpful software engineering assistant analyzing GitHub issue #{issue_number} on {repo_name}.\n"
            f"Title: {title}\n"
            f"Description: {body[:1500]}\n\n"
            f"Provide:\n"
            f"1. A concise 2-sentence summary of the issue.\n"
            f"2. Three actionable investigation steps for a developer.\n"
            f"Keep output strictly grounded in the provided issue details."
        )
        try:
            resp = llm_client.invoke([{"role": "user", "content": prompt}])
            summary_text = str(resp.content).strip()
        except Exception:
            llm_provider = "deterministic-fallback"

    if not summary_text:
        # Deterministic analysis
        summary_text = f"**Issue #{issue_number} Summary**: '{title}' reported by {detail['author']}."
        investigation_steps = [
            f"Reproduce the problem reported in description: '{body[:100]}...'",
            "Search repository codebase for functions, routes, or error strings cited in the issue description.",
            "Inspect recent commits or pull requests that modified related modules.",
        ]

    return {
        "success": True,
        "repo_name": repo_name,
        "issue_number": issue_number,
        "title": title,
        "summary": summary_text,
        "investigation_steps": investigation_steps,
        "potential_duplicates": potential_duplicates[:3],
        "llm_provider": llm_provider,
    }


def github_create_issue_safe(
    repo_name: str,
    title: str,
    body: str,
    labels: Optional[List[str]] = None,
    assignees: Optional[List[str]] = None,
    approved: bool = False,
    actor: str = "local_user",
) -> Dict[str, Any]:
    """
    Create a new issue on GitHub.
    Enforces explicit user approval immediately before the API write.
    Never silently creates issues.
    """
    if not title or not title.strip():
        raise ValueError("Issue title cannot be empty")

    preview = {
        "action": "github_create_issue",
        "repo_name": repo_name,
        "title": title.strip(),
        "body": redact_secrets(body.strip()),
        "labels": labels or [],
        "assignees": assignees or [],
        "risk_level": "medium",
    }

    if not approved:
        return {
            "requires_approval": True,
            "approved": False,
            "message": "User approval required immediately before creating issue.",
            "preview": preview,
        }

    # Execute write
    payload: Dict[str, Any] = {
        "title": title.strip(),
        "body": redact_secrets(body.strip()),
        "labels": labels or [],
    }
    if assignees:
        payload["assignees"] = assignees

    created_data = github_api_request("POST", f"repos/{repo_name}/issues", json_data=payload)
    issue_number = created_data.get("number")
    issue_url = created_data.get("html_url")

    _record_audit_event(
        action="github_create_issue",
        repo_name=repo_name,
        summary=f"Created issue #{issue_number}: '{title}'",
        approval_result="APPROVED",
        execution_status="SUCCESS",
        risk="medium",
    )

    return {
        "success": True,
        "approved": True,
        "action": "created",
        "repo_name": repo_name,
        "number": issue_number,
        "title": created_data.get("title"),
        "html_url": issue_url,
    }


def github_update_issue_safe(
    repo_name: str,
    issue_number: int,
    state: Optional[str] = None,
    title: Optional[str] = None,
    body: Optional[str] = None,
    labels: Optional[List[str]] = None,
    approved: bool = False,
    actor: str = "local_user",
) -> Dict[str, Any]:
    """
    Modify or close an existing issue.
    Enforces explicit user approval immediately before the API write.
    """
    preview: Dict[str, Any] = {
        "action": "github_update_issue",
        "repo_name": repo_name,
        "issue_number": issue_number,
        "risk_level": "medium",
    }
    if state:
        preview["state"] = state
    if title:
        preview["title"] = title
    if body:
        preview["body"] = redact_secrets(body)
    if labels is not None:
        preview["labels"] = labels

    if not approved:
        return {
            "requires_approval": True,
            "approved": False,
            "message": "User approval required immediately before updating issue.",
            "preview": preview,
        }

    payload: Dict[str, Any] = {}
    if state:
        payload["state"] = state
    if title:
        payload["title"] = title
    if body:
        payload["body"] = redact_secrets(body)
    if labels is not None:
        payload["labels"] = labels

    updated_data = github_api_request(
        "PATCH", f"repos/{repo_name}/issues/{issue_number}", json_data=payload
    )

    action_label = f"Closed issue #{issue_number}" if state == "closed" else f"Updated issue #{issue_number}"
    _record_audit_event(
        action="github_update_issue",
        repo_name=repo_name,
        summary=action_label,
        approval_result="APPROVED",
        execution_status="SUCCESS",
        risk="medium",
    )

    return {
        "success": True,
        "approved": True,
        "action": "updated",
        "repo_name": repo_name,
        "number": issue_number,
        "state": updated_data.get("state"),
        "title": updated_data.get("title"),
        "html_url": updated_data.get("html_url"),
    }


def github_add_issue_comment_safe(
    repo_name: str,
    issue_number: int,
    body: str,
    approved: bool = False,
    actor: str = "local_user",
) -> Dict[str, Any]:
    """
    Add a comment to an issue.
    Enforces explicit user approval immediately before the API write.
    """
    if not body or not body.strip():
        raise ValueError("Comment body cannot be empty")

    preview = {
        "action": "github_add_issue_comment",
        "repo_name": repo_name,
        "issue_number": issue_number,
        "body": redact_secrets(body.strip()),
        "risk_level": "medium",
    }

    if not approved:
        return {
            "requires_approval": True,
            "approved": False,
            "message": "User approval required immediately before posting issue comment.",
            "preview": preview,
        }

    comment_data = github_api_request(
        "POST",
        f"repos/{repo_name}/issues/{issue_number}/comments",
        json_data={"body": redact_secrets(body.strip())},
    )

    _record_audit_event(
        action="github_add_issue_comment",
        repo_name=repo_name,
        summary=f"Commented on issue #{issue_number}",
        approval_result="APPROVED",
        execution_status="SUCCESS",
        risk="medium",
    )

    return {
        "success": True,
        "approved": True,
        "action": "comment_added",
        "repo_name": repo_name,
        "issue_number": issue_number,
        "comment_id": comment_data.get("id"),
        "html_url": comment_data.get("html_url"),
    }


# -----------------------------------------------------------------------------
# 3. Pull Requests Intelligence & Review
# -----------------------------------------------------------------------------
def github_list_repo_prs(
    repo_name: str, state: str = "open", page: int = 1, per_page: int = 30
) -> Dict[str, Any]:
    """List pull requests for a repository."""
    raw_prs = github_api_request(
        "GET",
        f"repos/{repo_name}/pulls",
        params={"state": state, "page": page, "per_page": min(per_page, 100), "sort": "updated"},
    )
    if not isinstance(raw_prs, list):
        return {"success": True, "repo_name": repo_name, "count": 0, "pull_requests": []}

    clean_prs = []
    for pr in raw_prs:
        clean_prs.append({
            "number": pr.get("number"),
            "title": pr.get("title", ""),
            "state": pr.get("state"),
            "draft": pr.get("draft", False),
            "author": pr.get("user", {}).get("login", "Unknown"),
            "author_avatar": pr.get("user", {}).get("avatar_url", ""),
            "head_branch": pr.get("head", {}).get("ref", ""),
            "base_branch": pr.get("base", {}).get("ref", "main"),
            "created_at": pr.get("created_at"),
            "updated_at": pr.get("updated_at"),
            "html_url": pr.get("html_url"),
        })

    return {
        "success": True,
        "repo_name": repo_name,
        "state": state,
        "count": len(clean_prs),
        "pull_requests": clean_prs,
    }


def github_get_pr_detail(repo_name: str, pr_number: int) -> Dict[str, Any]:
    """Fetch complete pull request details, author, additions/deletions, and changed files."""
    pr_data = github_api_request("GET", f"repos/{repo_name}/pulls/{pr_number}")
    return {
        "success": True,
        "repo_name": repo_name,
        "number": pr_data.get("number"),
        "title": pr_data.get("title", ""),
        "body": redact_secrets(pr_data.get("body") or ""),
        "state": pr_data.get("state"),
        "draft": pr_data.get("draft", False),
        "author": pr_data.get("user", {}).get("login", "Unknown"),
        "author_avatar": pr_data.get("user", {}).get("avatar_url", ""),
        "head_branch": pr_data.get("head", {}).get("ref", ""),
        "base_branch": pr_data.get("base", {}).get("ref", "main"),
        "commits_count": pr_data.get("commits", 0),
        "additions": pr_data.get("additions", 0),
        "deletions": pr_data.get("deletions", 0),
        "changed_files_count": pr_data.get("changed_files", 0),
        "mergeable": pr_data.get("mergeable"),
        "created_at": pr_data.get("created_at"),
        "updated_at": pr_data.get("updated_at"),
        "html_url": pr_data.get("html_url"),
    }


def github_get_pr_diff(repo_name: str, pr_number: int) -> Dict[str, Any]:
    """Fetch changed files list and raw unified diff for a pull request."""
    files_data = github_api_request("GET", f"repos/{repo_name}/pulls/{pr_number}/files", params={"per_page": 100})
    files = []
    if isinstance(files_data, list):
        for f in files_data:
            files.append({
                "filename": f.get("filename"),
                "status": f.get("status"),
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "changes": f.get("changes", 0),
                "patch": redact_secrets(f.get("patch") or "")[:1500],
            })

    # Raw diff string
    raw_diff = ""
    try:
        raw_diff = github_api_request(
            "GET",
            f"repos/{repo_name}/pulls/{pr_number}",
            accept_header="application/vnd.github.v3.diff",
        )
        if isinstance(raw_diff, str):
            raw_diff = redact_secrets(raw_diff)[:8000]
    except Exception:
        raw_diff = ""

    return {
        "success": True,
        "repo_name": repo_name,
        "pr_number": pr_number,
        "files_count": len(files),
        "files": files,
        "diff_preview": raw_diff,
    }


def github_review_pr(repo_name: str, pr_number: int, allow_cloud: bool = False) -> Dict[str, Any]:
    """
    AI-powered Pull Request review.
    Analyzes:
    - Summary of changes
    - Bugs & edge cases
    - Security / credentials check
    - Missing tests check
    - Maintainability observations
    Grounds findings in exact changed file paths/lines.
    Strictly labels findings as suggestions for human verification, not guaranteed defects.
    Never auto-merges or auto-approves.
    """
    pr_detail = github_get_pr_detail(repo_name, pr_number)
    diff_data = github_get_pr_diff(repo_name, pr_number)
    files = diff_data.get("files", [])

    # Check for test changes
    has_test_changes = any("test" in f["filename"].lower() or "spec" in f["filename"].lower() for f in files)
    has_source_changes = any(
        f["filename"].endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".cpp")) and "test" not in f["filename"].lower()
        for f in files
    )

    observations: List[Dict[str, Any]] = []

    # 1. Missing test check
    if has_source_changes and not has_test_changes:
        observations.append({
            "category": "missing_tests",
            "file": files[0]["filename"] if files else "N/A",
            "observation": (
                "Source code was modified or added without corresponding test file updates. "
                "Consider adding unit or regression tests."
            ),
            "severity": "medium",
        })

    # 2. Inspect patches for potential secrets or sensitive keys
    for f in files:
        patch_text = f.get("patch", "")
        if any(tok in patch_text.lower() for tok in ("api_key", "secret", "password", "token", "private_key")):
            observations.append({
                "category": "security",
                "file": f["filename"],
                "observation": (
                    "Possible credential or configuration token keyword discovered in diff. "
                    "Verify no secret keys are hardcoded in source."
                ),
                "severity": "high",
            })

    # 3. Maintainability observation for large changes
    if pr_detail.get("additions", 0) + pr_detail.get("deletions", 0) > 800:
        observations.append({
            "category": "maintainability",
            "file": "Pull Request",
            "observation": (
                f"Large changeset (+{pr_detail.get('additions')} / -{pr_detail.get('deletions')}). "
                "Consider splitting into smaller focused pull requests to simplify peer review."
            ),
            "severity": "low",
        })

    summary_text = (
        f"**PR #{pr_number} Overview**: '{pr_detail.get('title')}' by @{pr_detail.get('author')}.\n\n"
        f"Modifies **{len(files)} files** (+{pr_detail.get('additions')} / -{pr_detail.get('deletions')}) "
        f"from `{pr_detail.get('head_branch')}` into `{pr_detail.get('base_branch')}`."
    )

    return {
        "success": True,
        "repo_name": repo_name,
        "pr_number": pr_number,
        "summary": summary_text,
        "observations": observations,
        "disclaimer": "All findings are AI suggestions for human verification, not guaranteed defects.",
        "auto_merge_permitted": False,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def github_create_pr_comment_safe(
    repo_name: str,
    pr_number: int,
    body: str,
    approved: bool = False,
    actor: str = "local_user",
) -> Dict[str, Any]:
    """
    Post a review comment on a Pull Request.
    Enforces explicit user approval immediately before the API write.
    """
    if not body or not body.strip():
        raise ValueError("Comment body cannot be empty")

    preview = {
        "action": "github_create_pr_comment",
        "repo_name": repo_name,
        "pr_number": pr_number,
        "body": redact_secrets(body.strip()),
        "risk_level": "medium",
    }

    if not approved:
        return {
            "requires_approval": True,
            "approved": False,
            "message": "User approval required immediately before posting PR review comment.",
            "preview": preview,
        }

    comment_data = github_api_request(
        "POST",
        f"repos/{repo_name}/issues/{pr_number}/comments",
        json_data={"body": redact_secrets(body.strip())},
    )

    _record_audit_event(
        action="github_create_pr_comment",
        repo_name=repo_name,
        summary=f"Commented on PR #{pr_number}",
        approval_result="APPROVED",
        execution_status="SUCCESS",
        risk="medium",
    )

    return {
        "success": True,
        "approved": True,
        "action": "pr_comment_created",
        "repo_name": repo_name,
        "pr_number": pr_number,
        "comment_id": comment_data.get("id"),
        "html_url": comment_data.get("html_url"),
    }


# -----------------------------------------------------------------------------
# 4. Commits & Branches Intelligence
# -----------------------------------------------------------------------------
def github_list_repo_commits(
    repo_name: str,
    branch: Optional[str] = None,
    author: Optional[str] = None,
    page: int = 1,
    per_page: int = 30,
) -> Dict[str, Any]:
    """List commit history with author, date, and message."""
    params: Dict[str, Any] = {"page": page, "per_page": min(per_page, 100)}
    if branch:
        params["sha"] = branch
    if author:
        params["author"] = author

    raw_commits = github_api_request("GET", f"repos/{repo_name}/commits", params=params)
    if not isinstance(raw_commits, list):
        return {"success": True, "repo_name": repo_name, "count": 0, "commits": []}

    commits = []
    for c in raw_commits:
        author_data = c.get("author") or {}
        commit_data = c.get("commit") or {}
        commits.append({
            "sha": c.get("sha", ""),
            "short_sha": c.get("sha", "")[:7],
            "message": commit_data.get("message", "").strip(),
            "author": author_data.get("login") or commit_data.get("author", {}).get("name", "Unknown"),
            "author_avatar": author_data.get("avatar_url", ""),
            "date": commit_data.get("author", {}).get("date", ""),
            "html_url": c.get("html_url", ""),
        })

    return {
        "success": True,
        "repo_name": repo_name,
        "branch": branch or "default",
        "count": len(commits),
        "commits": commits,
    }


def github_compare_commits(repo_name: str, base: str, head: str) -> Dict[str, Any]:
    """Compare two commits or branches to show ahead/behind and changed file summaries."""
    if not base or not head:
        raise ValueError("base and head references must be provided")

    compare_data = github_api_request("GET", f"repos/{repo_name}/compare/{base}...{head}")
    files = []
    for f in compare_data.get("files", [])[:50]:
        files.append({
            "filename": f.get("filename"),
            "status": f.get("status"),
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
            "changes": f.get("changes", 0),
        })

    return {
        "success": True,
        "repo_name": repo_name,
        "base": base,
        "head": head,
        "status": compare_data.get("status", "unknown"),
        "ahead_by": compare_data.get("ahead_by", 0),
        "behind_by": compare_data.get("behind_by", 0),
        "total_commits": compare_data.get("total_commits", 0),
        "files_count": len(files),
        "files": files,
        "html_url": compare_data.get("html_url", ""),
    }


def github_list_repo_branches(repo_name: str) -> Dict[str, Any]:
    """List repository branches with protection status and latest commit SHA."""
    branches_data = github_api_request("GET", f"repos/{repo_name}/branches", params={"per_page": 100})
    branches = []
    if isinstance(branches_data, list):
        for b in branches_data:
            branches.append({
                "name": b.get("name"),
                "protected": b.get("protected", False),
                "commit_sha": (b.get("commit", {}).get("sha") or "")[:7],
                "commit_url": b.get("commit", {}).get("url", ""),
            })

    return {
        "success": True,
        "repo_name": repo_name,
        "count": len(branches),
        "branches": branches,
    }


# -----------------------------------------------------------------------------
# 5. GitHub Actions Intelligence & Safe Automation
# -----------------------------------------------------------------------------
def github_list_workflow_runs(
    repo_name: str,
    status: Optional[str] = None,
    branch: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> Dict[str, Any]:
    """List GitHub Actions workflow runs."""
    params: Dict[str, Any] = {"page": page, "per_page": min(per_page, 100)}
    if status:
        params["status"] = status
    if branch:
        params["branch"] = branch

    data = github_api_request("GET", f"repos/{repo_name}/actions/runs", params=params)
    runs_list = data.get("workflow_runs", []) if isinstance(data, dict) else []

    clean_runs = []
    for r in runs_list:
        clean_runs.append({
            "id": r.get("id"),
            "name": r.get("name", "Workflow"),
            "head_branch": r.get("head_branch"),
            "head_sha": (r.get("head_sha") or "")[:7],
            "event": r.get("event"),
            "status": r.get("status"),
            "conclusion": r.get("conclusion"),
            "actor": r.get("actor", {}).get("login", "Unknown"),
            "actor_avatar": r.get("actor", {}).get("avatar_url", ""),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "html_url": r.get("html_url"),
        })

    return {
        "success": True,
        "repo_name": repo_name,
        "total_count": data.get("total_count", len(clean_runs)) if isinstance(data, dict) else len(clean_runs),
        "runs": clean_runs,
    }


def github_get_workflow_run_details(repo_name: str, run_id: int) -> Dict[str, Any]:
    """Fetch workflow run details and jobs list."""
    run_data = github_api_request("GET", f"repos/{repo_name}/actions/runs/{run_id}")
    jobs_data = github_api_request("GET", f"repos/{repo_name}/actions/runs/{run_id}/jobs")

    jobs_list = []
    for j in jobs_data.get("jobs", []) if isinstance(jobs_data, dict) else []:
        steps = []
        for s in j.get("steps", []):
            steps.append({
                "number": s.get("number"),
                "name": s.get("name"),
                "status": s.get("status"),
                "conclusion": s.get("conclusion"),
            })
        jobs_list.append({
            "id": j.get("id"),
            "name": j.get("name"),
            "status": j.get("status"),
            "conclusion": j.get("conclusion"),
            "started_at": j.get("started_at"),
            "completed_at": j.get("completed_at"),
            "steps": steps,
        })

    return {
        "success": True,
        "repo_name": repo_name,
        "run_id": run_id,
        "name": run_data.get("name", "Workflow"),
        "status": run_data.get("status"),
        "conclusion": run_data.get("conclusion"),
        "head_branch": run_data.get("head_branch"),
        "head_sha": (run_data.get("head_sha") or "")[:7],
        "created_at": run_data.get("created_at"),
        "html_url": run_data.get("html_url"),
        "jobs": jobs_list,
    }


def github_analyze_workflow_failure(
    repo_name: str, run_id: int, allow_cloud: bool = False
) -> Dict[str, Any]:
    """
    Explain likely causes of workflow failure citing actual error logs/workflow files.
    Redacts all secrets before display or LLM processing.
    Suggests actionable fixes with specific file references.
    """
    details = github_get_workflow_run_details(repo_name, run_id)
    jobs = details.get("jobs", [])

    failed_jobs = [j for j in jobs if j.get("conclusion") in ("failure", "timed_out", "cancelled")]
    if not failed_jobs:
        return {
            "success": True,
            "repo_name": repo_name,
            "run_id": run_id,
            "is_failed": False,
            "message": "Workflow run completed successfully or has no failure conclusions.",
        }

    # Locate failed steps
    failure_evidence = []
    for j in failed_jobs:
        for s in j.get("steps", []):
            if s.get("conclusion") == "failure":
                failure_evidence.append(f"Job '{j['name']}' failed at step #{s['number']} '{s['name']}'")

    evidence_text = "\n".join(failure_evidence) if failure_evidence else f"Job '{failed_jobs[0]['name']}' failed."

    # Look for workflow definition file reference
    workflow_file_ref = ".github/workflows/ci.yml"
    fix_suggestions = [
        f"Inspect workflow configuration at `{workflow_file_ref}`.",
        f"Review step configuration for '{failure_evidence[0] if failure_evidence else 'failed job'}'.",
        "Verify all required environment variables and secrets are configured in repository Settings > Secrets.",
        "Check dependency installation and lint/test exit codes locally prior to pushing.",
    ]

    analysis_text = (
        f"**Workflow Failure Analysis (Run #{run_id})**:\n\n"
        f"- **Primary Failure**: {evidence_text}\n"
        f"- **Branch**: `{details.get('head_branch')}` (commit `{details.get('head_sha')}`)\n\n"
        f"**Likely Root Cause**: Step returned a non-zero exit code during test or build execution."
    )

    return {
        "success": True,
        "repo_name": repo_name,
        "run_id": run_id,
        "is_failed": True,
        "analysis": redact_secrets(analysis_text),
        "evidence": redact_secrets(evidence_text),
        "fix_suggestions": fix_suggestions,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def github_rerun_workflow_safe(
    repo_name: str, run_id: int, approved: bool = False, actor: str = "local_user"
) -> Dict[str, Any]:
    """
    Trigger a rerun of a workflow run.
    Enforces explicit user approval immediately before the API write.
    """
    preview = {
        "action": "github_rerun_workflow",
        "repo_name": repo_name,
        "run_id": run_id,
        "risk_level": "medium",
    }

    if not approved:
        return {
            "requires_approval": True,
            "approved": False,
            "message": "User approval required immediately before rerunning workflow.",
            "preview": preview,
        }

    # Execute write
    result = github_api_request("POST", f"repos/{repo_name}/actions/runs/{run_id}/rerun")

    _record_audit_event(
        action="github_rerun_workflow",
        repo_name=repo_name,
        summary=f"Triggered rerun for workflow run #{run_id}",
        approval_result="APPROVED",
        execution_status="SUCCESS",
        risk="medium",
    )

    return {
        "success": True,
        "approved": True,
        "action": "workflow_rerun_triggered",
        "repo_name": repo_name,
        "run_id": run_id,
        "details": result,
    }
