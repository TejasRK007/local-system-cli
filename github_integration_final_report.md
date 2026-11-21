# Milestone 9 — GitHub AI Intelligence & Repository Chat Final Report

## 1. Executive Summary
This milestone completes the **AI Repository Intelligence & Grounded Repository Chat (Prompts 1, 2, and 3)** for the Local Agentic Automation System on the `m9` branch.

Building on Prompt 1 (OAuth authentication, repository management, tracking) and Prompt 2 (evidence-grounded static intelligence and 6-panel technical reports), Prompt 3 delivers an interactive, grounded **AI Repository Chat** interface:
- **Evidence-Grounded RAG Engine**: Indexes eligible repository source and text files into an isolated SQLite FTS5 full-text search index with exact line-range metadata and overlapping chunking.
- **Strict Anti-Hallucination & Grounding**: The AI assistant answers questions strictly using retrieved code chunks and metadata. If evidence is insufficient, it states so honestly. Cites exact file paths, line ranges, and short code excerpts.
- **Zero Arbitrary Code Execution**: Never executes repository scripts, test runners, or binaries.
- **Complete Repository & Commit Isolation**: Code chunks and chat histories are strictly segregated by `(repo_name, commit_sha)`. Queries never leak data across different repositories or stale commits.
- **Stale Commit SHA Detection**: Detects if the remote repository has newer commits on GitHub than the indexed commit SHA, alerting the user and offering one-click re-analysis.
- **Privacy Gating & Secret Redaction**: Secrets (GitHub tokens, AWS keys, API credentials, passwords) are purged before chunking, indexing, and model context. Local Ollama (`qwen2.5:3b`) execution is preferred. If cloud processing is disabled, source code remains local; a deterministic code-search synthesis engine provides full offline functionality.
- **Interactive UI**: Added top subnav switcher in AI Manager > GitHub ("Repositories & Intelligence" vs "Repository Chat"), repository selector, session management ("New Chat", "Clear History"), clickable citations, quick prompt chips, and instant "💬 Chat" shortcuts from repository cards and analysis views.

---

## 2. Changed & Created Files

| File | Type | Description |
|---|---|---|
| `app/tools/github_chat.py` | New | SQLite FTS5 schema & indexing, line-based chunking with 1-indexed line metadata, secret redaction, BM25 full-text retrieval, stale commit SHA detection, grounded Q&A execution, and session/message persistence. |
| `app/tools/github_analyzer.py` | New | Static analysis engine: safe ZIP extraction, file tree discovery, manifest parsing, entry point/test discovery, instruction extraction, maintainability observations, and grounded architecture reporting. |
| `app/tools/github_tools.py` | Modified | Integrated text indexing into repo analysis, hooked chat tables into database initialization, updated analysis storage. |
| `app/tools/__init__.py` | Modified | Re-exported `clear_chat_history`, `create_chat_session`, `execute_repository_chat`, `get_chat_history`, and `list_analyzed_repos_for_chat`. |
| `app/server.py` | Modified | Added 5 REST API routes under `/api/github/chat/*` for repository listing, code chat Q&A, chat history, clearing, and new session creation. Direct stdlib multipart boundary parsing for ZIP uploads. |
| `app/policy.py` | Modified | Registered `github_repo_chat` and `github_clear_chat` as `low` risk operations in `_ACTION_RISK_MAP`. |
| `app/ui/index.html` | Modified | Added GitHub subnav bar ("Repositories & Intelligence" vs "Repository Chat"), Chat header with repo dropdown, commit badge, stale warning banner, chat stream, suggested prompt chips, input area, and "💬 Chat with Code" action button in analysis view. |
| `app/ui/index.css` | Modified | Added styling for subnav tabs, chat container, bubbles, collapsible citation cards with code excerpts, prompt chips, inline loaders, and stale warning banners. |
| `app/ui/app.js` | Modified | Added `initGithubChat()`, subnav switching, repo selection, optimistic message rendering, citation expanders, suggested prompt clicks, re-analyze triggers, and card quick chat buttons. |
| `tests/test_github_chat.py` | New | Comprehensive automated test suite for chat chunking, FTS5 retrieval, repo/commit isolation, citations, insufficient evidence, stale warning, history clearing, privacy gating, and REST APIs (13 tests). |
| `tests/test_github_analyzer.py` | New | Static analyzer test suite covering discovery, redactions, ZIP security, manifest parsing, observations, privacy gating, and REST APIs (19 tests). |
| `tests/test_github_integration.py` | Existing | OAuth, account management, and repository tracking test suite (20 tests). |

