"""
FastAPI Server & REST API for the Local Agentic Automation System UI.
Serves the web dashboard and provides endpoints for tasks, workspaces,
audit logs, and Milestone 8 productivity tools.
"""

import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import app.database as db
from app.policy import get_action_risk
from app.tasks.executor import StepExecutor
from app.tasks.goal_planner import GoalPlanner
from app.tasks.manager import TaskManager
from app.tasks.models import Task, TaskStatus
from app.tools.attendance_tools import (
    attendance_checkin,
    attendance_end_session,
    attendance_export_csv,
    attendance_get_active_session,
    attendance_rotate_token,
    attendance_start_session,
    get_local_ip,
)
from app.tools.browser_tools import browser_fetch_page
from app.tools.calendar_tools import (
    calendar_create_event,
    calendar_delete_event,
    calendar_list_events,
)
from app.tools.document_tools import (
    _extract_text_from_file,
    _redact_secrets,
    read_document,
    summarize_document,
)
from app.tools.email_tools import (
    email_draft,
    email_generate_reply,
    email_get_account,
    email_link_account,
    email_link_google_oauth,
    email_mark_all_read,
    email_read,
    email_search,
    email_send,
    email_summarize,
    email_sync,
)
from app.tools.github_tools import github_list_issues
from app.tools.system_tools import get_system_info
from app.workspaces import WorkspaceManager

# Define directories
BASE_DIR = Path(__file__).resolve().parent
UI_DIR = BASE_DIR / "ui"

server_app = FastAPI(
    title="Local Agentic Automation System",
    description="Local-first agentic automation dashboard and API",
    version="0.8.0",
)
app = server_app
ACTIVE_PLANS: Dict[str, Any] = {}

# CORS
server_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Request Schemas
# -----------------------------------------------------------------------------
class ChatAttachment(BaseModel):
    name: str
    size: Optional[int] = 0
    type: Optional[str] = ""
    data: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    mode: Optional[str] = "safe"
    workspace: Optional[str] = None
    attachments: Optional[List[ChatAttachment]] = None
    history: Optional[List[Dict[str, Any]]] = None
    llm_enabled: Optional[bool] = True


class GoalPlanRequest(BaseModel):
    goal: str
    workspace: Optional[str] = None


class ExecutePlanRequest(BaseModel):
    task_id: str
    approved: bool = True


class ReadDocRequest(BaseModel):
    path: str
    max_chars: int = 4000


class EmailDraftRequest(BaseModel):
    to: str
    subject: str
    body: str


class EmailSendRequest(BaseModel):
    to: str
    subject: str
    body: str
    draft_id: Optional[int] = None


class EmailSummarizeRequest(BaseModel):
    message_id: str


class EmailReplyRequest(BaseModel):
    message_id: str
    tone: Optional[str] = "professional"
    user_notes: Optional[str] = ""


class EmailLinkAccountRequest(BaseModel):
    email: str
    account_type: Optional[str] = "demo"
    imap_host: Optional[str] = ""
    imap_port: Optional[int] = 993
    smtp_host: Optional[str] = ""
    smtp_port: Optional[int] = 587
    username: Optional[str] = ""
    password: Optional[str] = ""


class CalendarEventRequest(BaseModel):
    title: str
    start_time: str
    end_time: str
    description: str = ""
    sync_to_google: bool = False
    calendar_id: Optional[str] = "primary"
    access_token: Optional[str] = None


class BrowserFetchRequest(BaseModel):
    url: str
    max_chars: int = 4000


class AttendanceSessionStartRequest(BaseModel):
    course_name: Optional[str] = None
    course: Optional[str] = None
    section: str = "Section A"
    rotation_interval_seconds: Optional[int] = None
    rotation_interval: Optional[int] = None
    host_url: Optional[str] = None
    use_tunnel: Optional[bool] = True


class AttendanceCheckinRequest(BaseModel):
    session_id: str
    token: str
    student_id: str
    student_name: str
    device_info: Optional[str] = "Mobile Client"
    device_id: Optional[str] = None


class AttendanceRotateRequest(BaseModel):
    session_id: str
    host_url: Optional[str] = None


def _extract_request_host(request: Optional[Request] = None) -> str:
    """Determine best external URL from active Cloudflare tunnel, client request headers, or local network IP."""
    try:
        from app.tunnel import get_tunnel_url
        tunnel_url = get_tunnel_url()
        if tunnel_url:
            return tunnel_url
    except Exception:
        pass

    if request:
        host_header = request.headers.get("host")
        if host_header:
            scheme = request.url.scheme or "http"
            return f"{scheme}://{host_header}"
    lan_ip = get_local_ip()
    return f"http://{lan_ip}:8000" if lan_ip != "127.0.0.1" else "http://127.0.0.1:8000"


# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------
@server_app.get("/api/status")
def get_status() -> Dict[str, Any]:
    """Return system readiness, active LLM model, and workspace metrics."""
    workspaces = WorkspaceManager.list_workspaces()
    sys_info = get_system_info()
    provider = os.getenv("LLM_PROVIDER", "ollama")
    model = (
        os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        if provider == "ollama"
        else os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    )
    lan_ip = get_local_ip()
    return {
        "status": "online",
        "llm_provider": provider,
        "llm_model": model,
        "workspaces_count": len(workspaces),
        "cpu_usage": sys_info.get("cpu_percent", 0),
        "ram_usage": sys_info.get("memory", {}).get("percent", 0),
        "platform": sys_info.get("platform", "Windows"),
        "lan_ip": lan_ip,
        "network_url": f"http://{lan_ip}:8000" if lan_ip != "127.0.0.1" else None,
    }


@server_app.get("/api/workspaces")
def list_workspaces() -> List[Dict[str, Any]]:
    """Return all configured workspaces."""
    return [w.to_dict() for w in WorkspaceManager.list_workspaces()]


@server_app.get("/api/workspaces/presets")
def get_workspace_presets() -> Dict[str, Any]:
    """Return common user directory presets with local paths."""
    from pathlib import Path
    home = Path.home()
    return {
        "downloads": {
            "name": "Downloads",
            "path": str(home / "Downloads"),
            "exists": (home / "Downloads").exists(),
        },
        "documents": {
            "name": "Documents",
            "path": str(home / "Documents"),
            "exists": (home / "Documents").exists(),
        },
        "desktop": {
            "name": "Desktop",
            "path": str(home / "Desktop"),
            "exists": (home / "Desktop").exists(),
        },
        "project": {
            "name": "Project Root",
            "path": str(Path.cwd().resolve()),
            "exists": True,
        },
    }


