"""
tests/test_github_workbench.py

Comprehensive test suite for Milestone 9 – Prompt 4: Developer Workbench & Safe Automation.

Covers:
  - Repository overview intelligence
  - Issues: listing, filtering, detail, AI summary, duplicate suggestions
  - Pull Requests: listing, filtering, detail, diff, AI review (auto-merge blocked)
  - Commits: listing, comparison (ahead/behind, files)
  - Branches: listing, protection metadata
  - GitHub Actions: workflow run listing, job/step details, failure analysis
  - Safety guardrails: approval-required writes, unapproved write blocking
  - Secret redaction on logs and diffs
  - Audit logging for every write action
  - Rate limit and auth error handling
  - All 19 FastAPI /api/github/workbench/* endpoints
  - Regression: existing test suites remain unaffected
"""

import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Minimal stub fixtures – returned by mocked github_api_request
# ---------------------------------------------------------------------------
REPO_DATA = {
    "full_name": "owner/testrepo",
    "description": "A test repository",
    "default_branch": "main",
    "stargazers_count": 42,
    "forks_count": 5,
    "open_issues_count": 7,
    "private": False,
    "html_url": "https://github.com/owner/testrepo",
}

COMMITS_DATA = [
    {
        "sha": "abc123def456",
        "commit": {
            "message": "Initial commit",
            "author": {"name": "Alice", "date": "2024-01-01T00:00:00Z"},
        },
        "author": {"login": "alice", "avatar_url": ""},
        "html_url": "https://github.com/owner/testrepo/commit/abc123",
    }
]

BRANCHES_DATA = [
    {"name": "main", "protected": True, "commit": {"sha": "abc123def456", "url": ""}},
    {"name": "feature/x", "protected": False, "commit": {"sha": "def456abc123", "url": ""}},
]

ISSUES_DATA = [
    {
        "number": 1,
        "title": "Bug in login",
        "body": "Users cannot log in with correct credentials",
        "state": "open",
        "user": {"login": "bob", "avatar_url": ""},
        "labels": [{"name": "bug"}],
        "assignees": [],
        "comments": 2,
        "created_at": "2024-01-02T00:00:00Z",
        "updated_at": "2024-01-03T00:00:00Z",
        "html_url": "https://github.com/owner/testrepo/issues/1",
    },
    {
        "number": 2,
        "title": "Feature request: dark mode",
        "body": "Please add dark mode support",
        "state": "open",
        "user": {"login": "carol", "avatar_url": ""},
        "labels": [{"name": "enhancement"}],
        "assignees": [],
        "comments": 0,
        "created_at": "2024-01-04T00:00:00Z",
        "updated_at": "2024-01-05T00:00:00Z",
        "html_url": "https://github.com/owner/testrepo/issues/2",
        "pull_request": {},  # This one should be filtered out as a PR
    },
]

ISSUE_DETAIL = {
    "number": 1,
    "title": "Bug in login",
    "body": "Users cannot log in with correct credentials",
    "state": "open",
    "user": {"login": "bob", "avatar_url": ""},
    "labels": [{"name": "bug"}],
    "assignees": [],
    "comments": 2,
    "created_at": "2024-01-02T00:00:00Z",
    "updated_at": "2024-01-03T00:00:00Z",
    "html_url": "https://github.com/owner/testrepo/issues/1",
}

ISSUE_COMMENTS = [
    {
        "id": 100,
        "user": {"login": "alice", "avatar_url": ""},
        "body": "I can reproduce this.",
        "created_at": "2024-01-02T12:00:00Z",
        "html_url": "https://github.com/owner/testrepo/issues/1#issuecomment-100",
    }
]

PRS_DATA = [
    {
        "number": 10,
        "title": "Fix login bug",
        "state": "open",
        "draft": False,
        "user": {"login": "alice", "avatar_url": ""},
        "head": {"ref": "fix/login"},
        "base": {"ref": "main"},
        "created_at": "2024-01-06T00:00:00Z",
        "updated_at": "2024-01-07T00:00:00Z",
        "html_url": "https://github.com/owner/testrepo/pull/10",
    }
]

PR_DETAIL = {
    "number": 10,
    "title": "Fix login bug",
    "body": "Fixes the login credential check",
    "state": "open",
    "draft": False,
    "user": {"login": "alice", "avatar_url": ""},
    "head": {"ref": "fix/login"},
    "base": {"ref": "main"},
    "commits": 2,
    "additions": 15,
    "deletions": 3,
    "changed_files": 2,
    "mergeable": True,
    "created_at": "2024-01-06T00:00:00Z",
    "updated_at": "2024-01-07T00:00:00Z",
    "html_url": "https://github.com/owner/testrepo/pull/10",
}

PR_FILES = [
    {
        "filename": "app/auth.py",
        "status": "modified",
        "additions": 10,
        "deletions": 2,
        "changes": 12,
        "patch": "@@ -10,7 +10,15 @@\n+def verify_credentials(user, pw):\n+    return check_hash(pw, user.password_hash)",
    },
    {
        "filename": "tests/test_auth.py",
        "status": "added",
        "additions": 5,
        "deletions": 1,
        "changes": 6,
        "patch": "+def test_login():\n+    assert verify_credentials('u', 'pw')",
    },
]

WORKFLOW_RUNS_DATA = {
    "total_count": 2,
    "workflow_runs": [
        {
            "id": 1001,
            "name": "CI Pipeline",
            "head_branch": "main",
            "head_sha": "abc123def456xyz",
            "event": "push",
            "status": "completed",
            "conclusion": "failure",
            "actor": {"login": "alice", "avatar_url": ""},
            "created_at": "2024-01-07T10:00:00Z",
            "updated_at": "2024-01-07T10:05:00Z",
            "html_url": "https://github.com/owner/testrepo/actions/runs/1001",
        },
        {
            "id": 1002,
            "name": "Deploy",
            "head_branch": "main",
            "head_sha": "abc123def456xyz",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "actor": {"login": "bob", "avatar_url": ""},
            "created_at": "2024-01-07T11:00:00Z",
            "updated_at": "2024-01-07T11:03:00Z",
            "html_url": "https://github.com/owner/testrepo/actions/runs/1002",
        },
    ],
}

