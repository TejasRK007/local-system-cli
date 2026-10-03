"""
Domain models for stateful tasks and steps (Milestone 3).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    CANCELLED = "CANCELLED"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class TaskStep:
    step_id: str
    task_id: str
    step_order: int
    action: str
    arguments: dict[str, Any]
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    output: Optional[dict[str, Any]] = None
    error_info: Optional[str] = None
    depends_on_step_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "task_id": self.task_id,
            "step_order": self.step_order,
            "action": self.action,
            "arguments": self.arguments,
            "status": self.status.value,
            "attempts": self.attempts,
            "output": self.output,
            "error_info": self.error_info,
            "depends_on_step_id": self.depends_on_step_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskStep":
        return cls(
            step_id=data["step_id"],
            task_id=data["task_id"],
            step_order=data["step_order"],
            action=data["action"],
            arguments=data.get("arguments", {}),
            status=StepStatus(data.get("status", StepStatus.PENDING.value)),
            attempts=data.get("attempts", 0),
            output=data.get("output"),
            error_info=data.get("error_info"),
            depends_on_step_id=data.get("depends_on_step_id"),
        )


@dataclass
class Task:
    task_id: str
    user_request: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = ""
    updated_at: str = ""
    steps: list[TaskStep] = field(default_factory=list)
    error_summary: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_request": self.user_request,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error_summary": self.error_summary,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], steps: Optional[list[TaskStep]] = None) -> "Task":
        return cls(
            task_id=data["task_id"],
            user_request=data["user_request"],
            status=TaskStatus(data.get("status", TaskStatus.PENDING.value)),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            steps=steps
            if steps is not None
            else [TaskStep.from_dict(s) for s in data.get("steps", [])],
            error_summary=data.get("error_summary"),
        )
