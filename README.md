# 🤖 Local Agentic Automation System

A robust, local-first agentic automation system built with Python, FastAPI, SQLite, and LangChain / Groq — featuring a full web dashboard with live class attendance, email, calendar, and AI-powered chat.

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

## 🚀 Milestone Evolution (M1 – M9)

The system was developed iteratively across nine core milestones:

| Milestone | Title | Focus & Delivered Capabilities |
|-----------|-------|--------------------------------|
| **M1** | Controlled Local Filesystem Agent | Single-step intent recognition, safe filesystem actions (`search`, `move`, `rename`, `delete`), path safety, allowed directory restrictions, protected path handling, overwrite protection, cross-directory ambiguity detection, deterministic risk classification (`LOW`, `MEDIUM`, `HIGH`), interactive approval for modifying actions, physical verification, SQLite audit logging with secret sanitization, Rich CLI UI. |
| **M2** | Verification, Recovery & Replanning | Failure categorization (`PERMISSION_DENIED`, `NOT_FOUND`, `CONFLICT`, `UNVERIFIED`, `UNKNOWN`), retry handling with maximum retry limits (default 3), post-execution physical verification preventing false `SUCCESS` reporting, automated recovery replanning, fresh policy/approval gating for replanned actions, no-overwrite safety. |
| **M3** | Stateful Multi-Step Tasks | Persistent task and step lifecycle in SQLite (`Task`, `TaskStep`, `TaskStatus`, `StepStatus`), sequential execution, dependency DAG enforcement, dynamic output reference resolution (`$output.step_N.path`, `$prev.path`, `it`), per-step risk gating and approval, partial failure handling, reverse compensation rollbacks, CLI task management commands (`task`, `tasks`, `task-status`, `task-resume`). |
| **M4** | Persistent Workspaces & Permissions | Persistent workspace registration in SQLite, unique workspace IDs, names, canonical path resolution, enabled/disabled toggles, granular permissions (`READ`, `WRITE`, `DELETE`), primary authorization boundary, source `READ` + destination `WRITE` enforcement for moves, `WRITE` for rename, `DELETE` for delete, `READ` for search, protection against unauthorized directories and traversal escapes. |
| **M5** | Natural-Language Goal Planning | High-level goal planning, authorized workspace inspection, grounded plan synthesis with zero hallucinated source files, `PlanValidator` security gating, plan-level cumulative risk calculation, plan-level approval, execution via `StepExecutor`, `CREATE_DIRECTORY` physical verification, bulk move destination collision prevention, natural-language search variations, partial failure handling, and compensation rollbacks. |
| **M6** | Adaptive Filesystem Agent | Read-only workspace observation, observe → plan → validate → approve → act → verify → replan cycles, bounded adaptive replanning, filesystem diffs, physical goal-completion verification, stable-plan loop protection, and explainable cycle summaries. |
| **M7** | General Local System Tools | Controlled local system tools: hardware & resource inspection (`sys-info`), process listing & filtering (`ps`), clipboard read/write with approval gate (`clipboard`), archive inspection & Zip Slip-safe extraction (`archive`), and rich file metadata with SHA-256/MD5 hashes (`metadata`). Zero arbitrary shell access. |
| **M8** | Personal Automation & Integrations | Isolated, permission-controlled productivity integrations: safe document reading & summarization, clean browser extraction & workspace download, email staging & dispatch, calendar inspection & scheduling, and GitHub repository tools. Dual-provider LLM support for local Ollama and cloud Groq. |
| **M9** | Web Dashboard & Live Attendance | Full-featured web UI served via FastAPI on LAN (`0.0.0.0:8000`), AI-powered chat panel with LLM toggle, live class dynamic attendance with rotating anti-proxy QR codes, Google Calendar integration, email copilot inbox, classroom projector mode, and dedicated mobile student scanner portal. |

---

## 🖥️ Web Dashboard (M9)

The system includes a fully-featured browser-based dashboard accessible at `http://localhost:8000` (or over LAN at `http://<your-ip>:8000`).

### Starting the Dashboard (One-Click or Terminal)

#### Option 1: One-Click Launch (No Commands Needed)
* **Desktop Icon**: Double-click **`AI Manager Dashboard`** directly on your Windows Desktop.
* **Batch Launcher**: Double-click **`start.bat`** in the project folder.
  - Automatically starts the server and opens your default browser at `http://127.0.0.1:8000`.
* **HTTPS Mode (For Mobile Camera Scanning on LAN)**: Double-click **`start-https.bat`**.
  - Starts with SSL enabled and opens `https://127.0.0.1:8443`.
