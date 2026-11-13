"""Theme assets are shared by public/auth/internal shells, excluding protected identity flows."""
import pytest


@pytest.mark.parametrize("role", ["admin", "staff"])
@pytest.mark.parametrize("url", ["/dashboard/", "/dashboard/?ui=jinja", "/orders/"])
def test_internal_shell_loads_shared_prepaint_theme(request, role, url):
    client = request.getfixturevalue(f"{role}_client")
    response = client.get(url, follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    head = html.split("</head>")[0]
    assert head.count('/core/static/js/theme.js') == 1
    assert 'href="/core/static/css/theme.css"' in head
    script = head.split('src="/core/static/js/theme.js"')[1].split("></script>")[0]
    assert "defer" not in script and "async" not in script
    assert 'aria-label="Personal Settings"' in html
    assert 'href="/settings"' in html
    assert 'data-theme-picker' not in html


@pytest.mark.parametrize("url", ["/", "/auth/login", "/staff/login"])
def test_public_pages_load_shared_prepaint_theme(anon_client, url):
    response = anon_client.get(url, follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    head = html.split("</head>")[0]
    assert head.count('/core/static/js/theme.js') == 1
    assert head.count('/core/static/css/theme.css') == 1
    assert 'defer' not in head.split('src="/core/static/js/theme.js"')[1].split('></script>')[0]
    assert 'data-theme-option="system"' in html if url == '/' else 'name="password"' in html


@pytest.mark.parametrize("role", ["admin", "staff"])
def test_authorized_identity_screen_uses_shared_theme(request, role):
    client = request.getfixturevalue(f"{role}_client")
    response = client.get('/identity/', follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '/core/static/js/theme.js' in html
    assert '/core/static/css/theme.css' in html
    assert 'data-theme-picker' not in html