---

## 3. Architecture & RAG Pipeline

```
[Connected GitHub Repo] OR [Uploaded ZIP Snapshot]
         │
         ▼
  [Safe File Discovery] (skips .git, node_modules, binaries, >500KB)
         │
         ▼
  [Secret Redaction] (replaces tokens, keys, passwords with [REDACTED])
         │
         ▼
  [Chunking Engine] (60 lines per chunk, 15 lines overlap, 1-indexed lines)
         │
         ▼
  [SQLite FTS5 Code Index] (github_repo_file_chunks + github_repo_chunks_fts)
         │
         ▼
[User Question] ──► [Hybrid Retrieval] (exact paths + FTS5 BM25 match + LIKE fallback)
         │
         ▼
  [Prompt Synthesis] (Persona with strict grounding & non-fabrication rules)
         │
  ┌──────┴────────────────────────────────────────────────┐
  │ Local Ollama? ──► YES: Invoke Ollama (qwen2.5:3b)    │
  │ Cloud Consented? ──► YES: Invoke Groq (llama-3.3)    │
  │ Disallowed/Offline? ──► Deterministic Code Synthesis  │
  └───────────────────────────────────────────────────────┘
         │
         ▼
[Grounded Answer] + [Citations: path, line range, code excerpt]
         │
         ▼
[Persisted in Session History] (Scoped to user & repository)
```

---

## 4. Database Schema

### 1. `github_repo_file_chunks` & `github_repo_chunks_fts` (FTS5)
```sql
CREATE TABLE IF NOT EXISTS github_repo_file_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER,
    repo_name TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    content TEXT NOT NULL,
    language TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_repo_chunks_lookup ON github_repo_file_chunks(repo_name, commit_sha);
CREATE INDEX IF NOT EXISTS idx_repo_chunks_repo_id ON github_repo_file_chunks(repo_id);

CREATE VIRTUAL TABLE IF NOT EXISTS github_repo_chunks_fts USING fts5(
    content,
    file_path,
    content='github_repo_file_chunks',
    content_rowid='id',
    tokenize = 'unicode61'
);
```

### 2. `github_repo_chat_sessions` & `github_repo_chat_messages`
```sql
CREATE TABLE IF NOT EXISTS github_repo_chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER,
    repo_name TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_repo ON github_repo_chat_sessions(repo_name);

CREATE TABLE IF NOT EXISTS github_repo_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources_json TEXT,
    commit_sha TEXT NOT NULL,
    is_stale INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES github_repo_chat_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON github_repo_chat_messages(session_id);
```

---

## 5. REST API Endpoints

### 1. `GET /api/github/chat/repos`
- **Description**: Returns all analyzed and indexed repositories available for chat, including index status and chunk counts.
- **Response**:
  ```json
  {
    "success": true,
    "count": 2,
    "repositories": [
      {
        "analysis_id": 1,
        "repo_id": 1,
        "repo_name": "octocat/Hello-World",
        "commit_sha": "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d",
        "summary": "Sample repository",
        "frameworks": [],
        "chunks_count": 14,
        "is_indexed": true
      }
    ]
  }
  ```

### 2. `POST /api/github/chat/query`
- **Description**: Answers a natural language question about the repository codebase using retrieved FTS5 chunks.
- **Request Body**:
  ```json
  {
    "repo_name": "octocat/Hello-World",
    "commit_sha": "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d",
    "message": "Where is the main entry point defined?",
    "session_id": null
  }
  ```