@server_app.post("/api/workspaces")
def add_workspace(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Add a new authorized workspace."""
    path = payload.get("path")
    name = payload.get("name")
    perms = payload.get("permissions", ["READ", "WRITE"])
    if not path or not name:
        raise HTTPException(status_code=400, detail="Path and name are required")
    try:
        ws = WorkspaceManager.add_workspace(path, name=name, permissions=perms)
        return {"success": True, "workspace": ws.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@server_app.delete("/api/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str) -> Dict[str, Any]:
    """Unregister an authorized workspace."""
    success = WorkspaceManager.remove_workspace(workspace_id)
    if not success:
        ws = WorkspaceManager.get_workspace_by_name(workspace_id)
        if ws:
            success = WorkspaceManager.remove_workspace(ws.workspace_id)
    if not success:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"success": True, "workspace_id": workspace_id}


@server_app.patch("/api/workspaces/{workspace_id}/toggle")
def toggle_workspace(workspace_id: str) -> Dict[str, Any]:
    """Toggle workspace enabled/disabled."""
    ws = WorkspaceManager.get_workspace(workspace_id)
    if not ws:
        ws = WorkspaceManager.get_workspace_by_name(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if ws.enabled:
        WorkspaceManager.disable_workspace(ws.workspace_id)
    else:
        WorkspaceManager.enable_workspace(ws.workspace_id)
    updated = WorkspaceManager.get_workspace(ws.workspace_id)
    return {"success": True, "workspace": updated.to_dict() if updated else {}}


@server_app.get("/api/system/access_mode")
def get_system_access_mode() -> Dict[str, Any]:
    """Inspect whether All Files mode or Sandboxed Workspaces mode is active."""
    all_files = WorkspaceManager.is_all_files_mode()
    return {
        "all_files_mode": all_files,
        "mode_label": "All Files Access" if all_files else "Sandboxed Workspaces",
    }


@server_app.post("/api/system/access_mode")
def set_system_access_mode(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Dynamically toggle All Files access mode."""
    enable = bool(payload.get("all_files_mode", True))
    WorkspaceManager.set_all_files_mode(enable)
    return {
        "success": True,
        "all_files_mode": WorkspaceManager.is_all_files_mode(),
        "mode_label": (
            "All Files Access"
            if WorkspaceManager.is_all_files_mode()
            else "Sandboxed Workspaces"
        ),
    }


@server_app.get("/api/llm/status")
def api_llm_status() -> Dict[str, Any]:
    """Return real-time status of local Ollama and Groq cloud configurations."""
    from app.llm import is_ollama_online
    ollama_ok = is_ollama_online()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    model_name = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

    models: list[str] = []
    if ollama_ok:
        try:
            import json
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", [])]
        except Exception:
            pass

    is_available = ollama_ok if provider == "ollama" else bool(groq_key)
    return {
        "provider": provider,
        "ollama_online": ollama_ok,
        "ollama_model": model_name,
        "ollama_models_installed": models,
        "groq_configured": bool(groq_key),
        "groq_model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "groq_key_preview": f"{groq_key[:6]}...{groq_key[-4:]}" if len(groq_key) > 10 else "",
        "llm_available": is_available,
    }


def fetch_groq_models(api_key: str) -> list[str]:
    """Fetch active chat models from Groq using provided API key."""
    import groq

    client = groq.Client(api_key=api_key.strip(), timeout=10.0)
    data = client.models.list().data
    ids = [m.id for m in data if hasattr(m, "id")]
    # Filter for chat/completion models, excluding whisper/guard/embedding models
    non_chat = ("whisper", "guard", "embedding", "moderation", "tts", "stt")
    chat_models = [mid for mid in ids if not any(k in mid.lower() for k in non_chat)]
    return chat_models if chat_models else ids


@server_app.post("/api/llm/groq/models")
def api_groq_models(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch list of accessible models directly from Groq for the given API key."""
    groq_key = str(payload.get("groq_api_key") or os.getenv("GROQ_API_KEY", "") or "").strip()
    if not groq_key:
        return {"success": False, "error": "Groq API key is required."}
    try:
        models = fetch_groq_models(groq_key)
        return {"success": True, "models": models}
    except Exception as e:
        err_msg = str(e)
        if "401" in err_msg or "invalid_api_key" in err_msg.lower():
            return {"success": False, "error": "Invalid Groq API key. Check console.groq.com."}
        return {"success": False, "error": f"Failed to fetch Groq models: {err_msg}"}


@server_app.post("/api/llm/config")
def api_llm_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Configure active LLM provider (Ollama or Groq) and update credentials."""
    provider = payload.get("provider", "").lower().strip()
    groq_key = payload.get("groq_api_key")
    groq_model = payload.get("groq_model")
    ollama_model = payload.get("ollama_model")

    env_path = Path(".env")
    env_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    def _set_env_key(key: str, val: str) -> list[str]:
        os.environ[key] = val
        found = False
        new_lines = []
        for line in env_lines:
            if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
                new_lines.append(f"{key}={val}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={val}")
        return new_lines

    active_groq_model = None
    if groq_key is not None:
        groq_clean = groq_key.strip()
        if groq_clean:
            import groq

            try:
                client = groq.Client(api_key=groq_clean, timeout=10.0)
                available = fetch_groq_models(groq_clean)
            except Exception as e:
                err_msg = str(e)
                if "401" in err_msg or "invalid_api_key" in err_msg.lower():
                    clean_err = "Invalid Groq API key. Please check your key from console.groq.com."
                else:
                    clean_err = f"Groq authentication error: {err_msg}"
                return {"success": False, "error": clean_err}

            def _model_priority(name: str) -> int:
                n = name.lower()
                if "qwen" in n:
                    return 1
                if "gpt-oss" in n:
                    return 2
                if "llama" in n:
                    return 3
                if "english" in n:
                    return 4
                if "allam" in n or "arabic" in n:
                    return 10
                return 5

            available.sort(key=_model_priority)
            req_model = (groq_model or "").strip()
            target_model = (
                req_model
                if req_model
                else (available[0] if available else "qwen/qwen3.8-27b")
            )

            # Try requested model, and fallback to any available model from the account
            candidates = [target_model] + [m for m in available if m != target_model]
            working_model = None
            last_err = ""

            for candidate in candidates:
                try:
                    client.chat.completions.create(
                        model=candidate,
                        messages=[{"role": "user", "content": "hi"}],
                        max_tokens=3,
                    )
                    working_model = candidate
                    break
                except Exception as ex:
                    last_err = str(ex)
                    continue

            if not working_model:
                return {
                    "success": False,
                    "error": f"Groq test invocation failed for '{target_model}': {last_err}",
                    "available_models": available,
                }

            active_groq_model = working_model
            env_lines = _set_env_key("GROQ_API_KEY", groq_clean)
            env_lines = _set_env_key("GROQ_MODEL", working_model)
    elif groq_model:
        env_lines = _set_env_key("GROQ_MODEL", groq_model.strip())

    if ollama_model:
        env_lines = _set_env_key("OLLAMA_MODEL", ollama_model.strip())

    if "cpu_mode" in payload:
        cpu_m = bool(payload["cpu_mode"])
        env_lines = _set_env_key("OLLAMA_CPU_MODE", "1" if cpu_m else "0")
        if cpu_m:
            os.environ["OLLAMA_GPU_OVERHEAD"] = "0"
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
        else:
            os.environ.pop("OLLAMA_GPU_OVERHEAD", None)
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)

    if provider in ("ollama", "groq"):
        env_lines = _set_env_key("LLM_PROVIDER", provider)

    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    from app.llm import is_ollama_online

    active_prov = os.getenv("LLM_PROVIDER", "ollama")
    is_avail = is_ollama_online() if active_prov == "ollama" else bool(os.getenv("GROQ_API_KEY"))

    msg = f"LLM provider updated to {active_prov}."
    if active_groq_model:
        msg = f"Connected to Groq using model: {active_groq_model}."

    model_key = "GROQ_MODEL" if active_prov == "groq" else "OLLAMA_MODEL"
    return {
        "success": True,
        "provider": active_prov,
        "model": active_groq_model or os.getenv(model_key),
        "llm_available": is_avail,
        "message": msg,
    }


@server_app.post("/api/llm/start_ollama")
def api_start_ollama(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Attempt to launch the local Ollama background server if installed.

    Accepts optional JSON body:
      { "cpu_mode": true }   — forces CPU-only by setting OLLAMA_GPU_OVERHEAD=0
                               and CUDA_VISIBLE_DEVICES="" before launching.
    """
    import shutil
    import subprocess
    import time

    from app.llm import is_ollama_online

    if payload is None:
        payload = {}

    cpu_mode = bool(payload.get("cpu_mode", False))

    if is_ollama_online():
        return {
            "success": True,
            "message": "Ollama is already online and listening on port 11434.",
            "cpu_mode": cpu_mode,
        }

    ollama_path = shutil.which("ollama") or ""
    if not ollama_path:
        import platform as _platform
        _sys = _platform.system()
        if _sys == "Windows":
            _local = os.environ.get("LOCALAPPDATA", "")
            _candidate = os.path.join(_local, "Programs", "Ollama", "ollama.exe") if _local else ""
            ollama_path = _candidate if _candidate and Path(_candidate).exists() else ""
        elif _sys == "Darwin":
            _candidate = "/Applications/Ollama.app/Contents/Resources/ollama"
            ollama_path = _candidate if Path(_candidate).exists() else ""
        else:
            ollama_path = "/usr/local/bin/ollama" if Path("/usr/local/bin/ollama").exists() else ""
    if not ollama_path or not Path(ollama_path).exists():
        return {
            "success": False,
            "error": "Ollama executable not found. Please install from ollama.com.",
        }

    try:
        env = os.environ.copy()
        if cpu_mode:
            # Force CPU-only: disable GPU overhead and hide CUDA/ROCm devices
            env["OLLAMA_GPU_OVERHEAD"] = "0"
            env["CUDA_VISIBLE_DEVICES"] = ""
            env["HIP_VISIBLE_DEVICES"] = ""
            env["ROCR_VISIBLE_DEVICES"] = ""
            # Also persist these to the .env file so subsequent launches use CPU
            env_path = Path(".env")
            env_lines = (
                env_path.read_text(encoding="utf-8").splitlines()
                if env_path.exists()
                else []
            )

            def _set_or_update(lines: list, key: str, val: str) -> list:
                found = False
                result = []
                for line in lines:
                    if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
                        result.append(f"{key}={val}")
                        found = True
                    else:
                        result.append(line)
                if not found:
                    result.append(f"{key}={val}")
                return result

            env_lines = _set_or_update(env_lines, "OLLAMA_GPU_OVERHEAD", "0")
            env_lines = _set_or_update(env_lines, "CUDA_VISIBLE_DEVICES", "")
            env_lines = _set_or_update(env_lines, "HIP_VISIBLE_DEVICES", "")
            env_lines = _set_or_update(env_lines, "ROCR_VISIBLE_DEVICES", "")
            env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
            # Also set in current process env
            os.environ["OLLAMA_GPU_OVERHEAD"] = "0"
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            os.environ["HIP_VISIBLE_DEVICES"] = ""
            os.environ["ROCR_VISIBLE_DEVICES"] = ""

        subprocess.Popen(
            [ollama_path, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        # Give it up to 5 seconds to come online
        for _ in range(5):
            time.sleep(1)
            if is_ollama_online():
                mode_label = "CPU-only mode" if cpu_mode else "GPU-accelerated mode"
                return {
                    "success": True,
                    "message": f"Ollama started successfully in {mode_label}.",
                    "cpu_mode": cpu_mode,
                }

        return {
            "success": False,
            "message": (
                "Ollama launched but is still starting up. Wait a few seconds and try again."
            ),
            "cpu_mode": cpu_mode,
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to start Ollama: {e}"}


_GPU_STATUS_CACHE: Optional[Dict[str, Any]] = None


@server_app.get("/api/llm/gpu_status")
def api_gpu_status(force: bool = False) -> Dict[str, Any]:
    """
    Detect whether a GPU suitable for LLM inference is available.

    Detection order:
      1. Apple Silicon (arm64 Darwin) - always Metal-capable, treated as gpu_available=True
      2. nvidia-smi (NVIDIA, all platforms)
      3. rocm-smi (AMD ROCm, Linux)
      4. WMI via PowerShell (Windows fallback)
      5. lspci (Linux fallback when no driver tools found)
    Intel integrated graphics are treated as cpu-only.
    """
    global _GPU_STATUS_CACHE
    forced_cpu = (
        os.getenv("OLLAMA_CPU_MODE", "0") == "1"
        or os.getenv("OLLAMA_GPU_OVERHEAD", "") == "0"
    )
    if _GPU_STATUS_CACHE is not None and not force:
        cached = dict(_GPU_STATUS_CACHE)
        cached["forced_cpu_mode"] = forced_cpu
        return cached
    import platform
    import subprocess

    gpu_available = False
    gpu_name = ""
    gpu_type = "none"
    _sys = platform.system()

    # 1. Apple Silicon: arm64 Darwin always has Metal GPU support in Ollama
    if _sys == "Darwin" and platform.machine() == "arm64":
        try:
            result = subprocess.run(
                ["system_profiler", "SPHardwareDataType"],
                capture_output=True, text=True, timeout=5
            )
            chip = ""
            for line in result.stdout.splitlines():
                if "Chip" in line or "Processor" in line:
                    chip = line.split(":")[-1].strip()
                    break
            gpu_name = chip if chip else "Apple Silicon"
        except Exception:
            gpu_name = "Apple Silicon"
        gpu_available = True
        gpu_type = "apple_metal"

    # 2. NVIDIA via nvidia-smi (works on Linux, Windows, occasionally Mac with eGPU)
    if not gpu_available:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                gpu_name = result.stdout.strip().splitlines()[0].strip()
                gpu_available = True
                gpu_type = "nvidia"
        except Exception:
            pass

    # 3. AMD via rocm-smi (Linux)
    if not gpu_available:
        try:
            result = subprocess.run(
                ["rocm-smi", "--showproductname"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.splitlines():
                    if "GPU" in line.upper() and ":" in line:
                        gpu_name = line.split(":")[-1].strip()
                        break
                gpu_name = gpu_name or "AMD GPU (ROCm)"
                gpu_available = True
                gpu_type = "amd"
        except Exception:
            pass

    # 4. Windows WMI via PowerShell
    if not gpu_available and _sys == "Windows":
        try:
            cmd = (
                "(Get-CimInstance Win32_VideoController | "
                "Select-Object -ExpandProperty Name) -join ','"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                names = [n.strip() for n in result.stdout.strip().split(",") if n.strip()]
                for name in names:
                    n_lower = name.lower()
                    nvidia_keys = ("nvidia", "geforce", "quadro", "tesla", "rtx", "gtx")
                    intel_keys = ("iris", "uhd", "hd graphics", "arc")
                    if any(k in n_lower for k in nvidia_keys):
                        gpu_name = name
                        gpu_available = True
                        gpu_type = "nvidia"
                        break
                    elif any(k in n_lower for k in ("amd", "radeon", "rx ")):
                        gpu_name = name
                        gpu_available = True
                        gpu_type = "amd"
                        break
                    elif "intel" in n_lower and any(k in n_lower for k in intel_keys):
                        # Intel Arc is discrete and capable; Iris/UHD is integrated
                        if "arc" in n_lower:
                            gpu_name = name
                            gpu_available = True
                            gpu_type = "intel_arc"
                            break
                        else:
                            gpu_name = gpu_name or name
                            gpu_type = "intel_integrated"
                if not gpu_name and names:
                    gpu_name = names[0]
        except Exception:
            pass

    # 5. Linux fallback: lspci
    if not gpu_available and _sys == "Linux":
        try:
            result = subprocess.run(
                ["lspci"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    l_lower = line.lower()
                    if "vga" in l_lower or "3d controller" in l_lower or "display" in l_lower:
                        device = line.split(":")[-1].strip() if ":" in line else line.strip()
                        if any(k in l_lower for k in ("nvidia",)):
                            gpu_name = device
                            gpu_available = True
                            gpu_type = "nvidia"
                            break
                        elif any(k in l_lower for k in ("amd", "radeon")):
                            gpu_name = device
                            gpu_available = True
                            gpu_type = "amd"
                            break
                        elif "intel" in l_lower:
                            gpu_name = gpu_name or device
                            gpu_type = "intel_integrated"
        except Exception:
            pass

    forced_cpu = os.getenv("OLLAMA_GPU_OVERHEAD", "") == "0"

    res = {
        "gpu_available": gpu_available,
        "gpu_name": gpu_name or "Unknown",
        "gpu_type": gpu_type,
        "platform": _sys,
        "forced_cpu_mode": forced_cpu,
        "recommend_cpu_mode": not gpu_available,
        "recommendation": (
            f"GPU detected: {gpu_name} ({gpu_type}). GPU-accelerated inference available."
            if gpu_available
            else f"No capable GPU detected ({gpu_name or 'none'}). CPU mode recommended."
        ),
    }
    _GPU_STATUS_CACHE = res
    return res


@server_app.get("/api/audit")
def get_audit(limit: int = 25) -> List[Dict[str, Any]]:
    """Return recent SQLite audit events."""
    return db.get_recent_logs(limit=limit)


@server_app.get("/api/tasks")
def get_recent_tasks(limit: int = 15) -> List[Dict[str, Any]]:
    """Return recent tasks and their step states."""
    tasks = db.list_task_records(limit=limit)
    out = []
    for t in tasks:
        t_obj = Task.from_dict(t)
        steps = db.get_task_steps_records(t_obj.task_id)
        out.append({**t_obj.to_dict(), "steps": steps})
    return out


def _analyze_attached_document(
    file_name: str, file_path: Path, file_text: str, user_query: str
) -> str:
    """Analyze an attached file and generate a comprehensive executive summary."""
    clean_text = _redact_secrets(file_text)
    if not clean_text or len(clean_text.strip()) < 5:
        return f"Notice: Could not extract readable text from attached file **{file_name}**."

    # Attempt LLM generation
    try:
        from app.llm import get_configured_llm

        llm = get_configured_llm()
        prompt = (
            f"You are an expert AI document analyst assisting a developer.\n"
            f"The user attached a document named '{file_name}'.\n"
            f"User Question: '{user_query}'\n\n"
            f"--- EXTRACTED CONTENT (EXCERPT) ---\n"
            f"{clean_text[:3500]}\n"
            f"--- END OF EXCERPT ---\n\n"
            "Please provide an accurate, well-structured response answering the user question. "
            "Include: Document title, high-level summary of what it is, "
            "core topics/milestones covered, and key takeaways."
        )
        res = llm.generate(prompt)
        if res and len(res.strip()) > 40 and "canned" not in res.lower():
            return res.strip()
    except Exception:
        pass

    # Heuristic structured summary
    lines = [item.strip() for item in clean_text.splitlines() if item.strip()]
    title = lines[0] if lines else file_name
    total_words = len(clean_text.split())

    sections = []
    for line in lines[:30]:
        if any(
            h in line.lower()
            for h in [
                "milestone",
                "roadmap",
                "purpose",
                "overview",
                "architecture",
                "goal",
                "summary",
                "layer",
                "principle",
                "handover",
                "safety",
                "scope",
            ]
        ):
            if line not in sections and len(line) < 140:
                sections.append(line)

    result = [
        f"**Document Analysis: `{file_name}`**\n",
        "### Document Overview",
    ]

    intro_lines = [
        item
        for item in lines[1:8]
        if len(item) > 25 and not item.startswith("Page") and not item.startswith("http")
    ][:3]
    if intro_lines:
        result.append(" ".join(intro_lines))
    else:
        result.append(
            f"This document is a technical reference containing ~{total_words} words "
            f"detailing: **{title}**."
        )

    if sections:
        result.append("\n### Core Themes & Topics Identified:")
        for s in sections[:6]:
            result.append(f"- **{s}**")

    result.append("\n### Excerpt & Content Preview:")
    excerpts = [
        f"> {item}" for item in lines[3:12] if len(item) > 20 and not item.startswith("Page")
    ][:4]
    if excerpts:
        result.append("\n".join(excerpts))
    else:
        result.append(f"> {clean_text[:280]}...")

    result.append(
        f"\n---\n"
        f"*File Details: `{file_name}` • ~{total_words} words extracted • "
        f"Ready for automation or queries.*"
    )
    return "\n".join(result)


@server_app.post("/api/chat")
def handle_chat_message(req: ChatRequest) -> Dict[str, Any]:
    """Unified conversational and agentic planning handler."""
    msg = req.message.strip()
    if not msg and not req.attachments:
        return {"success": False, "error": "Empty message"}

    # 0. Attached Document Inspection
    if req.attachments and len(req.attachments) > 0:
        att = req.attachments[0]
        safe_name = Path(att.name).name
        uploads_dir = Path("uploads")
        uploads_dir.mkdir(parents=True, exist_ok=True)
        saved_file = uploads_dir / safe_name

        if att.data and "base64," in att.data:
            import base64

            b64_str = att.data.split("base64,", 1)[1]
            try:
                saved_file.write_bytes(base64.b64decode(b64_str))
            except Exception:
                pass

        # Check saved file or fallback to local user directories
        target_path = saved_file
        if not target_path.exists() or target_path.stat().st_size == 0:
            dl_path = Path(os.path.expanduser("~/Downloads")) / safe_name
            if dl_path.exists():
                target_path = dl_path

        if target_path.exists():
            extracted_text = _extract_text_from_file(target_path, max_chars=8000)
            redacted_text = _redact_secrets(extracted_text)

            analysis = _analyze_attached_document(
                file_name=safe_name,
                file_path=target_path,
                file_text=redacted_text,
                user_query=msg or "What is this document?",
            )
            return {
                "success": True,
                "type": "conversation",
                "message": analysis,
                "file_analyzed": safe_name,
            }

    msg_lower = msg.lower()

    # File search / listing guard: DO NOT trigger hardware metrics if searching files/PDFs!
    file_intent_words = [
        "pdf",
        "file",
        "files",
        "document",
        "documents",
        "folder",
        "folders",
        "find",
        "search",
        "list",
        "locate",
    ]
    is_file_search_query = any(f in msg_lower for f in file_intent_words)

    # 1. Device Storage & System Metrics Inspection
    # Match only if explicitly asking for storage capacity, hardware metrics, or specs
    storage_keywords = [
        "storage space",
        "disk space",
        "storage capacity",
        "hardware",
        "cpu usage",
        "ram usage",
        "memory usage",
        "system specs",
        "hardware specs",
        "specs of this",
        "specs of device",
        "system info",
        "specs",
        "drive space",
        "how much storage",
        "how much ram",
        "how much disk",
    ]
    is_explicit_storage = (
        any(k in msg_lower for k in storage_keywords)
        or ("storage" in msg_lower and not is_file_search_query)
        or (
            ("cpu" in msg_lower or "ram" in msg_lower or "disk" in msg_lower)
            and not is_file_search_query
        )
        or (
            "device" in msg_lower
            and any(
                w in msg_lower
                for w in ["storage", "spec", "metric", "hardware", "memory", "ram", "cpu", "disk"]
            )
            and not is_file_search_query
        )
    )
    if is_explicit_storage and not any(k in msg_lower for k in ["delete", "remove", "clean disk"]):
        try:
            info = get_system_info()
            os_desc = f"{info.get('os')} {info.get('release')} ({info.get('architecture')})"
            proc_desc = f"{info.get('processor')} ({info.get('cpu_count')} logical cores)"
            ram_desc = (
                f"{info.get('ram_percent')}% utilized "
                f"({info.get('ram_available_gb')} GB free of {info.get('ram_total_gb')} GB total)"
            )
            resp_text = (
                f"**Device & System Metrics**\n\n"
                f"- **Operating System**: {os_desc}\n"
                f"- **Processor**: {proc_desc}\n"
                f"- **RAM Memory**: {ram_desc}\n"
                f"- **Device Storage**:\n"
                f"  - **Free Space**: {info.get('disk_free_gb')} GB\n"
                f"  - **Used Space**: {info.get('disk_used_gb')} GB ({info.get('disk_percent')}%)\n"
                f"  - **Total Capacity**: {info.get('disk_total_gb')} GB\n\n"
                "Your storage and workspace directories are accessible for local automation."
            )
            return {
                "success": True,
                "type": "conversation",
                "message": resp_text,
            }
        except Exception:
            pass

    # 2. Priority Email Summarization (Points-wise, Priority-wise, Uniquely numbered 1 to N)
    is_email_summary_query = (
        (
            any(w in msg_lower for w in ["summarize", "summary", "brief", "digest"])
            and any(e in msg_lower for e in ["mail", "email", "inbox", "message", "communication"])
        )
        or ("priority" in msg_lower and any(e in msg_lower for e in ["mail", "email", "inbox"]))
        or "numbering them uniquely" in msg_lower
    )

    if is_email_summary_query:
        try:
            acc = email_get_account()
            unread_res = email_search(category="unread", max_results=12)
            msgs = unread_res.get("messages", [])
            if not msgs:
                all_res = email_search(category="all", max_results=10)
                msgs = all_res.get("messages", [])

            if not msgs:
                return {
                    "success": True,
                    "type": "conversation",
                    "message": (
                        "No emails found in your inbox to summarize. Sync mail or check back later."
                    ),
                }

            # Sort strictly priority-wise: URGENT/SECURITY/HIGH -> NORMAL -> LOW
            priority_rank = {"urgent": 0, "security": 1, "high": 2, "normal": 3, "low": 4}
            sorted_msgs = sorted(
                msgs, key=lambda m: priority_rank.get((m.get("priority") or "normal").lower(), 3)
            )

            llm_summary = None
            try:
                from app.llm import get_configured_llm

                llm = get_configured_llm()
                emails_text = "\n\n".join(
                    [
                        f"Email #{i + 1} [Priority: {(m.get('priority') or 'normal').upper()}]\n"
                        f"From: {m.get('sender', 'Unknown')}\n"
                        f"Subject: {m.get('subject', '(No Subject)')}\n"
                        f"Date: {m.get('date', 'Today')}\n"
                        f"Body:\n{m.get('body', '')[:600]}"
                        for i, m in enumerate(sorted_msgs)
                    ]
                )
                num_msgs = len(sorted_msgs)
                summary_prompt = (
                    f"You are an executive AI assistant. Summarize {num_msgs} emails.\n"
                    f"Organize them by priority and uniquely number each from 1 to {num_msgs}.\n\n"
                    "STRICT REQUIREMENTS:\n"
                    f"1. ZERO EMOJIS.\n"
                    f"2. Number each email from 1 to {num_msgs}.\n"
                    f"3. For each email, provide:\n"
                    f"   - Header: #1 to #{num_msgs}. [PRIORITY] Subject — From: Sender\n"
                    f"   - Key Points: 2 concise bullet points summarizing content.\n"
                    f"   - Required Action: Specific follow-up or 'None (Informational)'.\n\n"
                    f"Emails:\n{emails_text}"
                )
                resp = llm.invoke(summary_prompt)
                content = str(getattr(resp, "content", resp)).strip()
                if content:
                    llm_summary = content
            except Exception:
                pass

            def _clean_body_text(txt: str) -> str:
                if not txt:
                    return ""
                # Strip HTML comments like <!--[if !mso]>...<![endif]-->
                cleaned = re.sub(r"<!--[\s\S]*?-->", " ", txt)
                # Strip HTML tags
                cleaned = re.sub(r"<[^>]+>", " ", cleaned)
                # Strip emojis
                emoji_re = (
                    r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|"
                    r"[\u2b50-\u2b55]|[\ufe0f]|[\u200d]"
                )
                cleaned = re.sub(emoji_re, "", cleaned)
                return re.sub(r"\s+", " ", cleaned).strip()

            if not llm_summary:
                lines = [
                    f"### Priority-Wise Executive Email Summary ({len(sorted_msgs)} Messages)\n",
                    f"*Organized priority-wise and numbered from 1 to {len(sorted_msgs)}.*\n",
                ]
                for i, m in enumerate(sorted_msgs, 1):
                    prio = (m.get("priority") or "normal").upper()
                    sender_clean = (
                        _clean_body_text(m.get("sender", "Unknown")).split("<")[0].strip()
                        or "Unknown"
                    )
                    subj = _clean_body_text(m.get("subject", "(No Subject)"))
                    body = _clean_body_text(m.get("body", ""))
                    summary_snippet = body[:160] + ("..." if len(body) > 160 else "")
                    if not summary_snippet.strip():
                        summary_snippet = "Automated notification or social feed update from sender."
                    action_item = (
                        "Immediate review and response needed"
                        if prio in ("URGENT", "SECURITY", "HIGH")
                        else "None (Informational update)"
                    )

                    lines.append(f"**#{i}. [{prio}] {subj}**")
                    lines.append(f"- **From**: `{sender_clean}` ({m.get('date', 'Today')})")
                    lines.append(f"- **Key Points**: {summary_snippet}")
                    lines.append(f"- **Required Action**: {action_item}\n")
                llm_summary = "\n".join(lines)

            return {
                "success": True,
                "type": "conversation",
                "message": llm_summary,
                "quick_actions": [
                    {"id": "open_inbox", "label": "Open Inbox Tab", "action": "switch_to_inbox"},
                    {"id": "sync_mail", "label": "Sync Mail", "action": "sync_emails"},
                ],
            }
        except Exception:
            pass

    # 3. Executive Morning Briefing & Digest
    briefing_keywords = [
        "morning briefing",
        "daily briefing",
        "email briefing",
        "mail briefing",
        "daily digest",
        "brief me",
        "morning digest",
        "executive briefing",
        "inbox briefing",
    ]
    is_briefing_query = any(k in msg_lower for k in briefing_keywords) or (
        ("briefing" in msg_lower or "digest" in msg_lower)
        and any(e in msg_lower for e in ["mail", "email", "inbox", "today"])
    )
    if is_briefing_query:
        try:
            acc = email_get_account()
            unread_res = email_search(category="unread", max_results=6)
            msgs = unread_res.get("messages", [])
            if not msgs:
                all_res = email_search(category="all", max_results=4)
                msgs = all_res.get("messages", [])

            cal_res = calendar_list_events()
            cal_events = cal_res.get("events", [])[:3]

            lines = [
                "### Executive Briefing\n",
                f"Account: `{acc.get('email', 'Sandbox')}` | Pending Communications: {len(msgs)}",
                "",
                "**Actionable Communications:**",
            ]

            if msgs:
                for i, m in enumerate(msgs[:3], 1):
                    sender_clean = m.get("sender", "Unknown").split("<")[0].strip()
                    prio = (m.get("priority") or "normal").upper()
                    clean_body = re.sub(r"\s+", " ", m.get("body", "")).strip()[:110]
                    lines.append(f"{i}. [{prio}] **{m.get('subject', '(No Subject)')}**")
                    lines.append(f"   From: `{sender_clean}`")
                    lines.append(f"   Summary: {clean_body}...")
                lines.append("")
            else:
                lines.append("No pending unread communications in your inbox.\n")

            if cal_events:
                lines.append("**Scheduled Events:**")
                for ev in cal_events:
                    lines.append(
                        f"- **{ev.get('title')}** ({ev.get('start_time')} to {ev.get('end_time')})"
                    )
                lines.append("")

            lines.append(
                "*Open the **Inbox** tab to review messages, generate deep summaries, or reply.*"
            )

            return {
                "success": True,
                "type": "conversation",
                "message": "\n".join(lines),
            }
        except Exception:
            pass

    # 3b. Executive Daily Tasks & Agenda Inspection (Tasks for Today / Today's Schedule)
    is_today_tasks_query = any(
        p in msg_lower
        for p in [
            "tasks for today",
            "task for today",
            "tasks today",
            "task today",
            "today's tasks",
            "todays tasks",
            "today tasks",
            "tasks for tomorrow",
            "tomorrow's tasks",
            "tasks tomorrow",
            "what are the tasks",
            "what are my tasks",
            "what tasks do i have",
            "show tasks",
            "show my tasks",
            "list tasks",
            "list my tasks",
            "check tasks",
            "check my tasks",
            "any tasks",
            "do i have tasks",
            "what do i have today",
            "what do i have scheduled",
            "what is on my schedule",
            "what's on my schedule",
            "whats on my schedule",
            "what is my schedule",
            "what's my schedule",
            "whats my schedule",
            "my schedule today",
            "schedule today",
            "today's schedule",
            "todays schedule",
            "today's agenda",
            "todays agenda",
            "agenda today",
            "agenda for today",
            "what is on my agenda",
            "what's on my agenda",
            "whats on my agenda",
            "what do i have planned",
            "what is planned for today",
            "what's planned today",
            "meetings today",
            "today's meetings",
            "todays meetings",
            "meetings for today",
            "what meetings do i have",
            "show meetings",
            "list meetings",
            "my meetings",
        ]
    ) or (
        any(
            w in msg_lower
            for w in [
                "what are",
                "what is",
                "show",
                "list",
                "check",
                "tell me",
                "any",
                "do i have",
                "what do i have",
            ]
        )
        and any(
            t in msg_lower
            for t in ["task", "tasks", "schedule", "agenda", "meeting", "meetings", "todo", "todos"]
        )
        and any(
            d in msg_lower for d in ["today", "upcoming", "scheduled", "planned", "tomorrow", "day"]
        )
        and not any(
            a in msg_lower for a in ["create", "add", "new", "delete", "remove", "organize", "move"]
        )
    )

    if is_today_tasks_query:
        try:
            import datetime

            is_tomorrow = "tomorrow" in msg_lower
            now = datetime.datetime.now()
            target_dt = (now + datetime.timedelta(days=1)) if is_tomorrow else now
            date_iso = target_dt.strftime("%Y-%m-%d")
            day_label = target_dt.strftime("%A, %B %d, %Y")
            relative_label = "Tomorrow" if is_tomorrow else "Today"

            cal_res = calendar_list_events()
            all_events = cal_res.get("events", [])

            # Filter events for target date
            day_events = [
                ev for ev in all_events if (ev.get("start_time") or "").startswith(date_iso)
            ]
            other_upcoming = [
                ev
                for ev in all_events
                if not (ev.get("start_time") or "").startswith(date_iso)
                and (ev.get("start_time") or "") >= date_iso
            ][:3]

            # Fetch actionable emails
            actionable_emails = []
            try:
                mail_res = email_search(category="all", max_results=6)
                all_msgs = mail_res.get("messages", [])
                actionable_emails = [
                    m
                    for m in all_msgs
                    if (m.get("priority") or "normal").lower() in ("urgent", "security", "high")
                    or not m.get("is_read")
                ][:3]
            except Exception:
                pass

            lines = [
                f"### Agenda & Tasks for {relative_label} ({day_label})\n",
            ]

            lines.append(f"**Scheduled Calendar Events & Meetings ({len(day_events)}):**")
            if day_events:
                for i, ev in enumerate(day_events, 1):
                    raw_s = ev.get("start_time", "")
                    raw_e = ev.get("end_time", "")
                    s_fmt = raw_s.split("T")[-1][:5] if "T" in raw_s else raw_s
                    e_fmt = raw_e.split("T")[-1][:5] if "T" in raw_e else raw_e
                    span = f"{s_fmt} - {e_fmt}" if s_fmt and e_fmt else "All Day"
                    lines.append(f"{i}. [{span}] **{ev.get('title')}** (Confirmed)")
                    if ev.get("description"):
                        lines.append(f"   Notes: {ev.get('description')}")
            else:
                lines.append(f"No calendar events scheduled for {relative_label.lower()}.")
                if other_upcoming:
                    lines.append("\n**Upcoming Later This Week:**")
                    for ev in other_upcoming:
                        lines.append(f"- **{ev.get('title')}** ({ev.get('start_time')})")

            lines.append("")
            lines.append(f"**Action Items from Communications ({len(actionable_emails)}):**")
            if actionable_emails:
                for i, m in enumerate(actionable_emails, 1):
                    prio = (m.get("priority") or "normal").upper()
                    sender_clean = m.get("sender", "Unknown").split("<")[0].strip()
                    subj = m.get("subject", "(No Subject)")
                    status_lbl = "Unread" if not m.get("is_read") else "Follow-up required"
                    lines.append(f"{i}. [{prio}] **{subj}** - From `{sender_clean}` ({status_lbl})")
            else:
                lines.append(
                    "All inbox communications are reviewed. No urgent action items pending."
                )

            lines.append("")
            lines.append(
                "*All agenda and task data is processed locally with 100% offline privacy.*"
            )

            return {
                "success": True,
                "type": "conversation",
                "message": "\n".join(lines),
                "quick_actions": [
                    {
                        "id": "open_calendar",
                        "label": "Open Multi-Calendar",
                        "action": "switch_to_calendar",
                    },
                    {"id": "open_inbox", "label": "Review Inbox", "action": "switch_to_inbox"},
                    {
                        "id": "add_event",
                        "label": "Schedule New Event",
                        "prompt": "Schedule meeting today at 4:00 PM",
                    },
                ],
            }
        except Exception:
            pass

    # 4. Email & Inbox Status Inspection (Single-row list + quick action buttons)
    compound_action_words = [
        "schedule",
        "shedule",
        "calendar",
        "meeting",
        "todo",
        "to-do",
        "reminder",
        "draft",
        "compose",
        "send email",
        "send mail",
        "create event",
        "book meeting",
        "delete email",
        "delete mail",
    ]
    is_action_flow = any(w in msg_lower for w in compound_action_words)

    email_keywords = [
        "mail",
        "mails",
        "email",
        "emails",
        "inbox",
        "unread message",
        "unread",
        "read mail",
        "read mails",
        "read email",
        "read emails",
    ]
    if any(k in msg_lower for k in email_keywords) and not is_action_flow:
        try:
            acc = email_get_account()
            is_unread_query = "unread" in msg_lower
            is_urgent_query = any(
                w in msg_lower
                for w in ["urgent", "high priority", "critical", "important", "alert"]
            )

            # 1. Sender extraction (e.g. "from chatgpt", "form chatgpt", "by google", "sender alex")
            sender_match = re.search(r"\b(?:from|form|sender|by)\s+([a-zA-Z0-9_\-\.]+)", msg_lower)
            extracted_sender = sender_match.group(1).strip() if sender_match else ""
            if not extracted_sender:
                for cand in [
                    "chatgpt",
                    "google",
                    "marcus",
                    "alex",
                    "github",
                    "slack",
                    "apple",
                    "microsoft",
                ]:
                    if re.search(rf"\b{cand}\b", msg_lower):
                        extracted_sender = cand
                        break

            # 2. Subject / topic extraction (e.g. "about SLA", "regarding security")
            query_match = re.search(
                r"\b(?:about|regarding|topic|keyword|subject)\s+([a-zA-Z0-9_\-\.\s]+)", msg_lower
            )
            extracted_query = query_match.group(1).strip() if query_match else ""

            category = "unread" if (is_unread_query and not is_urgent_query) else "all"
            search_res = email_search(
                query=extracted_query, sender=extracted_sender, category=category, max_results=20
            )
            all_msgs = search_res.get("messages", [])

            # Secondary in-memory sender guard
            if extracted_sender:
                all_msgs = [
                    m
                    for m in all_msgs
                    if extracted_sender.lower() in (m.get("sender") or "").lower()
                ]

            unread_cnt = sum(1 for m in all_msgs if not m.get("is_read"))

            def _clean_body_text(txt: str) -> str:
                if not txt:
                    return ""
                # Strip HTML comments like <!--[if !mso]>...<![endif]-->
                cleaned = re.sub(r"<!--[\s\S]*?-->", " ", txt)
                # Strip HTML tags
                cleaned = re.sub(r"<[^>]+>", " ", cleaned)
                # Strip emojis
                emoji_re = (
                    r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|"
                    r"[\u2b50-\u2b55]|[\ufe0f]|[\u200d]"
                )
                cleaned = re.sub(emoji_re, "", cleaned)
                return re.sub(r"\s+", " ", cleaned).strip()

            if extracted_sender:
                title_sender = extracted_sender.capitalize()
                if all_msgs:
                    msgs_to_show = all_msgs
                    filter_desc = (
                        f"Sender matching `{extracted_sender}` "
                        f"({len(all_msgs)} matching message{'s' if len(all_msgs) != 1 else ''})"
                    )
                    msg_header = (
                        f"**Email Inbox: Messages from {title_sender}**\n\n"
                        f"- **Account**: `{acc.get('email', 'Sandbox')}`\n"
                        f"- **Filter**: {filter_desc}"
                    )
                else:
                    msgs_to_show = []
                    msg_header = (
                        f"**No Emails Found from {title_sender}**\n\n"
                        f"- **Account**: `{acc.get('email', 'Sandbox')}`\n"
                        f"- **Search Filter**: Sender matching `{extracted_sender}`\n\n"
                        f"No messages from this sender were found in your recent inbox."
                    )
            elif is_urgent_query:
                urgent_msgs = [
                    m
                    for m in all_msgs
                    if (m.get("priority") or "normal").lower() in ("urgent", "high", "security")
                    or any(
                        w in m.get("subject", "").lower()
                        for w in ["urgent", "security", "alert", "critical"]
                    )
                ]
                if urgent_msgs:
                    msgs_to_show = urgent_msgs
                    msg_header = (
                        f"**Urgent Communications** ({len(urgent_msgs)} urgent messages found)"
                    )
                else:
                    msgs_to_show = all_msgs[:8]
                    msg_header = (
                        f"**No Urgent Emails Found**\n\n"
                        f"All {len(all_msgs)} current messages in your inbox are marked "
                        "**NORMAL** priority. There are no critical alerts pending.\n\n"
                        "Recent Communications:"
                    )
            elif is_unread_query:
                msgs_to_show = [m for m in all_msgs if not m.get("is_read")] or all_msgs[:8]
                msg_header = f"**Unread Messages** ({len(msgs_to_show)} total unread)"
            else:
                msgs_to_show = all_msgs[:12]
                conn_mode = (
                    "IMAP Connected"
                    if acc.get("account_type") == "imap"
                    else "Offline Sandbox"
                )
                msg_header = (
                    f"**Email Inbox Status**\n\n"
                    f"- **Account**: `{acc.get('email', 'Sandbox')}` ({conn_mode})\n"
                    f"- **Recent Messages**: {len(all_msgs)} total ({unread_cnt} unread)"
                )

            emails_payload = []
            for i, m in enumerate(msgs_to_show, 1):
                clean_body = _clean_body_text(m.get("body", ""))[:140]
                sender_raw = _clean_body_text(m.get("sender", "Unknown"))
                sender_clean = sender_raw.split("<")[0].strip() or sender_raw
                emails_payload.append(
                    {
                        "id": m.get("id", f"msg-{i}"),
                        "index": i,
                        "sender": sender_clean,
                        "sender_email": sender_raw,
                        "subject": _clean_body_text(m.get("subject", "(No Subject)")),
                        "snippet": clean_body,
                        "priority": (m.get("priority") or "normal").lower(),
                        "date": m.get("date", "Today"),
                        "is_read": bool(m.get("is_read", False)),
                    }
                )

            quick_actions = [
                {
                    "id": "summarize_priority",
                    "label": "Summarize All Mails Priority-Wise (1 to N)",
                    "prompt": (
                        "Please summarize all these emails points-wise and priority-wise, "
                        "uniquely numbering each mail from 1 to N."
                    ),
                },
                {
                    "id": "extract_todos",
                    "label": "Extract Action Items & Tasks",
                    "prompt": "Extract all action items, tasks, and deadlines from these emails.",
                },
                {"id": "open_inbox", "label": "Open in Inbox Tab", "action": "switch_to_inbox"},
            ]

            return {
                "success": True,
                "type": "email_list",
                "message": msg_header,
                "emails": emails_payload,
                "quick_actions": quick_actions,
            }
        except Exception:
            pass

    # 4. Calendar & Schedule Operations (Event creation & Inspection)
    is_cal_add = any(
        w in msg_lower
        for w in [
            "add event",
            "create event",
            "new event",
            "schedule event",
            "schedule meeting",
            "book meeting",
            "add meeting",
            "set reminder",
            "add one more event",
            "put an event",
            "schedule a call",
        ]
    ) or (
        any(w in msg_lower for w in ["add", "create", "new", "schedule", "book", "set"])
        and any(c in msg_lower for c in ["event", "meeting", "reminder", "appointment"])
        and any(t in msg_lower for t in ["am", "pm", "at", "on", "tomorrow", "today", "clock", ":"])
    )
    if is_cal_add:
        try:
            from app.tools.calendar_tools import parse_calendar_event_request

            parsed = parse_calendar_event_request(msg)
            res = calendar_create_event(
                title=parsed["title"],
                start_time=parsed["start_time"],
                end_time=parsed["end_time"],
                description=f"Calendar event scheduled via assistant: {msg}",
            )
            if res.get("success"):
                return {
                    "success": True,
                    "type": "conversation",
                    "message": (
                        f"**Calendar Event Scheduled**\n\n"
                        f"- **Title**: {parsed['title']}\n"
                        f"- **Start Time**: `{parsed['start_time']}`\n"
                        f"- **End Time**: `{parsed['end_time']}`\n"
                        f"- **Status**: Scheduled (ID: #{res.get('event_id')})\n\n"
                        "The event has been added to your local calendar. "
                        "You can view all appointments in the **Multi-calendar** tab."
                    ),
                    "quick_actions": [
                        {
                            "id": "show_events",
                            "label": "Show Upcoming Events",
                            "prompt": "Show upcoming calendar events",
                        },
                        {
                            "id": "open_calendar",
                            "label": "Open Multi-Calendar Tab",
                            "action": "switch_to_calendar",
                        },
                    ],
                }
        except Exception:
            pass

    cal_keywords = ["calendar", "meeting", "meetings", "events", "schedule", "agenda"]
    if any(k in msg_lower for k in cal_keywords) and not is_action_flow:
        try:
            cal_res = calendar_list_events()
            events = cal_res.get("events", [])
            if events:
                lines = [f"**Upcoming Calendar Events** ({len(events)} total):\n"]
                for i, ev in enumerate(events[:5], 1):
                    t = ev.get("title")
                    st = ev.get("start_time")
                    et = ev.get("end_time")
                    lines.append(f"{i}. **{t}** - {st} to {et}")
                return {"success": True, "type": "conversation", "message": "\n".join(lines)}
            else:
                return {
                    "success": True,
                    "type": "conversation",
                    "message": (
                        "No upcoming events scheduled on your local calendar. "
                        "You can tell me to schedule one or visit the Multi-calendar tab."
                    ),
                }
        except Exception:
            pass

    # 5. Workspaces & Directory Inspection
    ws_keywords = ["workspace", "workspaces", "registered folder", "sandboxed folder"]
    if any(k in msg_lower for k in ws_keywords) and not any(
        k in msg_lower for k in ["create workspace", "delete workspace"]
    ):
        try:
            ws_list = WorkspaceManager.list_workspaces()
            if ws_list:
                lines = [f"**Authorized Workspaces** ({len(ws_list)} active):\n"]
                for w in ws_list:
                    perms = ", ".join(w.permissions)
                    lines.append(f"- **{w.name}** (`{w.path}`) — Permissions: `[{perms}]`")
                return {"success": True, "type": "conversation", "message": "\n".join(lines)}
            else:
                return {
                    "success": True,
                    "type": "conversation",
                    "message": (
                        "No authorized workspaces are currently registered. Register a directory "
                        "in the **Workspaces** tab to begin automating file actions safely."
                    ),
                }
        except Exception:
            pass

    # 6. Goal Planning & File / Productivity Automation
    planning_keywords = [
        "organize",
        "move",
        "rename",
        "create",
        "make",
        "mkdir",
        "touch",
        "generate",
        "delete",
        "remove",
        "copy",
        "archive",
        "zip",
        "unzip",
        "read",
        "fetch",
        "browse",
        "draft",
        "send",
        "clean",
        "sort",
        "scan",
        "backup",
        "find",
        "search",
        "list",
        "show",
        "locate",
    ]
    is_action = any(k in msg_lower for k in planning_keywords) and not is_today_tasks_query

    if is_action:
        try:
            plan = GoalPlanner.plan_goal(msg)
            task_id = f"task-{int(time.time())}"
            steps_payload = []
            for i, s in enumerate(plan.steps):
                steps_payload.append(
                    {
                        "step_id": f"s{i + 1}",
                        "step_order": s.get("step_order", i + 1),
                        "action": s.get("action"),
                        "arguments": s.get("arguments", {}),
                        "risk": get_action_risk(s.get("action", "")),
                    }
                )
            ACTIVE_PLANS[task_id] = {
                "goal": msg,
                "steps": steps_payload,
                "requires_approval": plan.requires_approval,
            }
            if plan.requires_approval:
                risk_lvl = plan.cumulative_risk.upper()
                msg_text = (
                    f"I have analyzed your goal ('{msg}') and synthesized an execution plan "
                    f"consisting of {len(steps_payload)} step(s).\n\n"
                    f"Safety Policy: Because this workflow includes modifying or external actions "
                    f"(Risk: {risk_lvl}), explicit human approval is required before execution."
                )
            else:
                modifying_verbs = (
                    "move", "rename", "delete", "remove", "copy",
                    "archive", "clean", "organize", "zip", "unzip",
                    "create", "make", "mkdir", "touch", "generate",
                )
                has_modifying_intent = any(v in msg_lower for v in modifying_verbs)
                search_triggers = (
                    "find", "search", "list", "locate", "show",
                    "what is in", "whats in", "view", "display",
                )
                search_targets = (
                    "file", "files", "fils", "fls", "pdf", "pdfs",
                    "doc", "docs", "txt", "folder", "folders",
                    "download", "desktop", "document", "directory",
                    "item", "items",
                )
                is_search_intent = not has_modifying_intent and (
                    (
                        any(w in msg_lower for w in search_triggers)
                        and any(f in msg_lower for f in search_targets)
                    )
                    or any(s.get("action") == "search" for s in plan.steps)
                )
                if is_search_intent:
                    if plan.discovered_files:
                        lines = [
                            f"**Discovered Files ({len(plan.discovered_files)} matching found):**\n"
                        ]
                        max_to_show = 30
                        for idx, f in enumerate(plan.discovered_files[:max_to_show], 1):
                            p_str = f.get("path", "")
                            p_name = Path(p_str).name
                            size_kb = round(f.get("size", 0) / 1024, 1)
                            lines.append(f"{idx}. **{p_name}** ({size_kb} KB) — `{p_str}`")
                        if len(plan.discovered_files) > max_to_show:
                            rem = len(plan.discovered_files) - max_to_show
                            lines.append(f"\n*...and {rem} more files.*")
                        msg_text = "\n".join(lines)
                    else:
                        ws_names = ", ".join(
                            [f"`{w.name}`" for w in WorkspaceManager.list_workspaces()]
                        )
                        # Check if user was asking about a common standard folder
                        standard_folder = None
                        if "download" in msg_lower:
                            standard_folder = "Downloads"
                        elif "desktop" in msg_lower:
                            standard_folder = "Desktop"
                        elif "document" in msg_lower:
                            standard_folder = "Documents"

                        if standard_folder:
                            standard_path = Path.home() / standard_folder
                            if WorkspaceManager.is_all_files_mode() and standard_path.exists():
                                found_items = []
                                try:
                                    for entry in standard_path.iterdir():
                                        if not entry.name.startswith("."):
                                            found_items.append(entry)
                                except Exception:
                                    pass
                                if found_items:
                                    item_cnt = len(found_items)
                                    hdr = (
                                        f"**Files in {standard_folder} "
                                        f"({item_cnt} items found):**\n"
                                    )
                                    lines = [hdr]
                                    for idx, p in enumerate(
                                        sorted(found_items, key=lambda x: x.name)[:30], 1
                                    ):
                                        sz = round(p.stat().st_size / 1024, 1) if p.is_file() else 0
                                        sz_str = f"({sz} KB)" if p.is_file() else "[Folder]"
                                        lines.append(f"{idx}. **{p.name}** {sz_str} — `{p}`")
                                    msg_text = "\n".join(lines)
                                else:
                                    msg_text = (
                                        f"The **{standard_folder}** directory "
                                        f"(`{standard_path}`) is currently empty."
                                    )
                            elif not any(
                                w.name.lower() == standard_folder.lower()
                                for w in WorkspaceManager.list_workspaces()
                            ):
                                msg_text = (
                                    f"The **{standard_folder}** folder (`{standard_path}`) "
                                    "is not yet registered in your authorized workspaces.\n\n"
                                    "Security Policy: The agent is restricted to authorized "
                                    "directories only.\n\n"
                                    "To authorize it, open the **Workspaces** tab and click "
                                    f"the **{standard_folder}** quick preset to grant "
                                    "`READ` permission."
                                )
                            else:
                                msg_text = f"No matching files found in **{standard_folder}**."
                        else:
                            ws_label = ws_names or "None"
                            msg_text = (
                                f"No matching files found across workspaces ({ws_label}).\n\n"
                                "To search a specific folder, mention it by name "
                                "(e.g. 'list files in downloads')."
                            )
                elif (
                    any(s.get("action") == "email_search" for s in plan.steps)
                    and len(plan.steps) == 1
                ):
                    is_urgent = any(
                        w in msg_lower for w in ["urgent", "high", "security", "alert"]
                    )
                    search_res = email_search(category="all", max_results=15)
                    all_m = search_res.get("messages", [])
                    if is_urgent:
                        filtered_m = [
                            m
                            for m in all_m
                            if (m.get("priority") or "normal").lower()
                            in ("urgent", "high", "security")
                            or any(
                                w in m.get("subject", "").lower()
                                for w in ["urgent", "security", "alert"]
                            )
                        ]
                    else:
                        filtered_m = all_m[:8]

                    if filtered_m:
                        lines = [f"**Matching Emails ({len(filtered_m)} found):**\n"]
                        for idx, m in enumerate(filtered_m, 1):
                            prio = (m.get("priority") or "normal").upper()
                            sender = m.get("sender", "Unknown").split("<")[0].strip()
                            subj = m.get("subject", "(No Subject)")
                            lines.append(f"{idx}. [{prio}] **{subj}** — From: `{sender}`")
                        msg_text = "\n".join(lines)
                    else:
                        msg_text = "No matching urgent or high-priority emails found in your inbox."
                else:
                    msg_text = (
                        f"I have analyzed your goal ('{msg}') and synthesized an execution plan "
                        f"consisting of {len(steps_payload)} verified step(s)."
                        if steps_payload
                        else plan.summary
                    )
            return {
                "success": True,
                "type": "plan",
                "task_id": task_id,
                "goal": msg,
                "workspace": plan.target_workspace.name if plan.target_workspace else None,
                "discovered_files_count": len(plan.discovered_files),
                "cumulative_risk": plan.cumulative_risk,
                "requires_approval": plan.requires_approval,
                "summary": plan.summary,
                "steps": steps_payload,
                "message": msg_text,
            }
        except Exception:
            pass

    # 7. Conversational Handling: Smart Offline Assistant & Local LLM
    llm_enabled = getattr(req, "llm_enabled", True)
    try:
        from app.assistant import get_assistant_conversational_response

        assistant_reply = get_assistant_conversational_response(
            msg, getattr(req, "history", None), llm_enabled=llm_enabled
        )
        if assistant_reply:
            return {
                "success": True,
                "type": "conversation",
                "message": assistant_reply,
            }
    except Exception:
        pass

    llm_error_reason = None
    if llm_enabled:
        try:
            from app.llm import get_configured_llm

            llm = get_configured_llm()
            resp = llm.invoke(msg)
            content = str(getattr(resp, "content", resp)).strip()
            if content:
                emoji_re = (
                    r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|"
                    r"[\u2b50-\u2b55]|[\ufe0f]|[\u200d]"
                )
                content_clean = re.sub(emoji_re, "", content)
                return {
                    "success": True,
                    "type": "conversation",
                    "message": content_clean,
                }
        except Exception as e:
            llm_error_reason = str(e)

    # If LLM was enabled but was offline or failed:
    if llm_enabled:
        from app.llm import is_ollama_online
        provider = os.getenv("LLM_PROVIDER", "ollama").lower()
        err_msg = llm_error_reason or (
            "Local Ollama is not responding on port 11434."
            if provider == "ollama" and not is_ollama_online()
            else "LLM service is currently unavailable."
        )
        return {
            "success": True,
            "type": "conversation",
            "message": (
                "**LLM is not available.**\n\n"
                f"- Diagnosis: {err_msg}\n\n"
                "**How to enable:**\n"
                "1. **Cloud Fast Inference**: Click the **LLM On/Off** button in the header "
                "and enter your **Groq API Key** (from `console.groq.com`).\n"
                "2. **Local Private Model**: Open a terminal and run `ollama serve`, "
                "then `ollama pull qwen2.5:3b`.\n\n"
                "You can also toggle the LLM switch OFF to run in instant offline rule mode."
            ),
        }

    import datetime

    now_hour = datetime.datetime.now().hour
    if now_hour < 12:
        time_greeting = "Good morning"
    elif now_hour < 17:
        time_greeting = "Good afternoon"
    else:
        time_greeting = "Good evening"

    msg_words = msg.strip().split()
    if len(msg_words) <= 3:
        intro_line = f"{time_greeting}! I am standing by to assist you privately on this computer."
    else:
        intro_line = (
            "I am your local, private executive assistant operating directly on this device."
        )

    bullets = (
        "- **Emails & Communications**: Ask *'Read mails'*, or visit the **Inbox** tab.\n"
        "- **Workspaces & Files**: Ask *'Organize files'* in your registered workspaces.\n"
        "- **Device Storage & Metrics**: Ask *'Show system specs'*.\n"
        "- **Calendar & Agendas**: Ask *'Show upcoming meetings'*, or visit the Calendar tab."
    )
    return {
        "success": True,
        "type": "conversation",
        "message": (
            f"{intro_line}\n\n"
            f"Here is how I can assist you right now:\n"
            f"{bullets}\n\n"
            f"Let me know which task you would like to proceed with."
        ),
    }


@server_app.post("/api/tasks/plan")
def plan_goal(req: GoalPlanRequest) -> Dict[str, Any]:
    """Plan a goal and return synthesized steps with risk classification."""
    try:
        plan = GoalPlanner.plan_goal(req.goal)
        task_id = f"task-{int(time.time())}"
        steps_payload = []
        for i, s in enumerate(plan.steps):
            steps_payload.append(
                {
                    "step_id": f"s{i + 1}",
                    "step_order": s.get("step_order", i + 1),
                    "action": s.get("action"),
                    "arguments": s.get("arguments", {}),
                    "risk": get_action_risk(s.get("action", "")),
                }
            )

        ACTIVE_PLANS[task_id] = {
            "goal": req.goal,
            "steps": steps_payload,
            "requires_approval": plan.requires_approval,
        }

        return {
            "success": True,
            "task_id": task_id,
            "goal": req.goal,
            "workspace": plan.target_workspace.name if plan.target_workspace else None,
            "discovered_files_count": len(plan.discovered_files),
            "cumulative_risk": plan.cumulative_risk,
            "requires_approval": plan.requires_approval,
            "summary": plan.summary,
            "steps": steps_payload,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@server_app.post("/api/tasks/execute")
def execute_task_steps(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a task's steps through StepExecutor."""
    task_id = payload.get("task_id")
    steps_data = payload.get("steps") or []
    req_text = payload.get("goal") or "Web UI Execution"

    if not steps_data and task_id and task_id in ACTIVE_PLANS:
        cached = ACTIVE_PLANS[task_id]
        steps_data = cached.get("steps", [])
        req_text = cached.get("goal", req_text)

    task = TaskManager.create_task(req_text, steps_data)

    # Execute
    executed_task = StepExecutor.execute_task(
        task,
        confirm_callback=lambda a, p, d: payload.get("approved", True),
    )

    return {
        "success": executed_task.status in (TaskStatus.COMPLETED, TaskStatus.PARTIAL_FAILURE),
        "task_id": task.task_id,
        "status": executed_task.status.value,
        "steps": [s.to_dict() for s in executed_task.steps],
    }


# -----------------------------------------------------------------------------
# M8 Productivity Tool Endpoints
# -----------------------------------------------------------------------------
@server_app.post("/api/docs/read")
def api_read_doc(req: ReadDocRequest) -> Dict[str, Any]:
    return read_document(req.path, max_chars=req.max_chars)


@server_app.post("/api/docs/summarize")
def api_summarize_doc(req: ReadDocRequest) -> Dict[str, Any]:
    return summarize_document(req.path, max_chars=req.max_chars)


@server_app.get("/api/email/inbox")
def api_email_inbox(query: str = "", category: str = "all") -> Dict[str, Any]:
    return email_search(query=query, category=category)


@server_app.get("/api/email/read")
def api_email_read(id: str) -> Dict[str, Any]:
    return email_read(id)


@server_app.post("/api/email/summarize")
def api_email_summarize(req: EmailSummarizeRequest) -> Dict[str, Any]:
    return email_summarize(req.message_id)


@server_app.post("/api/email/generate_reply")
def api_email_generate_reply(req: EmailReplyRequest) -> Dict[str, Any]:
    return email_generate_reply(
        message_id=req.message_id,
        tone=req.tone or "professional",
        user_notes=req.user_notes or "",
    )


@server_app.get("/api/email/account")
def api_email_account_get() -> Dict[str, Any]:
    return email_get_account()


@server_app.post("/api/email/account")
def api_email_account_link(req: EmailLinkAccountRequest) -> Dict[str, Any]:
    return email_link_account(
        email_address=req.email,
        account_type=req.account_type or "demo",
        imap_host=req.imap_host or "",
        imap_port=req.imap_port or 993,
        smtp_host=req.smtp_host or "",
        smtp_port=req.smtp_port or 587,
        username=req.username or "",
        password=req.password or "",
    )


@server_app.get("/api/auth/google/status")
def api_auth_google_status() -> Dict[str, Any]:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    return {
        "configured": bool(client_id and client_secret),
        "client_id": client_id,
        "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback"),
    }


@server_app.get("/api/auth/google/login")
def api_auth_google_login() -> RedirectResponse:
    import urllib.parse
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback").strip()

    if not client_id:
        raise HTTPException(status_code=400, detail="GOOGLE_CLIENT_ID is not configured in .env")

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send",
        "access_type": "offline",
        "prompt": "consent",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return RedirectResponse(url=url, status_code=302)


@server_app.get("/api/auth/google/callback")
def api_auth_google_callback(
    code: Optional[str] = None,
    error: Optional[str] = None,
) -> RedirectResponse:
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    if error:
        return RedirectResponse(url=f"/?google_error={urllib.parse.quote(error)}#email", status_code=302)

    if not code:
        return RedirectResponse(url="/?google_error=missing_code#email", status_code=302)

    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback").strip()

    try:
        token_data = urllib.parse.urlencode({
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_json = json.loads(resp.read().decode("utf-8"))

        access_token = token_json.get("access_token")
        refresh_token = token_json.get("refresh_token", "")
        expires_in = int(token_json.get("expires_in", 3600))

        if not access_token:
            return RedirectResponse(url="/?google_error=token_exchange_failed#email", status_code=302)

        userinfo_req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(userinfo_req, timeout=12) as u_resp:
            userinfo = json.loads(u_resp.read().decode("utf-8"))

        email_address = userinfo.get("email") or "user@gmail.com"

        email_link_google_oauth(
            email_address=email_address,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

        try:
            email_sync()
        except Exception:
            pass

        return RedirectResponse(url=f"/?google_auth=success&email={urllib.parse.quote(email_address)}#email", status_code=302)
    except Exception as exc:
        err_msg = urllib.parse.quote(str(exc))
        return RedirectResponse(url=f"/?google_error={err_msg}#email", status_code=302)


@server_app.post("/api/email/sync")
def api_email_sync() -> Dict[str, Any]:
    return email_sync()


@server_app.post("/api/email/mark_all_read")
def api_email_mark_all_read() -> Dict[str, Any]:
    return email_mark_all_read()


@server_app.post("/api/email/draft")
def api_email_draft(req: EmailDraftRequest) -> Dict[str, Any]:
    return email_draft(req.to, req.subject, req.body)


@server_app.post("/api/email/send")
def api_email_send(req: EmailSendRequest) -> Dict[str, Any]:
    return email_send(req.to, req.subject, req.body, req.draft_id)


@server_app.get("/api/calendar/events")
def api_calendar_events() -> Dict[str, Any]:
    return calendar_list_events()


@server_app.post("/api/calendar/create")
def api_calendar_create(req: CalendarEventRequest) -> Dict[str, Any]:
    if req.sync_to_google:
        from app.tools.calendar_tools import calendar_create_google_event
        return calendar_create_google_event(
            req.title,
            req.start_time,
            req.end_time,
            req.description,
            calendar_id=req.calendar_id or "primary",
            access_token=req.access_token,
        )
    return calendar_create_event(req.title, req.start_time, req.end_time, req.description)


@server_app.delete("/api/calendar/events/{event_id}")
def api_calendar_delete(event_id: int) -> Dict[str, Any]:
    return calendar_delete_event(event_id)


@server_app.post("/api/calendar/google/sync")
def api_calendar_google_sync(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Sync events from Google Calendar (REST API or iCal feed)."""
    from app.tools.calendar_tools import calendar_sync_google
    cal_id = payload.get("calendar_id_or_url") or payload.get("calendar_id") or "primary"
    api_key = payload.get("api_key")
    token = payload.get("access_token")
    return calendar_sync_google(cal_id, api_key=api_key, access_token=token)


@server_app.get("/api/github/issues")
def api_github_issues(
    repo: str = "TejasRK007/local-system-cli", state: str = "open"
) -> Dict[str, Any]:
    return github_list_issues(repo, state=state)


@server_app.post("/api/browser/fetch")
def api_browser_fetch(req: BrowserFetchRequest) -> Dict[str, Any]:
    return browser_fetch_page(req.url, max_chars=req.max_chars)


# -----------------------------------------------------------------------------
# Live Class Dynamic Attendance Endpoints
# -----------------------------------------------------------------------------
@server_app.post("/api/attendance/session/start")
def api_attendance_start(req: AttendanceSessionStartRequest, request: Request) -> Dict[str, Any]:
    c_name = req.course_name or req.course or "Live Classroom"
    rot_val = req.rotation_interval_seconds if req.rotation_interval_seconds is not None else (req.rotation_interval if req.rotation_interval is not None else 1)
    rot = max(1, int(rot_val))
    host = req.host_url or _extract_request_host(request)
    use_tun = req.use_tunnel if req.use_tunnel is not None else True
    return attendance_start_session(
        course_name=c_name,
        section=req.section,
        rotation_interval_seconds=rot,
        host_url=host,
        use_tunnel=use_tun,
    )


@server_app.get("/api/attendance/session/active")
def api_attendance_get_active(request: Request) -> Dict[str, Any]:
    host = _extract_request_host(request)
    return attendance_get_active_session(host_url=host)


@server_app.post("/api/attendance/session/rotate")
def api_attendance_rotate(req: AttendanceRotateRequest, request: Request) -> Dict[str, Any]:
    host = req.host_url or _extract_request_host(request)
    return attendance_rotate_token(req.session_id, host_url=host)


@server_app.post("/api/attendance/session/end")
def api_attendance_end(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    sess_id = (payload or {}).get("session_id")
    stop_tun = (payload or {}).get("stop_tunnel", True)
    return attendance_end_session(sess_id, stop_tunnel=stop_tun)


# -----------------------------------------------------------------------------
# Cloudflare Public Tunnel Control Endpoints
# -----------------------------------------------------------------------------
@server_app.get("/api/tunnel/status")
def api_tunnel_status() -> Dict[str, Any]:
    from app.tunnel import get_tunnel_status
    return get_tunnel_status()


@server_app.post("/api/tunnel/start")
def api_tunnel_start(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.tunnel import get_tunnel_status, start_cloudflare_tunnel
    timeout = float((payload or {}).get("timeout", 14.0))
    url = start_cloudflare_tunnel(port=8000, timeout=timeout)
    return {"success": url is not None, "url": url, "status": get_tunnel_status()}


@server_app.post("/api/tunnel/stop")
def api_tunnel_stop() -> Dict[str, Any]:
    from app.tunnel import get_tunnel_status, stop_cloudflare_tunnel
    stopped = stop_cloudflare_tunnel()
    return {"success": True, "stopped": stopped, "status": get_tunnel_status()}


@server_app.post("/api/attendance/checkin")
def api_attendance_checkin(req: AttendanceCheckinRequest, request: Request) -> Dict[str, Any]:
    dev_id = req.device_id or request.headers.get("x-device-id") or request.cookies.get("device_id")
    return attendance_checkin(
        session_id=req.session_id,
        token=req.token,
        student_id=req.student_id,
        student_name=req.student_name,
        device_info=req.device_info or "Mobile Client",
        device_id=dev_id,
    )


@server_app.get("/api/attendance/export")
def api_attendance_export(session_id: str) -> Response:
    csv_data = attendance_export_csv(session_id)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=attendance_{session_id}.csv"},
    )


@server_app.post("/api/attendance/simulate_scan")
def api_attendance_simulate_scan(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Helper for instructor testing: simulates an instant student scan with the active token."""
    active = attendance_get_active_session()
    if not active.get("active") or not active.get("current_token"):
        raise HTTPException(status_code=400, detail="No active attendance session.")

    sample_names = [
        "Alex Rivera",
        "Priya Sharma",
        "Jordan Lee",
        "Taylor Swift",
        "David Chen",
        "Marcus Vance",
        "Elena Rostova",
        "Liam O'Connor",
    ]
    chosen_name = sample_names[secrets.randbelow(len(sample_names))]
    s_id = f"STU-{secrets.randbelow(8999) + 1000}"

    if payload:
        if payload.get("student_name"):
            chosen_name = payload["student_name"]
        if payload.get("student_id"):
            s_id = payload["student_id"]

    return attendance_checkin(
        session_id=active["session_id"],
        token=active["current_token"],
        student_id=s_id,
        student_name=chosen_name,
        device_info="Classroom Simulator",
    )


@server_app.get("/attendance/checkin", response_class=HTMLResponse)
def serve_student_checkin():
    checkin_file = UI_DIR / "student_checkin.html"
    if checkin_file.exists():
        return FileResponse(str(checkin_file))
    return HTMLResponse("<h3>Student check-in portal under construction.</h3>")


@server_app.get("/attendance/student", response_class=HTMLResponse)
@server_app.get("/attendance/scan", response_class=HTMLResponse)
def serve_student_scanner():
    scanner_file = UI_DIR / "student_scanner.html"
    if scanner_file.exists():
        return FileResponse(str(scanner_file))
    return HTMLResponse("<h3>Student scanner portal under construction.</h3>")


# -----------------------------------------------------------------------------
# Static UI Serving
# -----------------------------------------------------------------------------
if UI_DIR.exists():
    server_app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


@server_app.get("/", response_class=HTMLResponse)
def serve_ui():
    index_file = UI_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("<h1>UI files under construction. Please check back in a moment.</h1>")
