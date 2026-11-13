"""Isolated browser-test server. Never opens the configured production database."""
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server, WSGIRequestHandler

from app.catalog.seed import seed_catalog
from app.extensions import db
from app.models import OrderStatus, Role, Service, User
from app.payments.seed import seed_payments
from config import TestingConfig
from tests.laundry.conftest import _login, _make_app
from tests.staffmgmt.test_unified_login import make_staff


_payment_uploads = tempfile.TemporaryDirectory(prefix="laundrix-browser-payment-qr-")


class BrowserConfig(TestingConfig):
    WTF_CSRF_ENABLED = True
    IDV_ENABLED = False  # No external identity provider requests in browser tests.
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    PAYMENT_UPLOAD_DIR = _payment_uploads.name
    PROFILE_AVATAR_DIR = str(Path(_payment_uploads.name) / 'profile-avatars')
    SMS_ENABLED = False


app = _make_app(BrowserConfig)
with app.app_context():
    db.create_all()
    seed_catalog()
    seed_payments()
    for code in ('wash', 'dry', 'spin'):
        db.session.execute(db.select(Service).filter_by(code=code)).scalar_one().pricing_unit = 'load'
    admin = User(email='admin@example.test', full_name='Browser Admin', role=Role.ADMIN,
                 username='browseradmin', password_hash=generate_password_hash('Browser-Test-Password!42'),
                 is_active=True)
    db.session.add(admin)
    db.session.commit()
    make_staff(email='staff@example.test', password='Browser-Test-Password!42')
    client = app.test_client()
    _login(client, admin)
    page = client.get('/orders/new').get_data(as_text=True)
    token = re.search(r'data-csrf="([^"]+)"', page).group(1)
    service = db.session.execute(db.select(Service).filter_by(code='wash')).scalar_one()
    for index in range(28):
        payment = {'arrangement': 'pay_later', 'entries': []}
        if index % 3 == 1:
            payment = {'arrangement': 'full', 'entries': [{'method': 'cash', 'amount': '80.00'}]}
        body = {
            'items': [{'kind': 'service', 'id': service.id, 'quantity': '1'}], 'extras': [],
            'customer': {'new': {'full_name': f'Customer {index:02}', 'contact_number': f'0917{index:07}'}},
            'payment': payment,
        }
        response = client.post('/orders/new/confirm', json=body, headers={'X-CSRFToken': token})
        if response.status_code != 200:
            raise RuntimeError(response.get_data(as_text=True))
        reference = response.get_json()['redirect'].split('/')[2]
        if index % 6:
            received = client.post(f'/orders/{reference}/confirm-received', json={}, headers={'X-CSRFToken': token})
            assert received.get_json()['ok']
            for status in OrderStatus.FLOW[1:index % 6 + 1]:
                client.post(f'/orders/{reference}/status', data={'csrf_token': token, 'status': status})

if __name__ == '__main__':
    class QuietHandler(WSGIRequestHandler):
        def log_request(self, code='-', size='-'):
            pass
    server = make_server('127.0.0.1', 8771, app, threaded=False, request_handler=QuietHandler)
    print('React browser fixtures ready at http://127.0.0.1:8771', flush=True)
    server.serve_forever()
