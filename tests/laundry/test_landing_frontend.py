"""Approved v0 presentation, original authentication and landing route behavior."""
import re

import pytest


def test_approved_landing_sections_and_real_authentication_links(anon_client):
    response = anon_client.get('/')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for section in ('home', 'features', 'how-it-works', 'preview', 'about'):
        assert f'id="{section}"' in html
    for text in ('Laundry Management,', 'Made Simple.', 'Built for Wash Up! Laundry Shop',
                 'demonstration only', 'demo records', 'Authorized Admin and Staff access'):
        assert text in html
    assert html.count('data-sign-in=""') == 3
    assert html.count('href="/auth/login"') == 3
    assert '/staff/login' not in html
    assert 'sign-in is not connected' not in html
    assert '/core/static/images/mascot-original.svg' in html
    assert 'Original Laundrix design' in html
    assert 'style=' not in html
    assert '/_next/' not in html and '/react/' not in html
    assert '/theme.js' not in html and '/theme.css' not in html


def test_all_workflow_and_preview_states_are_server_rendered(anon_client):
    html = anon_client.get('/').get_data(as_text=True)
    assert len(re.findall(r'data-workflow-step="[0-3]"', html)) == 4
    assert len(re.findall(r'data-workflow-template="[0-3]"', html)) == 4
    assert len(re.findall(r'data-preview-template="[0-2]"', html)) == 3
    assert 'role="tablist"' in html and 'role="tabpanel"' in html
    assert 'aria-controls="mobile-menu"' in html


@pytest.mark.parametrize('role', ['admin', 'staff'])
def test_authenticated_landing_redirect_is_unchanged(request, role):
    client = request.getfixturevalue(f'{role}_client')
    response = client.get('/')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/dashboard/')


def test_landing_assets_are_local_and_available(anon_client):
    html = anon_client.get('/').get_data(as_text=True)
    urls = set(re.findall(r'(?:href|src)="(/(?:landing|core)/static/[^\"]+)"', html))
    assert urls
    for url in urls:
        assert anon_client.get(url).status_code == 200, url
    css = anon_client.get('/landing/static/css/v0-landing.css').get_data(as_text=True)
    assert 'https://' not in css.split('\n', 1)[1]
    for font in re.findall(r'url\(\.\./fonts/([^\)]+)\)', css):
        assert anon_client.get('/landing/static/fonts/' + font).status_code == 200


def test_landing_preserves_flashed_messages(anon_client):
    with anon_client.session_transaction() as session:
        session['_flashes'] = [('success', 'You have signed out.')]
    html = anon_client.get('/').get_data(as_text=True)
    assert 'You have signed out.' in html
    assert 'aria-live="polite"' in html


@pytest.mark.parametrize('screen,expected', [
    ('dashboard', ('Admin Dashboard', 'Order Overview', 'Financial Overview', 'Outstanding Balance')),
    ('orders', ('Manage Orders', 'Contact Number', 'Laundry Status', 'Payment Status')),
    ('payments', ('Payment Records', 'Recorded By', 'Amount', 'Reversals Only')),
])
def test_preview_captures_original_design_and_fields(anon_client, screen, expected):
    import io
    from PIL import Image
    response = anon_client.get(f'/landing/static/previews/{screen}.png')
    assert response.status_code == 200
    assert Image.open(io.BytesIO(response.data)).size == (1440, 1000)
    manifest = anon_client.get('/landing/static/previews/manifest.json').get_json()
    assert manifest['data'] == 'Synthetic browser fixture records'
    actual = next(item for item in manifest['screens'] if item['name'] == screen)
    details = actual['title'] + ' ' + ' '.join(actual['fields'] + actual['sections'] + actual['metrics'] + actual['filters'])
    for text in expected:
        assert text in details
