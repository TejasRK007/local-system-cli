"""
Goal planner for Milestone 5: Intelligent Goal-to-Plan Reasoning.

Transforms high-level declarative user goals into concrete, structured,
workspace-grounded execution plans without direct LLM filesystem writes.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from app.policy import get_action_risk
from app.tasks.validator import PlanValidator
from app.tools.filesystem import search_files
from app.workspaces import Permission, Workspace, WorkspaceManager

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    api_key=os.getenv("GROQ_API_KEY"),  # type: ignore[arg-type]
    temperature=0,
)


@dataclass
class GoalPlan:
    goal: str
    target_workspace: Optional[Workspace]
    discovered_files: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    cumulative_risk: str
    requires_approval: bool
    summary: str


class GoalPlanner:
    """Intelligent planner converting declarative goals into grounded multi-step plans."""

    @classmethod
    def analyze_goal(cls, goal: str) -> dict[str, Any]:
        """
        Analyze a high-level goal using LLM extraction with deterministic regex fallback.

        Extracts:
        - action_type: "organize" | "move" | "delete" | "archive" | "clean" | "search"
          | "rename" | "create_directory"
        - extension: ".pdf" | ".txt" | null
        - keywords: list of search keywords (e.g. ["internship"])
        - target_directory_name: "Internship" | "Archive" | null
        - target_workspace_name: explicit workspace name if given | null
        - source_workspace_name: source workspace for cross-workspace moves | null
        - target_workspace_names: list of workspaces for multi-workspace search
        """
        prompt = f"""
You are a goal analysis component for a local file automation system.

Given a user's high-level goal, extract the planning intent into valid JSON.

User goal:
{goal}

Return ONLY valid JSON matching this schema:
{{
    "action_type": "organize" | "move" | "delete" | "archive" | "clean" | "search"
                   | "rename" | "create_directory",
    "extension": "file extension like .pdf or .txt or .py if specified, otherwise null",
    "filename": "specific filename or existing source file for rename, otherwise null",
    "new_filename": "new filename for rename action, otherwise null",
    "keywords": ["list of keyword strings identifying target files"],
    "target_directory_name": "folder name to create or move files into, otherwise null",
    "target_workspace_name": "workspace name if explicitly specified, otherwise null"
}}

Rules:
1. For rename actions, "filename" is the existing source file to rename,
   and "new_filename" is the new/target filename.
2. For create_directory actions, "target_directory_name" is the folder to create,
   and "target_workspace_name" is where to create it.
