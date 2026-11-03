"""Turns an HTTP request (JSON or HTML form) into the plain structures the payment service validates."""


def entries_from_request(req):
    """Returns (entries, idempotency_key). Nothing here is trusted; the service validates it."""
    if req.is_json:
        data = req.get_json(silent=True)
        if not isinstance(data, dict):
            return None, None
        return data.get("entries"), data.get("idempotency_key")
    methods = req.form.getlist("method")
    amounts = req.form.getlist("amount")
    refs = req.form.getlist("reference")
    entries = []
    for i, (method, amount) in enumerate(zip(methods, amounts)):
        if not (method.strip() or amount.strip()):
            continue  # blank row
        entries.append({
            "method": method, "amount": amount,
            "reference": refs[i] if i < len(refs) else "", "notes": req.form.get("notes", ""),
        })
    return entries, req.form.get("idempotency_key")


def body_from_request(req):
    """Flat dict from JSON or form, for settings/method/reverse endpoints."""
    if req.is_json:
        data = req.get_json(silent=True)
        return data if isinstance(data, dict) else {}
    return req.form
