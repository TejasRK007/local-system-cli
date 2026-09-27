# 🤖 Local Agentic Automation System

A terminal-based agentic automation tool built with Python, LangChain, Groq, Typer, and Rich.

The system accepts natural-language requests and turns them into safe, verified, locally executed file operations — without giving the LLM unrestricted filesystem access.

---

## Architecture Principle

> **LLM decides what to do. Application code decides how it is actually executed.**

The LLM proposes an intent (search, rename, move, delete).  
Python validates it, classifies its risk, requests approval when needed, executes it, and verifies the result.

---

## Agent Lifecycle

```
RECEIVE      → User types a natural-language request
UNDERSTAND   → LLM extracts the intent and parameters
PLAN         → Application identifies the required tool/action
VALIDATE     → Path safety, existence, and input checks
RISK CHECK   → policy.py classifies risk (LOW / MEDIUM / HIGH)
APPROVE      → User confirms for MEDIUM and HIGH operations
EXECUTE      → Controlled Python function performs the operation
VERIFY       → Application confirms the resulting filesystem state
AUDIT        → Persistent SQLite audit record logged to data/agent.db
REPORT       → Rich terminal UI shows the final outcome
```

---

## Architecture Overview

```
User (natural language)
         │
         ▼
  app/main.py  (Typer CLI, Rich UI, approval flow)
         │
         ├──▶ app/agent.py           LangChain + ChatGroq reasoning
         │         │
         │         └──▶ app/tools/filesystem.py   search_files tool
         │
         ├──▶ app/policy.py          Risk classification & approval gate
         │
         └──▶ app/tools/file_actions.py   delete / move / rename
                   │
                   └─── is_allowed_path()   path safety validation
```

---

## Tool Architecture

| Module | Role |
|--------|------|
| `app/main.py` | CLI entry point. Orchestrates the full lifecycle. |
| `app/agent.py` | LangChain agent. Calls the LLM, invokes tools, extracts structured intents for rename/move. |
| `app/policy.py` | **Risk engine.** Classifies actions into LOW/MEDIUM/HIGH. Gates approval decisions. |
| `app/database.py` | **Audit logging.** SQLite persistence for all executions with secret sanitization. |
| `app/tools/filesystem.py` | `search_files` LangChain tool. Handles all file discovery with exclusion filter. |
| `app/tools/file_actions.py` | Pure Python functions for delete, move, rename. Validates paths, blocks overwrite, verifies result. |

---

## Policy / Risk Layer

Every modifying or destructive operation goes through `app/policy.py` before execution.

### Risk Tiers

| Tier | Operations | Approval Required |
|------|-----------|-------------------|
| **LOW** | search, find, list | No |
| **MEDIUM** | rename, move | Yes |
| **HIGH** | delete | Yes |

### Key functions

```python
# Classify risk from a natural-language request
check_risk("Rename report.pdf to final.pdf")   # → "medium"
check_risk("Delete old files")                 # → "high"
check_risk("Find PDFs in Downloads")           # → "low"

# Classify risk from a structured action type (authoritative)
get_action_risk("rename")   # → "medium"
get_action_risk("delete")   # → "high"
get_action_risk("search")   # → "low"

# Gate the approval step
requires_approval("medium") # → True
requires_approval("low")    # → False
```

---

## Approval Mechanism

The UI shows an **Action Summary** panel before any MEDIUM or HIGH operation executes:

```
╭──── Action Summary ────────────────────────────╮
│ Action :  Rename                               │
│ Risk   :  MEDIUM                               │
│ File   :  /Users/you/Downloads/report.pdf      │
│ New name: final_report.pdf                     │
╰────────────────────────────────────────────────╯

Do you want to rename this file to final_report.pdf? [y/N]
```

Only after the user types `y` does the operation execute.

---

## Path Safety

All filesystem operations are restricted to:

- `~/Downloads`
- `~/Documents`
- `~/Desktop`

`is_allowed_path()` resolves symlinks with `Path.resolve()` before checking, preventing `../` traversal attacks and symbolic-link escapes.

Operations on paths outside allowed directories are blocked at the `file_actions.py` level, independently of the UI flow.

---

## Current Capabilities

| Capability | Command |
|-----------|---------|
| Find files by extension | `agent "Find PDFs in Downloads"` |
| Find a specific filename | `agent "Find report.pdf"` |
| Recursive search in nested folders | automatic via rglob |
| Filter by creation date (absolute) | `agent "Find PDFs from 2024-09-01 to 2024-09-30"` |
| Filter by creation date (natural language) | `agent "Show me files from yesterday"` |
| Delete with approval | `agent "Delete old_file.txt"` or `delete <path>` |
| Move with approval | `agent "Move report.pdf to Documents"` |
| Rename with approval | `agent "Rename draft.pdf to final.pdf"` |
| View audit logs | `logs` or `logs --limit 10` |
| List capabilities | `help` or `agent "What can you do?"` |