- **Response**:
  ```json
  {
    "success": true,
    "session_id": 1,
    "repo_name": "octocat/Hello-World",
    "commit_sha": "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d",
    "answer": "The main entry point is defined in `main.py`...",
    "sources": [
      {
        "file_path": "main.py",
        "start_line": 1,
        "end_line": 25,
        "excerpt": "def main():\n    print('Hello world')",
        "code_snippet": "def main():\n    print('Hello world')"
      }
    ],
    "warning": null,
    "is_stale": false,
    "llm_provider": "ollama",
    "timestamp": "2026-11-14 15:00:00"
  }
  ```

### 3. `GET /api/github/chat/history`
- **Description**: Retrieves persistent chat messages scoped strictly to `repo_name` and optional `session_id`.
- **Query Params**: `repo_name` (required), `session_id` (optional), `limit` (optional, default 50)

### 4. `POST /api/github/chat/clear`
- **Description**: Clears persistent chat messages for a repository or specific session.
- **Request Body**:
  ```json
  { "repo_name": "octocat/Hello-World", "session_id": null }
  ```

### 5. `POST /api/github/chat/new`
- **Description**: Creates a new scoped chat session for a repository.
- **Request Body**:
  ```json
  { "repo_name": "octocat/Hello-World", "commit_sha": "7fd1a60b", "title": "New Chat" }
  ```

---

## 6. Test Suite Results

### A. Repository Chat Test Suite (`tests/test_github_chat.py`)
- `test_chunk_text_content_metadata`: PASSED
- `test_chunk_text_redacts_secrets_prior_to_chunking`: PASSED
- `test_index_repository_text_files_and_exclusions`: PASSED
- `test_repository_and_commit_isolation`: PASSED
- `test_retrieval_citations_formatting`: PASSED
- `test_insufficient_evidence_honest_fallback`: PASSED
- `test_check_repository_stale`: PASSED
- `test_chat_history_isolation_and_clearing`: PASSED
- `test_create_new_chat_session`: PASSED
- `test_privacy_gating_blocks_cloud_when_disallowed`: PASSED
- `test_mocked_llm_failure_graceful_fallback`: PASSED
- `test_list_analyzed_repos_for_chat`: PASSED
- `test_api_github_chat_endpoints`: PASSED

### B. Full GitHub Test Suite Summary
- `tests/test_github_chat.py`: **13/13 PASSED**
- `tests/test_github_analyzer.py`: **19/19 PASSED**
- `tests/test_github_integration.py`: **20/20 PASSED**
- **Combined GitHub Suite**: **52/52 PASSED** (0 failures, 0 regressions)

### C. System Regression Test Suite
- `test_policy.py`, `test_tasks.py`, `test_filesystem.py`, `test_google_oauth.py`, `test_email_intelligence.py`: **76/76 PASSED** (0 regressions)
- **Flake8 Linter**: **0 warnings / 0 errors** across all modified files.

---

## 7. Manual Verification Walkthrough

### 1. Navigating to Repository Chat
1. Open the AI Manager dashboard in your browser (`http://localhost:8000/#tab-github`).
2. Notice the new subnavigation bar at the top of the GitHub pane:
   - **📦 Repositories & Intelligence**: Browse connected repos, upload archives, and review technical reports.
   - **💬 Repository Chat (AI RAG)**: Code Q&A grounded in source files.
3. Alternatively, click **💬 Chat** on any repository card in the grid to jump directly into chat with that repository pre-selected.

### 2. Asking Codebase Questions
1. In the **Repository** dropdown, select an analyzed repository (e.g. `pallets/flask` or an uploaded ZIP snapshot).
2. The UI renders the indexed commit SHA badge and indexed chunk counter.
3. Click one of the quick prompt chips (e.g. *"Explain overall architecture"*, *"Where is authentication implemented?"*, or *"Where are tests located?"*).
4. The assistant responds with a grounded answer citing exact file paths and line ranges.
5. Expand the **📎 Sources / Citations** card at the bottom of the message to inspect the exact file path, line numbers (`app/main.py:L12-L35`), and supporting code excerpt.

### 3. Testing Stale Commit Detection
1. If new commits are pushed to GitHub after indexing, querying the repository displays the amber **⚠️ Repository Out of Date** banner.
2. Click **⚡ Re-analyze Now** in the banner to update the repository snapshot and refresh the FTS5 index.

