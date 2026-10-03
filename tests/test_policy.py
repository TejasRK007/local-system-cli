from app.policy import (
    check_risk,
    get_action_risk,
    requires_approval,
)

# ------------------------------------------------------------------
# check_risk  — natural-language classification
# ------------------------------------------------------------------


def test_check_risk_high():
    assert check_risk("Please delete my old files") == "high"
    assert check_risk("Remove all PDFs from Downloads") == "high"
    assert check_risk("Erase text documents") == "high"
    assert check_risk("Destroy confidential files") == "high"


def test_check_risk_medium():
    """Rename and move requests must be classified as medium risk."""
    assert check_risk("Rename report.pdf to final.pdf") == "medium"
    assert check_risk("Move file.txt to Documents") == "medium"


def test_check_risk_low():
    assert check_risk("Show me PDFs from yesterday") == "low"
    assert check_risk("Find Word documents in Documents folder") == "low"
    assert check_risk("Search for text files") == "low"


# ------------------------------------------------------------------
# get_action_risk  — structured action classification
# ------------------------------------------------------------------


def test_get_action_risk_low():
    """Read-only actions must return low risk."""
    assert get_action_risk("search") == "low"
    assert get_action_risk("find") == "low"
    assert get_action_risk("list") == "low"


def test_get_action_risk_medium():
    """Modifying actions must return medium risk."""
    assert get_action_risk("rename") == "medium"
    assert get_action_risk("move") == "medium"


def test_get_action_risk_high():
    """Destructive actions must return high risk."""
    assert get_action_risk("delete") == "high"


def test_get_action_risk_case_insensitive():
    """get_action_risk must be case-insensitive."""
    assert get_action_risk("RENAME") == "medium"
    assert get_action_risk("Delete") == "high"
    assert get_action_risk("SEARCH") == "low"


def test_get_action_risk_unknown_defaults_low():
    """Unknown action strings must default to low rather than raising."""
    assert get_action_risk("email") == "low"
    assert get_action_risk("") == "low"


# ------------------------------------------------------------------
# requires_approval  — approval gate
# ------------------------------------------------------------------


def test_requires_approval():
    """Low risk must not require approval; medium and high must."""
    assert requires_approval("low") is False
    assert requires_approval("medium") is True
    assert requires_approval("high") is True


def test_requires_approval_unknown_defaults_no_approval():
    """An unrecognised risk string must not incorrectly require approval."""
    assert requires_approval("unknown") is False
    assert requires_approval("") is False