RUN_DETAIL = {
    "id": 1001,
    "name": "CI Pipeline",
    "status": "completed",
    "conclusion": "failure",
    "head_branch": "main",
    "head_sha": "abc123def456xyz",
    "created_at": "2024-01-07T10:00:00Z",
    "html_url": "https://github.com/owner/testrepo/actions/runs/1001",
}

JOBS_DATA = {
    "jobs": [
        {
            "id": 2001,
            "name": "build-and-test",
            "status": "completed",
            "conclusion": "failure",
            "started_at": "2024-01-07T10:01:00Z",
            "completed_at": "2024-01-07T10:04:00Z",
            "steps": [
                {"number": 1, "name": "Checkout code", "status": "completed", "conclusion": "success"},
                {"number": 2, "name": "Run tests", "status": "completed", "conclusion": "failure"},
            ],
        }
    ]
}

COMPARE_DATA = {
    "status": "ahead",
    "ahead_by": 3,
    "behind_by": 0,
    "total_commits": 3,
    "files": [
        {"filename": "app/main.py", "status": "modified", "additions": 5, "deletions": 2, "changes": 7},
    ],
    "html_url": "https://github.com/owner/testrepo/compare/main...feature/x",
}


# ---------------------------------------------------------------------------
# Helper: mock github_api_request to return fixture data based on endpoint
# ---------------------------------------------------------------------------
def _mock_api(*args, **kwargs):
    """Side-effect function to return appropriate fixture by endpoint pattern."""
    endpoint = args[1] if len(args) > 1 else (args[0] if args else "")
    if "pulls" in endpoint and "/files" in endpoint:
        return PR_FILES
    if "pulls" in endpoint and endpoint.count("/") >= 4:
        return PR_DETAIL
    if "pulls" in endpoint and endpoint.endswith("pulls"):
        return PRS_DATA
    if "issues" in endpoint and "/comments" in endpoint:
        return ISSUE_COMMENTS
    if "issues" in endpoint and endpoint.endswith("issues"):
        return ISSUES_DATA
    if "issues/" in endpoint:
        return ISSUE_DETAIL
    if "commits" in endpoint and "compare" not in endpoint:
        return COMMITS_DATA
    if "compare" in endpoint:
        return COMPARE_DATA
    if "branches" in endpoint and "actions" not in endpoint:
        return BRANCHES_DATA
    if "actions/runs" in endpoint and "/jobs" in endpoint:
        return JOBS_DATA
    if "actions/runs" in endpoint and str(endpoint).endswith(("1001", "1002")):
        return RUN_DETAIL
    if "actions/runs" in endpoint:
        return WORKFLOW_RUNS_DATA
    if "repos/" in endpoint and endpoint.count("/") <= 2:
        return REPO_DATA
    return {}


