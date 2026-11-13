"""Bounded, re-encoded private profile images. No supplied filename is used for storage."""
import io
import os
from pathlib import Path
import re
import secrets
import warnings

from flask import current_app, url_for
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 1024 * 1024
MAX_SIDE = 2048
FORMATS = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP'}
NAME = re.compile(r'avatar-[0-9a-f]{32}\.png\Z')


def directory():
    configured = current_app.config.get('PROFILE_AVATAR_DIR')
    return Path(configured) if configured else Path(current_app.instance_path) / 'uploads' / 'profile_avatars'


def stored_name(url):
    if not isinstance(url, str):
        return None
    name = url.rsplit('/', 1)[-1]
    return name if NAME.fullmatch(name) and url == url_for('core.profile_avatar', filename=name) else None


def path_for(name):
    if not isinstance(name, str) or not NAME.fullmatch(name):
        return None
    root = directory().resolve()
    path = (root / name).resolve()
    return path if path.parent == root and path.is_file() else None


def delete(name):
    path = path_for(name)
    if path is not None:
        try:
            path.unlink()
        except OSError:
            current_app.logger.warning('Could not remove an obsolete profile image.')


def save(upload):
    extension = Path(upload.filename or '').suffix.lower()
    if extension not in FORMATS:
        return None, 'Choose a PNG, JPEG, or WebP image.'
    data = upload.stream.read(MAX_BYTES + 1)
    if not data:
        return None, 'The image file is empty.'
    if len(data) > MAX_BYTES:
        return None, 'The image must be 1 MB or smaller.'
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format != FORMATS[extension]:
                    return None, 'The image content must match its PNG, JPEG, or WebP file extension.'
                if min(probe.size) < 32 or max(probe.size) > MAX_SIDE:
                    return None, 'Use an image between 32 and 2048 pixels on each side.'
                if getattr(probe, 'n_frames', 1) != 1:
                    return None, 'Choose a still image, not an animation.'
                probe.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                pixels = ImageOps.fit(ImageOps.exif_transpose(image).convert('RGBA'), (512, 512))
                clean = Image.new('RGBA', pixels.size)
                clean.paste(pixels)
            output = io.BytesIO()
            clean.save(output, format='PNG', optimize=True)
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, SyntaxError, ValueError):
        return None, 'That file is not a valid supported image.'
    name = f'avatar-{secrets.token_hex(16)}.png'
    root = directory()
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f'.{name}.tmp'
    try:
        with temporary.open('xb') as target:
            target.write(output.getvalue())
        os.replace(temporary, root / name)
    finally:
        temporary.unlink(missing_ok=True)
    return name, None