3. Do NOT invent filenames. Only extract search criteria.
4. Return JSON only with no markdown formatting.
"""
        try:
            res = llm.invoke(prompt)
            content = str(res.content).strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]
                if content.endswith("```"):
                    content = content.rsplit("```", 1)[0]
                content = content.strip()
                if content.startswith("json"):
                    content = content[4:].strip()
            data = json.loads(content)
            if isinstance(data, dict):
                # Ensure rename intent extracts both source and destination cleanly
                is_rename_cmd = bool(
                    (
                        data.get("action_type") == "rename"
                        or re.search(r"^\s*(?:please\s+)?rename\b", goal, re.IGNORECASE)
                        or re.search(r"\brename\b(?:\s+the\s+file)?\s+", goal, re.IGNORECASE)
                    )
                    and not re.search(
                        r"\b(?:move|delete|remove|clean|find|search|show|list|locate)\b",
                        goal,
                        re.IGNORECASE,
                    )
                )
                if is_rename_cmd:
                    data["action_type"] = "rename"
                    heur = cls._heuristic_goal_analysis(goal)
                    if not data.get("filename") and heur.get("filename"):
                        data["filename"] = heur["filename"]
                    if not data.get("new_filename") and heur.get("new_filename"):
                        data["new_filename"] = heur["new_filename"]
                    if not data.get("target_workspace_name") and heur.get("target_workspace_name"):
                        data["target_workspace_name"] = heur["target_workspace_name"]
                    data["target_directory_name"] = None
                elif data.get("action_type") == "create_directory" or any(
                    w in goal.lower()
                    for w in (
                        "create a folder",
                        "make a directory",
                        "create folder",
                        "make folder",
                        "mkdir",
                    )
                ):
                    heur = cls._heuristic_goal_analysis(goal)
                    data["action_type"] = "create_directory"
                    if not data.get("target_directory_name") and heur.get("target_directory_name"):
                        data["target_directory_name"] = heur["target_directory_name"]
                    if not data.get("target_workspace_name") and heur.get("target_workspace_name"):
                        data["target_workspace_name"] = heur["target_workspace_name"]
                else:
                    # For all other actions (move, delete, search, organize, etc.),
                    # merge heuristic-extracted fields the LLM prompt doesn't cover.
                    heur = cls._heuristic_goal_analysis(goal)
                    if not data.get("filename") and heur.get("filename"):
                        data["filename"] = heur["filename"]
                    if not data.get("source_workspace_name") and heur.get("source_workspace_name"):
                        data["source_workspace_name"] = heur["source_workspace_name"]
                    if not data.get("target_workspace_name") and heur.get("target_workspace_name"):
                        data["target_workspace_name"] = heur["target_workspace_name"]
                    if not data.get("target_workspace_names") and heur.get(
                        "target_workspace_names"
                    ):
                        data["target_workspace_names"] = heur["target_workspace_names"]
                    if not data.get("target_directory_name") and heur.get("target_directory_name"):
                        data["target_directory_name"] = heur["target_directory_name"]
                    # Prefer heuristic action_type for cross-workspace moves or move goals
                    if heur.get("source_workspace_name") and heur.get("target_workspace_name"):
                        data["action_type"] = heur["action_type"]
                    elif (
                        data.get("action_type") in ("archive", "rename")
                        and re.search(r"\bmove\b", goal, re.IGNORECASE)
                    ):
                        data["action_type"] = "move"

                    # Sanitize keywords so workspace names are not used as file search filters
                    excluded_words = {
                        w.lower()
                        for w in (
                            data.get("target_workspace_name"),
                            data.get("source_workspace_name"),
                            heur.get("target_workspace_name"),
                            heur.get("source_workspace_name"),
                        )
                        if w
                    }
                    for w_obj in WorkspaceManager.list_workspaces():
                        excluded_words.add(w_obj.name.lower())
                    if data.get("target_workspace_names"):
                        for twn in data["target_workspace_names"]:
                            excluded_words.add(twn.lower())
                    if heur.get("target_workspace_names"):
                        for twn in heur["target_workspace_names"]:
                            excluded_words.add(twn.lower())

                    if data.get("keywords"):
                        data["keywords"] = [
                            k for k in data["keywords"] if k.lower() not in excluded_words
                        ]
                return data
        except Exception:
            pass

        # Deterministic regex heuristic fallback
        return cls._heuristic_goal_analysis(goal)

    @classmethod
    def _heuristic_goal_analysis(cls, goal: str) -> dict[str, Any]:
        """Fallback analysis for offline, missing API keys, or mocked tests."""
        goal_lower = goal.lower()

        # 1. Handle standalone directory creation goals
        if (
            re.search(r"\b(?:create|make|mkdir)\b.*?\b(?:folder|directory)\b", goal_lower)
            or re.search(r"\bmkdir\s+", goal_lower)
        ):
            target_ws = None
            for ws in WorkspaceManager.list_workspaces():
                if re.search(r"\b" + re.escape(ws.name) + r"\b", goal, re.IGNORECASE):
                    target_ws = ws.name
                    break

            target_dir = None
            m_named = re.search(
                r"\b(?:called|named)\s+[\"']?([A-Za-z0-9_\-\.\/]+)[\"']?",
                goal,
                re.IGNORECASE,
            )
            if m_named:
                target_dir = m_named.group(1).strip()
            else:
                m_folder = re.search(
                    r"\b(?:folder|directory|mkdir)\s+[\"']?([A-Za-z0-9_\-\.\/]+)[\"']?",
                    goal,
                    re.IGNORECASE,
                )
                if m_folder:
                    cand = m_folder.group(1).strip()
                    if cand.lower() not in (
                        "called",
                        "named",
                        "an",
                        "the",
                        "a",
                        "in",
                        "inside",
                        "under",
                        "workspace",
                    ):
                        target_dir = cand

            return {
                "action_type": "create_directory",
                "extension": None,
                "filename": None,
                "new_filename": None,
                "keywords": [],
                "target_directory_name": target_dir,
                "target_workspace_name": target_ws,
                "source_workspace_name": None,
                "target_workspace_names": [target_ws] if target_ws else [],
            }

        # 2. Handle rename goals specifically with robust quote and space parsing
        m_action = re.search(r"\brename\b(?:\s+the\s+file)?\s+", goal, re.IGNORECASE)
        is_conflicting_verb = bool(
            re.search(
                r"\b(?:move|delete|remove|clean|find|search|show|list|locate)\b",
                goal,
                re.IGNORECASE,
            )
        )
        if m_action and not is_conflicting_verb:
            target_ws = None
            for ws in WorkspaceManager.list_workspaces():
                if ws.name.lower() in goal_lower:
                    target_ws = ws.name
                    break

            source_filename = None
            new_filename = None

            m_action = re.search(r"\brename\b(?:\s+the\s+file)?\s+", goal, re.IGNORECASE)
            if m_action:
                rest = goal[m_action.end():].strip()

                # Trailing workspace: "in/inside/under/from [workspace]"
                ws_match = re.search(
                    r"\s+\b(?:in|inside|under|from)\s+(?:workspace\s+)?([A-Za-z0-9_\-]+)\s*$",
                    rest,
                    re.IGNORECASE,
                )
                if ws_match:
                    possible_ws = ws_match.group(1).strip()
                    if not target_ws:
                        target_ws = possible_ws
                    rest = rest[: ws_match.start()].strip()

                # 1. Quoted source and quoted dest: "src" to "dst"
                m_both = re.match(
                    r"^[\"'](.+?)[\"']\s+\b(?:to|as)\b\s+[\"'](.+?)[\"']$",
                    rest,
                    re.IGNORECASE,
                )
                if m_both:
                    source_filename = m_both.group(1).strip()
                    new_filename = m_both.group(2).strip()
                else:
                    # 2. Quoted source and unquoted dest: "src" to dst
                    m_src = re.match(
                        r"^[\"'](.+?)[\"']\s+\b(?:to|as)\b\s+(.+)$",
                        rest,
                        re.IGNORECASE,
                    )
                    if m_src:
                        source_filename = m_src.group(1).strip()
                        new_filename = m_src.group(2).strip().strip("\"'")
                    else:
                        # 3. Unquoted source and quoted dest: src to "dst"
                        m_dst = re.match(
                            r"^(.+?)\s+\b(?:to|as)\b\s+[\"'](.+?)[\"']$",
                            rest,
                            re.IGNORECASE,
                        )
                        if m_dst:
                            source_filename = m_dst.group(1).strip().strip("\"'")
                            new_filename = m_dst.group(2).strip()
                        else:
                            # 4. Neither quoted: split by " to " or " as "
                            m_unq = re.split(
                                r"\s+\b(?:to|as)\b\s+", rest, maxsplit=1, flags=re.IGNORECASE
                            )
                            if len(m_unq) == 2:
                                source_filename = m_unq[0].strip().strip("\"'")
                                new_filename = m_unq[1].strip().strip("\"'")

            ext = (
                Path(source_filename).suffix
                if source_filename and "." in source_filename
                else None
            )

            return {
                "action_type": "rename",
                "extension": ext,
                "filename": source_filename,
                "new_filename": new_filename,
                "keywords": [],
                "target_directory_name": None,
                "target_workspace_name": target_ws,
                "source_workspace_name": None,
                "target_workspace_names": [target_ws] if target_ws else [],
            }

        # 3. Check for cross-workspace move e.g. "Move the PDF files from Downloads into Documents"
        source_ws = None
        target_ws = None
        m_cross = re.search(
            r"\bfrom\s+([A-Za-z0-9_\-]+)\s+(?:in)?to\s+([A-Za-z0-9_\-]+)",
            goal,
            re.IGNORECASE,
        )
        if m_cross:
            raw_from = m_cross.group(1).strip()
            raw_to = m_cross.group(2).strip()
            ws_from = WorkspaceManager.get_workspace_by_name(raw_from)
            ws_to = WorkspaceManager.get_workspace_by_name(raw_to)
            # Pass raw names even if one doesn't exist, so plan_goal
            # can produce proper "not configured" errors.
            source_ws = ws_from.name if ws_from else raw_from
            target_ws = ws_to.name if ws_to else raw_to

        # 4. Detect action type
        if "delete" in goal_lower or "remove" in goal_lower or "clean" in goal_lower:
            action_type = "delete"
        elif source_ws and target_ws:
            action_type = "move"
        elif "move" in goal_lower:
            action_type = "move"
        elif "organize" in goal_lower:
            action_type = "organize"
        elif "archive" in goal_lower:
            action_type = "archive"
        elif "into" in goal_lower:
            action_type = "move"
        elif any(v in goal_lower for v in ("find", "search", "show me", "show", "list", "locate")):
            action_type = "search"
        else:
            action_type = "organize"

        # Detect specific filename if given, e.g. "Find m4_test.txt"
        filename = None
        m_file = re.search(r"\b([A-Za-z0-9_\-]+\.[A-Za-z0-9]+)\b", goal)
        if m_file:
            cand = m_file.group(1).strip()
            if not cand.startswith(".") and "." in cand:
                filename = cand

        # Detect extension
        ext = None
        for candidate_ext in (".pdf", ".docx", ".txt", ".png", ".jpg", ".csv", ".xlsx", ".py"):
            if candidate_ext in goal_lower or candidate_ext[1:] in goal_lower:
                ext = candidate_ext
                break
        if not ext:
            if "pdf" in goal_lower:
                ext = ".pdf"
            elif "text" in goal_lower or "txt" in goal_lower:
                ext = ".txt"
            elif "word" in goal_lower or "docx" in goal_lower:
                ext = ".docx"
            elif "python" in goal_lower or "py" in goal_lower.split():
                ext = ".py"
            elif filename:
                ext = Path(filename).suffix

        # Detect target directory name e.g. "into an Internship folder", "into Internship"
        target_dir = None
        if not (source_ws and target_ws):
            m_dir = re.search(
                r"(?:into|to)\s+(?:(?:an?|the)\s+)?([A-Za-z0-9_\-]+)\s*(?:folder|directory)?",
                goal,
                re.IGNORECASE,
            )
            if m_dir:
                matched_name = m_dir.group(1).strip()
                if matched_name.lower() not in (
                    "folder",
                    "directory",
                    "an",
                    "the",
                    "a",
                    "workspace",
                ):
                    matched_ws_obj = WorkspaceManager.get_workspace_by_name(matched_name)
                    if matched_ws_obj:
                        # Destination is an existing workspace, not a subfolder to create!
                        target_ws = matched_ws_obj.name
                    else:
                        target_dir = matched_name

        # Detect keywords e.g. "internship", "report", "invoice", "resume"
        keywords = []
        tokens = re.findall(r"\b[A-Za-z0-9_\-]{3,}\b", goal)
        stop_words = {
            "organize",
            "move",
            "into",
            "folder",
            "directory",
            "files",
            "file",
            "all",
            "and",
            "the",
            "for",
            "from",
            "with",
            "clean",
            "delete",
            "archive",
            "pdfs",
            "documents",
            "workspace",
            "manual",
            "find",
            "search",
            "show",
            "list",
            "locate",
            "me",
            "my",
            "python",
            "txt",
            "pdf",
            "docx",
        }

        # Detect all explicitly mentioned workspaces
        target_workspaces: list[str] = []
        for ws in WorkspaceManager.list_workspaces():
            if re.search(r"\b" + re.escape(ws.name) + r"\b", goal, re.IGNORECASE):
                target_workspaces.append(ws.name)

        # Multi-workspace e.g. "in MultiOne and MultiTwo"
        m_multi = re.search(
            r"\b(?:in|inside|from)\s+([A-Za-z0-9_\-]+)\s+and\s+([A-Za-z0-9_\-]+)",
            goal,
            re.IGNORECASE,
        )
        if m_multi:
            cand1, cand2 = m_multi.group(1).strip(), m_multi.group(2).strip()
            for cand in (cand1, cand2):
                if cand.lower() not in stop_words and cand not in target_workspaces:
                    target_workspaces.append(cand)

        # Single trailing workspace e.g. "in SecretWs", "in MvColWs", "from DelMultiWs"
        if not target_ws:
            m_single_ws = re.search(
                r"\s+\b(?:in|inside|under|from)\s+(?:workspace\s+)?([A-Za-z0-9_\-]+)\s*$",
                goal,
                re.IGNORECASE,
            )
            if m_single_ws:
                cand = m_single_ws.group(1).strip()
                if cand.lower() not in (
                    "folder",
                    "directory",
                    "an",
                    "the",
                    "a",
                    "workspace",
                    "here",
                    "subfolder",
                    "dir",
                ) and cand.lower() not in stop_words:
                    if not (target_dir and cand.lower() == target_dir.lower()):
                        target_ws = cand
                        if cand not in target_workspaces:
                            target_workspaces.append(cand)

        if not target_ws and target_workspaces:
            if len(target_workspaces) == 1:
                target_ws = target_workspaces[0]

        # Collect workspace names for exclusion from keywords
        ws_name_set = {ws.name.lower() for ws in WorkspaceManager.list_workspaces()}
        if target_ws:
            ws_name_set.add(target_ws.lower())
        for ws_n in target_workspaces:
            ws_name_set.add(ws_n.lower())
        if source_ws:
            ws_name_set.add(source_ws.lower())

        for t in tokens:
            t_lower = t.lower()
            if filename and t_lower in filename.lower():
                continue
            if t_lower in ws_name_set:
                continue
            if t_lower not in stop_words and t_lower != (ext[1:] if ext else ""):
                keywords.append(t_lower)

        return {
            "action_type": action_type,
            "extension": ext,
            "filename": filename,
            "keywords": keywords,
            "target_directory_name": target_dir,
            "target_workspace_name": target_ws,
            "source_workspace_name": source_ws,
            "target_workspace_names": target_workspaces,
        }

    @classmethod
    def plan_goal(cls, goal: str) -> GoalPlan:
        """
        Synthesize a validated GoalPlan grounded in real workspace files.
        """
        if WorkspaceManager.count_workspaces() == 0:
            return GoalPlan(
                goal=goal,
                target_workspace=None,
                discovered_files=[],
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary="No workspaces configured. Please configure an authorized workspace first.",
            )

        analysis = cls.analyze_goal(goal)
        action_type = analysis.get("action_type", "organize")
        ext = analysis.get("extension") or ""
        filename = analysis.get("filename") or ""
        new_filename = analysis.get("new_filename") or ""
        keywords = analysis.get("keywords") or []
        target_dir_name = analysis.get("target_directory_name")
        explicit_ws_name = analysis.get("target_workspace_name")
        source_ws_name = analysis.get("source_workspace_name")
        target_ws_names = analysis.get("target_workspace_names") or []

        # 1. Determine active workspace(s)
        enabled_workspaces = WorkspaceManager.list_workspaces(enabled_only=True)
        read_workspaces = [w for w in enabled_workspaces if Permission.READ.value in w.permissions]

        target_workspace = None
        search_scope: list[Workspace] = []

        # Special handling for standalone directory creation
        if action_type == "create_directory":
            target_ws_obj = (
                WorkspaceManager.get_workspace_by_name(explicit_ws_name)
                if explicit_ws_name
                else (read_workspaces[0] if read_workspaces else None)
            )
            return cls._plan_create_directory_goal(
                goal=goal,
                target_dir_name=target_dir_name,
                target_workspace=target_ws_obj,
                explicit_ws_name=explicit_ws_name,
            )

        # Cross-workspace move handling
        if source_ws_name and explicit_ws_name:
            ws_from = WorkspaceManager.get_workspace_by_name(source_ws_name)
            ws_to = WorkspaceManager.get_workspace_by_name(explicit_ws_name)
            if not ws_from or not ws_to:
                missing = source_ws_name if not ws_from else explicit_ws_name
                return GoalPlan(
                    goal=goal,
                    target_workspace=None,
                    discovered_files=[],
                    steps=[],
                    cumulative_risk="low",
                    requires_approval=False,
                    summary=f"Workspace '{missing}' is not configured or unauthorized.",
                )
            if not ws_from.enabled:
                return GoalPlan(
                    goal=goal,
                    target_workspace=ws_from,
                    discovered_files=[],
                    steps=[],
                    cumulative_risk="low",
                    requires_approval=False,
                    summary=f"Workspace '{ws_from.name}' is currently disabled.",
                )
            if not ws_to.enabled:
                return GoalPlan(
                    goal=goal,
                    target_workspace=ws_to,
                    discovered_files=[],
                    steps=[],
                    cumulative_risk="low",
                    requires_approval=False,
                    summary=f"Workspace '{ws_to.name}' is currently disabled.",
                )
            if Permission.READ.value not in ws_from.permissions:
                return GoalPlan(
                    goal=goal,
                    target_workspace=ws_from,
                    discovered_files=[],
                    steps=[],
                    cumulative_risk="low",
                    requires_approval=False,
                    summary=f"Workspace '{ws_from.name}' lacks READ permission.",
                )
            if Permission.WRITE.value not in ws_to.permissions:
                return GoalPlan(
                    goal=goal,
                    target_workspace=ws_to,
                    discovered_files=[],
                    steps=[],
                    cumulative_risk="medium",
                    requires_approval=True,
                    summary=(
                        f"Workspace '{ws_to.name}' lacks WRITE permission required to move files."
                    ),
                )
            search_scope = [ws_from]
            target_workspace = ws_to
            # Clear target_dir_name: for cross-workspace moves, the destination
            # is the workspace root — not a subdirectory named after the workspace.
            if target_dir_name and target_dir_name.lower() == ws_to.name.lower():
                target_dir_name = None

        # Multi-workspace search handling (when multiple workspaces are specified)
        elif action_type == "search" and len(target_ws_names) > 1:
            search_scope = [
                w for w in enabled_workspaces
                if w.name in target_ws_names and Permission.READ.value in w.permissions
            ]
            if search_scope:
                target_workspace = search_scope[0]
            elif read_workspaces:
                search_scope = read_workspaces
                target_workspace = read_workspaces[0]
            else:
                return GoalPlan(
                    goal=goal,
                    target_workspace=None,
                    discovered_files=[],
                    steps=[],
                    cumulative_risk="low",
                    requires_approval=False,
                    summary="No enabled workspaces with READ permission are available.",
                )
        elif explicit_ws_name:
            ws_found = WorkspaceManager.get_workspace_by_name(explicit_ws_name)
            if ws_found:
                if not ws_found.enabled:
                    return GoalPlan(
                        goal=goal,
                        target_workspace=ws_found,
                        discovered_files=[],
                        steps=[],
                        cumulative_risk="low",
                        requires_approval=False,
                        summary=f"Workspace '{explicit_ws_name}' is currently disabled.",
                    )
                if Permission.READ.value not in ws_found.permissions:
                    return GoalPlan(
                        goal=goal,
                        target_workspace=ws_found,
                        discovered_files=[],
                        steps=[],
                        cumulative_risk="low",
                        requires_approval=False,
                        summary=f"Workspace '{explicit_ws_name}' lacks READ permission.",
                    )
                target_workspace = ws_found
                search_scope = [ws_found]
            else:
                return GoalPlan(
                    goal=goal,
                    target_workspace=None,
                    discovered_files=[],
                    steps=[],
                    cumulative_risk="low",
                    requires_approval=False,
                    summary=f"Workspace '{explicit_ws_name}' is not configured or unauthorized.",
                )
        elif not read_workspaces:
            return GoalPlan(
                goal=goal,
                target_workspace=None,
                discovered_files=[],
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary="No enabled workspaces with READ permission are available.",
            )
        else:
            search_scope = read_workspaces
            target_workspace = read_workspaces[0]

        # Special handling for rename goals
        if action_type == "rename":
            return cls._plan_rename_goal(
                goal=goal,
                filename=filename,
                new_filename=new_filename,
                search_scope=search_scope,
                default_target_ws=target_workspace,
                explicit_ws_name=explicit_ws_name,
            )

        # 2. Inspect real filesystem across authorized workspace(s)
        discovered_files: list[dict[str, Any]] = []
        for ws in search_scope:
            res = search_files.invoke(
                {
                    "directory": str(ws.canonical_path),
                    "extension": ext,
                    "filename": filename,
                    "start_date": "",
                    "end_date": "",
                }
            )
            for f in res.get("files", []):
                p = Path(f["path"])
                # Filter by keyword if keywords are specified and no specific filename was requested
                if keywords and not filename:
                    p_name_lower = p.name.lower()
                    p_stem_lower = p.stem.lower()
                    matched = False
                    for k in keywords:
                        if k in p_name_lower:
                            matched = True
                            break
                        if len(k) >= 4 and p_stem_lower.startswith(k[:4]):
                            matched = True
                            break
                        if len(k) >= 4:
                            for part in p_stem_lower.split("_"):
                                if len(part) >= 3 and part.startswith(k[:4]):
                                    matched = True
                                    break
                        if matched:
                            break
                    if matched:
                        # Avoid adding files already in the target directory
                        if target_dir_name and target_dir_name.lower() in [
                            part.lower() for part in p.parts
                        ]:
                            continue
                        discovered_files.append(f)
                else:
                    if target_dir_name and target_dir_name.lower() in [
                        part.lower() for part in p.parts
                    ]:
                        continue
                    discovered_files.append(f)

        # 3. Handle zero matching files (safe no-op)
        if not discovered_files:
            return GoalPlan(
                goal=goal,
                target_workspace=target_workspace,
                discovered_files=[],
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=(
                    "No matching files were found in the authorized workspaces. "
                    "No changes were made."
                ),
            )

        # Require disambiguation if specific single filename targeted & multiple matches exist
        if (
            filename
            and len(discovered_files) > 1
            and action_type in ("move", "organize", "delete", "archive", "clean")
        ):
            matches_str = ", ".join(f["path"] for f in discovered_files)
            return GoalPlan(
                goal=goal,
                target_workspace=target_workspace,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=(
                    f"Ambiguous {action_type} goal: found {len(discovered_files)} matching files "
                    f"({matches_str}). Please specify the exact workspace or directory."
                ),
            )

        # Ensure target workspace has WRITE permission if modifying files
        if (
            target_workspace
            and Permission.WRITE.value not in target_workspace.permissions
            and action_type in ("organize", "move", "archive")
        ):
            return GoalPlan(
                goal=goal,
                target_workspace=target_workspace,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk="medium",
                requires_approval=True,
                summary=(
                    f"Workspace '{target_workspace.name}' lacks WRITE permission "
                    f"required to {action_type} files."
                ),
            )

        # Ensure target workspace has DELETE permission if deleting files
        if (
            target_workspace
            and Permission.DELETE.value not in target_workspace.permissions
            and action_type in ("delete", "clean")
        ):
            return GoalPlan(
                goal=goal,
                target_workspace=target_workspace,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk="high",
                requires_approval=True,
                summary=(
                    f"Workspace '{target_workspace.name}' lacks DELETE permission "
                    "required to delete files."
                ),
            )

        # 4. Plan Synthesis
        steps: list[dict[str, Any]] = []
        step_order = 1

        if action_type in ("organize", "move", "archive"):
            assert target_workspace is not None
            if target_dir_name:
                target_dir_path = target_workspace.canonical_path / target_dir_name
                dir_exists = target_dir_path.exists() and target_dir_path.is_dir()

                # Step 1: create_directory
                steps.append(
                    {
                        "step_order": step_order,
                        "action": "create_directory",
                        "arguments": {
                            "directory": str(target_dir_path),
                        },
                        "depends_on_order": None,
                    }
                )
                dir_step_order = step_order
                step_order += 1
                dst_arg = f"$output.step_{dir_step_order}.path"
                dep_order: Optional[int] = dir_step_order
            else:
                target_dir_path = target_workspace.canonical_path
                dir_exists = True
                dst_arg = str(target_dir_path)
                dep_order = None

            planned_names: set[str] = set()
            if dir_exists and target_dir_path.exists():
                planned_names.update(
                    f.name.lower() for f in target_dir_path.iterdir() if f.is_file()
                )

            skipped_due_to_collision = 0
            for file_info in discovered_files:
                src_path = Path(file_info["path"])
                if src_path.name.lower() in planned_names:
                    skipped_due_to_collision += 1
                    continue
                planned_names.add(src_path.name.lower())

                steps.append(
                    {
                        "step_order": step_order,
                        "action": "move",
                        "arguments": {
                            "source": file_info["path"],
                            "destination": dst_arg,
                        },
                        "depends_on_order": dep_order,
                    }
                )
                step_order += 1

            if not steps or (target_dir_name and len(steps) == 1):
                if skipped_due_to_collision > 0:
                    return GoalPlan(
                        goal=goal,
                        target_workspace=target_workspace,
                        discovered_files=discovered_files,
                        steps=[],
                        cumulative_risk="low",
                        requires_approval=False,
                        summary=(
                            f"Destination collision: file(s) with matching names "
                            f"already exist in '{target_dir_path}'."
                        ),
                    )

        elif action_type in ("delete", "clean"):
            for file_info in discovered_files:
                steps.append(
                    {
                        "step_order": step_order,
                        "action": "delete",
                        "arguments": {
                            "target": file_info["path"],
                        },
                        "depends_on_order": None,
                    }
                )
                step_order += 1

        elif action_type == "search":
            for ws in search_scope:
                search_args: dict[str, Any] = {
                    "directory": str(ws.canonical_path),
                }
                if ext:
                    search_args["extension"] = ext
                if filename:
                    search_args["filename"] = filename
                if keywords:
                    search_args["query"] = " ".join(keywords)
                steps.append(
                    {
                        "step_order": step_order,
                        "action": "search",
                        "arguments": search_args,
                        "depends_on_order": None,
                    }
                )
                step_order += 1

        # 5. Calculate cumulative plan risk
        plan_risk = cls.calculate_plan_risk(steps)
        req_approval = plan_risk in ("medium", "high")

        # 6. Validate synthesized plan
        valid, val_reason = PlanValidator.validate_plan(steps)
        if not valid:
            return GoalPlan(
                goal=goal,
                target_workspace=target_workspace,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk=plan_risk,
                requires_approval=req_approval,
                summary=f"Plan rejected by policy: {val_reason}",
            )

        summary_msg = (
            f"Generated {len(steps)} steps to {action_type} {len(discovered_files)} file(s)."
        )
        return GoalPlan(
            goal=goal,
            target_workspace=target_workspace,
            discovered_files=discovered_files,
            steps=steps,
            cumulative_risk=plan_risk,
            requires_approval=req_approval,
            summary=summary_msg,
        )

    @classmethod
    def calculate_plan_risk(cls, steps: list[dict[str, Any]]) -> str:
        """
        Calculate cumulative plan risk.
        If any step is HIGH (delete) -> HIGH
        If any step is MEDIUM (create_directory, move, rename) -> MEDIUM
        Otherwise -> LOW
        """
        has_high = False
        has_medium = False

        for step in steps:
            act = step.get("action", "")
            risk = get_action_risk(act)
            if risk == "high":
                has_high = True
            elif risk == "medium":
                has_medium = True

        if has_high:
            return "high"
        if has_medium:
            return "medium"
        return "low"

    @classmethod
    def _plan_create_directory_goal(
        cls,
        goal: str,
        target_dir_name: Optional[str],
        target_workspace: Optional[Workspace],
        explicit_ws_name: Optional[str] = None,
    ) -> GoalPlan:
        """
        Synthesize a grounded GoalPlan specifically for creating a controlled directory.
        """
        if not target_dir_name:
            return GoalPlan(
                goal=goal,
                target_workspace=target_workspace,
                discovered_files=[],
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary="Could not determine folder or directory name to create.",
            )

        if not target_workspace:
            return GoalPlan(
                goal=goal,
                target_workspace=None,
                discovered_files=[],
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=f"Workspace '{explicit_ws_name}' is not configured or unauthorized."
                if explicit_ws_name
                else "No authorized workspace specified for directory creation.",
            )

        if not target_workspace.enabled:
            return GoalPlan(
                goal=goal,
                target_workspace=target_workspace,
                discovered_files=[],
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=f"Workspace '{target_workspace.name}' is currently disabled.",
            )

        if Permission.WRITE.value not in target_workspace.permissions:
            return GoalPlan(
                goal=goal,
                target_workspace=target_workspace,
                discovered_files=[],
                steps=[],
                cumulative_risk="medium",
                requires_approval=True,
                summary=(
                    f"Workspace '{target_workspace.name}' lacks WRITE permission "
                    "required to create directories."
                ),
            )

        target_path = Path(target_dir_name).expanduser()
        if target_path.is_absolute():
            target_dir_path = target_path.resolve()
        else:
            target_dir_path = (target_workspace.canonical_path / target_path).resolve()

        safe_ok, safe_reason = PlanValidator._check_path_safety(target_dir_path)
        if not safe_ok:
            return GoalPlan(
                goal=goal,
                target_workspace=target_workspace,
                discovered_files=[],
                steps=[],
                cumulative_risk="medium",
                requires_approval=True,
                summary=f"Target directory path unsafe: {safe_reason}",
            )

        if not WorkspaceManager._is_subpath(target_dir_path, target_workspace.canonical_path):
            return GoalPlan(
                goal=goal,
                target_workspace=target_workspace,
                discovered_files=[],
                steps=[],
                cumulative_risk="medium",
                requires_approval=True,
                summary=(
                    f"Path is outside configured workspace '{target_workspace.name}': "
                    f"{target_dir_path}"
                ),
            )

        if target_dir_path.exists() and target_dir_path.is_file():
            return GoalPlan(
                goal=goal,
                target_workspace=target_workspace,
                discovered_files=[],
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=f"Cannot create directory: a file already exists at '{target_dir_path}'.",
            )

        steps = [
            {
                "step_order": 1,
                "action": "create_directory",
                "arguments": {
                    "directory": str(target_dir_path),
                },
                "depends_on_order": None,
            }
        ]

        plan_risk = cls.calculate_plan_risk(steps)
        req_approval = plan_risk in ("medium", "high")

        valid, val_reason = PlanValidator.validate_plan(steps)
        if not valid:
            return GoalPlan(
                goal=goal,
                target_workspace=target_workspace,
                discovered_files=[],
                steps=[],
                cumulative_risk=plan_risk,
                requires_approval=req_approval,
                summary=f"Plan rejected by policy: {val_reason}",
            )

        summary_msg = (
            f"Generated 1 step to create directory '{target_dir_path.name}' "
            f"in workspace '{target_workspace.name}'."
        )
        return GoalPlan(
            goal=goal,
            target_workspace=target_workspace,
            discovered_files=[],
            steps=steps,
            cumulative_risk=plan_risk,
            requires_approval=req_approval,
            summary=summary_msg,
        )

    @classmethod
    def _plan_rename_goal(
        cls,
        goal: str,
        filename: str,
        new_filename: str,
        search_scope: list[Workspace],
        default_target_ws: Optional[Workspace],
        explicit_ws_name: Optional[str] = None,
    ) -> GoalPlan:
        """
        Synthesize a grounded GoalPlan specifically for renaming an existing file.
        """
        if not filename or not new_filename or new_filename in (".", ".."):
            return GoalPlan(
                goal=goal,
                target_workspace=default_target_ws,
                discovered_files=[],
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=f"Invalid rename target filename '{new_filename}'."
                if new_filename in (".", "..")
                else "Could not determine source and destination filenames for rename goal.",
            )

        # Disallow path separators in new_name
        if "/" in new_filename or "\\" in new_filename:
            return GoalPlan(
                goal=goal,
                target_workspace=default_target_ws,
                discovered_files=[],
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=f"Rename target name '{new_filename}' must not contain path separators.",
            )

        # 1. Discover the EXISTING source file across authorized workspace(s)
        discovered_files: list[dict[str, Any]] = []
        src_path_obj = Path(filename).expanduser()

        if src_path_obj.is_absolute() and src_path_obj.exists() and src_path_obj.is_file():
            ws_match = WorkspaceManager.find_workspace_for_path(src_path_obj)
            if ws_match and (
                not explicit_ws_name
                or ws_match.name.lower() == explicit_ws_name.lower()
            ):
                discovered_files.append(
                    {"path": str(src_path_obj.resolve()), "name": src_path_obj.name}
                )
        else:
            search_fn = src_path_obj.name if ("/" in filename or "\\" in filename) else filename
            search_ext = src_path_obj.suffix if "." in search_fn else ""
            for ws in search_scope:
                res = search_files.invoke(
                    {
                        "directory": str(ws.canonical_path),
                        "extension": search_ext,
                        "filename": search_fn,
                        "start_date": "",
                        "end_date": "",
                    }
                )
                for f in res.get("files", []):
                    if Path(f["path"]).name.lower() == search_fn.lower():
                        discovered_files.append(f)

        # 2. Zero matches -> safe no-op
        if not discovered_files:
            return GoalPlan(
                goal=goal,
                target_workspace=default_target_ws,
                discovered_files=[],
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=(
                    f"No matching file '{filename}' was found in the authorized workspaces. "
                    "No changes were made."
                ),
            )

        # 3. Multiple matches -> require disambiguation
        if len(discovered_files) > 1:
            matches_str = ", ".join(f["path"] for f in discovered_files)
            return GoalPlan(
                goal=goal,
                target_workspace=default_target_ws,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=(
                    f"Ambiguous rename goal: found {len(discovered_files)} matching files "
                    f"({matches_str}). Please specify the exact workspace or directory."
                ),
            )

        # 4. Exactly one source file resolved
        resolved_src = Path(discovered_files[0]["path"]).resolve()
        dest_path = (resolved_src.parent / new_filename).resolve()

        if not resolved_src.parent.exists():
            return GoalPlan(
                goal=goal,
                target_workspace=default_target_ws,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=f"Destination directory does not exist: {resolved_src.parent}.",
            )

        if resolved_src.name == new_filename:
            return GoalPlan(
                goal=goal,
                target_workspace=default_target_ws,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=f"Rename source and destination filenames are identical: '{new_filename}'.",
            )

        # Workspace containment & permissions
        ws_containing = WorkspaceManager.find_workspace_for_path(resolved_src)
        if not ws_containing:
            return GoalPlan(
                goal=goal,
                target_workspace=None,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=f"Path is outside configured workspaces: {resolved_src}",
            )

        if not ws_containing.enabled:
            return GoalPlan(
                goal=goal,
                target_workspace=ws_containing,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=f"Workspace '{ws_containing.name}' is currently disabled.",
            )

        if Permission.WRITE.value not in ws_containing.permissions:
            return GoalPlan(
                goal=goal,
                target_workspace=ws_containing,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk="medium",
                requires_approval=True,
                summary=(
                    f"Workspace '{ws_containing.name}' lacks WRITE permission "
                    "required to rename files."
                ),
            )

        # Protected system directory check
        if (
            WorkspaceManager.is_protected_system_path(resolved_src)
            or WorkspaceManager.is_protected_system_path(dest_path)
        ):
            return GoalPlan(
                goal=goal,
                target_workspace=ws_containing,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk="medium",
                requires_approval=True,
                summary=f"Cannot rename protected system path: {resolved_src}",
            )

        # Destination collision check
        if dest_path.exists():
            return GoalPlan(
                goal=goal,
                target_workspace=ws_containing,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary=(
                    f"Destination collision: a file named '{new_filename}' "
                    f"already exists at {resolved_src.parent}."
                ),
            )

        # 5. Synthesize rename step
        steps = [
            {
                "step_order": 1,
                "action": "rename",
                "arguments": {
                    "source": str(resolved_src),
                    "new_name": new_filename,
                },
                "depends_on_order": None,
            }
        ]

        plan_risk = cls.calculate_plan_risk(steps)
        req_approval = plan_risk in ("medium", "high")

        valid, val_reason = PlanValidator.validate_plan(steps)
        if not valid:
            return GoalPlan(
                goal=goal,
                target_workspace=ws_containing,
                discovered_files=discovered_files,
                steps=[],
                cumulative_risk=plan_risk,
                requires_approval=req_approval,
                summary=f"Plan rejected by policy: {val_reason}",
            )

        summary_msg = f"Generated 1 step to rename '{resolved_src.name}' to '{new_filename}'."
        return GoalPlan(
            goal=goal,
            target_workspace=ws_containing,
            discovered_files=discovered_files,
            steps=steps,
            cumulative_risk=plan_risk,
            requires_approval=req_approval,
            summary=summary_msg,
        )
