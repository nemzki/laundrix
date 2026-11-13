"""Verification presentation preserves backend states, consent, ownership and account gates."""
import pytest
from app.extensions import db
from app.identity.statuses import STATUS_COPY
from app.models import AccountStatus, IdentityVerification


@pytest.mark.parametrize('role', ['admin', 'staff'])
@pytest.mark.parametrize('status', tuple(STATUS_COPY))
def test_verification_state_presentation(request, role, status):
    app = request.getfixturevalue('app')
    app.config['IDV_ENABLED'] = True
    client = request.getfixturevalue(f'{role}_client')
    user = request.getfixturevalue(role)
    if status != 'not_started':
        db.session.add(IdentityVerification(user_id=user.id, provider='didit', environment='sandbox', purpose='kyc', status=status))
        db.session.commit()
    html = client.get('/identity/').get_data(as_text=True)
    assert f'data-idv-status="{status}"' in html
    assert STATUS_COPY[status]['label'].title() in html
    assert 'href="/settings"' in html
    assert '/core/static/js/theme.js' in html
    assert '/core/static/css/theme.css' in html
    assert '/identity/static/css/verification.css' in html
    assert ('href="/identity/start"' in html) == STATUS_COPY[status]['can_start']
    assert ('action="/identity/refresh"' in html) == (status in ('in_progress', 'pending_review'))
    assert 'provider_session_id' not in html and 'session_token' not in html


def test_consent_notice_and_required_fields_remain_intact(app, admin_client):
    app.config['IDV_ENABLED'] = True
    html = admin_client.get('/identity/start').get_data(as_text=True)
    assert 'method="post" action="/identity/start"' in html
    assert 'name="csrf_token"' in html
    assert '<input type="checkbox" name="consent" required>' in html
    for text in ('National Privacy Commission', 'handled outside your country', 'not</strong> stored on Laundrix servers', "I've read this notice", 'Continue to Verification', 'Back to Personal Settings'):
        assert text in html
    assert 'iframe' not in html and 'type="file"' not in html


def test_historical_attempts_stay_read_only_and_owned(app, admin_client, admin, staff_client):
    app.config['IDV_ENABLED'] = True
    old = IdentityVerification(user_id=admin.id, provider='didit', environment='sandbox', purpose='kyc', status='rejected')
    new = IdentityVerification(user_id=admin.id, provider='didit', environment='sandbox', purpose='kyc', status='verified')
    db.session.add_all([old,new]); db.session.commit()
    html = admin_client.get('/identity/').get_data(as_text=True)
    assert 'Previous Attempts' in html
    historical = admin_client.get(f'/identity/attempt/{old.public_id}').get_data(as_text=True)
    assert 'View Current Status' in historical
    assert 'href="/identity/start"' not in historical
    assert 'action="/identity/refresh"' not in historical
    assert staff_client.get(f'/identity/attempt/{old.public_id}').status_code == 404


@pytest.mark.parametrize('status', AccountStatus.PENDING)
def test_restricted_accounts_keep_gate_and_do_not_get_dead_settings_link(app, admin_client, admin, status):
    app.config['IDV_ENABLED'] = True
    admin.account_status = status; db.session.commit()
    html = admin_client.get('/identity/').get_data(as_text=True)
    assert 'href="/settings"' not in html
    assert 'verification and account approval' in html
    assert '/identity/' in admin_client.get('/settings').headers['Location']