### 4. Session & History Management
1. Click **＋ New Chat** in the chat header to start a fresh thread.
2. Click **🗑 Clear History** to purge past messages for the selected repository.
3. Switch between different repositories in the dropdown; confirm that conversations remain strictly isolated to each repository.

---

# Milestone 9 — GitHub Prompt 4: Developer Workbench & Safe Automation Final Report

## 8. Developer Workbench & Safe Automation Overview

GitHub Prompt 4 extends the GitHub AI system into a complete **Developer Workbench** providing read-first repository intelligence and safe, approval-gated automation across Issues, Pull Requests, Commits, Branches, and GitHub Actions.

### Key Capabilities
- **Repository Overview**: At-a-glance health metrics, open issue/PR counts, active branch counts, recent commit feed, and workflow failure detection.
- **Issues Intelligence & Safe Actions**:
  - Filter/search by state (`open`/`closed`/`all`), labels, assignee, and text query.
  - Issue detail view with comment history and timelines.
  - AI investigation assistant synthesizing root causes, debugging steps, and potential duplicate suggestions (labeled strictly as suggestions for human verification).
  - Safe issue creation, editing, closing/reopening, and commenting with explicit preview and pre-write approval modal.
- **Pull Request Review & Diff Intelligence**:
  - Filter/list PRs, inspect changed files, and view color-coded unified diff previews.
  - Grounded AI code review analyzing bug risks, security patterns, performance, and missing test coverage.
  - Review findings explicitly labeled as suggestions for human review.
  - Guaranteed `auto_merge_permitted: False` invariant — zero auto-merging or auto-closing.
  - Safe commenting with exact diff/content preview and user confirmation.
- **Commits & Branches Intelligence**:
  - Recent commit history with author, relative timestamp, SHA, and commit message.
  - Two-way branch comparison (`base...head`) showing ahead/behind commit counts and changed files.
  - Protected branch metadata viewer; read-only operations with zero force-push or branch deletion capability.
- **GitHub Actions Failure Diagnostics & Safe Reruns**:
  - Filter workflow runs by conclusion and branch.
  - Step-by-step job execution tree identifying failed steps and run duration.
  - Secret-redacted log diagnostics explaining root failure causes with cited workflow lines and recommended fixes.
  - Safe workflow reruns gated by explicit user approval.
- **Global Safety & Audit Architecture**:
  - Integrated into the existing SQLite `audit_log` via `db.log_event()`.
  - Audits actor, action, repository, timestamp, and redacted outcome without ever persisting tokens or raw secrets.
  - Policy engine registration in `app/policy.py` (13 low-risk reads, 5 medium-risk approval-required writes).

---

## 9. Changed & Created Files

| File | Purpose |
|------|---------|
| `app/tools/github_workbench.py` | **New**: Core developer workbench service (1,215 lines) implementing all 19 workbench intelligence functions, custom exceptions (`GitHubRateLimitError`, `GitHubAuthError`, `GitHubNotFoundError`, `GitHubApprovalRequiredError`), audit logging, and strict write guards. |
| `app/server.py` | **Modified**: Added 19 REST API endpoints under `/api/github/workbench/*`, Pydantic request models, and error handling. |
| `app/policy.py` | **Modified**: Registered 15 workbench actions (reads mapped to `"low"`, writes mapped to `"medium"` requiring explicit approval). |
| `app/tools/__init__.py` | **Modified**: Re-exported all workbench functions. |
| `app/tools/github_analyzer.py` | **Modified**: Enhanced secret redaction patterns for short test tokens, JWTs, and multiline/header private key blocks. |
| `app/ui/index.html` | **Modified**: Expanded GitHub dashboard with global repository selector (`#github-global-repo-select`), 8-tab subnav, dedicated views for Overview, Issues, PRs, Commits & Branches, and Actions, plus safety approval modal (`#github-approval-modal`) and issue creation modal. |
| `app/ui/index.css` | **Modified**: Added styling for workbench item cards, badges (`success`, `danger`, `warn`), diff viewer chunk headers, observation items, and comment feeds. |
| `app/ui/app.js` | **Modified**: Added 23 interactive functions wiring all 8 subnav tabs, filters, modals, diff rendering, AI investigations, code reviews, and failure diagnostics. |
| `tests/test_github_workbench.py` | **New**: 96 unit, integration, policy, secret-redaction, and safety-invariant tests covering all workbench features and endpoints. |

