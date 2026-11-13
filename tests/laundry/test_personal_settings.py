"""Personal Settings shows only current-user fields and reuses existing verification rules."""
import pytest
from app.extensions import db
from app.identity import services
from app.identity.statuses import STATUS_COPY
from app.models import AccountStatus, IdentityVerification


@pytest.mark.parametrize('role', ['admin', 'staff'])
def test_current_user_profile_and_no_sensitive_fields(request, role):
    client = request.getfixturevalue(f'{role}_client')
    user = request.getfixturevalue(role)
    user.full_name = f'{role.title()} Own Profile'
    db.session.commit()
    response = client.get('/settings?user_id=999&email=someone@example.test')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'private, no-store'
    html = response.get_data(as_text=True)
    assert user.full_name in html and user.email in html
    assert 'someone@example.test' not in html
    assert 'data-theme-preferences' in html
    for forbidden in ('password_hash', 'google_sub', 'staff_id_hash', 'enroll_token_hash', 'Change Password'):
        assert forbidden not in html
    assert 'name="full_name"' in html and 'name="role"' not in html
    assert client.post('/settings').status_code == 405
    assert client.get('/settings/999').status_code == 404


@pytest.mark.parametrize('role', ['admin', 'staff'])
@pytest.mark.parametrize('status', tuple(STATUS_COPY))
def test_settings_uses_owned_verification_and_eligibility(request, role, status):
    app = request.getfixturevalue('app')
    app.config['IDV_ENABLED'] = True
    client = request.getfixturevalue(f'{role}_client')
    user = request.getfixturevalue(role)
    if status != 'not_started':
        db.session.add(IdentityVerification(user_id=user.id, provider='didit', environment='sandbox', purpose='kyc', status=status))
        db.session.commit()
    expected = services.summary_for(user)
    before = db.session.scalar(db.select(db.func.count(IdentityVerification.id)))
    html = client.get('/settings').get_data(as_text=True)
    assert f'data-idv-status="{status}"' in html
    assert f'data-idv-can-start="{str(expected["can_start"]).lower()}"' in html
    assert STATUS_COPY[status]['body'] in html.replace('&#39;', "'")
    assert ('href="/identity/start"' in html) == expected['can_start']
    assert ('action="/identity/refresh"' in html) == expected['can_refresh']
    assert 'href="/identity/"' in html
    assert client.get('/identity/').status_code == 200
    if expected['can_start']:
        assert client.get('/identity/start').status_code == 200
    assert db.session.scalar(db.select(db.func.count(IdentityVerification.id))) == before


def test_feature_disabled_has_no_fabricated_state(app, admin_client):
    app.config['IDV_ENABLED'] = False
    html = admin_client.get('/settings').get_data(as_text=True)
    assert 'not enabled for this installation' in html
    assert 'data-idv-status=' not in html
    assert 'href="/identity/' not in html


def test_unauthenticated_uses_existing_login(anon_client):
    response = anon_client.get('/settings')
    assert response.status_code == 302
    assert '/auth/login' in response.headers['Location']


@pytest.mark.parametrize('status', AccountStatus.ALL)
def test_account_gate_is_not_bypassed(app, admin_client, admin, status):
    admin.account_status = status
    db.session.commit()
    response = admin_client.get('/settings')
    if status == AccountStatus.ACTIVE:
        assert response.status_code == 200
    elif status in AccountStatus.PENDING:
        assert response.status_code == 302 and '/identity/' in response.headers['Location']
    else:
        assert response.status_code == 302 and '/auth/login' in response.headers['Location']