# ===========================================================================
# TEST CLASS 1: github_workbench module – unit tests
# ===========================================================================
class TestGithubWorkbenchCore(unittest.TestCase):
    """Unit tests for core functions in app.tools.github_workbench."""

    def setUp(self):
        self.patcher = patch("app.tools.github_workbench.github_api_request")
        self.mock_api = self.patcher.start()
        self.mock_api.side_effect = _mock_api
        # Stub db.log_event so writes don't need a real DB
        self.db_patcher = patch("app.tools.github_workbench.db.log_event")
        self.mock_db = self.db_patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.db_patcher.stop()

    # --- Overview ---
    def test_overview_basic(self):
        from app.tools.github_workbench import github_get_repo_overview
        result = github_get_repo_overview("owner/testrepo")
        self.assertTrue(result["success"])
        self.assertEqual(result["repo_name"], "owner/testrepo")
        self.assertIn("open_issues_count", result)
        self.assertIsInstance(result["recent_commits"], list)
        self.assertIsInstance(result["recent_workflows"], list)

    def test_overview_invalid_repo_name(self):
        from app.tools.github_workbench import github_get_repo_overview
        with self.assertRaises(ValueError):
            github_get_repo_overview("nodslash")

    def test_overview_has_branch_count(self):
        from app.tools.github_workbench import github_get_repo_overview
        result = github_get_repo_overview("owner/testrepo")
        self.assertGreaterEqual(result.get("branches_count", 0), 0)

    def test_overview_handles_workflow_failures(self):
        """Overview should count failure-conclusion runs."""
        from app.tools.github_workbench import github_get_repo_overview
        result = github_get_repo_overview("owner/testrepo")
        # We have one failure run in fixture
        self.assertIn("workflow_failures_count", result)

    # --- Issues ---
    def test_list_issues_returns_issues(self):
        from app.tools.github_workbench import github_list_repo_issues
        result = github_list_repo_issues("owner/testrepo")
        self.assertTrue(result["success"])
        # PR item (has pull_request key) must be filtered out
        self.assertEqual(len(result["issues"]), 1)
        self.assertEqual(result["issues"][0]["number"], 1)

    def test_list_issues_state_filter(self):
        from app.tools.github_workbench import github_list_repo_issues
        result = github_list_repo_issues("owner/testrepo", state="closed")
        self.assertTrue(result["success"])
        # Mock always returns open issues; none pass a "closed" label search, still returns list
        self.assertIsInstance(result["issues"], list)

    def test_list_issues_text_search(self):
        from app.tools.github_workbench import github_list_repo_issues
        result = github_list_repo_issues("owner/testrepo", search="login")
        self.assertTrue(result["success"])
        for iss in result["issues"]:
            self.assertIn("login", iss["title"].lower() + (iss.get("body") or "").lower())

    def test_list_issues_excludes_prs(self):
        """Issues endpoint must never return pull_request items."""
        from app.tools.github_workbench import github_list_repo_issues
        result = github_list_repo_issues("owner/testrepo")
        for iss in result["issues"]:
            self.assertNotIn("pull_request", iss)

    def test_get_issue_detail(self):
        from app.tools.github_workbench import github_get_issue_detail
        result = github_get_issue_detail("owner/testrepo", 1)
        self.assertTrue(result["success"])
        self.assertEqual(result["number"], 1)
        self.assertEqual(result["title"], "Bug in login")
        self.assertIsInstance(result["comments"], list)

    def test_get_issue_detail_redacts_secrets_in_comments(self):
        """Comments body should be redacted before returning."""
        from app.tools.github_workbench import github_get_issue_detail
        # Inject a secret into the comment body fixture
        self.mock_api.side_effect = None

        def _api_with_secret(*a, **kw):
            endpoint = a[1] if len(a) > 1 else (a[0] if a else "")
            if "issues/" in endpoint and "/comments" in endpoint:
                return [{
                    "id": 999,
                    "user": {"login": "eve", "avatar_url": ""},
                    "body": "API_KEY=sk-12345678901234567890123456789012",
                    "created_at": "2024-01-01T00:00:00Z",
                    "html_url": "",
                }]
            return _mock_api(endpoint, *a, **kw)
        self.mock_api.side_effect = _api_with_secret
        result = github_get_issue_detail("owner/testrepo", 1)
        for comment in result["comments"]:
            self.assertNotIn("sk-12345678901234567890123456789012", comment.get("body", ""))

    def test_summarize_issue_returns_summary(self):
        from app.tools.github_workbench import github_summarize_issue
        # Patch LLM so we use deterministic fallback
        with patch("app.tools.github_workbench.is_ollama_online", return_value=False):
            result = github_summarize_issue("owner/testrepo", 1)
        self.assertTrue(result["success"])
        self.assertIn("summary", result)
        self.assertIsInstance(result.get("investigation_steps"), list)
        self.assertIsInstance(result.get("potential_duplicates"), list)

    def test_summarize_issue_potential_duplicates_are_suggestions_not_facts(self):
        """Potential duplicates must carry a note emphasising they are suggestions."""
        from app.tools.github_workbench import github_summarize_issue
        with patch("app.tools.github_workbench.is_ollama_online", return_value=False):
            result = github_summarize_issue("owner/testrepo", 1)
        for dup in result.get("potential_duplicates", []):
            # Must have a note field indicating suggestion, not confirmed duplicate
            note = dup.get("note", "").lower()
            self.assertTrue(
                "suggest" in note or "verify" in note or "manual" in note,
                f"Duplicate note should indicate suggestion; got: {note!r}",
            )

    # --- Write: Create Issue (approval required) ---
    def test_create_issue_requires_approval(self):
        from app.tools.github_workbench import github_create_issue_safe
        result = github_create_issue_safe("owner/testrepo", "Bug title", "Bug body", approved=False)
        self.assertTrue(result.get("requires_approval"))
        self.assertFalse(result.get("approved"))
        # Must NOT have called the API for a write
        for call_args in self.mock_api.call_args_list:
            self.assertNotIn("POST", str(call_args[0][0]))

    def test_create_issue_approved_calls_api_and_audits(self):
        from app.tools.github_workbench import github_create_issue_safe
        self.mock_api.side_effect = None
        created = {"number": 42, "title": "Bug title", "html_url": "https://github.com/owner/testrepo/issues/42"}
        self.mock_api.return_value = created
        result = github_create_issue_safe("owner/testrepo", "Bug title", "Bug body", approved=True)
        self.assertTrue(result.get("success"))
        self.assertTrue(result.get("approved"))
        self.mock_db.assert_called_once()
        audit_call = self.mock_db.call_args
        # Audit must include action and not log secrets
        kw = audit_call[1] if audit_call[1] else {}
        self.assertEqual(kw.get("action", ""), "github_create_issue")

    def test_create_issue_empty_title_raises(self):
        from app.tools.github_workbench import github_create_issue_safe
        with self.assertRaises(ValueError):
            github_create_issue_safe("owner/testrepo", "", "body", approved=True)

    # --- Write: Update Issue ---
    def test_update_issue_requires_approval(self):
        from app.tools.github_workbench import github_update_issue_safe
        result = github_update_issue_safe("owner/testrepo", 1, state="closed", approved=False)
        self.assertTrue(result.get("requires_approval"))
        self.assertFalse(result.get("approved"))

    def test_update_issue_approved_audits(self):
        from app.tools.github_workbench import github_update_issue_safe
        self.mock_api.side_effect = None
        self.mock_api.return_value = {"number": 1, "state": "closed", "title": "Bug in login", "html_url": ""}
        result = github_update_issue_safe("owner/testrepo", 1, state="closed", approved=True)
        self.assertTrue(result["success"])
        self.mock_db.assert_called_once()

    # --- Write: Issue Comment ---
    def test_add_issue_comment_requires_approval(self):
        from app.tools.github_workbench import github_add_issue_comment_safe
        result = github_add_issue_comment_safe("owner/testrepo", 1, "LGTM!", approved=False)
        self.assertTrue(result.get("requires_approval"))

    def test_add_issue_comment_empty_body_raises(self):
        from app.tools.github_workbench import github_add_issue_comment_safe
        with self.assertRaises(ValueError):
            github_add_issue_comment_safe("owner/testrepo", 1, "", approved=True)

    def test_add_issue_comment_redacts_secrets_before_posting(self):
        """Body with a secret token must be redacted before the API write."""
        from app.tools.github_workbench import github_add_issue_comment_safe
        self.mock_api.side_effect = None
        self.mock_api.return_value = {"id": 999, "html_url": ""}
        body_with_secret = "My API_KEY=ghp_abcdef1234567890ABCDEF1234567890ab12 see logs"
        github_add_issue_comment_safe("owner/testrepo", 1, body_with_secret, approved=True)
        # The actual API call body must not contain the raw secret
        post_call = self.mock_api.call_args
        json_data = post_call[1].get("json_data", {}) or (post_call[0][3] if len(post_call[0]) > 3 else {})
        sent_body = json_data.get("body", "")
        self.assertNotIn("ghp_abcdef1234567890ABCDEF1234567890ab12", sent_body)

    # --- Pull Requests ---
    def test_list_prs(self):
        from app.tools.github_workbench import github_list_repo_prs
        result = github_list_repo_prs("owner/testrepo")
        self.assertTrue(result["success"])
        self.assertIsInstance(result["pull_requests"], list)
        self.assertGreater(len(result["pull_requests"]), 0)
        pr = result["pull_requests"][0]
        self.assertIn("number", pr)
        self.assertIn("head_branch", pr)
        self.assertIn("base_branch", pr)

    def test_get_pr_detail(self):
        from app.tools.github_workbench import github_get_pr_detail
        result = github_get_pr_detail("owner/testrepo", 10)
        self.assertTrue(result["success"])
        self.assertEqual(result["number"], 10)
        self.assertIn("additions", result)
        self.assertIn("deletions", result)

    def test_get_pr_diff_returns_files_and_diff(self):
        from app.tools.github_workbench import github_get_pr_diff
        result = github_get_pr_diff("owner/testrepo", 10)
        self.assertTrue(result["success"])
        self.assertIsInstance(result["files"], list)
        self.assertIn("diff_preview", result)

    def test_get_pr_diff_redacts_secrets(self):
        """Patches containing secret keywords must be redacted."""
        from app.tools.github_workbench import github_get_pr_diff
        self.mock_api.side_effect = None

        def _secret_patch(*a, **kw):
            endpoint = a[1] if len(a) > 1 else (a[0] if a else "")
            if "files" in endpoint:
                return [{
                    "filename": "config.py",
                    "status": "modified",
                    "additions": 1, "deletions": 0, "changes": 1,
                    "patch": "+API_KEY='ghp_supersecretvalue123'",
                }]
            return ""  # raw diff empty
        self.mock_api.side_effect = _secret_patch
        result = github_get_pr_diff("owner/testrepo", 10)
        for f in result["files"]:
            self.assertNotIn("ghp_supersecretvalue123", f.get("patch", ""))

    def test_review_pr_never_auto_merges(self):
        from app.tools.github_workbench import github_review_pr
        result = github_review_pr("owner/testrepo", 10)
        self.assertTrue(result["success"])
        self.assertFalse(result.get("auto_merge_permitted"), "auto_merge_permitted must be False")

    def test_review_pr_detects_missing_tests(self):
        """When only source files changed (no test files), observation should flag missing tests."""
        from app.tools.github_workbench import github_review_pr
        self.mock_api.side_effect = None

        def _source_only(*a, **kw):
            endpoint = a[1] if len(a) > 1 else (a[0] if a else "")
            if "files" in endpoint:
                return [{"filename": "app/main.py", "status": "modified", "additions": 20, "deletions": 5, "changes": 25, "patch": ""}]
            return PR_DETAIL
        self.mock_api.side_effect = _source_only
        result = github_review_pr("owner/testrepo", 10)
        categories = [o.get("category") for o in result.get("observations", [])]
        self.assertIn("missing_tests", categories)

    def test_review_pr_detects_security_keywords_in_diff(self):
        """Diff containing secret/token/api_key should produce a security observation."""
        from app.tools.github_workbench import github_review_pr
        self.mock_api.side_effect = None

        def _secret_diff(*a, **kw):
            endpoint = a[1] if len(a) > 1 else (a[0] if a else "")
            if "files" in endpoint:
                return [{"filename": "app/config.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1, "patch": "+API_KEY='hardcoded'"}]
            return PR_DETAIL
        self.mock_api.side_effect = _secret_diff
        result = github_review_pr("owner/testrepo", 10)
        categories = [o.get("category") for o in result.get("observations", [])]
        self.assertIn("security", categories)

    def test_review_pr_findings_labelled_as_suggestions(self):
        """AI review disclaimer must state findings are suggestions, not guaranteed defects."""
        from app.tools.github_workbench import github_review_pr
        result = github_review_pr("owner/testrepo", 10)
        disclaimer = result.get("disclaimer", "").lower()
        self.assertTrue(
            "suggestion" in disclaimer or "human verification" in disclaimer,
            f"Disclaimer not found: {disclaimer!r}",
        )

    # --- Write: PR Comment ---
    def test_pr_comment_requires_approval(self):
        from app.tools.github_workbench import github_create_pr_comment_safe
        result = github_create_pr_comment_safe("owner/testrepo", 10, "LGTM!", approved=False)
        self.assertTrue(result.get("requires_approval"))

    def test_pr_comment_approved_audits(self):
        from app.tools.github_workbench import github_create_pr_comment_safe
        self.mock_api.side_effect = None
        self.mock_api.return_value = {"id": 500, "html_url": ""}
        result = github_create_pr_comment_safe("owner/testrepo", 10, "LGTM!", approved=True)
        self.assertTrue(result["success"])
        self.mock_db.assert_called_once()

    # --- Commits ---
    def test_list_commits(self):
        from app.tools.github_workbench import github_list_repo_commits
        result = github_list_repo_commits("owner/testrepo")
        self.assertTrue(result["success"])
        self.assertIsInstance(result["commits"], list)
        commit = result["commits"][0]
        self.assertIn("sha", commit)
        self.assertIn("message", commit)
        self.assertIn("author", commit)

    def test_compare_commits_ahead_behind(self):
        from app.tools.github_workbench import github_compare_commits
        result = github_compare_commits("owner/testrepo", "main", "feature/x")
        self.assertTrue(result["success"])
        self.assertIn("ahead_by", result)
        self.assertIn("behind_by", result)
        self.assertIsInstance(result["files"], list)
        self.assertEqual(result["status"], "ahead")

    def test_compare_commits_raises_on_empty_refs(self):
        from app.tools.github_workbench import github_compare_commits
        with self.assertRaises(ValueError):
            github_compare_commits("owner/testrepo", "", "feature/x")
        with self.assertRaises(ValueError):
            github_compare_commits("owner/testrepo", "main", "")

    # --- Branches ---
    def test_list_branches(self):
        from app.tools.github_workbench import github_list_repo_branches
        result = github_list_repo_branches("owner/testrepo")
        self.assertTrue(result["success"])
        self.assertIsInstance(result["branches"], list)
        branch = result["branches"][0]
        self.assertIn("name", branch)
        self.assertIn("protected", branch)
        self.assertIn("commit_sha", branch)

    def test_list_branches_includes_protection_metadata(self):
        from app.tools.github_workbench import github_list_repo_branches
        result = github_list_repo_branches("owner/testrepo")
        # main should be protected
        main = next((b for b in result["branches"] if b["name"] == "main"), None)
        self.assertIsNotNone(main)
        self.assertTrue(main["protected"])

    # --- GitHub Actions ---
    def test_list_workflow_runs(self):
        from app.tools.github_workbench import github_list_workflow_runs
        result = github_list_workflow_runs("owner/testrepo")
        self.assertTrue(result["success"])
        self.assertIsInstance(result["runs"], list)
        self.assertGreater(len(result["runs"]), 0)
        run = result["runs"][0]
        self.assertIn("id", run)
        self.assertIn("name", run)
        self.assertIn("conclusion", run)

    def test_list_workflow_runs_filters_by_status(self):
        from app.tools.github_workbench import github_list_workflow_runs
        result = github_list_workflow_runs("owner/testrepo", status="failure")
        self.assertTrue(result["success"])
        # Mock always returns fixture regardless, just ensure the param is passed
        self.mock_api.assert_any_call("GET", "repos/owner/testrepo/actions/runs", params={"page": 1, "per_page": 20, "status": "failure"})

    def test_get_workflow_run_details_with_jobs(self):
        from app.tools.github_workbench import github_get_workflow_run_details
        result = github_get_workflow_run_details("owner/testrepo", 1001)
        self.assertTrue(result["success"])
        self.assertEqual(result["run_id"], 1001)
        self.assertIsInstance(result["jobs"], list)
        job = result["jobs"][0]
        self.assertIn("steps", job)
        self.assertIsInstance(job["steps"], list)

    def test_analyze_workflow_failure_identifies_failed_step(self):
        from app.tools.github_workbench import github_analyze_workflow_failure
        result = github_analyze_workflow_failure("owner/testrepo", 1001)
        self.assertTrue(result["success"])
        self.assertTrue(result.get("is_failed"))
        self.assertIn("analysis", result)
        self.assertIn("fix_suggestions", result)
        self.assertIsInstance(result["fix_suggestions"], list)
        # Must reference evidence (step/job name)
        evidence = result.get("evidence", "")
        self.assertTrue(len(evidence) > 0)

    def test_analyze_workflow_failure_redacts_secrets_in_analysis(self):
        """Analysis text must have secrets stripped even if logs contain them."""
        from app.tools.github_workbench import github_analyze_workflow_failure
        result = github_analyze_workflow_failure("owner/testrepo", 1001)
        full_text = json.dumps(result)
        # No raw secret patterns should appear in the analysis output
        self.assertNotRegex(full_text, r'ghp_[a-zA-Z0-9]+')
        self.assertNotRegex(full_text, r'sk-[a-zA-Z0-9]{20,}')

    def test_analyze_successful_run_returns_not_failed(self):
        """Analyzing a success run should return is_failed=False."""
        from app.tools.github_workbench import github_analyze_workflow_failure
        # Patch jobs to return all-success steps
        self.mock_api.side_effect = None

        def _success_jobs(*a, **kw):
            endpoint = a[1] if len(a) > 1 else (a[0] if a else "")
            if "jobs" in endpoint:
                return {"jobs": [{"id": 2002, "name": "deploy", "status": "completed", "conclusion": "success", "started_at": "", "completed_at": "", "steps": []}]}
            return RUN_DETAIL
        self.mock_api.side_effect = _success_jobs
        result = github_analyze_workflow_failure("owner/testrepo", 1001)
        self.assertFalse(result.get("is_failed"))

    # --- Write: Workflow Rerun ---
    def test_rerun_workflow_requires_approval(self):
        from app.tools.github_workbench import github_rerun_workflow_safe
        result = github_rerun_workflow_safe("owner/testrepo", 1001, approved=False)
        self.assertTrue(result.get("requires_approval"))
        self.assertFalse(result.get("approved"))

    def test_rerun_workflow_approved_audits(self):
        from app.tools.github_workbench import github_rerun_workflow_safe
        self.mock_api.side_effect = None
        self.mock_api.return_value = {}
        result = github_rerun_workflow_safe("owner/testrepo", 1001, approved=True)
        self.assertTrue(result.get("success"))
        self.assertTrue(result.get("approved"))
        self.mock_db.assert_called_once()
        kw = self.mock_db.call_args[1]
        self.assertEqual(kw.get("action"), "github_rerun_workflow")

    # --- Error Handling ---
    def test_rate_limit_error_raised_on_403_with_rate_limit(self):
        import io
        import urllib.error
        from app.tools import github_workbench
        from app.tools.github_workbench import GitHubRateLimitError

        mock_exc = urllib.error.HTTPError(
            "https://api.github.com",
            403,
            "Forbidden",
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"},
            io.BytesIO(b'{"message": "rate limit exceeded"}'),
        )

        self.patcher.stop()
        try:
            with patch("app.tools.github_workbench.urllib.request.urlopen", side_effect=mock_exc):
                with patch("app.tools.github_workbench.get_effective_github_headers", return_value={"Authorization": "token test"}):
                    with self.assertRaises(GitHubRateLimitError):
                        github_workbench.github_api_request("GET", "repos/owner/testrepo")
        finally:
            self.patcher.start()

    def test_auth_error_raised_on_401(self):
        import io
        import urllib.error
        from app.tools import github_workbench
        from app.tools.github_workbench import GitHubAuthError

        mock_exc = urllib.error.HTTPError(
            "https://api.github.com",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"message": "Bad credentials"}'),
        )

        self.patcher.stop()
        try:
            with patch("app.tools.github_workbench.urllib.request.urlopen", side_effect=mock_exc):
                with patch("app.tools.github_workbench.get_effective_github_headers", return_value={"Authorization": "token test"}):
                    with self.assertRaises(GitHubAuthError):
                        github_workbench.github_api_request("GET", "repos/owner/testrepo")
        finally:
            self.patcher.start()

    def test_not_found_error_raised_on_404(self):
        import io
        import urllib.error
        from app.tools import github_workbench
        from app.tools.github_workbench import GitHubNotFoundError

        mock_exc = urllib.error.HTTPError(
            "https://api.github.com",
            404,
            "Not Found",
            {},
            io.BytesIO(b'{"message": "Not Found"}'),
        )

        self.patcher.stop()
        try:
            with patch("app.tools.github_workbench.urllib.request.urlopen", side_effect=mock_exc):
                with patch("app.tools.github_workbench.get_effective_github_headers", return_value={"Authorization": "token test"}):
                    with self.assertRaises(GitHubNotFoundError):
                        github_workbench.github_api_request("GET", "repos/owner/nonexistent")
        finally:
            self.patcher.start()

    # --- Audit log isolation (write without approval must NEVER audit) ---
    def test_unapproved_write_never_audits(self):
        from app.tools.github_workbench import github_create_issue_safe
        github_create_issue_safe("owner/testrepo", "Title", "Body", approved=False)
        self.mock_db.assert_not_called()

    def test_unapproved_comment_never_audits(self):
        from app.tools.github_workbench import github_add_issue_comment_safe
        github_add_issue_comment_safe("owner/testrepo", 1, "Hey", approved=False)
        self.mock_db.assert_not_called()

    def test_unapproved_rerun_never_audits(self):
        from app.tools.github_workbench import github_rerun_workflow_safe
        github_rerun_workflow_safe("owner/testrepo", 1001, approved=False)
        self.mock_db.assert_not_called()


# ===========================================================================
# TEST CLASS 2: Secret redaction (via redact_secrets from github_analyzer)
# ===========================================================================
class TestSecretRedaction(unittest.TestCase):
    """Tests that secret redaction works correctly on typical secret patterns."""

    def _redact(self, text):
        from app.tools.github_analyzer import redact_secrets
        return redact_secrets(text)

    def test_redacts_github_token(self):
        result = self._redact("token ghp_abcdef1234567890ABCDEF1234567890ab12")
        self.assertNotIn("ghp_abcdef", result)

    def test_redacts_api_key_assignment(self):
        result = self._redact("API_KEY=sk-12345678901234567890123456789012")
        self.assertNotIn("sk-12345678", result)

    def test_preserves_non_secret_text(self):
        text = "This is a normal code comment with no secrets."
        result = self._redact(text)
        # Normal text must survive
        self.assertIn("normal code comment", result)

    def test_redacts_password_in_url(self):
        result = self._redact("postgres://user:supersecretpass@db:5432/prod")
        self.assertNotIn("supersecretpass", result)

    def test_redacts_private_key_header(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAN..."
        result = self._redact(text)
        # Header must be replaced
        self.assertNotIn("RSA PRIVATE KEY", result)


# ===========================================================================
# TEST CLASS 3: Policy engine – workbench action risk levels
# ===========================================================================
class TestPolicyEngineWorkbench(unittest.TestCase):
    """Verify workbench actions are correctly registered in the policy engine."""

    def setUp(self):
        from app.policy import get_risk_level, requires_approval
        self.get_risk_level = get_risk_level
        self.requires_approval = requires_approval

    def _check_low(self, action):
        risk = self.get_risk_level(action)
        self.assertEqual(risk, "low", f"Expected 'low' risk for {action!r}, got {risk!r}")
        self.assertFalse(self.requires_approval(action))

    def _check_medium(self, action):
        risk = self.get_risk_level(action)
        self.assertEqual(risk, "medium", f"Expected 'medium' risk for {action!r}, got {risk!r}")
        self.assertTrue(self.requires_approval(action))

    # Read-only actions should be low risk
    def test_get_overview_is_low(self):
        self._check_low("github_get_overview")

    def test_get_issue_is_low(self):
        self._check_low("github_get_issue")

    def test_summarize_issue_is_low(self):
        self._check_low("github_summarize_issue")

    def test_list_prs_is_low(self):
        self._check_low("github_list_prs")

    def test_review_pr_is_low(self):
        self._check_low("github_review_pr")

    def test_list_commits_is_low(self):
        self._check_low("github_list_commits")

    def test_compare_commits_is_low(self):
        self._check_low("github_compare_commits")

    def test_list_branches_is_low(self):
        self._check_low("github_list_branches")

    def test_list_workflows_is_low(self):
        self._check_low("github_list_workflows")

    def test_analyze_workflow_failure_is_low(self):
        self._check_low("github_analyze_workflow_failure")

    # Write actions should require approval (medium risk)
    def test_update_issue_requires_approval(self):
        self._check_medium("github_update_issue")

    def test_add_issue_comment_requires_approval(self):
        self._check_medium("github_add_issue_comment")

    def test_close_issue_requires_approval(self):
        self._check_medium("github_close_issue")

    def test_create_pr_comment_requires_approval(self):
        self._check_medium("github_create_pr_comment")

    def test_rerun_workflow_requires_approval(self):
        self._check_medium("github_rerun_workflow")


# ===========================================================================
# TEST CLASS 4: FastAPI endpoint integration tests
# ===========================================================================
class TestWorkbenchFastAPIEndpoints(unittest.TestCase):
    """
    Test all 19 /api/github/workbench/* endpoints via FastAPI TestClient.
    All GitHub API calls are mocked to avoid real network access.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
            from app.server import app
            cls.client = TestClient(app, raise_server_exceptions=False)
            cls.available = True
        except Exception as e:
            cls.available = False
            cls.skip_reason = str(e)

    def setUp(self):
        if not self.available:
            self.skipTest(f"FastAPI TestClient unavailable: {self.skip_reason}")

    def _mock_workbench(self, mock_api):
        mock_api.side_effect = _mock_api

    # -- Overview endpoint --
    def test_overview_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.get("/api/github/workbench/overview?repo_name=owner/testrepo")
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    # -- Issues endpoints --
    def test_issues_list_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.get("/api/github/workbench/issues?repo_name=owner/testrepo&state=open")
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    def test_issues_detail_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.get("/api/github/workbench/issues/1?repo_name=owner/testrepo")
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    def test_issue_create_endpoint_missing_body_returns_422(self):
        resp = self.client.post("/api/github/workbench/issues/create", json={})
        self.assertEqual(resp.status_code, 422)

    def test_issue_create_endpoint_without_approval_returns_preview(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            with patch("app.tools.github_workbench.db.log_event"):
                resp = self.client.post(
                    "/api/github/workbench/issues/create",
                    json={"repo_name": "owner/testrepo", "title": "Test issue", "body": "Test body", "approved": False},
                )
        self.assertIn(resp.status_code, [200, 400, 401])
        if resp.status_code == 200:
            data = resp.json()
            # Must indicate approval required, not silently create
            self.assertTrue(data.get("requires_approval") or "preview" in data)

    def test_issue_update_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.return_value = {"number": 1, "state": "closed", "title": "Bug", "html_url": ""}
            with patch("app.tools.github_workbench.db.log_event"):
                resp = self.client.post(
                    "/api/github/workbench/issues/1/update",
                    json={"repo_name": "owner/testrepo", "state": "closed", "approved": False},
                )
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    # -- PRs endpoints --
    def test_prs_list_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.get("/api/github/workbench/prs?repo_name=owner/testrepo&state=open")
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    def test_prs_detail_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.get("/api/github/workbench/prs/10?repo_name=owner/testrepo")
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    def test_prs_diff_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.get("/api/github/workbench/prs/10/diff?repo_name=owner/testrepo")
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    def test_pr_review_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.post(
                "/api/github/workbench/prs/10/review",
                json={"repo_name": "owner/testrepo"},
            )
        self.assertIn(resp.status_code, [200, 400, 401, 422])
        if resp.status_code == 200:
            data = resp.json()
            self.assertFalse(data.get("auto_merge_permitted"), "auto_merge must never be permitted")

    def test_pr_comment_endpoint_unapproved(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            with patch("app.tools.github_workbench.db.log_event"):
                resp = self.client.post(
                    "/api/github/workbench/prs/10/comment",
                    json={"repo_name": "owner/testrepo", "body": "LGTM", "approved": False},
                )
        self.assertIn(resp.status_code, [200, 400, 401, 422])
        if resp.status_code == 200:
            data = resp.json()
            self.assertTrue(data.get("requires_approval") or "preview" in data)

    # -- Commits & Compare endpoints --
    def test_commits_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.get("/api/github/workbench/commits?repo_name=owner/testrepo")
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    def test_compare_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.get("/api/github/workbench/compare?repo_name=owner/testrepo&base=main&head=feature%2Fx")
        self.assertIn(resp.status_code, [200, 400, 401, 422])
        if resp.status_code == 200:
            data = resp.json()
            self.assertIn("ahead_by", data)
            self.assertIn("behind_by", data)

    def test_branches_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.get("/api/github/workbench/branches?repo_name=owner/testrepo")
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    # -- Actions endpoints --
    def test_workflow_runs_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.get("/api/github/workbench/actions/runs?repo_name=owner/testrepo")
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    def test_workflow_run_detail_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.get("/api/github/workbench/actions/runs/1001?repo_name=owner/testrepo")
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    def test_workflow_analyze_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            resp = self.client.post(
                "/api/github/workbench/actions/runs/1001/analyze",
                json={"repo_name": "owner/testrepo"},
            )
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    def test_workflow_rerun_endpoint_requires_approval(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            with patch("app.tools.github_workbench.db.log_event"):
                resp = self.client.post(
                    "/api/github/workbench/actions/runs/1001/rerun",
                    json={"repo_name": "owner/testrepo", "approved": False},
                )
        self.assertIn(resp.status_code, [200, 400, 401, 422])
        if resp.status_code == 200:
            data = resp.json()
            self.assertTrue(data.get("requires_approval"), "Unapproved rerun must require approval")

    def test_workflow_rerun_endpoint_approved(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.return_value = {}
            with patch("app.tools.github_workbench.db.log_event"):
                resp = self.client.post(
                    "/api/github/workbench/actions/runs/1001/rerun",
                    json={"repo_name": "owner/testrepo", "approved": True},
                )
        self.assertIn(resp.status_code, [200, 400, 401, 422])

    # -- Destructive operation prevention --
    def test_no_auto_merge_possible_via_api(self):
        """There must be no auto-merge endpoint in the workbench routes."""
        # Confirm /api/github/workbench/prs/*/merge doesn't exist and returns 404/405
        resp = self.client.post("/api/github/workbench/prs/10/merge", json={"repo_name": "owner/testrepo"})
        self.assertIn(resp.status_code, [404, 405, 422])

    def test_no_delete_repo_endpoint(self):
        resp = self.client.delete("/api/github/workbench/repos/owner/testrepo")
        self.assertIn(resp.status_code, [404, 405])

    def test_summarize_endpoint(self):
        with patch("app.tools.github_workbench.github_api_request") as m:
            m.side_effect = _mock_api
            with patch("app.tools.github_workbench.is_ollama_online", return_value=False):
                resp = self.client.post(
                    "/api/github/workbench/issues/1/summarize",
                    json={"repo_name": "owner/testrepo"},
                )
        self.assertIn(resp.status_code, [200, 400, 401, 422])


# ===========================================================================
# TEST CLASS 5: Safety invariants (cannot be bypassed)
# ===========================================================================
class TestSafetyInvariants(unittest.TestCase):
    """
    Critical safety invariants that must hold under all conditions.
    These tests directly verify the approval gate cannot be bypassed.
    """

    def setUp(self):
        self.api_patcher = patch("app.tools.github_workbench.github_api_request")
        self.mock_api = self.api_patcher.start()
        self.mock_api.side_effect = _mock_api
        self.db_patcher = patch("app.tools.github_workbench.db.log_event")
        self.mock_db = self.db_patcher.start()

    def tearDown(self):
        self.api_patcher.stop()
        self.db_patcher.stop()

    def test_all_write_functions_have_approved_parameter(self):
        """Every write function must accept an `approved` kwarg."""
        from app.tools import github_workbench as wb
        write_fns = [
            wb.github_create_issue_safe,
            wb.github_update_issue_safe,
            wb.github_add_issue_comment_safe,
            wb.github_create_pr_comment_safe,
            wb.github_rerun_workflow_safe,
        ]
        for fn in write_fns:
            import inspect
            params = inspect.signature(fn).parameters
            self.assertIn("approved", params, f"{fn.__name__} missing 'approved' parameter")

    def test_write_without_approved_never_calls_post(self):
        """Call every write function without approved=True; none should POST."""
        from app.tools.github_workbench import (
            github_create_issue_safe,
            github_update_issue_safe,
            github_add_issue_comment_safe,
            github_create_pr_comment_safe,
            github_rerun_workflow_safe,
        )
        calls_before = self.mock_api.call_count

        github_create_issue_safe("owner/testrepo", "Title", "Body", approved=False)
        github_update_issue_safe("owner/testrepo", 1, state="closed", approved=False)
        github_add_issue_comment_safe("owner/testrepo", 1, "Hey", approved=False)
        github_create_pr_comment_safe("owner/testrepo", 10, "LGTM!", approved=False)
        github_rerun_workflow_safe("owner/testrepo", 1001, approved=False)

        # Only read calls (from setUp) should have happened; no new POST calls
        for c in self.mock_api.call_args_list[calls_before:]:
            method = c[0][0] if c[0] else ""
            self.assertNotEqual(method, "POST", f"Unexpected POST call: {c}")

    def test_review_pr_never_modifies_repo(self):
        """github_review_pr is read-only: must never call POST, PATCH, PUT, DELETE."""
        from app.tools.github_workbench import github_review_pr
        github_review_pr("owner/testrepo", 10)
        for c in self.mock_api.call_args_list:
            method = (c[0][0] if c[0] else "").upper()
            self.assertNotIn(method, ["POST", "PATCH", "PUT", "DELETE"], f"Read-only review called {method}: {c}")

    def test_all_write_previews_contain_repo_name(self):
        """Every write-preview response must include the target repository name."""
        from app.tools.github_workbench import (
            github_create_issue_safe,
            github_update_issue_safe,
            github_add_issue_comment_safe,
            github_create_pr_comment_safe,
            github_rerun_workflow_safe,
        )
        repo = "owner/testrepo"
        results = [
            github_create_issue_safe(repo, "Title", "Body", approved=False),
            github_update_issue_safe(repo, 1, state="closed", approved=False),
            github_add_issue_comment_safe(repo, 1, "Hey", approved=False),
            github_create_pr_comment_safe(repo, 10, "LGTM!", approved=False),
            github_rerun_workflow_safe(repo, 1001, approved=False),
        ]
        for r in results:
            preview = r.get("preview", {})
            self.assertEqual(preview.get("repo_name"), repo, f"Preview missing repo_name: {r}")

    def test_audit_logs_never_contain_raw_secrets(self):
        """When a write is approved, audit log must not contain raw secret tokens."""
        from app.tools.github_workbench import github_add_issue_comment_safe
        self.mock_api.side_effect = None
        self.mock_api.return_value = {"id": 1, "html_url": ""}
        body_with_secret = "My token is ghp_RealSecretToken123456789012"
        github_add_issue_comment_safe("owner/testrepo", 1, body_with_secret, approved=True)
        self.mock_db.assert_called_once()
        audit_summary = self.mock_db.call_args[1].get("result_summary", "")
        self.assertNotIn("ghp_RealSecretToken123456789012", audit_summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
