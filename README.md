# 🤖 Local Agentic Automation System

[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57.svg?logo=sqlite&logoColor=white)](https://sqlite.org/)
[![Cloudflare Tunnel](https://img.shields.io/badge/Cloudflare-Tunnel%20Integrated-F38020.svg?logo=cloudflare&logoColor=white)](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
[![Groq Cloud](https://img.shields.io/badge/LLM-Groq%20Cloud-f55036.svg)](https://groq.com/)
[![Ollama Offline](https://img.shields.io/badge/LLM-Ollama%20Offline-black.svg)](https://ollama.com/)
[![Tests](https://img.shields.io/badge/tests-22%20suites%20passing-brightgreen.svg)]()
[![Code Style](https://img.shields.io/badge/code%20style-ruff%20%7C%20flake8%20%7C%20mypy-black.svg)]()

A robust, local-first agentic automation system and executive web cockpit built with Python, FastAPI, SQLite, LangChain, Groq, and Ollama. Features a rich browser dashboard, multi-step goal planning, zero-shell filesystem containment, an anti-proxy live class attendance engine, and full email/calendar productivity copilots.

The system translates natural-language goals into structured, deterministic, and securely gated filesystem workflows. By design, the LLM is **never** given unrestricted filesystem access or raw shell execution capabilities. Every operation is grounded inside authorized workspaces, validated by a deterministic plan validator, risk-classified by policy, confirmed by the user when modifying files, executed through controlled Python functions, physically verified on disk, and logged to a persistent SQLite audit trail with automated recovery and compensation support.

---

## 📑 Table of Contents

- [📐 Core Architecture & Safety Principle](#-core-architecture--safety-principle)
- [🔒 Security & Safety Model](#-security--safety-model)
  - [1. Workspace Authorization Boundary & Canonical Path Resolution](#1-workspace-authorization-boundary--canonical-path-resolution)
  - [2. Granular Permissions (RBAC)](#2-granular-permissions-rbac)
  - [3. Deterministic Risk Classification](#3-deterministic-risk-classification)
  - [4. Interactive Human Approval Gate](#4-interactive-human-approval-gate)
  - [5. No-Overwrite Guarantee & Physical Verification](#5-no-overwrite-guarantee--physical-verification)
  - [6. Why the LLM Is Denied Shell Execution](#6-why-the-llm-is-denied-shell-execution)
  - [7. Dual System Access Modes](#7-dual-system-access-modes)
- [🚀 Milestone Evolution (M1 – M9)](#-milestone-evolution-m1--m9)
- [🖥️ Web Dashboard (M9 Cockpit)](#️-web-dashboard-m9-cockpit)
  - [One-Click Desktop & Batch Launchers](#one-click-desktop--batch-launchers)
  - [Terminal Launch Options](#terminal-launch-options)
  - [Cockpit Feature Modules](#cockpit-feature-modules)
- [📱 Dynamic Anti-Proxy Live Attendance System](#-dynamic-anti-proxy-live-attendance-system)
  - [Anti-Proxy Defense Mechanism](#anti-proxy-defense-mechanism)
  - [Classroom Projector View](#classroom-projector-view)
  - [Dedicated Mobile Student Scanner Portal](#dedicated-mobile-student-scanner-portal)
  - [Dual Connectivity Modes: Local HTTPS & Cloudflare Quick Tunnel](#dual-connectivity-modes-local-https--cloudflare-quick-tunnel)
- [🧠 Dual AI Engine: Cloud Groq & Offline Ollama](#-dual-ai-engine-cloud-groq--offline-ollama)
- [🛠️ Complete CLI Command Reference](#️-complete-cli-command-reference)
  - [Goal Planning (M5)](#goal-planning-m5)
  - [Adaptive Goal Execution (M6)](#adaptive-goal-execution-m6)
  - [Multi-Step Tasks (M3)](#multi-step-tasks-m3)
  - [Workspace Management (M4)](#workspace-management-m4)
  - [Controlled System Tools (M7)](#controlled-system-tools-m7)
  - [Productivity Integrations (M8)](#productivity-integrations-m8)
  - [Web UI & Server Launchers](#web-ui--server-launchers)
  - [Audit Logs](#audit-logs)
- [🌐 REST API Reference](#-rest-api-reference)
- [⚙️ Configuration & Environment Variables](#️-configuration--environment-variables)
- [📁 Project Directory Structure](#-project-directory-structure)
- [⚡ Quick Start & Installation](#-quick-start--installation)
- [🧪 Testing & Quality Assurance](#-testing--quality-assurance)

---

## 📐 Core Architecture & Safety Principle

> **"The LLM decides *what* to do. Deterministic application code decides *if* and *how* it is executed."**

```
                     +---------------------------------------+
                     |         User Natural Language         |
                     +---------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |    Goal / Intent Understanding (LLM)  |
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

## 🔒 Security & Safety Model

The security model guarantees that arbitrary code, destructive actions, or unauthorized data access cannot be performed autonomously.

### 1. Workspace Authorization Boundary & Canonical Path Resolution
- The workspace engine ([`app/workspaces.py`](file:///app/workspaces.py)) forms the primary authorization boundary.
- All filesystem operations are strictly confined to enabled, registered workspaces.
- All target and source paths are canonicalized using `Path.resolve()` before permission checking to eliminate symlink escapes and `../` directory traversal attacks.
- Operations targeting root drives (`C:\`, `/`), operating system directories (`Windows`, `Program Files`, `/etc`, `/sys`), or unauthorized parent directories are strictly rejected.

### 2. Granular Permissions (RBAC)
Each registered workspace maintains explicit permissions:
- **`READ`**: Inspect directories, discover matching files, or use a file as a copy/move source.
- **`WRITE`**: Create directories, rename files, or accept moved files as a destination.
- **`DELETE`**: Permanently delete files or directories.
- Cross-workspace file operations require `READ` on the source workspace and `WRITE` on the destination workspace.

### 3. Deterministic Risk Classification
The policy engine ([`app/policy.py`](file:///app/policy.py)) authoritatively inspects all proposed actions before execution:
- **`LOW` (Search / Discovery / Inspection)**: Read-only operations. Auto-approved.
- **`MEDIUM` (Rename / Move / Directory Creation)**: Modifying operations. Require interactive user approval.
- **`HIGH` (Delete / Purge)**: Destructive operations. Require explicit confirmation.

### 4. Interactive Human Approval Gate
Plans containing modifying or destructive actions cannot execute without presenting a clear visual Action Summary table displaying:
- Action type (`MOVE`, `RENAME`, `DELETE`, `CREATE_DIRECTORY`)
- Source path and target destination path
- Deterministic risk badge (`LOW`, `MEDIUM`, `HIGH`)
- Explicit prompt: `Proceed with execution? [y/N]`

### 5. No-Overwrite Guarantee & Physical Verification
- File operations **strictly refuse to overwrite** existing files. If a destination path already exists on disk, operations abort immediately with a `CONFLICT` error status.
- The system never trusts action return codes alone. After execution, the physical filesystem is inspected directly (`dest_path.exists()`, `dest_path.is_file()`, `dest_path.is_dir()`, size checks). If physical disk confirmation fails, the step is marked `FAILED` and rolled back.

### 6. Why the LLM Is Denied Shell Execution
The LLM is utilized exclusively as a reasoning and extraction engine. It produces structured JSON metadata (action names, parameters, source patterns). Deterministic Python code validates boundaries, checks permissions, calculates risk, prompts the user, and invokes safe Python standard library functions (`pathlib.Path`, `shutil`). The model has **zero access to raw shell interpreters**, **no subprocess execution**, and **no arbitrary command execution capabilities**.

### 7. Dual System Access Modes
- **Workspace-Restricted Mode (Default)**: Strict isolation. Operations are strictly prohibited outside active, registered workspaces.
- **All-Files Audited Mode (Toggleable via UI/API)**: Allows authorized system-wide inspection while maintaining the full cryptographic audit ledger and interactive confirmation gates for modifying actions.

---

## 🚀 Milestone Evolution (M1 – M9)

The project was developed across nine comprehensive, test-driven milestones:

| Milestone | Title | Focus & Delivered Capabilities |
|-----------|-------|--------------------------------|
| **M1** | Controlled Local Filesystem Agent | Single-step intent recognition, safe filesystem actions (`search`, `move`, `rename`, `delete`), path safety, allowed directory restrictions, protected path handling, overwrite protection, cross-directory ambiguity detection, deterministic risk classification (`LOW`, `MEDIUM`, `HIGH`), interactive approval for modifying actions, physical verification, SQLite audit logging with secret sanitization, Rich CLI UI. |
| **M2** | Verification, Recovery & Replanning | Failure categorization (`PERMISSION_DENIED`, `NOT_FOUND`, `CONFLICT`, `UNVERIFIED`, `UNKNOWN`), retry handling with maximum retry limits (default 3), post-execution physical verification preventing false `SUCCESS` reporting, automated recovery replanning, fresh policy/approval gating for replanned actions, no-overwrite safety. |
| **M3** | Stateful Multi-Step Tasks | Persistent task and step lifecycle in SQLite (`Task`, `TaskStep`, `TaskStatus`, `StepStatus`), sequential execution, dependency DAG enforcement, dynamic output reference resolution (`$output.step_N.path`, `$prev.path`, `it`), per-step risk gating and approval, partial failure handling, reverse compensation rollbacks, CLI task management commands (`task`, `tasks`, `task-status`, `task-resume`). |
| **M4** | Persistent Workspaces & Permissions | Persistent workspace registration in SQLite, unique workspace IDs, names, canonical path resolution, enabled/disabled toggles, granular permissions (`READ`, `WRITE`, `DELETE`), primary authorization boundary, source `READ` + destination `WRITE` enforcement for moves, `WRITE` for rename, `DELETE` for delete, `READ` for search, protection against unauthorized directories and traversal escapes. Candidate unauthorized folder auto-discovery (`Downloads`, `Documents`, `Desktop`). |
| **M5** | Natural-Language Goal Planning | High-level goal planning, authorized workspace inspection, grounded plan synthesis with zero hallucinated source files, `PlanValidator` security gating, plan-level cumulative risk calculation, plan-level approval, execution via `StepExecutor`, `CREATE_DIRECTORY` physical verification, bulk move destination collision prevention, natural-language search variations, partial failure handling, and compensation rollbacks. |
| **M6** | Adaptive Filesystem Agent | Read-only workspace observation, observe → plan → validate → approve → act → verify → replan cycles, bounded adaptive replanning, filesystem diffs, physical goal-completion verification, stable-plan loop protection, and explainable cycle summaries. |
| **M7** | General Local System Tools | Controlled local system tools: hardware & resource inspection (`sys-info`), process listing & filtering (`ps`), clipboard read/write with approval gate (`clipboard`), archive inspection & Zip Slip-safe extraction (`archive`), and rich file metadata with SHA-256/MD5 hashes (`metadata`). Zero arbitrary shell access. |
| **M8** | Personal Automation & Integrations | Isolated, permission-controlled productivity integrations: safe document reading & summarization, clean browser extraction & workspace download, email staging & dispatch (IMAP/SMTP, Google OAuth), calendar inspection & scheduling (local SQLite + Google Calendar sync), and GitHub repository tools. Dual-provider LLM support for local Ollama and cloud Groq. |
| **M9** | Web Dashboard & Live Attendance | Full-featured executive web UI served via FastAPI on LAN (`0.0.0.0:8000`), AI-powered chat panel with LLM toggle, live class dynamic attendance with rotating anti-proxy QR codes, Google Calendar integration, email copilot inbox, classroom projector mode, dedicated mobile student scanner portal, local HTTPS certificate generation, and integrated Cloudflare Quick Tunnel. |

---

## 🖥️ Web Dashboard (M9 Cockpit)

The system includes a modern, high-performance browser dashboard accessible at `http://localhost:8000` (or over your LAN at `http://<your-lan-ip>:8000`).

### One-Click Desktop & Batch Launchers

No complex commands are required to run the dashboard on Windows:

1. **Desktop Shortcut**: Double-click **`AI Manager Dashboard`** directly on your Windows Desktop (create anytime by running [`create_desktop_shortcut.bat`](file:///create_desktop_shortcut.bat)).
2. **Standard HTTP Launcher**: Double-click [`start.bat`](file:///start.bat).
   - Automatically activates `.venv`, boots Uvicorn on port `8000`, and launches your default browser at `http://127.0.0.1:8000`.
3. **Secure HTTPS Launcher**: Double-click [`start-https.bat`](file:///start-https.bat).
   - Generates/uses self-signed TLS certificates and boots on port `8443` at `https://127.0.0.1:8443` (enables live camera scanning for phones over LAN Wi-Fi).

### Terminal Launch Options

```bash
# Standard browser launcher (HTTP)
python -m app.main ui

# Secure browser launcher with SSL (HTTPS)
python -m app.main https-ui

# Direct Uvicorn ASGI server
python -m uvicorn app.server:server_app --host 0.0.0.0 --port 8000
```

### Cockpit Feature Modules

| Module | Location in UI | Description |
|--------|----------------|-------------|
| **AI Chat & Plan Copilot** | Primary Sidebar / Chat View | Conversational natural language interface. Supports standard chat replies and multi-step plan generation with execution preview. Toggle the LLM on/off at runtime. |
| **Live Attendance Engine** | Attendance Tab | Anti-proxy classroom attendance engine with rotating QR codes, student rosters, projector display, and CSV export. |
| **Email Copilot** | Email Tab | Read, search, summarize, and draft email replies. Supports Gmail via Google OAuth2 or direct IMAP/SMTP credentials. |
| **Calendar Hub** | Calendar Tab | Daily/weekly event scheduling, event creation/deletion, and one-click Google Calendar iCal/ICS sync. |
| **Workspaces Manager** | Workspaces Tab | View, add, toggle, and configure granular permissions (`READ`, `WRITE`, `DELETE`) for local folders. Includes one-click presets for `Downloads`, `Documents`, and `Desktop`. |
| **Audit Ledger** | Audit Tab | Full cryptographic audit trail of all agent operations with parameter details, risk tags, and secret sanitization. |
| **System & Model Metrics** | Header & Status Bar | Live CPU and RAM usage, active workspace counts, Ollama local/GPU status, and Groq cloud model indicator. |

---

## 📱 Dynamic Anti-Proxy Live Attendance System

A comprehensive, production-ready anti-proxy attendance engine engineered for universities, schools, and corporate classrooms.

### Anti-Proxy Defense Mechanism

Proxy attendance (marking attendance for an absent friend) is prevented through four interlocking safeguards:

1. **Dynamic Time-Rotating Tokens**:
   - The server generates cryptographically signed tokens embedded into a live SVG QR code.
   - The QR code regenerates on a configurable timer (10–45 seconds, default 15 seconds).
   - Any forwarded screenshots or shared links expire before absent students can submit them.
2. **Single-Use Check-In per Student**:
   - Each student roll number/ID can only check into an active session once. Duplicate roll number submissions are rejected with clear error feedback.
3. **Device Fingerprint Rejection**:
   - The student portal generates and transmits a persistent client device identifier (`device_id`).
   - If a student in the classroom attempts to scan for multiple absent classmates using their own phone, subsequent attempts are rejected with: *"This device has already checked in for another student"*.
4. **Server-Side Token Verification**:
   - Tokens are validated strictly on the server against the active session's rotating token ledger.

### Classroom Projector View

Instructors can launch **Projector View** from the dashboard:
- Fullscreen, high-contrast display designed for auditorium projectors and smartboards.
- Prominent countdown indicator showing real-time token expiration and refresh.
- Course name, section title, and active live attendee count updated in real time.
- Hotkey shortcuts (`Esc` to exit projector mode).

### Dedicated Mobile Student Scanner Portal

Students navigate to `/attendance/student` (or alias `/attendance/scan`):
- **Step 1: Identity Registration**: Enter Full Name and Student ID/Roll Number. Stored securely in `localStorage` so students never have to retype it in future sessions.
- **Step 2: In-Browser Live Camera Scanning**:
  - Powered by [`jsqr.min.js`](file:///app/ui/jsqr.min.js) bundled directly in the application — **100% offline, zero external CDN dependencies**.
  - Auto-detects classroom QR codes with instant submission upon framing.
  - Camera flip toggle (switch between rear and front cameras).
- **Step 3: Fallback Input Options**:
  - **Upload Photo / Screenshot**: Allows students with camera permission issues to snap a photo and decode it locally.
  - **Direct URL Check-in**: Direct check-in page at `/attendance/checkin` for manual token validation.
- **Step 4: Digital Verification Receipt**:
  - Displays a green confirmation badge with course name, verified timestamp, student roll number, and anti-proxy verification seal.

### Dual Connectivity Modes: Local HTTPS & Cloudflare Quick Tunnel

Mobile phone browsers (Chrome, Safari, Firefox) mandate HTTPS security contexts before granting access to the camera (`navigator.mediaDevices.getUserMedia`). The system solves this with two seamless methods:

#### 1. Local HTTPS Mode (LAN Wi-Fi)
- Self-signed TLS certificate generator ([`app/ssl_cert.py`](file:///app/ssl_cert.py)) automatically issues certificates covering `localhost`, `127.0.0.1`, and your machine's LAN IP address with proper SAN extensions.
- Launch with [`start-https.bat`](file:///start-https.bat) or `python -m app.main https-ui`.
- Students connect to the local Wi-Fi and open `https://<YOUR-LAN-IP>:8443/attendance/student`.

#### 2. Cloudflare Quick Tunnel (External Cellular 4G/5G Access)
- Bundles zero-config [`cloudflared.exe`](file:///cloudflared.exe) managed by ([`app/tunnel.py`](file:///app/tunnel.py)).
- Automatically spawns an encrypted public tunnel when starting an attendance session (or toggleable via UI).
- Generates a public HTTPS URL (e.g. `https://random-subdomain.trycloudflare.com`).
- Embeds the public HTTPS URL directly into the projected QR code.
- **Students do not even need to be on the school Wi-Fi** — they can scan from their phone's 4G/5G cellular data network without encountering certificate warnings!

---

## 🧠 Dual AI Engine: Cloud Groq & Offline Ollama

The system provides dual-engine LLM support, configurable via `.env`, CLI, or directly in the dashboard UI:

```
           +-----------------------------------------------+
           |            LLM Provider Orchestrator          |
           +-----------------------------------------------+
                           /               \
                          /                 \
                         v                   v
              +--------------------+   +--------------------+
              |     Groq Cloud     |   |   Ollama Offline   |
              | (Ultra-fast cloud) |   | (100% Local / Air) |
              +--------------------+   +--------------------+
              | Models:            |   | Models:            |
              | openai/gpt-oss-120b|   | qwen2.5:3b         |
              | llama-3.3-70b      |   | llama3.2           |
              | deepseek-r1-distill|   | mistral            |
              +--------------------+   +--------------------+
```

### Groq Cloud Engine
- High-speed inference using Groq LPUs.
- Models: `openai/gpt-oss-120b`, `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `deepseek-r1-distill-llama-70b`.
- Configured with `GROQ_API_KEY`.
- View and select available Groq models dynamically via `/api/llm/groq/models`.

### Ollama Local Offline Engine
- 100% private, local inference without internet access.
- Default model: `qwen2.5:3b` (fast and compact) or `llama3.2`.
- GPU VRAM inspection and CPU fallback detection ([`app/llm.py`](file:///app/llm.py)).
- Automatic background process startup via `/api/llm/start_ollama`.
- Switch providers dynamically via UI or the `/api/llm/config` API.

---

## 🛠️ Complete CLI Command Reference

Execute CLI commands using: `python -m app.main <command>` (or `py -m app.main <command>`).

### Goal Planning (M5)

High-level natural language intent execution. Inspects workspaces, creates grounded plans, and requests confirmation before executing.

```bash
# Search and discover files (LOW risk, auto-approved)
python -m app.main goal "Find all PDF files across my workspaces"

# Organize files into a directory (MEDIUM risk, prompts for confirmation)
python -m app.main goal "Organize my PDF files into a Documents folder"

# Goal options
python -m app.main goal "Clean up my images" --auto-approve       # Skip interactive prompt
python -m app.main goal "Organize my logs" --compensate          # Roll back on partial failure
python -m app.main goal "Archive files" --no-compensate
```

### Adaptive Goal Execution (M6)

Multi-cycle autonomous agent loop (observe → plan → validate → approve → act → verify → replan) with cycle limits and loop prevention.

```bash
# Execute adaptive goal with default 3-cycle limit
python -m app.main adaptive "Organize all my spreadsheets into an Accounting folder"

# Auto-approve modifying actions
python -m app.main adaptive "Organize files" --yes

# Specify maximum replanning cycles
python -m app.main adaptive "Clean up project" --max-cycles 5
```

### Multi-Step Tasks (M3)

Deterministic multi-step task execution with dynamic output resolution and compensation rollbacks.

```bash
# Plan and execute a multi-step task
python -m app.main task "Move test.txt to archive and rename it to old.txt"

# List recent tasks and their execution status
python -m app.main tasks --limit 15

# Inspect detailed status and steps of a specific task
python -m app.main task-status <task_id>

# Resume a partially failed or interrupted task
python -m app.main task-resume <task_id>
```

### Workspace Management (M4)

Manage the primary security authorization boundaries.

```bash
# List all registered workspaces and permissions
python -m app.main workspace

# Add a directory as an authorized workspace
python -m app.main workspace-add "C:\Users\YourUser\Projects" --name "Projects"

# Set granular permissions (READ, WRITE, DELETE)
python -m app.main workspace-permissions <workspace_id> "READ,WRITE"

# Temporarily disable a workspace without deleting it
python -m app.main workspace-disable <workspace_id>

# Re-enable a disabled workspace
python -m app.main workspace-enable <workspace_id>

# Remove a workspace registration
python -m app.main workspace-remove <workspace_id>
```

### Controlled System Tools (M7)

Safe, zero-shell system inspection tools.

```bash
# Display CPU, RAM, disk, and operating system metrics
python -m app.main sys-info

# List running processes sorted by memory or CPU
python -m app.main ps --limit 20 --sort-by memory
python -m app.main ps --filter "python"

# Read clipboard contents (requires confirmation)
python -m app.main clipboard

# Safe archive inspection and Zip-Slip-safe extraction
python -m app.main archive ./backup.zip
python -m app.main archive ./backup.zip --extract-to ./extracted_files

# Inspect file metadata with SHA-256 and MD5 cryptographic hashes
python -m app.main metadata ./report.pdf
```

### Productivity Integrations (M8)

Safe document and workflow automation tools.

```bash
# Read and extract clean text from a document (.txt, .md, .pdf, .docx)
python -m app.main read-doc ./notes.txt

# Summarize a document using LLM
python -m app.main summarize-doc ./annual_report.pdf

# Safely extract sanitized readable text from a URL
python -m app.main browser-fetch https://example.com

# Draft an email
python -m app.main email-draft --to "team@example.com" --subject "Status Update" --body "Draft content"

# List upcoming calendar events
python -m app.main calendar-events --days 7

# Inspect GitHub repository issues
python -m app.main github-issues --repo "owner/repo" --state "open"
```

### Web UI & Server Launchers

```bash
# Launch HTTP dashboard and open browser
python -m app.main ui --host 0.0.0.0 --port 8000

# Launch HTTPS dashboard with auto-generated SSL
python -m app.main https-ui --host 0.0.0.0 --port 8443
```

### Audit Logs

```bash
# Browse recent audit log events from SQLite
python -m app.main logs --limit 20
```

---

## 🌐 REST API Reference

The FastAPI server exposes a complete REST API:

### System & Workspaces
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/status` | System health, active provider, CPU/RAM stats, workspace count. |
| `GET` | `/api/system/access_mode` | Get current access mode (sandbox vs all-files mode). |
| `POST` | `/api/system/access_mode` | Set access mode (`{"all_files_mode": true/false}`). |
| `GET` | `/api/workspaces` | List all registered workspaces and permissions. |
| `POST` | `/api/workspaces` | Add workspace (`{"name": "...", "path": "...", "permissions": [...]}`). |
| `DELETE` | `/api/workspaces/{id}` | Remove a workspace. |
| `PATCH` | `/api/workspaces/{id}/toggle` | Toggle enabled/disabled state of a workspace. |
| `GET` | `/api/workspaces/presets` | Get standard folder presets (`Downloads`, `Documents`, `Desktop`). |

### LLM Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/llm/status` | Current LLM provider, Ollama health, active models. |
| `POST` | `/api/llm/config` | Update provider (`groq` / `ollama`) and model selection. |
| `POST` | `/api/llm/groq/models` | Fetch available models for configured Groq API key. |
| `POST` | `/api/llm/start_ollama` | Trigger background start of local Ollama server process. |
| `GET` | `/api/llm/gpu_status` | Inspect local GPU VRAM usage and hardware availability. |

### Tasks & AI Chat
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/chat` | Send prompt to AI copilot (`{"message": "...", "llm_enabled": true}`). |
| `POST` | `/api/tasks/plan` | Synthesize a validated multi-step plan from a natural language goal. |
| `POST` | `/api/tasks/execute` | Execute planned steps (`{"task_id": "...", "compensate": true}`). |
| `GET` | `/api/tasks` | List recent task executions and status. |
| `GET` | `/api/audit` | Query cryptographic audit trail (`limit`, `action_filter`). |

### Attendance & Cloudflare Tunnel
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/attendance/session/start` | Start session (`{"course": "...", "section": "...", "rotation_interval": 15, "use_tunnel": true}`). |
| `GET` | `/api/attendance/session/active` | Get active session metadata, attendee roster, and live token. |
| `POST` | `/api/attendance/session/rotate` | Force immediate rotation of current QR token. |
| `POST` | `/api/attendance/session/end` | Close the active attendance session. |
| `POST` | `/api/attendance/checkin` | Submit student check-in with token and device fingerprint. |
| `GET` | `/api/attendance/export` | Download complete attendance roster as a `.csv` spreadsheet. |
| `POST` | `/api/attendance/simulate_scan` | Inject a simulated scan entry for instructor testing. |
| `GET` | `/api/tunnel/status` | Get Cloudflare tunnel status and public URL. |
| `POST` | `/api/tunnel/start` | Start public Cloudflare tunnel. |
| `POST` | `/api/tunnel/stop` | Terminate active Cloudflare tunnel. |

### Productivity (Email, Calendar, Docs, GitHub)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/email/inbox` | List recent inbox messages. |
| `GET` | `/api/email/read` | Fetch full content of specific email. |
| `POST` | `/api/email/summarize` | Generate AI summary of an email thread. |
| `POST` | `/api/email/generate_reply` | Generate AI context-aware reply draft. |
| `POST` | `/api/email/draft` | Save an email draft. |
| `POST` | `/api/email/send` | Send an email message. |
| `GET` | `/api/auth/google/status` | Check Google OAuth authentication status. |
| `GET` | `/api/auth/google/login` | Initiate Google OAuth2 login flow. |
| `GET` | `/api/auth/google/callback` | Google OAuth2 callback redirect handler. |
| `GET` | `/api/calendar/events` | List upcoming calendar events. |
| `POST` | `/api/calendar/create` | Create a calendar event (`title`, `start_time`, `end_time`). |
| `DELETE` | `/api/calendar/events/{id}` | Delete a calendar event. |
| `POST` | `/api/calendar/google/sync` | Sync calendar via iCal/ICS link or Google Calendar. |
| `POST` | `/api/docs/read` | Read document contents safely. |
| `POST` | `/api/docs/summarize` | Summarize document using AI. |
| `POST` | `/api/browser/fetch` | Fetch sanitized readable web page content. |
| `GET` | `/api/github/issues` | Query repository issues from GitHub. |

---

## ⚙️ Configuration & Environment Variables

Copy `.env.example` to `.env` and configure as needed:

```ini
# ==============================================================================
# LLM Provider Configuration
# ==============================================================================
# Provider selection: 'groq' (cloud) or 'ollama' (offline local)
LLM_PROVIDER=groq

# Groq Cloud API Settings
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b

# Ollama Offline Settings
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_CPU_MODE=false
OLLAMA_GPU_OVERHEAD=0

# ==============================================================================
# Security & Access Modes
# ==============================================================================
# Toggle system-wide file access (true) vs workspace-restricted sandbox (false)
ALL_FILES_ACCESS=false

# Enforce explicit workspace verification in test environments
AGENT_ENFORCE_WORKSPACES=false

# Custom SQLite database location (defaults to agent.db in root)
AGENT_DB_PATH=agent.db

# ==============================================================================
# Productivity Integrations (Optional)
# ==============================================================================
# Google Workspace OAuth2 (for Gmail & Calendar sync)
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback

# Google Calendar Direct API Key (alternative to OAuth)
GOOGLE_CALENDAR_API_KEY=your_calendar_api_key

# GitHub Personal Access Token (for GitHub Tools)
GITHUB_TOKEN=ghp_your_github_token_here
```

---

## 📁 Project Directory Structure

```
local-system-cli/
├── app/
│   ├── __init__.py
│   ├── agent.py               # LangChain reasoning agent & intent extraction
│   ├── assistant.py           # AI assistant logic for web chat & plan previews
│   ├── database.py            # SQLite persistence: audit ledger, workspaces, tasks, attendance
│   ├── llm.py                 # LLM configuration (Groq / Ollama toggle, GPU detection)
│   ├── main.py                # Typer CLI entrypoint, Rich UI, command handlers
│   ├── policy.py              # Deterministic risk engine (LOW/MEDIUM/HIGH) & approval rules
│   ├── recovery.py            # Failure categorization, retry loop, physical verification
│   ├── server.py              # FastAPI application: REST API & static UI endpoints
│   ├── ssl_cert.py            # Local self-signed SSL/TLS certificate generator
│   ├── tunnel.py              # Cloudflare Quick Tunnel service (zero-config public HTTPS)
│   ├── workspaces.py          # Workspace authorization boundary (READ/WRITE/DELETE)
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── models.py          # Task, TaskStep, TaskStatus, StepStatus data models
│   │   ├── planner.py         # Multi-step task planner ($output.step_N.path resolution)
│   │   ├── goal_planner.py    # Natural-language goal planner, workspace grounding
│   │   ├── adaptive.py        # M6 observe → plan → act → verify → replan loop
│   │   ├── validator.py       # PlanValidator: DAG cycles, permissions, containment
│   │   ├── executor.py        # StepExecutor: sequential step execution & rollbacks
│   │   └── manager.py         # TaskManager: SQLite task persistence & compensation
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── archive_tools.py   # Zip Slip-safe archive inspection & extraction (.zip, .tar)
│   │   ├── attendance_tools.py# Live attendance session manager & token rotator
│   │   ├── browser_tools.py   # Safe browser text extraction
│   │   ├── calendar_tools.py  # Local calendar CRUD & Google Calendar sync
│   │   ├── clipboard.py       # Safe cross-platform clipboard read/write
│   │   ├── document_tools.py  # Safe document reader & summarizer (.pdf, .docx, .txt)
│   │   ├── email_tools.py     # Email reader, summarizer, smart drafter & sender
│   │   ├── file_actions.py    # Safe filesystem actions (move, rename, delete, mkdir)
│   │   ├── filesystem.py      # search_files tool with regex, rglob & date filters
│   │   ├── github_tools.py    # GitHub repository issues & PR inspection
│   │   ├── metadata_tools.py  # File metadata, MIME types & SHA-256/MD5 hashing
│   │   └── system_tools.py    # Process listing & system hardware monitor
│   └── ui/
│       ├── index.html         # Main dashboard Single Page Application
│       ├── index.css          # Full dashboard stylesheet
│       ├── app.js             # Dashboard frontend application logic
│       ├── student_scanner.html  # Mobile student QR camera scanner portal
│       ├── student_checkin.html  # Direct URL check-in fallback page
│       └── jsqr.min.js        # Offline browser-side QR decoder (zero CDN dependency)
├── tests/
│   ├── test_ambiguity.py      # Ambiguity detection tests
│   ├── test_audit.py          # Cryptographic audit log tests
│   ├── test_cli_integration.py# CLI end-to-end integration tests
│   ├── test_cross_platform.py # Windows/Linux/macOS path compatibility tests
│   ├── test_file_actions.py   # Atomic file action tests
│   ├── test_filesystem.py     # Filesystem search and filter tests
│   ├── test_goal_planner.py   # M5 goal planner tests
│   ├── test_lazy_llm.py       # LLM lazy loading and offline fallback tests
│   ├── test_m5_matrix_*.py    # M5 matrix execution, rename, move, delete tests
│   ├── test_m6_adaptive.py    # M6 adaptive agent cycle tests
│   ├── test_m7_system_tools.py# M7 system, process, clipboard, archive tests
│   ├── test_m8_productivity_tools.py # Document, email, calendar, GitHub tests
│   ├── test_policy.py         # Deterministic policy risk tests
│   ├── test_recovery.py       # Physical verification and recovery replanning tests
│   ├── test_tasks.py          # Multi-step DAG task tests
│   ├── test_ui_server.py      # FastAPI REST routes, attendance & student portal tests
│   └── test_workspaces.py     # Workspace isolation and permission tests
├── cloudflared.exe            # Bundled Cloudflare Quick Tunnel binary
├── create_desktop_shortcut.bat# Windows batch script to create desktop shortcut
├── create_shortcut.vbs        # VBScript helper for desktop icon creation
├── start.bat                  # One-click HTTP launcher (opens browser at :8000)
├── start-https.bat            # One-click HTTPS launcher (opens browser at :8443)
├── pyproject.toml             # Ruff, Flake8, Mypy, and Pytest configuration
├── requirements.txt           # Core runtime dependencies
└── requirements-dev.txt       # Testing, linting, and development dependencies
```

---

## ⚡ Quick Start & Installation

### 1. Prerequisites
- **Python 3.10+** (Tested on Python 3.10, 3.11, 3.12, 3.13)
- Windows 10/11, macOS, or Linux
- **Cloud LLM**: Free [Groq API Key](https://console.groq.com/) **OR**
- **Offline LLM**: [Ollama](https://ollama.com/) installed locally

### 2. Installation

```bash
# Clone repository
git clone https://github.com/TejasRK007/local-system-cli.git
cd local-system-cli

# Create and activate virtual environment
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On macOS / Linux:
# source .venv/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Configure environment
cp .env.example .env
# Edit .env and paste your GROQ_API_KEY (or set LLM_PROVIDER=ollama)
```

### 3. Launching the System

#### One-Click Launch (Recommended on Windows):
- Double click [`start.bat`](file:///start.bat) to launch the HTTP dashboard.
- Double click [`start-https.bat`](file:///start-https.bat) for HTTPS mode (mobile phone camera scanning on LAN).
- Double click [`create_desktop_shortcut.bat`](file:///create_desktop_shortcut.bat) to place a shortcut on your Desktop.

#### Command-Line Launch:
```bash
# Start web UI and automatically open browser
python -m app.main ui

# Start web UI over HTTPS
python -m app.main https-ui

# Run CLI goal command
python -m app.main goal "Find all PDF files"
```

---

## 🧪 Testing & Quality Assurance

The system maintains 100% test coverage over critical safety mechanisms, permission boundaries, and API routes across 22 test suites.

### Running Pytest

```bash
# Run the complete test suite
pytest -v

# Run with test coverage report
pytest -v --cov=app --cov-report=term-missing

# Run fast UI and attendance tests
pytest tests/test_ui_server.py -v
```

### Code Formatting & Static Analysis

```bash
# Run Ruff linter and formatter
ruff check app tests
ruff format --check app tests

# Run Flake8
flake8 app tests

# Run Mypy static type checking
mypy app
```

---

## 📜 License & Compliance

Built for secure, local-first enterprise and classroom productivity. No telemetry is collected, and no private data is dispatched without explicit, audited user confirmation.
