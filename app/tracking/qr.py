"""Creates QR code images."""

import base64
from io import BytesIO

import qrcode


def generate_qr_data_uri(url):
    """Make a QR code for a URL and return it as an inline PNG data URI that can go straight into an <img> tag."""
    image = qrcode.make(url)

    buffer = BytesIO()
    image.save(buffer, format="PNG")

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    return f"data:image/png;base64,{encoded}"