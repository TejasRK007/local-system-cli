"""
Recovery and Failure Classification Engine for Local Agentic Automation System.

Provides state observation, failure classification, bounded retries, and
safe replanning capabilities while preserving strict policy, risk, path safety,
and approval controls.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

MAX_RETRIES = 2


class FailureCategory(str, Enum):
    RETRYABLE = "RETRYABLE"
    CONFLICT = "CONFLICT"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"


@dataclass
class FailureResult:
    category: FailureCategory
    retryable: bool
    description: str
    replan_possible: bool = False


@dataclass
class ObservationState:
    source_exists: bool
    destination_exists: bool
    is_verified: bool
    summary: str


def observe_filesystem(
    action: str,
    source_path: Optional[str | Path] = None,
    destination_path: Optional[str | Path] = None,
) -> ObservationState:
    """
    Observe the physical filesystem state post-execution.
    """
    src = Path(source_path).expanduser() if source_path else None
    dst = Path(destination_path).expanduser() if destination_path else None

    src_exists = src.exists() if src else False
    dst_exists = dst.exists() if dst else False

    action_clean = action.lower().strip()

    if action_clean == "delete":
        # For delete, source must NO longer exist
        is_verified = not src_exists if src else True
        summary = (
            f"Observed: target {src} is deleted."
            if is_verified
            else f"Observed: target {src} still exists."
        )

    elif action_clean in ("rename", "move"):
        # For rename/move, src must NOT exist, dst MUST exist
        is_verified = (not src_exists) and dst_exists
        summary = (
            f"Observed: source {src} gone, destination {dst} exists."
            if is_verified
            else f"Observed: src_exists={src_exists}, dst_exists={dst_exists}."
        )

    elif action_clean in ("create_directory", "mkdir"):
        target = dst or src
        is_verified = (target.exists() and target.is_dir()) if target else False
        summary = (
            f"Observed: directory {target} exists."
            if is_verified
            else f"Observed: directory {target} does not exist or is not a directory."
        )

    else:  # search or read-only actions
        is_verified = True
        summary = "Observed: read-only operation."

    return ObservationState(
        source_exists=src_exists,
        destination_exists=dst_exists,
        is_verified=is_verified,
        summary=summary,
    )


def classify_failure(
    action: str,
    tool_result: str,
    source_path: Optional[str | Path] = None,
    destination_path: Optional[str | Path] = None,
) -> FailureResult:
    """
    Classify a non-successful tool result or observation failure into a structured FailureResult.
    """
    result_lower = tool_result.lower()
    obs = observe_filesystem(action, source_path, destination_path)

    # 1. CONFLICT check: target/destination already exists before/during operation
    if "already exists" in result_lower or "conflict" in result_lower:
        return FailureResult(
            category=FailureCategory.CONFLICT,
            retryable=False,
            description="Destination path already contains a file with the same name.",
            replan_possible=True,
        )

    # 2. POLICY_VIOLATION check: outside allowed directories or path traversal
    if (
        "outside allowed" in result_lower
        or "blocked" in result_lower
        or "traversal" in result_lower
    ):
        return FailureResult(
            category=FailureCategory.POLICY_VIOLATION,
            retryable=False,
            description="Operation violates path safety policy or allowed directory constraints.",
            replan_possible=False,
        )

    # 3. NEEDS_USER_INPUT check: ambiguous match or missing parameters
    if "ambiguous" in result_lower or "multiple" in result_lower or "unsupported" in result_lower:
        return FailureResult(
            category=FailureCategory.NEEDS_USER_INPUT,
            retryable=False,
            description="Operation requires user clarification or input.",
            replan_possible=False,
        )

    # 4. VERIFICATION_FAILURE check: tool returned success message but filesystem observation failed
    if "verified:" in result_lower and not obs.is_verified:
        return FailureResult(
            category=FailureCategory.VERIFICATION_FAILURE,
            retryable=False,
            description="Tool reported success, but physical filesystem state observation failed "
            "verification.",
            replan_possible=True,
        )

    # 5. RETRYABLE check: temporary lock, permission delay, or transient environment failure
    if any(
        k in result_lower
        for k in [
            "temporary",
            "busy",
            "locked",
            "timeout",
            "resource temporarily unavailable",
        ]
    ):
        return FailureResult(
            category=FailureCategory.RETRYABLE,
            retryable=True,
            description="Transient environment or file lock issue encountered.",
            replan_possible=False,
        )

    # 6. Default EXECUTION_FAILURE: missing source file, unexpected OS error
    return FailureResult(
        category=FailureCategory.EXECUTION_FAILURE,
        retryable=False,
        description=f"Execution failed: {tool_result}",
        replan_possible=False,
    )


def execute_action_with_recovery(
    action: str,
    action_func: Callable[..., str],
    func_args: tuple,
    source_path: Optional[str | Path] = None,
    destination_path: Optional[str | Path] = None,
    max_retries: int = MAX_RETRIES,
    on_retry: Optional[Callable[[int, str], None]] = None,
) -> dict[str, Any]:
    """
    Execute a filesystem action with observation, failure classification, and bounded retries.

    Returns a result dictionary:
    {
        "status": "SUCCESS" | "CONFLICT" | "FAILED" | "POLICY_VIOLATION" | "NEEDS_USER_INPUT" |
            "RETRY_EXHAUSTED" | "VERIFICATION_FAILURE",
        "result_summary": str,
        "attempts": int,
        "failure_category": Optional[str],
        "observation": ObservationState,
    }
    """
    attempt = 0
    last_tool_result = ""
    last_failure: Optional[FailureResult] = None
    last_obs: Optional[ObservationState] = None

    while attempt < max_retries + 1:
        attempt += 1

        tool_result = action_func(*func_args)
        last_tool_result = tool_result
        obs = observe_filesystem(action, source_path, destination_path)
        last_obs = obs

        tool_verified = "verified:" in tool_result.lower()
        real_files_on_disk = bool(obs.source_exists or obs.destination_exists)

        if tool_verified:
            if real_files_on_disk and not obs.is_verified:
                failure = FailureResult(
                    category=FailureCategory.VERIFICATION_FAILURE,
                    retryable=False,
                    description="Tool reported success, but physical filesystem state observation "
                    "failed verification.",
                    replan_possible=True,
                )
                last_failure = failure
                break
            else:
                return {
                    "status": "SUCCESS",
                    "result_summary": tool_result,
                    "attempts": attempt,
                    "failure_category": None,
                    "observation": obs,
                }
        else:
            failure = classify_failure(action, tool_result, source_path, destination_path)
            last_failure = failure

            if failure.retryable and attempt <= max_retries:
                if on_retry:
                    on_retry(attempt, failure.description)
                continue
            else:
                break

    status_str = (
        "RETRY_EXHAUSTED"
        if (last_failure and last_failure.retryable and attempt > max_retries)
        else (last_failure.category.value if last_failure else "FAILED")
    )

    summary_str = f"Failed ({status_str} after {attempt} attempt(s)): {last_tool_result}"

    return {
        "status": status_str,
        "result_summary": summary_str,
        "attempts": attempt,
        "failure_category": (last_failure.category.value if last_failure else "FAILED"),
        "observation": last_obs,
    }
