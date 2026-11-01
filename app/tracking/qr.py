import base64
from io import BytesIO

import qrcode


def generate_qr_data_uri(url):
    image = qrcode.make(url)

    buffer = BytesIO()
    image.save(buffer, format="PNG")

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    return f"data:image/png;base64,{encoded}"