# 🤖 Local Agentic Automation System

A robust, local-first, terminal-based agentic automation system built with Python, Typer, Rich, SQLite, and LangChain / Groq.

The system translates natural-language goals into structured, deterministic, and securely gated filesystem workflows. By design, the LLM is **never** given unrestricted filesystem access or raw shell execution capabilities. Every operation is grounded inside authorized workspaces, validated by a deterministic plan validator, risk-classified by policy, confirmed by the user when modifying files, executed through controlled Python functions, physically verified on disk, and logged to a persistent SQLite audit trail with automated recovery and compensation support.

---

## 📐 Architecture Principle

> **The LLM decides *what* to do. Deterministic application code decides *if* and *how* it is executed.**

```
                     +---------------------------------------+
                     |         User Natural Language         |
                     +---------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |    Goal / Intent Understanding (LLM)   |
                     +---------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |     Workspace Discovery & Grounding   |
                     |   (Enabled Workspaces, Real Files)    |
                     +---------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |       Plan Synthesis (Task Steps)     |
                     +---------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |             PlanValidator             |
                     | (DAG check, permissions, containment) |
                     +---------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |         Policy / Risk Analysis        |
                     |          (LOW / MEDIUM / HIGH)        |
                     +---------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |          User Approval Gate           |
                     |      (Interactive confirmation)       |
                     +---------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |             StepExecutor              |
                     |     (Controlled File Action Tools)    |
                     +---------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |          Physical Verification        |
                     |  (Path.exists(), is_dir(), integrity) |
                     +---------------------------------------+
                                    /         \
                             Success           Failure
                                  /             \
                                 v               v
                     +----------------+   +-------------------+
                     |  Step Complete |   | Recovery/Replan   |
                     |  (Next Step)   |   |   Compensation    |
                     +----------------+   +-------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |     SQLite Audit & Task Persistence   |
                     |      (agent.db, sanitized secrets)    |
                     +---------------------------------------+
```

---

## 🚀 Milestone Evolution (M1 – M5)

The system was developed iteratively across five core milestones:

| Milestone | Title | Focus & Delivered Capabilities |
|-----------|-------|--------------------------------|
| **M1** | Controlled Local Filesystem Agent | Single-step intent recognition, safe filesystem actions (`search`, `move`, `rename`, `delete`), path safety, allowed directory restrictions, protected path handling, overwrite protection, cross-directory ambiguity detection, deterministic risk classification (`LOW`, `MEDIUM`, `HIGH`), interactive approval for modifying actions, physical verification, SQLite audit logging with secret sanitization, Rich CLI UI. |
| **M2** | Verification, Recovery & Replanning | Failure categorization (`PERMISSION_DENIED`, `NOT_FOUND`, `CONFLICT`, `UNVERIFIED`, `UNKNOWN`), retry handling with maximum retry limits (default 3), post-execution physical verification preventing false `SUCCESS` reporting, automated recovery replanning, fresh policy/approval gating for replanned actions, no-overwrite safety. |
| **M3** | Stateful Multi-Step Tasks | Persistent task and step lifecycle in SQLite (`Task`, `TaskStep`, `TaskStatus`, `StepStatus`), sequential execution, dependency DAG enforcement, dynamic output reference resolution (`$output.step_N.path`, `$prev.path`, `it`), per-step risk gating and approval, partial failure handling, reverse compensation rollbacks, CLI task management commands (`task`, `tasks`, `task-status`, `task-resume`). |
| **M4** | Persistent Workspaces & Permissions | Persistent workspace registration in SQLite, unique workspace IDs, names, canonical path resolution, enabled/disabled toggles, granular permissions (`READ`, `WRITE`, `DELETE`), primary authorization boundary, source `READ` + destination `WRITE` enforcement for moves, `WRITE` for rename, `DELETE` for delete, `READ` for search, protection against unauthorized directories and traversal escapes, workspace CLI commands (`workspace`, `workspace-add`, `workspace-remove`, `workspace-enable`, `workspace-disable`, `workspace-permissions`). |
| **M5** | Natural-Language Goal Planning | High-level goal planning, authorized workspace inspection, grounded plan synthesis with zero hallucinated source files, `PlanValidator` security gating, plan-level cumulative risk calculation, plan-level approval, execution via `StepExecutor`, `CREATE_DIRECTORY` physical verification, bulk move destination collision prevention, natural-language search variations, partial failure handling, and compensation rollbacks. |

---

## 🔒 Security & Safety Model

The security model guarantees that arbitrary code or destructive operations cannot be performed autonomously.

