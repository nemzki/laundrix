"""Payment QR image handling. The upload is never trusted: it is size-limited, decoded with Pillow,
dimension-checked and RE-ENCODED to a fresh PNG (dropping metadata and any trailing/hidden data).
The stored name is random and generated here; the user's filename and any path are discarded."""
import io
import os
import re
import secrets
from pathlib import Path

from flask import current_app
from PIL import Image, UnidentifiedImageError

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
MAX_BYTES = 2 * 1024 * 1024
MIN_SIDE, MAX_SIDE, MAX_PIXELS = 100, 2000, 4_000_000
NAME_RE = re.compile(r"^qr-[0-9a-f]{32}\.png$")


def upload_dir() -> Path:
    configured = current_app.config.get("PAYMENT_UPLOAD_DIR")
    base = Path(configured) if configured else Path(current_app.instance_path) / "uploads" / "payment_qr"
    base.mkdir(parents=True, exist_ok=True)
    return base


def qr_path(filename):
    """Resolve a stored name to a file path, or None. Only names we generated are accepted."""
    if not isinstance(filename, str) or not NAME_RE.match(filename):
        return None
    base = upload_dir().resolve()
    path = (base / filename).resolve()
    if path.parent != base or not path.is_file():
        return None
    return path


def save_qr_image(file_storage):
    """Returns (stored_filename, error)."""
    if file_storage is None or not getattr(file_storage, "filename", ""):
        return None, "Choose an image to upload."
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None, "Upload a PNG, JPEG or WebP image."
    data = file_storage.stream.read(MAX_BYTES + 1)
    if not data:
        return None, "The file is empty."
    if len(data) > MAX_BYTES:
        return None, "The image must be 2 MB or smaller."
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in ALLOWED_FORMATS:
                return None, "Upload a PNG, JPEG or WebP image."
            width, height = probe.size
            if min(width, height) < MIN_SIDE or max(width, height) > MAX_SIDE or width * height > MAX_PIXELS:
                return None, f"The image must be between {MIN_SIDE} and {MAX_SIDE} pixels on each side."
            probe.verify()
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            clean = img.convert("RGBA")
        out = io.BytesIO()
        clean.save(out, format="PNG", optimize=True)   # fresh PNG: no EXIF, no appended payloads
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        return None, "That file is not a valid image."

    name = f"qr-{secrets.token_hex(16)}.png"
    base = upload_dir()
    tmp = base / f".{name}.tmp"
    tmp.write_bytes(out.getvalue())
    os.replace(tmp, base / name)
    return name, None


def delete_qr(filename):
    path = qr_path(filename)
    if path is not None:
        try:
            path.unlink()
        except OSError:
            current_app.logger.warning("Could not delete old payment QR image %s", filename)
