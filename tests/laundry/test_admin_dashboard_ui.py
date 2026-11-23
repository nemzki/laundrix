"""Dashboard presentation must display backend verification decisions without changing them."""
import re

import pytest

from app.extensions import db
from app.identity import services
from app.identity.statuses import STATUS_COPY
from app.models import IdentityVerification


@pytest.mark.parametrize("status", tuple(STATUS_COPY))
def test_settings_replaces_admin_banner_without_changing_status_or_eligibility(app, admin_client, admin, status):
    if status != "not_started":
        db.session.add(IdentityVerification(
            user_id=admin.id, provider="didit", environment="sandbox", purpose="kyc", status=status,
        ))
        db.session.commit()
    expected = services.summary_for(admin)
    original_count = db.session.scalar(db.select(db.func.count(IdentityVerification.id)))
    html = admin_client.get("/settings").get_data(as_text=True)
    banner = re.search(r'<section class="card ps-card" aria-labelledby="verification-heading".*?</section>', html, re.S).group()
    assert f'data-idv-status="{status}"' in banner
    assert STATUS_COPY[status]["label"].capitalize() in banner
    assert f'data-idv-can-start="{str(expected["can_start"]).lower()}"' in banner
    assert 'href="/identity/"' in banner
    if expected["can_start"]:
        assert STATUS_COPY[status]["start_label"].capitalize() in banner
    else:
        assert "View verification details" in banner
    for url in ("/dashboard/admin", "/dashboard/admin?ui=jinja"):
        dashboard = admin_client.get(url).get_data(as_text=True)
        assert 'class="dashboard-identity"' not in dashboard
        assert 'aria-label="Identity verification"' not in dashboard
    assert admin_client.get("/identity/").status_code == 200
    assert db.session.scalar(db.select(db.func.count(IdentityVerification.id))) == original_count
    assert services.summary_for(admin)["status"] == status


def test_staff_dashboard_omits_identity_banner_and_keeps_settings_access(app, admin_client, staff_client):
    assert app.config["IDV_ENABLED"]
    for url in ("/dashboard/staff", "/dashboard/staff?ui=jinja"):
        response = staff_client.get(url)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'class="idv-card"' not in html
        assert 'class="dashboard-identity"' not in html
        assert 'id="dashboard-preserved-identity"' not in html
        assert "Identity verification" not in html
    settings = staff_client.get("/settings")
    assert settings.status_code == 200
    verification = re.search(
        r'<section\b[^>]*aria-labelledby="verification-heading".*?</section>',
        settings.get_data(as_text=True), re.S,
    )
    assert verification is not None
    assert 'href="/identity/"' in verification.group()
    assert staff_client.get("/identity/").status_code == 200
    app.config["IDV_ENABLED"] = False
    assert staff_client.get("/identity/").status_code == 404
    html = admin_client.get("/dashboard/admin").get_data(as_text=True)
    assert 'class="dashboard-identity"' not in html
    assert staff_client.get("/dashboard/admin").status_code == 403
