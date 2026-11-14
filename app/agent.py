import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from app.tools.filesystem import search_files
from app.workspaces import Permission, WorkspaceManager

load_dotenv()


tools = [search_files]

llm: Any = None
llm_with_tools: Any = None


from app.llm import get_configured_llm, is_ollama_online


def get_llm() -> Any:
    global llm
    if llm is not None:
        return llm
    provider = os.getenv("LLM_PROVIDER", "").lower()
    if provider == "ollama" and is_ollama_online():
        llm = get_configured_llm()
        return llm
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY environment variable is missing or empty. "
            "Please set GROQ_API_KEY in your environment or .env file."
        )
    llm = ChatGroq(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        api_key=api_key,  # type: ignore[arg-type]
        temperature=0,
    )
    return llm


def get_llm_with_tools() -> Any:
    global llm_with_tools
    if llm_with_tools is not None:
        return llm_with_tools
    current_llm = get_llm()
    llm_with_tools = current_llm.bind_tools(tools)
    return llm_with_tools


KNOWN_DIRECTORIES = {
    "downloads": Path.home() / "Downloads",
    "documents": Path.home() / "Documents",
    "desktop": Path.home() / "Desktop",
}


def extract_intent(request: str) -> dict:
    """
    Understand natural-language task intent using LLM extraction.

    Returns structured dict with action type and extracted parameter strings.
    This function ONLY extracts intent/strings; application code performs validation and execution.
    """
    prompt = f"""
You are an intent extraction component for a local file automation system.

Determine the user's intent and extract relevant fields.

User request:
{request}

Analyze if the request is one of:
- "move": Moving a file from a source location/directory to a destination directory.
- "rename": Renaming a file to a new filename.
- "delete": Deleting or removing a file.
- "search": Searching, finding, or listing files.
- "none": None of the above or unsupported request.

Return ONLY valid JSON matching ONE of the schemas below:

For MOVE requests:
{{
    "action": "move",
    "source": "exact source file path or filename provided in request",
    "destination": "exact destination directory or path provided in request"
}}

For RENAME requests:
{{
    "action": "rename",
    "source": "exact current file path or filename provided in request",
    "new_name": "exact new filename provided in request",
    "directory": "explicit directory if specified, otherwise null"
}}

For DELETE requests:
{{
    "action": "delete",
    "target": "exact file path or filename to delete",
    "directory": "explicit directory if specified, otherwise null"
}}

For SEARCH requests:
{{
    "action": "search",
    "filename": "filename if specified, otherwise null",
    "extension": "file extension if specified (e.g. .pdf), otherwise null",
    "directory": "directory if specified, otherwise null"
}}

For NONE (unrecognized / general question):
{{
    "action": "none"
}}

Rules:
1. Extract exact filenames, file paths, and directory paths as written in the user request.
2. Do NOT restrict directory names to predefined lists.
3. Do NOT invent filenames or directories.
4. Return valid JSON only with no markdown formatting.
"""

    llm_inst = get_llm()
    try:
        response = llm_inst.invoke(prompt)
        content = str(response.content).strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
            content = content.strip()
            if content.startswith("json"):
                content = content[4:].strip()
        return json.loads(content)
    except Exception:
        return {"action": "none"}


def extract_move_request(request: str):
    """Backwards compatibility helper."""
    intent = extract_intent(request)
    if intent.get("action") == "move":
        return {
            "action": "move",
            "filename": intent.get("source"),
            "source_directory": None,
            "destination_directory": intent.get("destination"),
        }
    return {"action": "none"}


def extract_rename_request(request: str):
    """Backwards compatibility helper."""
    intent = extract_intent(request)
    if intent.get("action") == "rename":
        return {
            "action": "rename",
            "filename": intent.get("source"),
            "new_name": intent.get("new_name"),
            "directory": intent.get("directory"),
        }
    return {"action": "none"}


def resolve_directory(dir_str: str | None) -> Path | None:
    """Resolve natural language directory alias, workspace name, or path string."""
    if not dir_str:
        return None
    dir_clean = dir_str.strip().lower()

    # 1. Check configured workspaces first
    ws = WorkspaceManager.get_workspace_by_name(dir_clean)
    if ws:
        return ws.canonical_path

    # 2. Check known static aliases
    if dir_clean in KNOWN_DIRECTORIES:
        return KNOWN_DIRECTORIES[dir_clean]

    # 3. Handle explicit paths
    p = Path(dir_str).expanduser()
    if p.is_absolute():
        return p
    return (Path.cwd() / p).resolve()