**Allowed search directories:** `Downloads`, `Documents`, `Desktop`  
**Default directory (when unspecified):** `~/Downloads`

---

## Search Exclusions

The search tool skips the following directories to avoid noise:

| Excluded | Reason |
|---------|--------|
| `.git/` | Version control internals |
| `.venv/`, `.env/` | Python virtual environments |
| `__pycache__/` | Python compiled bytecode |
| `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/` | Tooling caches |
| `node_modules/` | JavaScript dependencies |
| `*.app/` | macOS application bundles |

---

## Safety & Ambiguity Handling

1. **Cross-directory ambiguity detection.** When a filename exists in multiple allowed directories (`Downloads`, `Documents`, `Desktop`) without an explicit directory specified, the agent detects the collision and safely refuses to rename or move automatically.
2. **Path containment validation.** All operations verify `is_allowed_path()`, preventing path traversal or targeting paths outside allowed directories.
3. **Audit trail & secret sanitization.** Every execution is persistently logged to `data/agent.db`. API keys, tokens, and passwords are automatically redacted before persistence.

---

## How to Run

### Requirements

- Python 3.10+
- Groq API key in `.env` as `GROQ_API_KEY=your_key_here`

### Setup

```bash
git clone <repository-url>
cd "local system"

python3 -m venv .venv
source .venv/bin/activate       # macOS / Linux
# .venv\Scripts\activate        # Windows

pip install -r requirements.txt
pip install -r requirements-dev.txt

cp .env.example .env
# Edit .env and set GROQ_API_KEY=...
```

### Usage

```bash
python -m app.main agent "Find all PDFs in Downloads"
python -m app.main agent "Show me Word documents from last week"
python -m app.main agent "Rename draft.txt to final.txt"
python -m app.main agent "Move report.pdf to Documents"
python -m app.main agent "Delete temp_file.txt"

python -m app.main delete ~/Downloads/specific_file.txt  # direct delete

python -m app.main logs           # show recent 10 audit logs
python -m app.main logs --limit 5 # show recent 5 audit logs

python -m app.main help
```

---

## How to Test

```bash
python -m pytest tests/ -v
python -m pytest tests/ -v --cov=app   # with coverage
```

### Test files

| File | What is tested |
|------|---------------|
| `tests/test_policy.py` | check_risk (high/medium/low), get_action_risk (all tiers, case-insensitive, unknown), requires_approval |
| `tests/test_file_actions.py` | is_allowed_path (nested, home root), delete (success, blocked, traversal), rename (outside, empty, slash, overwrite), move (outside source, overwrite, missing source) |
| `tests/test_filesystem.py` | basic search, nonexistent dir, exclusion filter (.app, .git, __pycache__, mixed real+excluded) |
| `tests/test_ambiguity.py` | cross-directory ambiguity detection, single match across dirs, multi-match safety refusal, explicit dir scope |
| `tests/test_audit.py` | persistent SQLite audit logging, all action branches, status transitions, approval outcomes, CLI logs command, secret redaction |

---

## Example Execution Flows

### A. "Find all PDFs in Downloads"

```
User request → Find all PDFs in Downloads
     ↓
LLM          → search_files(directory="Downloads", extension=".pdf")
     ↓
Tool         → filesystem.py: rglob → exclusion filter → results
     ↓
Risk         → LOW  (no approval)
     ↓
Execution    → search_files returns list
     ↓
Verification → (read-only, no state change)
     ↓
Result       → Rich table with filenames and creation dates
```

### B. "Rename report.pdf to final_report.pdf"

```
User request → Rename report.pdf to final_report.pdf
     ↓
LLM          → extract_rename_request() → {source, new_name}
               search_files(directory="Downloads", filename="report.pdf")
     ↓
Tool         → 1 match found
     ↓
Risk         → get_action_risk("rename") → MEDIUM
               requires_approval("medium") → True
     ↓
Approval     → Action Summary panel (Rename / MEDIUM / File / New name)
               "Do you want to rename?" [y/N]
     ↓
Execution    → rename_file() → is_allowed_path() → target.exists() → Path.rename()
     ↓
Verification → old path gone, new path exists → "Verified"
     ↓
Result       → Success panel in terminal
```

### C. "Delete report.pdf"

```
User request → Delete report.pdf
     ↓
LLM          → search_files(directory="Downloads", filename="report.pdf")
               delete_request=True
     ↓
Tool         → 1 match found
     ↓
Risk         → get_action_risk("delete") → HIGH
               requires_approval("high") → True
     ↓
Approval     → Action Summary panel (Delete / HIGH in red)
               File table shown
               "This action is permanent. Delete ALL files?" [y/N]
     ↓
Execution    → delete_file() → is_allowed_path() → path.unlink()
     ↓
Verification → path.exists() is False → "Verified: deleted successfully."
     ↓
Result       → Success panel in terminal
```
