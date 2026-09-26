def check_risk(request: str) -> str:
    request_lower = request.lower()

    dangerous_words = [
        "delete",
        "remove",
        "erase",
        "destroy",
    ]

    for word in dangerous_words:
        if word in request_lower:
            return "high"

    return "low"