def resolve_file_sources(source_str: str, dir_str: str | None = None) -> list[dict]:
    """
    Resolve source_str (which may be a full/relative path or a bare filename)
    to a list of matching file dicts: [{'path': str, 'created': str}, ...].
    """
    if not source_str:
        return []

    source_path = Path(source_str).expanduser()

    # 1. If source_str represents an explicit path (has path separators or is absolute)
    if source_path.is_absolute() or len(source_path.parts) > 1:
        resolved = (
            source_path if source_path.is_absolute() else (Path.cwd() / source_path).resolve()
        )
        if resolved.exists() and resolved.is_file():
            stat = resolved.stat()
            birthtime = getattr(stat, "st_birthtime", None)
            timestamp = birthtime if birthtime is not None else stat.st_ctime
            created_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            return [{"path": str(resolved), "created": created_str}]
        else:
            return []

    # 2. Also check if source_str exists as a file directly in current working directory
    cwd_file = (Path.cwd() / source_str).resolve()
    if cwd_file.exists() and cwd_file.is_file():
        stat = cwd_file.stat()
        birthtime = getattr(stat, "st_birthtime", None)
        timestamp = birthtime if birthtime is not None else stat.st_ctime
        created_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        return [{"path": str(cwd_file), "created": created_str}]

    # 3. Otherwise, treat source_str as a bare filename and search
    filename = source_path.name
    if dir_str:
        resolved_d = resolve_directory(dir_str)
        target_dir = str(resolved_d) if resolved_d else dir_str
        search_res = search_files.invoke(
            {
                "directory": target_dir,
                "extension": "",
                "filename": filename,
                "start_date": "",
                "end_date": "",
            }
        )
        return search_res.get("files", [])
    else:
        matched = []
        if WorkspaceManager.count_workspaces() > 0:
            for ws in WorkspaceManager.list_workspaces(enabled_only=True):
                if Permission.READ.value in ws.permissions:
                    search_res = search_files.invoke(
                        {
                            "directory": str(ws.canonical_path),
                            "extension": "",
                            "filename": filename,
                            "start_date": "",
                            "end_date": "",
                        }
                    )
                    matched.extend(search_res.get("files", []))
        else:
            for d in KNOWN_DIRECTORIES:
                search_res = search_files.invoke(
                    {
                        "directory": d,
                        "extension": "",
                        "filename": filename,
                        "start_date": "",
                        "end_date": "",
                    }
                )
                matched.extend(search_res.get("files", []))
        return matched


