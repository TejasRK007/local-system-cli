"""
Task planner and multi-step intent decomposition for Milestone 3.
"""

import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from app.agent import extract_intent

load_dotenv()

llm: Any = None


def get_llm() -> Any:
    global llm
    if llm is not None:
        return llm
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY environment variable is missing or empty. "
            "Please set GROQ_API_KEY in your environment or .env file."
        )
    llm = ChatGroq(
        model="openai/gpt-oss-20b",
        api_key=api_key,  # type: ignore[arg-type]
        temperature=0,
    )
    return llm


def plan_task_steps(request: str) -> list[dict[str, Any]]:
    """
    Decompose a user request into an ordered sequence of step specifications.

    Returns a list of dicts:
    [
        {
            "step_order": 1,
            "action": "move" | "rename" | "delete" | "search",
            "arguments": { ... },
            "depends_on_order": Optional[int],
        },
        ...
    ]
    """
    prompt = f"""
You are a task planning component for a local file automation system.

Given a user request, break it down into an ORDERED LIST OF STEPS.
The request may contain ONE step or MULTIPLE dependent sequential steps.

User request:
{request}

Supported actions:
- "move": moving a file. Arguments: {{"source": "source file path or filename",
    "destination": "destination directory or path"}}
- "rename": renaming a file. Arguments: {{"source": "current file path or filename (use
    '$output.step_1.path' or '$prev.path' if referring to output of prior step)",
    "new_name": "new filename"}}
- "delete": deleting a file. Arguments: {{"target": "target file path or filename"}}
- "search": searching files. Arguments: {{"query": "...", "directory": "..."}}

If a step operates on the file produced/moved by a prior step, set "depends_on_order" to that
step's order number, and reference it in the source argument
(e.g. "$output.step_1.path" or "$prev.path" or "it").

Return ONLY a valid JSON list of step objects:
[
  {{
    "step_order": 1,
    "action": "move",
    "arguments": {{
      "source": "source/report.pdf",
      "destination": "documents"
    }},
    "depends_on_order": null
  }},
  {{
    "step_order": 2,
    "action": "rename",
    "arguments": {{
      "source": "$output.step_1.path",
      "new_name": "final_report.pdf"
    }},
    "depends_on_order": 1
  }}
]

Rules:
1. Preserve exact filenames, paths, and directory names.
2. Return JSON list only with no markdown or explanations.
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

        steps = json.loads(content)
        if isinstance(steps, list) and len(steps) > 0:
            return steps
    except Exception:
        pass

    # Multi-step heuristic fallback (for offline, missing API key, or non-JSON LLM responses)
    # Pattern 1: Move ... [from ...] to ... and [then] rename (it )?to ...
    m = re.search(
        r"move\s+(?P<src>.+?)(?:\s+from\s+(?P<from_dir>[^\s]+))?\s+to\s+(?P<dst>.+?)\s*"
        r"(?:,|and|\bthen\b)+\s*(?:then\s+)?rename\s*(?:it|\$prev\.path)?\s*(?:to\s+)?"
        r"(?P<new_name>[^\s,]+)",
        request,
        re.IGNORECASE,
    )
    if m:
        src = m.group("src").strip()
        from_dir = m.group("from_dir")
        if from_dir and not src.startswith(from_dir):
            src = f"{from_dir.strip()}/{src}"
        dst = m.group("dst").strip()
        new_name = m.group("new_name").strip().strip("'\"")
        return [
            {
                "step_order": 1,
                "action": "move",
                "arguments": {"source": src, "destination": dst},
                "depends_on_order": None,
            },
            {
                "step_order": 2,
                "action": "rename",
                "arguments": {"source": "$output.step_1.path", "new_name": new_name},
                "depends_on_order": 1,
            },
        ]

    # Fallback to single-action intent extraction
    single_intent = extract_intent(request)
    act = single_intent.get("action")
    if act == "move":
        return [
            {
                "step_order": 1,
                "action": "move",
                "arguments": {
                    "source": single_intent.get("source"),
                    "destination": single_intent.get("destination"),
                },
                "depends_on_order": None,
            }
        ]
    elif act == "rename":
        return [
            {
                "step_order": 1,
                "action": "rename",
                "arguments": {
                    "source": single_intent.get("source"),
                    "new_name": single_intent.get("new_name"),
                    "directory": single_intent.get("directory"),
                },
                "depends_on_order": None,
            }
        ]
    elif act == "delete":
        return [
            {
                "step_order": 1,
                "action": "delete",
                "arguments": {
                    "target": single_intent.get("target"),
                    "directory": single_intent.get("directory"),
                },
                "depends_on_order": None,
            }
        ]
    elif act == "search":
        return [
            {
                "step_order": 1,
                "action": "search",
                "arguments": {
                    "filename": single_intent.get("filename"),
                    "extension": single_intent.get("extension"),
                    "directory": single_intent.get("directory"),
                },
                "depends_on_order": None,
            }
        ]

    return []
