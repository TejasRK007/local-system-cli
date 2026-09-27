from app.policy import check_risk


def test_check_risk_high():
    assert check_risk("Please delete my old files") == "high"
    assert check_risk("Remove all PDFs from Downloads") == "high"
    assert check_risk("Erase text documents") == "high"
    assert check_risk("Destroy confidential files") == "high"


def test_check_risk_low():
    assert check_risk("Show me PDFs from yesterday") == "low"
    assert check_risk("Find Word documents in Documents folder") == "low"
    assert check_risk("Search for text files") == "low"