---

## 10. REST API Endpoints (19 Endpoints)

| Method | Endpoint | Description | Risk / Approval |
|--------|----------|-------------|-----------------|
| `GET` | `/api/github/workbench/overview` | Repository summary, commit/PR/branch counts, workflow failures | Low (None) |
| `GET` | `/api/github/workbench/issues` | List & filter issues by state, label, assignee, text | Low (None) |
| `GET` | `/api/github/workbench/issues/{n}` | Issue details, timeline, comment history | Low (None) |
| `POST` | `/api/github/workbench/issues/{n}/summarize` | AI issue investigation summary & duplicate suggestions | Low (None) |
| `POST` | `/api/github/workbench/issues/create` | Create new issue (requires `approved=true`) | Medium (Approval Required) |
| `POST` | `/api/github/workbench/issues/{n}/update` | Update issue state/labels (requires `approved=true`) | Medium (Approval Required) |
| `POST` | `/api/github/workbench/issues/{n}/comment` | Add comment to issue (requires `approved=true`) | Medium (Approval Required) |
| `GET` | `/api/github/workbench/prs` | List & filter pull requests | Low (None) |
| `GET` | `/api/github/workbench/prs/{n}` | Pull request details, author, head/base branches | Low (None) |
| `GET` | `/api/github/workbench/prs/{n}/diff` | Changed files list and color-coded unified diff | Low (None) |
| `POST` | `/api/github/workbench/prs/{n}/review` | AI grounded PR review (bugs, security, tests) | Low (None) |
| `POST` | `/api/github/workbench/prs/{n}/comment` | Post review comment to PR (requires `approved=true`) | Medium (Approval Required) |
| `GET` | `/api/github/workbench/commits` | Recent commits with author, date, SHA, and message | Low (None) |
| `GET` | `/api/github/workbench/compare` | Compare two refs/branches (ahead/behind counts, files) | Low (None) |
| `GET` | `/api/github/workbench/branches` | List branches with protection status & latest commit SHA | Low (None) |
| `GET` | `/api/github/workbench/actions/runs` | List workflow runs with conclusion, branch, event | Low (None) |
| `GET` | `/api/github/workbench/actions/runs/{id}` | Run details, duration, job tree, and failed step details | Low (None) |
| `POST` | `/api/github/workbench/actions/runs/{id}/analyze` | AI failure analysis explaining cause and suggested fix | Low (None) |
| `POST` | `/api/github/workbench/actions/runs/{id}/rerun` | Safe rerun of failed workflow (requires `approved=true`) | Medium (Approval Required) |

---

## 11. Safety Guarantees & Invariants Enforced

1. **Read-First Philosophy**: All inspection, listing, filtering, diff viewer, and AI diagnostic operations are strictly read-only and require zero confirmation.
2. **Approval Gate for Every Write**: Every modifying operation (`create_issue`, `update_issue`, `add_issue_comment`, `create_pr_comment`, `rerun_workflow`) requires explicit `approved=True` parameter immediately before the API call. Calls without approval return a structured preview (`requires_approval=True`) with exact repo name, action, and payload, and never trigger API writes or audit records.
3. **Prohibited Destructive Operations**:
   - Zero automatic merges or approvals (`auto_merge_permitted: False`).
   - Zero repository deletion endpoints.
   - Zero branch deletion or force-push capabilities.
   - Zero permission or visibility modification operations.
4. **Secret Redaction**: All API error bodies, diff chunks, code comments, AI review prompts, and audit log summaries pass through `redact_secrets()`, ensuring raw GitHub PATs, OAuth tokens, AWS keys, Groq/OpenAI keys, and private keys are replaced with redaction masks before storage or display.
5. **Audit Logging Without Credentials**: Modifying actions log actor, action, repository, timestamp, and sanitized summary to the SQLite `audit_log` table via `db.log_event()`.

---

## 12. OAuth Scopes & Environment Variables