def run_agent(request: str):
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_day = datetime.now().strftime("%A")

    intent = extract_intent(request)
    action = intent.get("action")

    # ---------------------------------------------------------
    # MOVE INTENT
    # ---------------------------------------------------------
    if action == "move":
        source_str = intent.get("source") or ""
        dest_str = intent.get("destination") or ""

        if not source_str or not dest_str:
            return "UNSUPPORTED_REQUEST"

        resolved_dest = resolve_directory(dest_str)
        if not resolved_dest:
            return "UNSUPPORTED_REQUEST"

        matched_files = resolve_file_sources(source_str)

        return {
            "action": "move",
            "source_files": matched_files,
            "count": len(matched_files),
            "destination": str(resolved_dest),
            "destination_name": dest_str,
            "directory_specified": bool(len(Path(source_str).parts) > 1),
        }

    # ---------------------------------------------------------
    # RENAME INTENT
    # ---------------------------------------------------------
    if action == "rename":
        source_str = intent.get("source") or ""
        new_name = intent.get("new_name") or ""
        dir_str = intent.get("directory")

        if not source_str or not new_name:
            return "UNSUPPORTED_REQUEST"

        matched_files = resolve_file_sources(source_str, dir_str=dir_str)

        return {
            "action": "rename",
            "source_files": matched_files,
            "count": len(matched_files),
            "new_name": new_name,
            "directory_specified": bool(dir_str or len(Path(source_str).parts) > 1),
        }

    # ---------------------------------------------------------
    # DELETE INTENT
    # ---------------------------------------------------------
    if action == "delete":
        target_str = intent.get("target") or ""
        dir_str = intent.get("directory")

        if not target_str:
            return "UNSUPPORTED_REQUEST"

        matched_files = resolve_file_sources(target_str, dir_str=dir_str)

        return {
            "action": "delete",
            "found": len(matched_files) > 0,
            "count": len(matched_files),
            "files": matched_files,
        }

    # ---------------------------------------------------------
    # SEARCH INTENT — workspace-aware explicit branch
    # ---------------------------------------------------------
    if action == "search":
        filename = intent.get("filename") or ""
        extension = intent.get("extension") or ""
        dir_str = intent.get("directory")

        # Normalize: if the LLM split "m4_test.txt" into filename="m4_test" and
        # extension=".txt", recombine them. search_files does an exact file.name
        # match when filename is set, so the full name is required.
        if filename and extension and not filename.endswith(extension):
            filename = filename + extension
            extension = ""

        if dir_str:
            # Resolve the specified directory through the workspace-aware resolver
            resolved_dir = resolve_directory(dir_str)
            if not resolved_dir:
                return {
                    "action": "search",
                    "found": False,
                    "files": [],
                    "count": 0,
                    "directory": dir_str,
                    "filename": filename,
                    "extension": extension,
                    "start_date": "",
                    "end_date": "",
                    "message": f"Location '{dir_str}' could not be resolved.",
                }
            # Workspace authorization check when workspaces are configured
            if WorkspaceManager.count_workspaces() > 0:
                ok, reason, _ = WorkspaceManager.check_workspace_authorization(
                    resolved_dir, Permission.READ.value
                )
                if not ok:
                    return {
                        "action": "search",
                        "found": False,
                        "files": [],
                        "count": 0,
                        "directory": str(resolved_dir),
                        "filename": filename,
                        "extension": extension,
                        "start_date": "",
                        "end_date": "",
                        "message": f"Search blocked: {reason}",
                    }
            result = search_files.invoke(
                {
                    "directory": str(resolved_dir),
                    "filename": filename,
                    "extension": extension,
                    "start_date": "",
                    "end_date": "",
                }
            )
            return result
        else:
            # No directory specified — search all enabled READ workspaces when configured
            if WorkspaceManager.count_workspaces() > 0:
                matched: list[dict] = []
                for ws in WorkspaceManager.list_workspaces(enabled_only=True):
                    if Permission.READ.value in ws.permissions:
                        res = search_files.invoke(
                            {
                                "directory": str(ws.canonical_path),
                                "filename": filename,
                                "extension": extension,
                                "start_date": "",
                                "end_date": "",
                            }
                        )
                        matched.extend(res.get("files", []))
                return {
                    "action": "search",
                    "found": len(matched) > 0,
                    "count": len(matched),
                    "files": matched,
                    "directory": "configured workspaces",
                    "filename": filename,
                    "extension": extension,
                    "start_date": "",
                    "end_date": "",
                }
            # No workspaces configured — fall through to legacy LLM path below

    # ---------------------------------------------------------
    # NORMAL SEARCH / DELETE AGENT  (legacy / LLM tool-call path)
    # ---------------------------------------------------------

    # Build workspace-aware directory instructions for the LLM prompt
    _ws_count = WorkspaceManager.count_workspaces()
    if _ws_count > 0:
        _ws_lines = "\n".join(
            f"- {ws.name}: {ws.canonical_path}"
            for ws in WorkspaceManager.list_workspaces(enabled_only=True)
            if Permission.READ.value in ws.permissions
        )
        _dir_section = (
            "DIRECTORIES:\n\n"
            "Use only configured workspaces:\n\n"
            f"{_ws_lines}\n\n"
            "For searches with no directory specified, use the first listed workspace."
        )
    else:
        _dir_section = (
            "DIRECTORIES:\n\n"
            "The allowed top-level directories are:\n\n"
            "- Downloads\n"
            "- Documents\n"
            "- Desktop\n\n"
            "These are separate directories.\n\n"
            "For normal searches with no directory specified,\n"
            "use Downloads.\n\n"
            "For specific filename searches with no directory specified,\n"
            "use Downloads."
        )

    system_prompt = f"""
You are the reasoning component of a local computer automation agent.

Today's date is {current_date}.
Today is {current_day}.

Your available tool is:

search_files(
    directory,
    extension,
    filename,
    start_date,
    end_date
)

The tool searches files by:

- filename
- extension
- directory
- creation date

Supported tasks:

1. Find files by extension.
2. Find a specific file by filename.
3. Search configured directories.
4. Filter files by creation date.
5. Understand natural-language dates.
6. Find files for deletion.

{_dir_section}

FILENAME SEARCH:

If the user gives a specific filename, put it in
the filename argument.

DELETE REQUESTS:

If the user asks to delete files,
first use search_files to identify the exact files.

Do NOT delete anything yourself.

The application handles:

- approval
- deletion
- path validation
- verification

DATE SEARCH:

Convert relative dates such as:

- today
- yesterday
- the day before yesterday
- last week

into concrete YYYY-MM-DD dates.

EXTENSION SEARCH:

PDF = .pdf
Word = .docx
Text = .txt

UNSUPPORTED REQUESTS:

If the request is unrelated to the supported
file-management capabilities or is meaningless,
return exactly:

UNSUPPORTED_REQUEST
"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=request),
    ]

    try:
        response = get_llm_with_tools().invoke(messages)
    except ValueError:
        raise
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "rate_limit" in err_str.lower():
            return (
                "Rate limit reached on cloud LLM provider. "
                "Please try again in a few minutes or run 'ollama serve' to use offline local AI."
            )
        return f"AI assistant could not complete request: {err_str}"

    if not response.tool_calls:
        response_text = str(response.content).strip()

        if response_text == "UNSUPPORTED_REQUEST":
            return "UNSUPPORTED_REQUEST"

        unsupported_phrases = [
            "i'm not sure what you're asking",
            "i’m not sure what you’re asking",
            "could you please clarify",
            "i don't understand",
            "i don’t understand",
            "i cannot help",
            "i can't help",
            "i can’t help",
        ]

        response_lower = response_text.lower()

        if any(phrase in response_lower for phrase in unsupported_phrases):
            return "UNSUPPORTED_REQUEST"

        return response.content

    results = []

    for tool_call in response.tool_calls:
        if tool_call["name"] == "search_files":
            result = search_files.invoke(tool_call["args"])

            results.append(result)

    if len(results) == 1:
        return results[0]

    return results
