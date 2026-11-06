"""Philippine mobile-number validation and normalisation (E.164)."""
import re

_SEPARATORS = re.compile(r"[\s\-().]")
_PATTERNS = (
    re.compile(r"^09(\d{9})$"),          # 09171234567
    re.compile(r"^639(\d{9})$"),         # 639171234567
    re.compile(r"^\+639(\d{9})$"),       # +639171234567
)


def normalize_ph_mobile(raw):
    """Return '+639XXXXXXXXX', or None when the value is not a complete Philippine mobile number.

    Landlines, other countries, short or over-long numbers and anything with letters are rejected."""
    if not isinstance(raw, str):
        return None
    text = _SEPARATORS.sub("", raw.strip())
    if not text or len(text) > 16:
        return None
    for pattern in _PATTERNS:
        match = pattern.match(text)
        if match:
            return "+639" + match.group(1)
    return None


def mask_phone(e164):
    """+639171234567 -> +63917•••4567 style masking for staff screens (never the full number)."""
    if not e164 or len(e164) < 8:
        return "\u2014"
    return f"{e164[:6]}\u2022\u2022\u2022{e164[-4:]}"