### 1. Workspace Authorization Boundary
- The workspace system (`app/workspaces.py`) is the **primary authorization boundary**.
- All filesystem operations are strictly confined to enabled, registered workspaces.
- Paths are resolved to their canonical form (`Path.resolve()`) before permission checking to eliminate symlink escapes and `../` traversal attacks.
- Operations on system drives, roots, or unauthorized directories outside active workspaces are strictly blocked.

### 2. Granular Permissions
Each workspace maintains explicit permissions:
- **`READ`**: Required to discover, inspect, or use a file as a move/copy source.
- **`WRITE`**: Required to create directories, rename files, or accept moved files as a destination.
- **`DELETE`**: Required to permanently remove files.
- Cross-workspace file moves require both `READ` on the source workspace and `WRITE` on the destination workspace.

### 3. Deterministic Risk Classification & Human Approval
The policy engine (`app/policy.py`) inspects actions authoritatively:
- **`LOW` (Search / Discovery)**: Read-only operations. Auto-approved.
- **`MEDIUM` (Rename / Move / Directory Creation)**: Modifying operations. Require user approval.
- **`HIGH` (Delete)**: Destructive operations. Require explicit confirmation.

Plans cannot execute modifying steps without displaying an interactive Action Summary table and receiving user confirmation (`y/N`).

### 4. Overwrite Prevention & Physical Verification
- File operations **refuse to overwrite** existing files. If a destination path already exists, operations abort with `CONFLICT`.
- The system never trusts action return codes alone. After execution, the physical filesystem is inspected (e.g. verifying `dest_path.exists()` and `dest_path.is_dir()`). If physical evidence is missing, the step is marked `FAILED`.

### 5. Why the LLM Is Not Given Shell Execution
The LLM is strictly used as a reasoning and parsing engine. It produces structured data (action names and arguments). Deterministic application code validates paths against workspace boundaries, checks permissions, calculates risk, prompts the user, and invokes safe Python standard library functions (`pathlib.Path`, `shutil`). The model has **no shell access**, **no subprocess execution**, and **no arbitrary command execution**.

---

## 🛠️ Technology Stack

Confirmed by the repository configuration:

