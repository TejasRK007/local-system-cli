# -------------------------------------------------------------
# RISK LEVELS
# -------------------------------------------------------------
#
# LOW    — read-only operations (search, list, find)
# MEDIUM — modifying but reversible operations (rename, move)
# HIGH   — destructive / irreversible operations (delete)
#
# -------------------------------------------------------------

# Risk tier displayed to the user (for the Rich UI)
RISK_COLORS: dict[str, str] = {
    "low": "green",
    "medium": "yellow",
    "high": "red",
}

# Authoritative mapping: structured action name → risk tier
_ACTION_RISK_MAP: dict[str, str] = {
    "search": "low",
    "find": "low",
    "list": "low",
    "create_directory": "medium",
    "mkdir": "medium",
    "create_file": "medium",
    "touch": "medium",
    "rename": "medium",
    "move": "medium",
    "delete": "high",
    # Milestone 7: General local system tools
    "get_system_info": "low",
    "sys_info": "low",
    "list_processes": "low",
    "find_process": "low",
    "read_clipboard": "low",
    "write_clipboard": "medium",
    "inspect_archive": "low",
    "extract_archive": "medium",
    "get_file_metadata": "low",
    "metadata": "low",
    # Milestone 8: Personal automation & productivity integrations
    "read_document": "low",
    "summarize_document": "low",
    "browser_fetch_page": "low",
    "browser_search": "low",
    "browser_download_file": "medium",
    "email_search": "low",
    "email_read": "low",
    "email_draft": "medium",
    "email_send": "high",
    "calendar_list_events": "low",
    "calendar_check_conflict": "low",
    "calendar_create_event": "medium",
    "github_list_issues": "low",
    "github_inspect_pr": "low",
    "github_create_issue": "medium",
}


def check_risk(request: str) -> str:
    """
    Classify the risk level from a natural-language request string.

    Checks for dangerous keywords first (high-risk), then modifying
    keywords (medium-risk), and defaults to low.

    Returns: 'high', 'medium', or 'low'.
    """
    request_lower = request.lower()

    high_risk_words = [
        "delete",
        "remove",
        "erase",
        "destroy",
    ]

    for word in high_risk_words:
        if word in request_lower:
            return "high"

    medium_risk_words = [
        "rename",
        "move",
    ]

    for word in medium_risk_words:
        if word in request_lower:
            return "medium"

    return "low"


def get_action_risk(action: str) -> str:
    """
    Return the authoritative risk level for a structured action type.

    This is the primary function used by the execution path.
    The LLM resolves the user's intent; this function then
    classifies the resulting action into a risk tier.

    Args:
        action: one of 'search', 'find', 'list', 'rename',
                'move', 'delete' (case-insensitive).

    Returns: 'high', 'medium', or 'low'.
    """
    return _ACTION_RISK_MAP.get(action.lower().strip(), "low")


def requires_approval(risk: str) -> bool:
    """
    Return True if the risk level requires explicit user approval
    before the operation is executed.

    LOW    → no approval needed.
    MEDIUM → approval required.
    HIGH   → approval required.
    """
    return risk in ("medium", "high")
