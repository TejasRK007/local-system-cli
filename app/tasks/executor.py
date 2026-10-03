"""
Step executor and policy/approval/recovery pipeline for Milestone 3.
"""

from pathlib import Path
from typing import Any, Callable, Optional

from app.agent import resolve_directory, resolve_file_sources
from app.database import log_event
from app.policy import get_action_risk, requires_approval
from app.recovery import execute_action_with_recovery
from app.tasks.manager import TaskManager
from app.tasks.models import StepStatus, Task, TaskStatus, TaskStep
from app.tools.file_actions import (
    create_directory,
    delete_file,
    is_allowed_path,
    move_file,
    rename_file,
)
from app.tools.filesystem import search_files
from app.workspaces import Permission, WorkspaceManager


class StepExecutor:
    """Executes task steps in dependency order preserving all policy, approval, recovery, and audit
        controls."""

    @staticmethod
    def execute_step(
        step: TaskStep,
        task: Task,
        resolved_args: dict[str, Any],
        confirm_callback: Optional[Callable[[str, str, dict[str, Any]], bool]] = None,
        on_retry: Optional[Callable[[int, str], None]] = None,
    ) -> bool:
        """
        Execute one step adhering to the existing Milestone 2 architecture:
        Policy check -> Approval -> Action with recovery -> Physical observation -> Audit.
        """
        action = step.action.lower().strip()
        risk = get_action_risk(action)

        # -------------------------------------------------------------
        # MOVE ACTION
        # -------------------------------------------------------------
        if action == "move":
            raw_src = resolved_args.get("source") or ""
            raw_dst = resolved_args.get("destination") or ""

            if not raw_src or not raw_dst:
                TaskManager.update_step_state(
                    step, StepStatus.FAILED, attempts=0, error_info="Missing source or destination"
                )
                return False

            dest_path = resolve_directory(raw_dst)
            if not dest_path:
                TaskManager.update_step_state(
                    step,
                    StepStatus.FAILED,
                    attempts=0,
                    error_info=f"Invalid destination: {raw_dst}",
                )
                return False

            matched = resolve_file_sources(raw_src)
            if len(matched) == 0:
                TaskManager.update_step_state(
                    step,
                    StepStatus.FAILED,
                    attempts=0,
                    error_info=f"Source file not found: {raw_src}",
                )
                log_event(
                    user_request=f"[{step.step_id}] move {raw_src} -> {raw_dst}",
                    action="move",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="NOT_APPLICABLE",
                    execution_status="FAILED",
                    result_summary=f"File not found: {raw_src}",
                )
                return False

            if len(matched) > 1:
                TaskManager.update_step_state(
                    step,
                    StepStatus.FAILED,
                    attempts=0,
                    error_info=f"Ambiguous: {len(matched)} matching files",
                )
                log_event(
                    user_request=f"[{step.step_id}] move {raw_src} -> {raw_dst}",
                    action="ambiguous",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="NOT_APPLICABLE",
                    execution_status="AMBIGUOUS",
                    result_summary=f"Ambiguous request: {len(matched)} files found",
                )
                return False

            source_file = matched[0]["path"]
            target_file = Path(dest_path) / Path(source_file).name

            # Policy check: workspace & path authorization
            auth_ok, auth_reason = WorkspaceManager.authorize_action(
                "move", source_path=source_file, destination_path=dest_path
            )
            if (
                not auth_ok
                or not is_allowed_path(Path(source_file), permission=Permission.READ.value)
                or not is_allowed_path(Path(dest_path), permission=Permission.WRITE.value)
            ):
                err_msg = (
                    auth_reason
                    if not auth_ok
                    else "POLICY_VIOLATION: Path outside allowed directories or lacks required "
                    "permission"
                )
                TaskManager.update_step_state(
                    step, StepStatus.FAILED, attempts=0, error_info=err_msg
                )
                log_event(
                    user_request=f"[{step.step_id}] move {source_file} -> {dest_path}",
                    action="move",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="NOT_APPLICABLE",
                    execution_status="POLICY_VIOLATION",
                    result_summary=err_msg,
                )
                return False

            # Approval gate
            if requires_approval(risk):
                TaskManager.update_step_state(step, StepStatus.WAITING_FOR_APPROVAL, attempts=0)
                TaskManager.update_task_state(task, TaskStatus.WAITING_FOR_APPROVAL)

                prompt_msg = f"Do you want to move {source_file} to {dest_path}?"
                approved = (
                    confirm_callback(
                        action, prompt_msg, {"File": source_file, "To": str(dest_path)}
                    )
                    if confirm_callback
                    else True
                )

                if not approved:
                    TaskManager.update_step_state(
                        step, StepStatus.FAILED, attempts=0, error_info="Approval denied by user"
                    )
                    log_event(
                        user_request=f"[{step.step_id}] move {source_file} -> {dest_path}",
                        action="move",
                        risk_level=risk,
                        approval_required=True,
                        approval_result="DENIED",
                        execution_status="CANCELLED",
                        result_summary=f"Cancelled move of {source_file}",
                    )
                    return False

            # Execution with Recovery & Observation
            TaskManager.update_step_state(step, StepStatus.RUNNING, attempts=1)
            TaskManager.update_task_state(task, TaskStatus.RUNNING)

            exec_res = execute_action_with_recovery(
                action="move",
                action_func=move_file,
                func_args=(source_file, str(dest_path)),
                source_path=source_file,
                destination_path=target_file,
                on_retry=on_retry,
            )

            status = exec_res["status"]
            summary = exec_res["result_summary"]
            attempts = exec_res["attempts"]

            if status == "SUCCESS":
                TaskManager.update_step_state(
                    step,
                    StepStatus.SUCCESS,
                    attempts=attempts,
                    output={"path": str(target_file)},
                    error_info=None,
                )
                log_event(
                    user_request=f"[{step.step_id}] move {source_file} -> {dest_path}",
                    action="move",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="APPROVED",
                    execution_status="SUCCESS",
                    result_summary=summary,
                )
                return True
            else:
                TaskManager.update_step_state(
                    step,
                    StepStatus.FAILED,
                    attempts=attempts,
                    output=None,
                    error_info=summary,
                )
                log_event(
                    user_request=f"[{step.step_id}] move {source_file} -> {dest_path}",
                    action="move",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="APPROVED",
                    execution_status=status,
                    result_summary=summary,
                )
                return False

        # -------------------------------------------------------------
        # RENAME ACTION
        # -------------------------------------------------------------
        elif action == "rename":
            raw_src = resolved_args.get("source") or ""
            new_name = resolved_args.get("new_name") or ""
            dir_str = resolved_args.get("directory")

            if not raw_src or not new_name:
                TaskManager.update_step_state(
                    step, StepStatus.FAILED, attempts=0, error_info="Missing source or new_name"
                )
                return False

            matched = resolve_file_sources(raw_src, dir_str=dir_str)
            if len(matched) == 0:
                TaskManager.update_step_state(
                    step,
                    StepStatus.FAILED,
                    attempts=0,
                    error_info=f"Source file not found: {raw_src}",
                )
                log_event(
                    user_request=f"[{step.step_id}] rename {raw_src} -> {new_name}",
                    action="rename",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="NOT_APPLICABLE",
                    execution_status="FAILED",
                    result_summary=f"File not found: {raw_src}",
                )
                return False

            if len(matched) > 1:
                TaskManager.update_step_state(
                    step,
                    StepStatus.FAILED,
                    attempts=0,
                    error_info=f"Ambiguous: {len(matched)} matching files",
                )
                log_event(
                    user_request=f"[{step.step_id}] rename {raw_src} -> {new_name}",
                    action="ambiguous",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="NOT_APPLICABLE",
                    execution_status="AMBIGUOUS",
                    result_summary=f"Ambiguous request: {len(matched)} files found",
                )
                return False

            source_file = matched[0]["path"]
            target_path = Path(source_file).parent / new_name

            # Policy check: workspace & path authorization
            auth_ok, auth_reason = WorkspaceManager.authorize_action(
                "rename", target_path=source_file
            )
            if not auth_ok or not is_allowed_path(
                Path(source_file), permission=Permission.WRITE.value
            ):
                err_msg = (
                    auth_reason
                    if not auth_ok
                    else "POLICY_VIOLATION: Path outside allowed directories or lacks WRITE "
                    "permission"
                )
                TaskManager.update_step_state(
                    step, StepStatus.FAILED, attempts=0, error_info=err_msg
                )
                log_event(
                    user_request=f"[{step.step_id}] rename {source_file} -> {new_name}",
                    action="rename",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="NOT_APPLICABLE",
                    execution_status="POLICY_VIOLATION",
                    result_summary=err_msg,
                )
                return False

            # Approval gate
            if requires_approval(risk):
                TaskManager.update_step_state(step, StepStatus.WAITING_FOR_APPROVAL, attempts=0)
                TaskManager.update_task_state(task, TaskStatus.WAITING_FOR_APPROVAL)

                prompt_msg = f"Do you want to rename {source_file} to {new_name}?"
                approved = (
                    confirm_callback(
                        action, prompt_msg, {"File": source_file, "New name": new_name}
                    )
                    if confirm_callback
                    else True
                )

                if not approved:
                    TaskManager.update_step_state(
                        step, StepStatus.FAILED, attempts=0, error_info="Approval denied by user"
                    )
                    log_event(
                        user_request=f"[{step.step_id}] rename {source_file} -> {new_name}",
                        action="rename",
                        risk_level=risk,
                        approval_required=True,
                        approval_result="DENIED",
                        execution_status="CANCELLED",
                        result_summary=f"Cancelled rename of {source_file}",
                    )
                    return False

            # Execution with Recovery & Observation
            TaskManager.update_step_state(step, StepStatus.RUNNING, attempts=1)
            TaskManager.update_task_state(task, TaskStatus.RUNNING)

            exec_res = execute_action_with_recovery(
                action="rename",
                action_func=rename_file,
                func_args=(source_file, new_name),
                source_path=source_file,
                destination_path=target_path,
                on_retry=on_retry,
            )

            status = exec_res["status"]
            summary = exec_res["result_summary"]
            attempts = exec_res["attempts"]

            if status == "SUCCESS":
                TaskManager.update_step_state(
                    step,
                    StepStatus.SUCCESS,
                    attempts=attempts,
                    output={"path": str(target_path)},
                    error_info=None,
                )
                log_event(
                    user_request=f"[{step.step_id}] rename {source_file} -> {new_name}",
                    action="rename",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="APPROVED",
                    execution_status="SUCCESS",
                    result_summary=summary,
                )
                return True
            else:
                TaskManager.update_step_state(
                    step,
                    StepStatus.FAILED,
                    attempts=attempts,
                    output=None,
                    error_info=summary,
                )
                log_event(
                    user_request=f"[{step.step_id}] rename {source_file} -> {new_name}",
                    action="rename",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="APPROVED",
                    execution_status=status,
                    result_summary=summary,
                )
                return False

        # -------------------------------------------------------------
        # DELETE ACTION
        # -------------------------------------------------------------
        elif action == "delete":
            raw_tgt = resolved_args.get("target") or ""
            dir_str = resolved_args.get("directory")

            if not raw_tgt:
                TaskManager.update_step_state(
                    step, StepStatus.FAILED, attempts=0, error_info="Missing target"
                )
                return False

            matched = resolve_file_sources(raw_tgt, dir_str=dir_str)
            if len(matched) == 0:
                TaskManager.update_step_state(
                    step, StepStatus.FAILED, attempts=0, error_info=f"File not found: {raw_tgt}"
                )
                log_event(
                    user_request=f"[{step.step_id}] delete {raw_tgt}",
                    action="delete",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="NOT_APPLICABLE",
                    execution_status="FAILED",
                    result_summary=f"File not found for deletion: {raw_tgt}",
                )
                return False

            target_file = matched[0]["path"]

            # Policy check: workspace & path authorization
            auth_ok, auth_reason = WorkspaceManager.authorize_action(
                "delete", target_path=target_file
            )
            if not auth_ok or not is_allowed_path(
                Path(target_file), permission=Permission.DELETE.value
            ):
                err_msg = (
                    auth_reason
                    if not auth_ok
                    else "POLICY_VIOLATION: Path outside allowed directories or lacks DELETE "
                    "permission"
                )
                TaskManager.update_step_state(
                    step, StepStatus.FAILED, attempts=0, error_info=err_msg
                )
                log_event(
                    user_request=f"[{step.step_id}] delete {target_file}",
                    action="delete",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="NOT_APPLICABLE",
                    execution_status="POLICY_VIOLATION",
                    result_summary=err_msg,
                )
                return False

            # Approval gate
            if requires_approval(risk):
                TaskManager.update_step_state(step, StepStatus.WAITING_FOR_APPROVAL, attempts=0)
                TaskManager.update_task_state(task, TaskStatus.WAITING_FOR_APPROVAL)

                prompt_msg = f"Warning: Permanent action. Do you want to delete {target_file}?"
                approved = (
                    confirm_callback(action, prompt_msg, {"File": target_file})
                    if confirm_callback
                    else True
                )

                if not approved:
                    TaskManager.update_step_state(
                        step, StepStatus.FAILED, attempts=0, error_info="Approval denied by user"
                    )
                    log_event(
                        user_request=f"[{step.step_id}] delete {target_file}",
                        action="delete",
                        risk_level=risk,
                        approval_required=True,
                        approval_result="DENIED",
                        execution_status="CANCELLED",
                        result_summary=f"Cancelled deletion of {target_file}",
                    )
                    return False

            # Execution with Recovery & Observation
            TaskManager.update_step_state(step, StepStatus.RUNNING, attempts=1)
            TaskManager.update_task_state(task, TaskStatus.RUNNING)

            exec_res = execute_action_with_recovery(
                action="delete",
                action_func=delete_file,
                func_args=(target_file,),
                source_path=target_file,
                on_retry=on_retry,
            )

            status = exec_res["status"]
            summary = exec_res["result_summary"]
            attempts = exec_res["attempts"]

            if status == "SUCCESS":
                TaskManager.update_step_state(
                    step,
                    StepStatus.SUCCESS,
                    attempts=attempts,
                    output={"path": target_file, "deleted": True},
                    error_info=None,
                )
                log_event(
                    user_request=f"[{step.step_id}] delete {target_file}",
                    action="delete",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="APPROVED",
                    execution_status="SUCCESS",
                    result_summary=summary,
                )
                return True
            else:
                TaskManager.update_step_state(
                    step,
                    StepStatus.FAILED,
                    attempts=attempts,
                    output=None,
                    error_info=summary,
                )
                log_event(
                    user_request=f"[{step.step_id}] delete {target_file}",
                    action="delete",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="APPROVED",
                    execution_status=status,
                    result_summary=summary,
                )
                return False

        # -------------------------------------------------------------
        # CREATE_DIRECTORY ACTION
        # -------------------------------------------------------------
        elif action in ("create_directory", "mkdir"):
            raw_dir = resolved_args.get("directory") or resolved_args.get("path") or ""
            if not raw_dir:
                TaskManager.update_step_state(
                    step, StepStatus.FAILED, attempts=0, error_info="Missing directory path"
                )
                return False

            dest_path = resolve_directory(raw_dir) or Path(raw_dir).expanduser().resolve()

            # Policy check: workspace & path authorization
            auth_ok, auth_reason = WorkspaceManager.authorize_action(
                "create_directory", target_path=dest_path
            )
            if not auth_ok or not is_allowed_path(dest_path, permission=Permission.WRITE.value):
                err_msg = (
                    auth_reason
                    if not auth_ok
                    else "POLICY_VIOLATION: Path outside allowed directories or lacks WRITE "
                    "permission"
                )
                TaskManager.update_step_state(
                    step, StepStatus.FAILED, attempts=0, error_info=err_msg
                )
                log_event(
                    user_request=f"[{step.step_id}] create_directory {dest_path}",
                    action="create_directory",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="NOT_APPLICABLE",
                    execution_status="POLICY_VIOLATION",
                    result_summary=err_msg,
                )
                return False

            # Approval gate
            if requires_approval(risk):
                TaskManager.update_step_state(step, StepStatus.WAITING_FOR_APPROVAL, attempts=0)
                TaskManager.update_task_state(task, TaskStatus.WAITING_FOR_APPROVAL)

                prompt_msg = f"Do you want to create directory {dest_path}?"
                approved = (
                    confirm_callback(action, prompt_msg, {"Directory": str(dest_path)})
                    if confirm_callback
                    else True
                )

                if not approved:
                    TaskManager.update_step_state(
                        step, StepStatus.FAILED, attempts=0, error_info="Approval denied by user"
                    )
                    log_event(
                        user_request=f"[{step.step_id}] create_directory {dest_path}",
                        action="create_directory",
                        risk_level=risk,
                        approval_required=True,
                        approval_result="DENIED",
                        execution_status="CANCELLED",
                        result_summary=f"Cancelled creation of directory {dest_path}",
                    )
                    return False

            # Execution with Recovery & Observation
            TaskManager.update_step_state(step, StepStatus.RUNNING, attempts=1)
            TaskManager.update_task_state(task, TaskStatus.RUNNING)

            exec_res = execute_action_with_recovery(
                action="create_directory",
                action_func=create_directory,
                func_args=(str(dest_path),),
                source_path=None,
                destination_path=dest_path,
                on_retry=on_retry,
            )

            status = exec_res["status"]
            summary = exec_res["result_summary"]
            attempts = exec_res["attempts"]

            # Physical filesystem verification
            physically_exists = dest_path.exists() and dest_path.is_dir()

            if status == "SUCCESS" and physically_exists:
                TaskManager.update_step_state(
                    step,
                    StepStatus.SUCCESS,
                    attempts=attempts,
                    output={"path": str(dest_path), "created_directory": str(dest_path)},
                    error_info=None,
                )
                log_event(
                    user_request=f"[{step.step_id}] create_directory {dest_path}",
                    action="create_directory",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="APPROVED",
                    execution_status="SUCCESS",
                    result_summary=summary,
                )
                return True
            else:
                err_msg = (
                    summary
                    if status != "SUCCESS"
                    else f"Physical verification failed: directory does not physically exist at "
                    f"{dest_path}"
                )
                TaskManager.update_step_state(
                    step,
                    StepStatus.FAILED,
                    attempts=attempts,
                    output=None,
                    error_info=err_msg,
                )
                log_event(
                    user_request=f"[{step.step_id}] create_directory {dest_path}",
                    action="create_directory",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="APPROVED",
                    execution_status="FAILED" if status == "SUCCESS" else status,
                    result_summary=err_msg,
                )
                return False

        # -------------------------------------------------------------
        # SEARCH ACTION
        # -------------------------------------------------------------
        elif action == "search":
            raw_dir = resolved_args.get("directory") or ""
            ext = resolved_args.get("extension") or ""
            fname = resolved_args.get("filename") or ""

            dest_path = resolve_directory(raw_dir) or (
                Path(raw_dir).expanduser().resolve() if raw_dir else None
            )

            # Policy check: workspace & path authorization
            if dest_path:
                auth_ok, auth_reason = WorkspaceManager.authorize_action(
                    "search", target_path=dest_path
                )
                if not auth_ok or not is_allowed_path(dest_path, permission=Permission.READ.value):
                    err_msg = (
                        auth_reason
                        if not auth_ok
                        else "POLICY_VIOLATION: Path outside allowed directories or lacks READ "
                        "permission"
                    )
                    TaskManager.update_step_state(
                        step, StepStatus.FAILED, attempts=0, error_info=err_msg
                    )
                    log_event(
                        user_request=f"[{step.step_id}] search {dest_path}",
                        action="search",
                        risk_level=risk,
                        approval_required=False,
                        approval_result="NOT_APPLICABLE",
                        execution_status="POLICY_VIOLATION",
                        result_summary=err_msg,
                    )
                    return False

            res = search_files.invoke(
                {
                    "directory": str(dest_path) if dest_path else "",
                    "extension": ext,
                    "filename": fname,
                    "start_date": "",
                    "end_date": "",
                }
            )
            files_found = res.get("files", [])
            summary = f"Found {len(files_found)} matching file(s)"
            TaskManager.update_step_state(
                step,
                StepStatus.SUCCESS,
                attempts=1,
                output={"files": [f["path"] for f in files_found], "count": len(files_found)},
                error_info=None,
            )
            log_event(
                user_request=f"[{step.step_id}] search {dest_path}",
                action="search",
                risk_level=risk,
                approval_required=False,
                approval_result="NOT_REQUIRED",
                execution_status="SUCCESS",
                result_summary=summary,
            )
            return True

        # -------------------------------------------------------------
        # UNRECOGNIZED ACTION
        # -------------------------------------------------------------
        else:
            TaskManager.update_step_state(
                step, StepStatus.FAILED, attempts=0, error_info=f"Unsupported step action: {action}"
            )
            return False

    @classmethod
    def execute_task(
        cls,
        task: Task,
        confirm_callback: Optional[Callable[[str, str, dict[str, Any]], bool]] = None,
        compensate_on_failure: bool = False,
        on_retry: Optional[Callable[[int, str], None]] = None,
    ) -> Task:
        """
        Execute all steps in task in order, handling dependencies, real output passing,
        per-step approvals, recovery, partial failure, and optional safe compensation.
        """
        TaskManager.update_task_state(task, TaskStatus.RUNNING)

        step_outputs: dict[str, dict[str, Any]] = {}
        completed_steps: list[TaskStep] = []
        failure_encountered = False

        for i, step in enumerate(task.steps):
            # 0. Skip already successfully verified steps (supports safe resume)
            if step.status == StepStatus.SUCCESS:
                if step.output:
                    step_outputs[step.step_id] = step.output
                completed_steps.append(step)
                continue

            # 1. Dependency check
            if step.depends_on_step_id:
                dep_step = next(
                    (s for s in task.steps if s.step_id == step.depends_on_step_id), None
                )
                if dep_step and dep_step.status != StepStatus.SUCCESS:
                    TaskManager.update_step_state(
                        step,
                        StepStatus.SKIPPED,
                        attempts=0,
                        error_info=f"Skipped: dependency step {dep_step.step_id} failed or was "
                        f"skipped",
                    )
                    continue

            # If previous sequential step failed and current step had no explicit dependency set,
            # but failure already occurred in earlier step, skip remaining steps in sequence
            if failure_encountered:
                TaskManager.update_step_state(
                    step,
                    StepStatus.SKIPPED,
                    attempts=0,
                    error_info="Skipped: prior step failed in sequence",
                )
                continue

            # 2. Output passing / argument resolution
            prev_step = completed_steps[-1] if completed_steps else None
            resolved_args = TaskManager.resolve_step_arguments(
                step, step_outputs, previous_step=prev_step
            )

            # 3. Execute step
            success = cls.execute_step(
                step=step,
                task=task,
                resolved_args=resolved_args,
                confirm_callback=confirm_callback,
                on_retry=on_retry,
            )

            if success:
                if step.output:
                    step_outputs[step.step_id] = step.output
                completed_steps.append(step)
            else:
                failure_encountered = True

        # 4. Safe compensation if enabled and partial failure occurred
        if failure_encountered and compensate_on_failure and completed_steps:
            TaskManager.compensate_task(task)

        # 5. Determine final task status
        statuses = [s.status for s in task.steps]
        if all(st == StepStatus.SUCCESS for st in statuses):
            TaskManager.update_task_state(task, TaskStatus.COMPLETED)
        elif any(st == StepStatus.SUCCESS for st in statuses):
            TaskManager.update_task_state(
                task,
                TaskStatus.PARTIAL_FAILURE,
                error_summary="One or more steps failed or were skipped",
            )
        else:
            if any(
                s.status == StepStatus.FAILED and "denied" in str(s.error_info).lower()
                for s in task.steps
            ):
                TaskManager.update_task_state(
                    task,
                    TaskStatus.CANCELLED,
                    error_summary="Task cancelled by user",
                )
            else:
                TaskManager.update_task_state(
                    task,
                    TaskStatus.FAILED,
                    error_summary="All steps failed or were skipped",
                )

        return task
