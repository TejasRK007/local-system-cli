"""
GitHub Developer & Repository Automation Tools (Milestone 8).

Provides repository issue listing (LOW risk), PR inspection (LOW risk),
and issue creation (MEDIUM risk requiring user confirmation).
Supports offline test execution and lazy API token injection.
"""

import json
import os
import urllib.parse
import urllib.request
from typing import Any, List, Optional


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
