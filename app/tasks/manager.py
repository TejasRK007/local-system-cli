"""
Task lifecycle, state management, output passing, and compensation for Milestone 3.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.database import (
    create_step_record,
    create_task_record,
    get_task_record,
    get_task_steps_records,
    list_task_records,
    log_event,
    update_step_record,
    update_task_record,
)
from app.recovery import execute_action_with_recovery
from app.tasks.models import StepStatus, Task, TaskStatus, TaskStep
from app.tools.file_actions import move_file, rename_file
from app.workspaces import Permission, WorkspaceManager


class TaskManager:
    """Manages task lifecycle, state transitions, output passing, and safe compensation."""

    @staticmethod
    def create_task(user_request: str, steps_spec: list[dict[str, Any]]) -> Task:
        """
        Instantiate and persist a new multi-step Task from parsed specifications.
        """
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        steps: list[TaskStep] = []
        order_to_id: dict[int, str] = {}

        for spec in steps_spec:
            order = spec.get("step_order", len(steps) + 1)
            step_id = f"{task_id}_s{order}"
            order_to_id[order] = step_id

            dep_order = spec.get("depends_on_order")
            dep_step_id = order_to_id.get(dep_order) if dep_order else None

            step = TaskStep(
                step_id=step_id,
                task_id=task_id,
                step_order=order,
                action=spec.get("action", "").lower().strip(),
                arguments=dict(spec.get("arguments", {})),
                status=StepStatus.PENDING,
                attempts=0,
                output=None,
                error_info=None,
                depends_on_step_id=dep_step_id,
            )
            steps.append(step)

        # Persist task in database
        create_task_record(
            task_id=task_id,
            user_request=user_request,
            status=TaskStatus.PENDING.value,
            created_at=created_at,
        )

        # Persist steps in database
        for s in steps:
            create_step_record(
                step_id=s.step_id,
                task_id=s.task_id,
                step_order=s.step_order,
                action=s.action,
                arguments=s.arguments,
                status=s.status.value,
                depends_on_step_id=s.depends_on_step_id,
            )

        return Task(
            task_id=task_id,
            user_request=user_request,
            status=TaskStatus.PENDING,
            created_at=created_at,
            updated_at=created_at,
            steps=steps,
        )

    @staticmethod
    def get_task(task_id: str) -> Optional[Task]:
        """Load a task and all its steps from the persistent SQLite database."""
        row = get_task_record(task_id)
        if not row:
            return None

        step_rows = get_task_steps_records(task_id)
        steps = [TaskStep.from_dict(s) for s in step_rows]
        return Task.from_dict(row, steps=steps)

    @staticmethod
    def list_tasks(limit: int = 10) -> list[Task]:
        """Retrieve recent tasks."""
        rows = list_task_records(limit=limit)
        tasks = []
        for r in rows:
            step_rows = get_task_steps_records(r["task_id"])
            steps = [TaskStep.from_dict(s) for s in step_rows]
            tasks.append(Task.from_dict(r, steps=steps))
        return tasks

    @staticmethod
    def update_step_state(
        step: TaskStep,
        status: StepStatus,
        attempts: int,
        output: Optional[dict[str, Any]] = None,
        error_info: Optional[str] = None,
    ) -> None:
        """Update step in-memory and in SQLite."""
        step.status = status
        step.attempts = attempts
        step.output = output
        step.error_info = error_info
        update_step_record(
            step_id=step.step_id,
            status=status.value,
            attempts=attempts,
            output=output,
            error_info=error_info,
        )

    @staticmethod
    def update_task_state(
        task: Task,
        status: TaskStatus,
        error_summary: Optional[str] = None,
    ) -> None:
        """Update task in-memory and in SQLite."""
        task.status = status
        task.error_summary = error_summary
        task.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_task_record(
            task_id=task.task_id,
            status=status.value,
            error_summary=error_summary,
            updated_at=task.updated_at,
        )

    @staticmethod
    def resolve_step_arguments(
        step: TaskStep,
        step_outputs: dict[str, dict[str, Any]],
        previous_step: Optional[TaskStep] = None,
    ) -> dict[str, Any]:
        """
        Dynamically resolve step arguments by substituting real outputs from prior steps.
        Supports references like:
        - "$output.step_1.path"
        - "$prev.path"
        - "it"
        """
        resolved_args = dict(step.arguments)

        # Helper to find output path by placeholder or step order
        for key, val in list(resolved_args.items()):
            if isinstance(val, str):
                val_clean = val.strip().lower()

                # Case 1: refers to "it" or "$prev.path"
                if val_clean in ("it", "$prev.path", "$output.prev.path") and previous_step:
                    prev_out = step_outputs.get(previous_step.step_id, {})
                    if "path" in prev_out:
                        resolved_args[key] = prev_out["path"]

                # Case 2: refers to explicit step like "$output.step_1.path"
                elif "$output.step_" in val_clean:
                    for s_id, out in step_outputs.items():
                        # Extract step order from s_id e.g. task_xyz_s1 -> 1
                        if "_s" in s_id:
                            order_str = s_id.split("_s")[-1]
                            marker = f"$output.step_{order_str}.path"
                            if marker in val_clean and "path" in out:
                                resolved_args[key] = out["path"]
                                break

        # If source is missing or refers to a previous step that had output
        if step.action in ("rename", "move", "delete"):
            src_val = resolved_args.get("source") or resolved_args.get("target")
            if (
                not src_val or str(src_val).lower().strip() in ("it", "$prev.path")
            ) and previous_step:
                prev_out = step_outputs.get(previous_step.step_id, {})
                if "path" in prev_out:
                    if step.action == "delete":
                        resolved_args["target"] = prev_out["path"]
                    else:
                        resolved_args["source"] = prev_out["path"]

        # Fallback to dependent step output if placeholder remains unresolved
        if step.depends_on_step_id and step.depends_on_step_id in step_outputs:
            dep_out = step_outputs[step.depends_on_step_id]
            for key in ("source", "target"):
                if key in resolved_args:
                    val = str(resolved_args[key]).strip().lower()
                    if val in ("it", "$prev.path") or val.startswith("$output."):
                        if "path" in dep_out:
                            resolved_args[key] = dep_out["path"]

        return resolved_args

    @staticmethod
    def compensate_task(task: Task) -> list[dict[str, Any]]:
        """
        Perform safe, deterministic compensation for completed steps in reverse order.
        - MOVE can be reversed by moving file back to original location.
        - RENAME can be reversed by renaming file back to original name.
        - DELETE is permanent and CANNOT be rolled back.
        """
        compensation_results = []
        completed_steps = [s for s in task.steps if s.status == StepStatus.SUCCESS]

        for step in reversed(completed_steps):
            if step.action == "rename":
                # Original source path was in step.arguments['source']
                # Current file path is in step.output['path']
                orig_source = step.arguments.get("source")
                current_path = (step.output or {}).get("path")
                if orig_source and current_path:
                    old_name = Path(orig_source).name
                    curr_file = Path(current_path)
                    if curr_file.exists():
                        target = curr_file.parent / old_name
                        res = execute_action_with_recovery(
                            action="rename",
                            action_func=rename_file,
                            func_args=(str(curr_file), old_name),
                            source_path=curr_file,
                            destination_path=target,
                        )
                        compensation_results.append(
                            {
                                "step_id": step.step_id,
                                "action": "rollback_rename",
                                "status": res["status"],
                                "summary": res["result_summary"],
                            }
                        )
                        log_event(
                            user_request=f"[Compensation] Rollback rename for {step.step_id}",
                            action="rename",
                            risk_level="medium",
                            approval_required=False,
                            approval_result="NOT_REQUIRED",
                            execution_status=res["status"],
                            result_summary=f"Compensated rename: {res['result_summary']}",
                        )

            elif step.action == "move":
                orig_source = step.arguments.get("source")
                current_path = (step.output or {}).get("path")
                if orig_source and current_path:
                    orig_dir = str(Path(orig_source).parent)
                    curr_file = Path(current_path)
                    if curr_file.exists():
                        target = Path(orig_dir) / curr_file.name
                        res = execute_action_with_recovery(
                            action="move",
                            action_func=move_file,
                            func_args=(str(curr_file), orig_dir),
                            source_path=curr_file,
                            destination_path=target,
                        )
                        compensation_results.append(
                            {
                                "step_id": step.step_id,
                                "action": "rollback_move",
                                "status": res["status"],
                                "summary": res["result_summary"],
                            }
                        )
                        log_event(
                            user_request=f"[Compensation] Rollback move for {step.step_id}",
                            action="move",
                            risk_level="medium",
                            approval_required=False,
                            approval_result="NOT_REQUIRED",
                            execution_status=res["status"],
                            result_summary=f"Compensated move: {res['result_summary']}",
                        )

            elif step.action in ("create_directory", "mkdir"):
                dir_path_str = (step.output or {}).get("path")
                if dir_path_str:
                    target_dir = Path(dir_path_str).resolve()
                    if target_dir.exists() and target_dir.is_dir():
                        auth_ok, _, _ = WorkspaceManager.check_workspace_authorization(
                            target_dir, Permission.WRITE.value
                        )
                        try:
                            is_empty = not any(target_dir.iterdir())
                        except Exception:
                            is_empty = False

                        if auth_ok and is_empty:
                            try:
                                target_dir.rmdir()
                                compensation_results.append(
                                    {
                                        "step_id": step.step_id,
                                        "action": "rollback_create_directory",
                                        "status": "SUCCESS",
                                        "summary": f"Removed empty directory created by task: "
                                        f"{target_dir}",
                                    }
                                )
                                log_event(
                                    user_request=f"[Compensation] Removed empty directory "
                                    f"{target_dir} for {step.step_id}",
                                    action="create_directory",
                                    risk_level="medium",
                                    approval_required=False,
                                    approval_result="NOT_REQUIRED",
                                    execution_status="SUCCESS",
                                    result_summary=f"Removed empty directory: {target_dir}",
                                )
                            except Exception as e:
                                compensation_results.append(
                                    {
                                        "step_id": step.step_id,
                                        "action": "rollback_create_directory",
                                        "status": "FAILED",
                                        "summary": f"Could not remove directory {target_dir}: {e}",
                                    }
                                )

            elif step.action == "delete":
                # Deletion cannot be rolled back safely
                compensation_results.append(
                    {
                        "step_id": step.step_id,
                        "action": "rollback_delete",
                        "status": "NOT_SUPPORTED",
                        "summary": f"Step {step.step_id} (delete) is permanent and cannot be "
                        f"restored.",
                    }
                )

        return compensation_results
