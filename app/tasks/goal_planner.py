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
        - action_type: "organize" | "move" | "delete" | "archive" | "clean"
        - extension: ".pdf" | ".txt" | null
        - keywords: list of search keywords (e.g. ["internship"])
        - target_directory_name: "Internship" | "Archive" | null
        - target_workspace_name: explicit workspace name if given | null
        """
        prompt = f"""
You are a goal analysis component for a local file automation system.

Given a user's high-level goal, extract the planning intent into valid JSON.

User goal:
{goal}

Return ONLY valid JSON matching this schema:
{{
    "action_type": "organize" | "move" | "delete" | "archive" | "clean" | "search",
    "extension": "file extension like .pdf or .txt or .py if specified or implied, otherwise null",
    "filename": "specific filename if specified (e.g. 'm4_test.txt'), otherwise null",
    "keywords": ["list of keyword strings identifying target files, e.g. 'internship', 'report',
        'resume']",
    "target_directory_name": "folder name to create or move files into, e.g. 'Internship',
        otherwise null",
    "target_workspace_name": "workspace name if explicitly specified in goal, otherwise null"
}}

Rules:
1. Do NOT invent filenames. Only extract search criteria.
2. Return JSON only with no markdown formatting.
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
                return data
        except Exception:
            pass

        # Deterministic regex heuristic fallback
        return cls._heuristic_goal_analysis(goal)

    @classmethod
    def _heuristic_goal_analysis(cls, goal: str) -> dict[str, Any]:
        """Fallback analysis for offline, missing API keys, or mocked tests."""
        goal_lower = goal.lower()

        # Detect action type
        if "delete" in goal_lower or "remove" in goal_lower or "clean" in goal_lower:
            action_type = "delete"
        elif "archive" in goal_lower:
            action_type = "archive"
        elif "move" in goal_lower or "into" in goal_lower or "organize" in goal_lower:
            action_type = "organize"
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
        m_dir = re.search(
            r"(?:into|to)\s+(?:an?|the)?\s*([A-Za-z0-9_\-]+)\s*(?:folder|directory)?",
            goal,
            re.IGNORECASE,
        )
        if m_dir:
            matched_name = m_dir.group(1).strip()
            if matched_name.lower() not in ("folder", "directory", "an", "the", "a", "workspace"):
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
        for t in tokens:
            t_lower = t.lower()
            if filename and t_lower in filename.lower():
                continue
            if t_lower not in stop_words and t_lower != (ext[1:] if ext else ""):
                keywords.append(t_lower)

        # Check for explicitly mentioned workspace
        target_ws = None
        for ws in WorkspaceManager.list_workspaces():
            if ws.name.lower() in goal_lower:
                target_ws = ws.name
                break

        return {
            "action_type": action_type,
            "extension": ext,
            "filename": filename,
            "keywords": keywords,
            "target_directory_name": target_dir,
            "target_workspace_name": target_ws,
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
        keywords = analysis.get("keywords") or []
        target_dir_name = analysis.get("target_directory_name")
        explicit_ws_name = analysis.get("target_workspace_name")

        # 1. Determine active workspace(s)
        enabled_workspaces = WorkspaceManager.list_workspaces(enabled_only=True)
        read_workspaces = [w for w in enabled_workspaces if Permission.READ.value in w.permissions]

        if not read_workspaces:
            return GoalPlan(
                goal=goal,
                target_workspace=None,
                discovered_files=[],
                steps=[],
                cumulative_risk="low",
                requires_approval=False,
                summary="No enabled workspaces with READ permission are available.",
            )

        target_workspace = None
        if explicit_ws_name:
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
                search_scope = read_workspaces
        else:
            search_scope = read_workspaces
            target_workspace = read_workspaces[0]

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
                # Filter by keyword if keywords are specified
                if keywords:
                    p_name_lower = p.name.lower()
                    if any(k in p_name_lower for k in keywords):
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
                summary="No matching files were found in the authorized workspaces. No changes "
                "were made.",
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
                summary=f"Workspace '{target_workspace.name}' lacks WRITE permission required to "
                f"organize files.",
            )

        # 4. Plan Synthesis
        steps: list[dict[str, Any]] = []
        step_order = 1

        if action_type in ("organize", "move", "archive"):
            # Target directory path inside target workspace
            dest_folder_name = target_dir_name if target_dir_name else "Organized"
            assert target_workspace is not None
            target_dir_path = target_workspace.canonical_path / dest_folder_name

            # Check if directory already exists physically
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

            # Subsequent steps: move each discovered file, avoiding destination filename collisions
            planned_names: set[str] = set()
            if dir_exists:
                planned_names.update(
                    f.name.lower() for f in target_dir_path.iterdir() if f.is_file()
                )

            for file_info in discovered_files:
                src_path = Path(file_info["path"])
                if src_path.name.lower() in planned_names:
                    continue
                planned_names.add(src_path.name.lower())

                steps.append(
                    {
                        "step_order": step_order,
                        "action": "move",
                        "arguments": {
                            "source": file_info["path"],
                            "destination": f"$output.step_{dir_step_order}.path",
                        },
                        "depends_on_order": dir_step_order,
                    }
                )
                step_order += 1

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
