"""Theme assets belong to internal shells, never authentication or identity flows."""
import pytest


@pytest.mark.parametrize("role", ["admin", "staff"])
@pytest.mark.parametrize("url", ["/dashboard/", "/dashboard/?ui=jinja", "/orders/"])
def test_internal_shell_loads_shared_prepaint_theme(request, role, url):
    client = request.getfixturevalue(f"{role}_client")
    response = client.get(url, follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    head = html.split("</head>")[0]
    assert 'src="/core/static/js/theme.js"' in head
    assert 'href="/core/static/css/theme.css"' in head
    script = head.split('src="/core/static/js/theme.js"')[1].split("></script>")[0]
    assert "defer" not in script and "async" not in script
    assert 'aria-label="Change Theme"' in html
    assert 'role="menuitemradio"' in html
    assert 'data-theme-option="system"' in html


@pytest.mark.parametrize("url", ["/", "/auth/login", "/staff/login"])
def test_public_pages_do_not_load_theme(anon_client, url):
    response = anon_client.get(url, follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '/core/static/js/theme.js' not in html
    assert '/core/static/css/theme.css' not in html
    assert 'data-theme-picker' not in html


@pytest.mark.parametrize("role", ["admin", "staff"])
def test_identity_screen_stays_outside_theme(request, role):
    client = request.getfixturevalue(f"{role}_client")
    response = client.get('/identity/', follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '/core/static/js/theme.js' not in html
    assert '/core/static/css/theme.css' not in html
    assert 'data-theme-picker' not in html
