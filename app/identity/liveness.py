
"""Validate Didit Passive Liveness responses before face search."""

def is_approved_passive_liveness(report) -> bool:
    """Return True only for a structurally valid, approved PASSIVE result."""
    if not isinstance(report, dict):
        return False

    # Require the documented nested liveness response.
    liveness = report.get("liveness")
    if not isinstance(liveness, dict):
        return False

    status = liveness.get("status")
    method = liveness.get("method")

    if not isinstance(status, str) or status != "Approved":
        return False

    if not isinstance(method, str) or method != "PASSIVE":
        return False

    return True