* **Create/Restore Desktop Shortcut**: Double-click **`create_desktop_shortcut.bat`**.

#### Option 2: Terminal Commands

```bash
# Launch UI and automatically open browser
python -m app.main ui

# Launch UI over HTTPS (required for phone camera access over LAN)
python -m app.main https-ui

# Or start the server directly
python -m uvicorn app.server:server_app --host 0.0.0.0 --port 8000
```

### Dashboard Features

| Feature | Description |
|---------|-------------|
| **AI Chat Panel** | Natural language interface to the agentic backend. LLM can be toggled on/off via a UI switch. |
| **Live Attendance** | Dynamic rotating QR-code attendance system with anti-proxy security (see below). |
| **Email Copilot** | View, summarize, and reply to emails. Supports Gmail via IMAP. |
| **Calendar** | View, create, and delete events. Supports Google Calendar import. |
| **System Metrics** | Live CPU/RAM usage, platform info, workspace count. |
| **Workspaces** | View registered authorized directories from the browser. |
| **Audit Logs** | Browse the full cryptographic audit trail directly in the UI. |

---

## 📱 Live Class Attendance System

A complete anti-proxy attendance engine built into the dashboard. Designed for real classroom use.

### How It Works

1. **Instructor** starts a session from the Dashboard → enters course name, section, and rotation interval (10–45 seconds).
2. A **dynamic QR code** is displayed on the dashboard (or in fullscreen **Projector Mode** for classroom display).
3. The QR code **automatically regenerates** every N seconds — any forwarded screenshots or shared links expire immediately.
4. **Students** connect to the same Wi-Fi and open the Student Portal on their phones.
5. Students scan the live QR code using their phone camera to mark attendance.
6. Each check-in is **server-validated** and appears in real-time on the instructor roster.

### Anti-Proxy Security

- QR tokens are time-limited and cryptographically signed by the server.
- Forwarded screenshots or shared links from absent students **fail verification** since the token has expired by the time they're used.
- Each token is single-use per student — duplicate check-ins are rejected.

### Student URLs

| URL | Purpose |
|-----|---------|
| `http://<LAN-IP>:8000/attendance/student` | Main student mobile scanner portal |
| `http://<LAN-IP>:8000/attendance/scan` | Alias for the scanner portal |
| `http://<LAN-IP>:8000/attendance/checkin` | Direct check-in page (URL-based flow) |

### Instructor Controls

| Button | Action |
|--------|--------|
| **Start Session** | Opens modal to configure course, section, and rotation interval |
| **Projector View** | Fullscreen QR display optimized for classroom projectors |
| **Simulate Scan** | Instantly adds a test student entry (for testing without a phone) |
| **Force Rotate** | Manually regenerate the QR token immediately |
| **Export CSV** | Download the full attendance roster as a CSV file |

### Mobile Student Portal

The student portal at `/attendance/student` provides:
- **Step 1**: Enter name and roll number (saved to `localStorage` for future sessions)
- **Step 2**: Open phone camera → point at classroom QR code → auto-detected and submitted
- **Fallback**: Upload a photo or paste the check-in URL manually if camera is unavailable
- **Receipt**: Displays a verification receipt with course, timestamp, and anti-proxy confirmation

### LAN Network Access

The server binds to `0.0.0.0`, making it accessible to all devices on the same Wi-Fi network. The dashboard displays your LAN IP automatically. Students navigate to `http://<shown-IP>:8000/attendance/student` on their phones.

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