- **Language**: Python 3.10+
- **CLI Framework**: [Typer](https://typer.tiangolo.com/) (modern type-hinted CLI builder)
- **Terminal UI**: [Rich](https://rich.readthedocs.io/) (tables, panels, status colors, styled output)
- **Database**: SQLite3 (`app/database.py`, standard library) for audit logs, workspaces, and task persistence
- **LLM & Agent Framework**: [LangChain Core](https://python.langchain.com/), [LangChain Groq](https://github.com/langchain-ai/langchain-groq), [Groq SDK](https://github.com/groq/groq-python)
- **Environment Management**: [python-dotenv](https://github.com/theskumar/python-dotenv)
- **Testing & Quality**:
  - [pytest](https://pytest.org/) & [pytest-cov](https://pytest-cov.readthedocs.io/) (test execution & coverage)
  - [Flake8](https://flake8.pycqa.org/) (PEP 8 linting)
  - [Ruff](https://beta.ruff.rs/docs/) (fast Python linter and formatter check)
  - [Mypy](http://mypy-lang.org/) (static type checking)

---

## 📁 Project Structure

```
local-system-cli/
├── app/
│   ├── __init__.py
│   ├── agent.py               # LangChain + ChatGroq reasoning agent & intent extraction
│   ├── database.py            # SQLite persistence: audit logs, workspaces, tasks, steps, secret sanitization
│   ├── llm.py                 # LLM client configuration
│   ├── main.py                # Typer CLI entrypoint, Rich UI, command handlers
│   ├── policy.py              # Deterministic risk engine (LOW/MEDIUM/HIGH) & approval rules
│   ├── recovery.py            # Failure categorization, retry loop, physical verification, replanning
│   ├── workspaces.py          # Workspace authorization boundary, permissions (READ/WRITE/DELETE), path safety
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── models.py          # Task, TaskStep, TaskStatus, StepStatus data models
│   │   ├── planner.py         # Multi-step task planner ($output.step_N.path resolution)
│   │   ├── goal_planner.py    # Natural-language goal planner, workspace grounding, collision-safe planning
│   │   ├── validator.py       # PlanValidator: DAG cycles, permissions, workspace containment
│   │   ├── executor.py        # StepExecutor: sequential step execution, physical checks, rollbacks
│   │   └── manager.py         # TaskManager: SQLite task persistence, resumption, compensation
│   └── tools/
│       ├── __init__.py
│       ├── file_actions.py    # Core filesystem actions (delete, move, rename, create_directory)
│       └── filesystem.py      # search_files tool with rglob, exclusion filtering, date filters
├── tests/
│   ├── test_ambiguity.py      # Cross-directory collision and ambiguity resolution tests
│   ├── test_audit.py          # SQLite audit logging, status transitions, secret redaction tests
│   ├── test_cli_integration.py# End-to-end CLI integration and command prompt tests
│   ├── test_file_actions.py   # Path validation, traversal prevention, file action tests
│   ├── test_filesystem.py     # File discovery and exclusion filter tests
│   ├── test_goal_planner.py   # Goal parsing, search variations, organize workflows, physical checks
│   ├── test_policy.py         # Risk classification and approval requirement tests
│   ├── test_recovery.py       # Failure categorization, retry thresholds, recovery replanning tests
│   ├── test_tasks.py          # Persistent task execution, DAG validation, compensation tests
│   └── test_workspaces.py     # Workspace CRUD, authorization boundaries, permission enforcement tests
├── .github/
│   └── workflows/
│       └── ci.yml             # GitHub Actions CI workflow (Python 3.10, 3.11, 3.12)
├── pyproject.toml             # Ruff, Flake8, Pytest, and Mypy configuration
├── requirements.txt           # Production dependencies
└── requirements-dev.txt       # Development, linting, and testing dependencies
```

---

## ⚡ Current CLI Commands

All commands are executed via the Python runner (e.g. `py -m app.main <command>` on Windows).

### 1. Goal Planning (M5)

Synthesizes a grounded execution plan from natural language, validates permissions, checks risk, asks for confirmation, and executes safely:

```bash
# Search-only goals (read-only, auto-approved)
py -m app.main goal "Find all PDF files"
py -m app.main goal "List all Python files"
py -m app.main goal "Find m4_test.txt"
py -m app.main goal "Search for my resume"

# Bulk file organization (modifying, requires approval)
py -m app.main goal "Organize my PDF files into a Documents folder"

# Options:
#   --compensate / --no-compensate    Roll back executed steps on failure (default: True)
#   --auto-approve / --no-auto-approve Bypass interactive confirmation (default: False)
```

### 2. Multi-Step Tasks (M3)

Execute or manage structured multi-step tasks:

```bash
# Execute a multi-step natural language request
py -m app.main task "Move test.txt to archive and rename it to old.txt"

# List recent tasks and statuses
py -m app.main tasks --limit 10

# Inspect execution details and per-step output for a specific task
py -m app.main task-status <task_id>

# Resume an incomplete or partially failed task
py -m app.main task-resume <task_id>
```

### 3. Workspaces & Permissions (M4)

Manage persistent authorization boundaries:

```bash
# List all registered workspaces and permissions
py -m app.main workspace

# Register an authorized directory (default permissions: READ,WRITE,DELETE)
py -m app.main workspace-add "C:\Users\You\manual_test" --name "TestWorkspace"

# Register with restricted permissions
py -m app.main workspace-add "C:\Users\You\archive" --name "Archive" --permissions "READ,WRITE"

# Update permissions (e.g. revoke DELETE)
py -m app.main workspace-permissions <workspace_id> "READ,WRITE"

# Temporarily disable / re-enable a workspace
py -m app.main workspace-disable <workspace_id>
py -m app.main workspace-enable <workspace_id>

# Remove a workspace registration
py -m app.main workspace-remove <workspace_id>
```

### 4. Interactive Agent & File Actions (M1 / M2)

Direct single-step requests and audit inspection:

```bash
# Interactive agent execution
py -m app.main agent "Find all PDF files in Downloads"
py -m app.main agent "Rename draft.txt to final.txt"

# Direct verified file deletion (with confirmation)
py -m app.main delete "C:\Users\You\manual_test\temp.txt"

# View recent SQLite audit logs
py -m app.main logs --limit 10
```

---

## 🔬 Safe Manual Testing Workflow

To safely test the system without affecting personal files, create a dedicated test workspace:

### Step 1: Create a Test Directory
In PowerShell:
```powershell
New-Item -ItemType Directory -Path .\manual_test -Force
New-Item -ItemType Directory -Path .\manual_test\folder1 -Force
New-Item -ItemType Directory -Path .\manual_test\folder2 -Force

# Create dummy sample files
Set-Content -Path .\manual_test\folder1\report.pdf -Value "Dummy PDF 1"
Set-Content -Path .\manual_test\folder2\summary.pdf -Value "Dummy PDF 2"
Set-Content -Path .\manual_test\folder1\notes.txt -Value "Sample Notes"
```

### Step 2: Register & Enable the Workspace
```bash
py -m app.main workspace-add "manual_test" --name "ManualTest"
py -m app.main workspace
```

### Step 3: Test Natural-Language Search
```bash
py -m app.main goal "Find all PDF files"
```
*Rich output displays discovered files grounded strictly within `manual_test` without requesting approval (LOW risk).*

### Step 4: Test Bulk Organization
```bash
py -m app.main goal "Organize my PDF files into a Documents folder"
```
1. The planner presents a **Proposed Execution Plan** (e.g. `CREATE_DIRECTORY Documents`, followed by `MOVE` steps).
2. The risk engine reports **Cumulative Plan Risk: MEDIUM**.
3. Typer prompts: `Execute this plan? (3 steps) [y/N]`.
4. Enter `y` to execute.

### Step 5: Verify Disk State via PowerShell
```powershell
Get-ChildItem .\manual_test\Documents -Recurse
```
Both `report.pdf` and `summary.pdf` are physically verified inside `.\manual_test\Documents`.

---

## 🛡️ Failure, Collision & Compensation Behavior

- **No Overwrite**: If a move or rename targets a destination file that already exists, the operation halts immediately with `CONFLICT`.
- **Destination Collision Prevention**: In M5 bulk move planning, if multiple files share identical names across different folders (e.g. `folder1/conflict.pdf` and `folder2/conflict.pdf`), the planner avoids planning duplicate moves to the same target name.
- **Partial Failure & Compensation**: If an unexpected collision occurs during multi-step execution, the task transitions to `PARTIAL_FAILURE`. When `--compensate` is active, the system automatically runs reverse rollback actions (restoring moved files to their source locations and cleaning up newly created empty directories).

---

## 🚦 CI/CD & Static Quality Pipeline

Every pull request and push to `main` or `master` runs the automated GitHub Actions CI pipeline defined in [`.github/workflows/ci.yml`](file:///.github/workflows/ci.yml):

- **Environment**: Ubuntu 24.04
- **Python Matrix**: `3.10`, `3.11`, `3.12`
- **Steps**:
  1. Installs dependencies from `requirements.txt` and `requirements-dev.txt`
  2. Runs **Flake8**:
     ```bash
     flake8 --max-line-length=100 app tests
     ```
  3. Runs **Ruff**:
     ```bash
     ruff check app tests
     ```
  4. Runs **Mypy**:
     ```bash
     mypy app
     ```
  5. Runs **Pytest**:
     ```bash
     pytest
     ```

All checks must pass before merging.

---

## 🧪 Running Tests Locally

Run the complete test suite:

```bash
# Run pytest in quiet mode
py -m pytest -q

# Run pytest with full verbosity and coverage report
py -m pytest -v --cov=app --cov-report=term-missing
```

### Current Test Suite Status
```
============================ 142 passed in 52.09s =============================
tests/test_ambiguity.py .........                                        [  6%]
tests/test_audit.py ..................                                   [ 19%]
tests/test_cli_integration.py ...........                                [ 26%]
tests/test_file_actions.py ..............                                [ 36%]
tests/test_filesystem.py ......                                          [ 40%]
tests/test_goal_planner.py ..........................                    [ 59%]
tests/test_policy.py ..........                                          [ 66%]
tests/test_recovery.py ..........                                        [ 73%]
tests/test_tasks.py ...........                                          [ 80%]
tests/test_workspaces.py ...........................                     [100%]

Overall Coverage: 79% (2,314 statements, 477 missed)
```

---

## ⚠️ Current Scope & Limitations

The system is deliberately focused on controlled, local filesystem management up to Milestone 5:

- **Supported Actions**: `search`, `create_directory`, `move`, `rename`, and `delete`.
- **Workspace Boundary**: The system operates **exclusively** inside explicitly configured and authorized workspaces.
- **Out of Scope (Not Implemented)**:
  - Arbitrary file content editing or document generation
  - Document parsing/summarization or internal modifications of PDF, DOCX, or XLSX files
  - File compression / archive extraction (.zip, .tar.gz)
  - Unrestricted shell command execution or OS-level automation
  - Autonomous network activity outside LLM provider API communication

Future milestones may extend capabilities into richer content manipulation and specialized workflows, but all current actions adhere strictly to the verified filesystem model above.

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.10, 3.11, or 3.12
- Groq API Key (for natural-language parsing)

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/your-username/local-system-cli.git
cd local-system-cli

# 2. Create and activate a virtual environment
py -m venv .venv
.venv\Scripts\activate       # Windows PowerShell / CMD
# source .venv/bin/activate  # macOS / Linux

# 3. Install dependencies
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m pip install -r requirements-dev.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and set your GROQ_API_KEY:
# GROQ_API_KEY=gsk_...

# 5. Verify installation
py -m app.main help
```