### Required GitHub Scopes
- `repo`: Required for reading repository metadata, issues, pull requests, and posting comments/issues with approval.
- `workflow`: Required for triggering safe GitHub Actions workflow reruns.

### Optional Environment Variables
- `GITHUB_TOKEN`: Fallback personal access token when OAuth session is not connected.
- `GROQ_API_KEY`: Enables cloud LLM synthesis for issue investigation, PR code review, and failure diagnostics when user has granted privacy consent. If unset or disallowed, the system deterministically falls back to local heuristic extraction or local Ollama.

---

## 13. Test Suite Verification

### Summary of Test Execution
- **Workbench Test Suite (`tests/test_github_workbench.py`)**: **96 passed / 96 total** (0 failures, 100% pass rate in 3.80s).
- **All 4 GitHub Milestones**: **148 passed / 148 total** in 10.19s:
  - `tests/test_github_integration.py`: 20/20 passed
  - `tests/test_github_analyzer.py`: 19/19 passed
  - `tests/test_github_chat.py`: 13/13 passed
  - `tests/test_github_workbench.py`: 96/96 passed
- **Core System Regression Tests**: **217 passed / 217 total** across policy, audit, filesystem, tasks, UI server, and GitHub modules.
- **Code Quality**: `flake8` passed with 0 errors across `github_workbench.py`, `policy.py`, `__init__.py`, and `test_github_workbench.py`.

---

## 14. Developer Workbench Manual Verification Walkthrough

### 1. Repository Selection & Overview
1. Navigate to **AI Manager > GitHub** in your browser (`http://localhost:8000/#tab-github`).
2. Use the global **Select Repository** dropdown in the workbench header to pick any connected repository.
3. Click the **📊 Overview** subnav tab:
   - Verify cards showing open issue count, open PR count, branch count, and workflow failure alerts.
   - Verify the recent commits list and recent workflow runs list render properly.

### 2. Issues Management & AI Investigation
1. Click the **🐛 Issues** subnav tab.
2. Filter issues by clicking **Open** or **Closed**, or type keywords into the search box.
3. Click any issue card in the left list to load its title, author, labels, and comment thread on the right.
4. Click **🤖 Run AI Investigation**:
   - Inspect the synthesized root cause summary and suggested debugging steps.
   - Note that potential duplicate issues are explicitly labeled with *"Suggested potential duplicate... Please verify manually."*
5. Click **＋ New Issue**:
   - Fill in title and body.
   - Notice the **Approval Confirmation Modal** appears showing the exact target repository, issue title, and body preview.
   - Click **Approve & Create** to submit.

### 3. Pull Request Review & Diff Intelligence
1. Click the **🔀 Pull Requests** subnav tab.
2. Select an open or closed PR from the list.
3. Review the changed files counter, additions (`+`), deletions (`-`), and color-coded unified diff preview.
4. Click **🤖 AI Code Review**:
   - Inspect findings categorized by bug risk, security, performance, or missing tests.
   - Verify the disclaimer banner: *"Findings are automated suggestions for human verification, not guaranteed defects."*
   - Verify there is **no auto-merge** button or option.

### 4. Commits & Branch Comparison
1. Click the **🌿 Commits & Branches** subnav tab.
2. Under the **Commit History** tab, browse recent commits with author badges, relative timestamps, and short SHAs.
3. Switch to the **Branch Compare** tab:
   - Select base branch (`main`) and compare branch (`feat/workbench`).
   - Click **Compare Refs** to inspect ahead/behind commit counts and changed files.
4. Switch to the **Branches** tab to inspect branch protection badges (`Protected` vs `Unprotected`).

### 5. GitHub Actions Failure Diagnostics
1. Click the **⚡ Actions** subnav tab.
2. Select any failed workflow run (marked with red `Failed` badge).
3. Inspect the failed job and step details showing elapsed execution time.
4. Click **🤖 Diagnose Failure**:
   - Review the explanation of the failure cause grounded in actual error logs.
   - Review suggested fix instructions.
5. Click **🔄 Safe Rerun**:
   - Verify the **Approval Confirmation Modal** opens showing run ID and target repository before any API write is made.
   - Confirming audits the rerun action in the system audit log.