- **Language**: Python 3.10+
- **Web Framework**: [FastAPI](https://fastapi.tiangolo.com/) — REST API & static file serving
- **Web Server**: [Uvicorn](https://www.uvicorn.org/) — ASGI server, binds to `0.0.0.0` for LAN access
- **Frontend**: Vanilla HTML/CSS/JavaScript (`app/ui/`) — no build step required
- **QR Codes**: [qrcode](https://pypi.org/project/qrcode/) (server-side SVG generation) + [jsQR](https://github.com/cozmo/jsQR) (offline browser-side decoding)
- **CLI Framework**: [Typer](https://typer.tiangolo.com/) (modern type-hinted CLI builder)
- **Terminal UI**: [Rich](https://rich.readthedocs.io/) (tables, panels, status colors, styled output)
- **Database**: SQLite3 (`agent.db`) — audit logs, workspaces, task persistence, attendance tokens
- **LLM & Agent Framework**: [LangChain Core](https://python.langchain.com/), [LangChain Groq](https://github.com/langchain-ai/langchain-groq), [Groq SDK](https://github.com/groq/groq-python)
- **Local LLM**: [Ollama](https://ollama.com/) (`qwen2.5:3b`) — 100% offline inference
- **Environment Management**: [python-dotenv](https://github.com/theskumar/python-dotenv)
- **Testing & Quality**:
  - [pytest](https://pytest.org/) & [pytest-cov](https://pytest-cov.readthedocs.io/)
  - [Flake8](https://flake8.pycqa.org/), [Ruff](https://beta.ruff.rs/docs/), [Mypy](http://mypy-lang.org/)

---

## 📁 Project Structure

```
local-system-cli/
├── app/
│   ├── __init__.py
│   ├── agent.py               # LangChain + ChatGroq reasoning agent & intent extraction
│   ├── assistant.py           # AI assistant logic for the web chat panel
│   ├── database.py            # SQLite persistence: audit logs, workspaces, tasks, steps, attendance
│   ├── llm.py                 # LLM client configuration (Groq / Ollama toggle)
│   ├── main.py                # Typer CLI entrypoint, Rich UI, command handlers; also `serve` command
│   ├── policy.py              # Deterministic risk engine (LOW/MEDIUM/HIGH) & approval rules
│   ├── recovery.py            # Failure categorization, retry loop, physical verification, replanning
│   ├── server.py              # FastAPI app: REST API, static file serving, attendance endpoints
│   ├── workspaces.py          # Workspace authorization boundary, permissions (READ/WRITE/DELETE)
│   ├── tasks/
│   │   ├── models.py          # Task, TaskStep, TaskStatus, StepStatus data models
│   │   ├── planner.py         # Multi-step task planner ($output.step_N.path resolution)
│   │   ├── goal_planner.py    # Natural-language goal planner, workspace grounding
│   │   ├── adaptive.py        # M6 observation, adaptive replanning, verification, completion
│   │   ├── validator.py       # PlanValidator: DAG cycles, permissions, workspace containment
│   │   ├── executor.py        # StepExecutor: sequential step execution, physical checks, rollbacks
│   │   └── manager.py         # TaskManager: SQLite task persistence, resumption, compensation
│   ├── tools/
│   │   ├── archive_tools.py   # Archive inspection & Zip Slip-safe extraction (.zip, .tar)
│   │   ├── attendance_tools.py# Live attendance: session management, token rotation, SQLite roster
│   │   ├── browser_tools.py   # Safe browser content extraction
│   │   ├── calendar_tools.py  # Calendar CRUD (local SQLite + Google Calendar import)
│   │   ├── clipboard.py       # Safe cross-platform clipboard read & write with fallbacks
│   │   ├── document_tools.py  # Safe document reading & summarization
│   │   ├── email_tools.py     # Email reading, summarization, drafting & sending (IMAP/SMTP)
│   │   ├── file_actions.py    # Core filesystem actions (delete, move, rename, create_directory)
│   │   ├── filesystem.py      # search_files tool with rglob, exclusion filtering, date filters
│   │   ├── github_tools.py    # GitHub repository tools (issues, PRs)
│   │   ├── metadata_tools.py  # File metadata, MIME type detection, cryptographic hashing
│   │   └── system_tools.py    # Structured process inspection and system resource monitoring
│   └── ui/
│       ├── index.html         # Main dashboard SPA (chat, attendance, email, calendar, audit)
│       ├── index.css          # Full dashboard stylesheet
│       ├── app.js             # Dashboard application logic (all feature modules)
│       ├── student_scanner.html  # Mobile student QR scanner portal (/attendance/student)
│       ├── student_checkin.html  # URL-based direct check-in page (/attendance/checkin)
│       └── jsqr.min.js        # Offline browser-side QR decoder (no CDN required)
├── tests/
│   ├── test_ambiguity.py
│   ├── test_audit.py
│   ├── test_cli_integration.py
│   ├── test_file_actions.py
│   ├── test_filesystem.py
│   ├── test_goal_planner.py
│   ├── test_m6_adaptive.py
│   ├── test_m7_system_tools.py
│   ├── test_m8_productivity_tools.py
│   ├── test_policy.py
│   ├── test_recovery.py
│   ├── test_tasks.py
│   ├── test_ui_server.py      # FastAPI route tests incl. attendance & student scanner endpoints
│   └── test_workspaces.py
├── .github/
│   └── workflows/
│       └── ci.yml             # GitHub Actions CI (Python 3.10, 3.11, 3.12)
├── pyproject.toml             # Ruff, Flake8, Pytest, and Mypy configuration
├── requirements.txt           # Production dependencies
└── requirements-dev.txt       # Development, linting, and testing dependencies
```

---

## ⚡ Quick Start

### Prerequisites
- Python 3.10, 3.11, or 3.12
- Groq API Key (for cloud LLM) **or** [Ollama](https://ollama.com/) running locally (for 100% offline)

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/TejasRK007/local-system-cli.git
cd local-system-cli

# 2. Create and activate a virtual environment
py -m venv .venv
.venv\Scripts\activate        # Windows PowerShell / CMD
# source .venv/bin/activate   # macOS / Linux

# 3. Install dependencies
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m pip install -r requirements-dev.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — set GROQ_API_KEY for cloud, or point to Ollama for offline:
# GROQ_API_KEY=gsk_...
# LLM_PROVIDER=ollama   (optional, defaults to groq)

# 5. Start the web dashboard
python -m uvicorn app.server:server_app --host 0.0.0.0 --port 8000
# Open http://localhost:8000 in your browser
```

---

## ⚡ CLI Commands

All commands are executed via: `py -m app.main <command>`

### Goal Planning (M5)

```bash
py -m app.main goal "Find all PDF files"
py -m app.main goal "Organize my PDF files into a Documents folder"
# Options: --compensate / --no-compensate  |  --auto-approve / --no-auto-approve
```

### Adaptive Goal Execution (M6)

```bash
py -m app.main adaptive "Organize my PDF files into an Archive folder"
py -m app.main adaptive "Organize my PDF files into an Archive folder" --yes
py -m app.main adaptive "Organize my PDF files into an Archive folder" --max-cycles 5
```

### Multi-Step Tasks (M3)

```bash
py -m app.main task "Move test.txt to archive and rename it to old.txt"
py -m app.main tasks --limit 10
py -m app.main task-status <task_id>
py -m app.main task-resume <task_id>
```

### Workspaces (M4)

```bash
py -m app.main workspace
py -m app.main workspace-add "C:\Users\You\manual_test" --name "TestWorkspace"
py -m app.main workspace-permissions <id> "READ,WRITE"
py -m app.main workspace-disable <id>
py -m app.main workspace-enable <id>
py -m app.main workspace-remove <id>
```

### System Tools (M7)

```bash
py -m app.main sys-info
py -m app.main ps --limit 20 --sort-by memory
py -m app.main clipboard
py -m app.main archive ./backup.zip --extract-to ./extracted_folder
py -m app.main metadata ./report.pdf
```

### Audit Logs

```bash
py -m app.main logs --limit 10
```

---

## 🔬 Safe Manual Testing Workflow

```powershell
# Create test workspace
New-Item -ItemType Directory -Path .\manual_test\folder1 -Force
New-Item -ItemType Directory -Path .\manual_test\folder2 -Force
Set-Content -Path .\manual_test\folder1\report.pdf  -Value "Dummy PDF 1"
Set-Content -Path .\manual_test\folder2\summary.pdf -Value "Dummy PDF 2"

# Register it
py -m app.main workspace-add "manual_test" --name "ManualTest"

# Test search (auto-approved, read-only)
py -m app.main goal "Find all PDF files"

# Test organization (requires approval)
py -m app.main goal "Organize my PDF files into a Documents folder"

# Verify physical result
Get-ChildItem .\manual_test\Documents -Recurse
```

---

## 🛡️ Failure, Collision & Compensation Behavior

- **No Overwrite**: If a move or rename targets an existing destination, the operation halts immediately with `CONFLICT`.
- **Destination Collision Prevention**: In bulk move planning, duplicate filenames across folders are detected and avoided.
- **Partial Failure & Compensation**: On unexpected collision during multi-step execution, the task transitions to `PARTIAL_FAILURE`. With `--compensate`, the system automatically rolls back executed steps (restores moved files, cleans up created directories).

---

## 🚦 CI/CD & Static Quality Pipeline

Every pull request and push to `main` runs the GitHub Actions CI pipeline:

- **Python Matrix**: `3.10`, `3.11`, `3.12`
- **Checks**: Flake8 → Ruff → Mypy → Pytest

```bash
# Run locally
py -m pytest -v --cov=app --cov-report=term-missing
```

---

## ⚠️ Current Scope & Limitations

- **Supported Filesystem Actions**: `search`, `create_directory`, `move`, `rename`, `delete`
- **Supported System Tools**: `sys-info`, `ps`, `clipboard`, `archive`, `metadata`
- **Supported Productivity Tools**: `read-doc`, `summarize-doc`, `browser-fetch`, `email`, `calendar`, `github-issues`
- **Supported Web Dashboard Features**: AI chat, live attendance, email copilot, calendar, system metrics, audit log
- **LLM Providers**: Groq (cloud) and Ollama (local/offline)
- **Out of Scope**: Unrestricted shell execution, arbitrary remote code execution, ungated network dispatches
