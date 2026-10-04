"""
Milestone 6: adaptive filesystem goal execution.

M6 adds a deterministic observe -> plan -> validate -> approve -> act -> verify ->
replan loop around the existing M1-M5 safety layers.  It never executes shell
commands and never lets the LLM bypass workspace authorization or policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from app.database import log_event
from app.tasks.executor import StepExecutor
from app.tasks.goal_planner import GoalPlan, GoalPlanner
from app.tasks.manager import TaskManager
from app.tasks.models import StepStatus, Task, TaskStatus
from app.tools.filesystem import EXCLUDED_DIR_NAMES
from app.workspaces import Permission, Workspace, WorkspaceManager

MAX_ADAPTIVE_CYCLES = 3


@dataclass(frozen=True)
class FileObservation:
    path: str
    size: int
    modified_ns: int
    extension: str


@dataclass
class WorkspaceObservation:
    workspace: Workspace
    files: list[FileObservation] = field(default_factory=list)
    directories: list[str] = field(default_factory=list)
    extension_counts: dict[str, int] = field(default_factory=dict)
    name_counts: dict[str, int] = field(default_factory=dict)

    @property
    def file_count(self) -> int:
        return len(self.files)


@dataclass
class EnvironmentObservation:
    workspaces: list[WorkspaceObservation]
    observed_at: str

    @property
    def files(self) -> list[FileObservation]:
        return [f for ws in self.workspaces for f in ws.files]

    @property
    def file_paths(self) -> set[str]:
        return {f.path for f in self.files}


@dataclass
class ObservationDiff:
    added: list[str]
    removed: list[str]
    changed: list[str]

    @property
    def changed_anything(self) -> bool:
        return bool(self.added or self.removed or self.changed)


@dataclass
class CycleReport:
    cycle: int
    plan: GoalPlan
    task: Optional[Task]
    before: EnvironmentObservation
    after: EnvironmentObservation
    diff: ObservationDiff
    verification: dict[str, Any]


@dataclass
class AdaptiveGoalResult:
    goal: str
    status: str  # COMPLETE / PARTIAL / BLOCKED
    cycles: list[CycleReport]
    summary: str
    remaining_steps: list[dict[str, Any]] = field(default_factory=list)
    observed_changes: list[str] = field(default_factory=list)


class AdaptiveFilesystemAgent:
    """Runs bounded adaptive filesystem goals on top of the M1-M5 controls."""

    @staticmethod
    def _skip_path(path: Path) -> bool:
        for part in path.parts:
            if part in EXCLUDED_DIR_NAMES or part.endswith(".app"):
                return True
        return False

    @classmethod
    def observe(cls) -> EnvironmentObservation:
        """Observe only enabled workspaces with READ permission."""
        from datetime import datetime

        observations: list[WorkspaceObservation] = []
        for ws in WorkspaceManager.list_workspaces(enabled_only=True):
            if Permission.READ.value not in ws.permissions:
                continue

            root = ws.canonical_path
            obs = WorkspaceObservation(workspace=ws)
            if not root.exists() or not root.is_dir():
                observations.append(obs)
                continue

            # The workspace itself is already an authorization boundary. We do
            # not inspect any path outside it and do not follow excluded trees.
            try:
                for path in root.rglob("*"):
                    if cls._skip_path(path):
                        continue
                    try:
                        if path.is_dir():
                            obs.directories.append(str(path.resolve()))
                        elif path.is_file():
                            resolved = path.resolve()
                            # Protect against a symlink escaping the workspace.
                            if not WorkspaceManager._is_subpath(resolved, root):
                                continue
                            stat = resolved.stat()
                            ext = resolved.suffix.lower()
                            obs.files.append(
                                FileObservation(
                                    path=str(resolved),
                                    size=stat.st_size,
                                    modified_ns=getattr(stat, "st_mtime_ns", 0),
                                    extension=ext,
                                )
                            )
                            obs.extension_counts[ext or "[no extension]"] = (
                                obs.extension_counts.get(ext or "[no extension]", 0) + 1
                            )
                            name_key = resolved.name.lower()
                            obs.name_counts[name_key] = obs.name_counts.get(name_key, 0) + 1
                    except (OSError, PermissionError):
                        # Observation is read-only and best-effort. Execution
                        # still goes through the normal policy and verification layers.
                        continue
            except (OSError, PermissionError):
                pass

            observations.append(obs)

        return EnvironmentObservation(
            workspaces=observations,
            observed_at=datetime.now().isoformat(timespec="seconds"),
        )

    @staticmethod
    def diff(before: EnvironmentObservation, after: EnvironmentObservation) -> ObservationDiff:
        def index(obs: EnvironmentObservation) -> dict[str, tuple[int, int]]:
            return {f.path: (f.size, f.modified_ns) for f in obs.files}

        old = index(before)
        new = index(after)
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        changed = sorted(path for path in set(old) & set(new) if old[path] != new[path])
        return ObservationDiff(added=added, removed=removed, changed=changed)

    @staticmethod
    def _plan_signature(plan: GoalPlan) -> tuple:
        return tuple(
            (
                step.get("action"),
                tuple(sorted((str(k), str(v)) for k, v in step.get("arguments", {}).items())),
            )
            for step in plan.steps
        )

    @staticmethod
    def _verify_task(task: Task) -> dict[str, Any]:
        """Verify every successful modifying step against physical disk state."""
        verified = 0
        failed = 0
        details: list[str] = []

        for step in task.steps:
            if step.status != StepStatus.SUCCESS:
                continue
            action = step.action.lower()
            args = step.arguments
            output = step.output or {}

            if action in ("move", "rename"):
                source = Path(str(args.get("source", ""))).expanduser()
                target = Path(str(output.get("path", ""))).expanduser()
                ok = bool(str(source)) and not source.exists() and target.exists()
                details.append(
                    f"{action}: {'verified' if ok else 'not verified'} "
                    f"source={source} target={target}"
                )
            elif action == "delete":
                target = Path(str(args.get("target", ""))).expanduser()
                ok = bool(str(target)) and not target.exists()
                details.append(f"delete: {'verified' if ok else 'not verified'} target={target}")
            elif action in ("create_directory", "mkdir"):
                target = Path(str(output.get("path") or args.get("directory", ""))).expanduser()
                ok = bool(str(target)) and target.exists() and target.is_dir()
                details.append(f"mkdir: {'verified' if ok else 'not verified'} target={target}")
            elif action == "search":
                ok = isinstance(output.get("files"), list)
                details.append(f"search: {'verified' if ok else 'not verified'}")
            else:
                ok = False
                details.append(f"{action}: unsupported verification")

            if ok:
                verified += 1
            else:
                failed += 1

        return {
            "verified": failed == 0,
            "verified_steps": verified,
            "failed_steps": failed,
            "details": details,
        }

    @classmethod
    def _plan_for_goal(cls, goal: str) -> GoalPlan:
        """Use the existing grounded M5 planner; M6 adds adaptation around it."""
        return GoalPlanner.plan_goal(goal)

    @classmethod
    def run(
        cls,
        goal: str,
        *,
        confirm_callback: Optional[Callable[[GoalPlan], bool]] = None,
        compensate_on_failure: bool = True,
        max_cycles: int = MAX_ADAPTIVE_CYCLES,
        on_cycle: Optional[Callable[[int, GoalPlan, EnvironmentObservation], None]] = None,
        on_retry: Optional[Callable[[int, str], None]] = None,
    ) -> AdaptiveGoalResult:
        if max_cycles < 1:
            raise ValueError("max_cycles must be at least 1")

        if WorkspaceManager.count_workspaces() == 0:
            return AdaptiveGoalResult(
                goal=goal,
                status="BLOCKED",
                cycles=[],
                summary="No workspaces configured. Configure an authorized workspace first.",
            )

        cycles: list[CycleReport] = []
        seen_signatures: set[tuple] = set()
        initial = cls.observe()
        previous = initial
        remaining_steps: list[dict[str, Any]] = []
        all_changes: list[str] = []
        pending_plan: Optional[GoalPlan] = None

        for cycle_no in range(1, max_cycles + 1):
            plan = pending_plan if pending_plan is not None else cls._plan_for_goal(goal)
            pending_plan = None
            remaining_steps = list(plan.steps)

            if on_cycle:
                on_cycle(cycle_no, plan, previous)

            # A zero-step plan is a stable completion only when the initial goal
            # did not have an expected source that vanished before execution.
            if not plan.steps:
                summary_lower = plan.summary.lower()
                search_goal = any(
                    word in goal.lower() for word in ("search", "find", "show", "list", "locate")
                )
                prior_task_failed = (
                    bool(cycles)
                    and cycles[-1].task is not None
                    and cycles[-1].task.status != TaskStatus.COMPLETED
                )
                if prior_task_failed:
                    status = "PARTIAL"
                elif "no matching files" in summary_lower:
                    status = "COMPLETE" if cycles else "BLOCKED"
                elif search_goal and (
                    "no matching files" in summary_lower or "no changes were made" in summary_lower
                ):
                    status = "COMPLETE"
                elif "no matching files" in summary_lower and cycle_no == 1:
                    status = "BLOCKED"
                else:
                    status = "BLOCKED"
                return AdaptiveGoalResult(
                    goal=goal,
                    status=status,
                    cycles=cycles,
                    summary=plan.summary,
                    remaining_steps=remaining_steps,
                    observed_changes=all_changes,
                )

            signature = cls._plan_signature(plan)
            if signature in seen_signatures:
                return AdaptiveGoalResult(
                    goal=goal,
                    status="BLOCKED",
                    cycles=cycles,
                    summary=(
                        "The same plan was produced again; stopping to avoid an unsafe "
                        "planning loop."
                    ),
                    remaining_steps=remaining_steps,
                    observed_changes=all_changes,
                )
            seen_signatures.add(signature)

            if plan.requires_approval:
                approved = confirm_callback(plan) if confirm_callback else False
                if not approved:
                    log_event(
                        user_request=goal,
                        action="adaptive_goal",
                        risk_level=plan.cumulative_risk,
                        approval_required=True,
                        approval_result="DENIED",
                        execution_status="CANCELLED",
                        result_summary=f"M6 cycle {cycle_no}: plan approval denied.",
                    )
                    return AdaptiveGoalResult(
                        goal=goal,
                        status="BLOCKED",
                        cycles=cycles,
                        summary="Adaptive execution stopped because plan approval was denied.",
                        remaining_steps=remaining_steps,
                        observed_changes=all_changes,
                    )

            task = TaskManager.create_task(goal, plan.steps)
            executed = StepExecutor.execute_task(
                task=task,
                confirm_callback=lambda *_args: True,
                compensate_on_failure=compensate_on_failure,
                on_retry=on_retry,
            )
            after = cls.observe()
            diff = cls.diff(previous, after)
            all_changes.extend(diff.added + diff.removed + diff.changed)
            verification = cls._verify_task(executed)
            cycles.append(
                CycleReport(
                    cycle=cycle_no,
                    plan=plan,
                    task=executed,
                    before=previous,
                    after=after,
                    diff=diff,
                    verification=verification,
                )
            )

            log_event(
                user_request=goal,
                action="adaptive_goal",
                risk_level=plan.cumulative_risk,
                approval_required=plan.requires_approval,
                approval_result="APPROVED" if plan.requires_approval else "NOT_REQUIRED",
                execution_status=executed.status.value,
                result_summary=(
                    f"M6 cycle {cycle_no}: task={executed.task_id}, "
                    f"filesystem changes="
                    f"{len(diff.added) + len(diff.removed) + len(diff.changed)}, "
                    f"physical_verification={'passed' if verification['verified'] else 'failed'}"
                ),
            )

            # Re-observe and re-plan. A completed task is not enough by itself:
            # new files may have appeared, and the destination may have changed.
            previous = after

            if executed.status == TaskStatus.CANCELLED:
                return AdaptiveGoalResult(
                    goal=goal,
                    status="BLOCKED",
                    cycles=cycles,
                    summary="Adaptive execution was cancelled by the user.",
                    remaining_steps=remaining_steps,
                    observed_changes=all_changes,
                )

            if executed.status != TaskStatus.COMPLETED or not verification["verified"]:
                if cycle_no == max_cycles:
                    return AdaptiveGoalResult(
                        goal=goal,
                        status="PARTIAL",
                        cycles=cycles,
                        summary=(
                            "Execution stopped after the adaptive cycle limit with unresolved "
                            "failures or verification issues."
                        ),
                        remaining_steps=remaining_steps,
                        observed_changes=all_changes,
                    )
                # Replan immediately from the new physical state.
                continue

            # Successful cycle: a second planning pass determines whether the
            # goal is now stable or whether new files/conflicts require more work.
            next_plan = cls._plan_for_goal(goal)
            if not next_plan.steps:
                if "no matching files" in next_plan.summary.lower():
                    return AdaptiveGoalResult(
                        goal=goal,
                        status="COMPLETE",
                        cycles=cycles,
                        summary=(
                            f"Goal completed after {cycle_no} adaptive cycle(s). "
                            f"All executed changes were physically verified."
                        ),
                        remaining_steps=[],
                        observed_changes=all_changes,
                    )
                return AdaptiveGoalResult(
                    goal=goal,
                    status="BLOCKED",
                    cycles=cycles,
                    summary=next_plan.summary,
                    remaining_steps=[],
                    observed_changes=all_changes,
                )

            # A read-only search has no filesystem mutation to wait for. If the
            # same search plan remains after a successful observation, the goal
            # itself is complete rather than an infinite search/replan loop.
            if (
                all(step.get("action") == "search" for step in next_plan.steps)
                and cls._plan_signature(next_plan) == signature
                and not diff.changed_anything
            ):
                return AdaptiveGoalResult(
                    goal=goal,
                    status="COMPLETE",
                    cycles=cycles,
                    summary=f"Read-only goal completed after {cycle_no} adaptive cycle(s).",
                    remaining_steps=[],
                    observed_changes=all_changes,
                )

            # Carry the already validated replan into the next cycle. This
            # avoids observing/planning twice without actually executing the
            # newly selected work.
            pending_plan = next_plan

        return AdaptiveGoalResult(
            goal=goal,
            status="PARTIAL",
            cycles=cycles,
            summary=f"Adaptive cycle limit ({max_cycles}) reached with work remaining.",
            remaining_steps=remaining_steps,
            observed_changes=all_changes,
        )
