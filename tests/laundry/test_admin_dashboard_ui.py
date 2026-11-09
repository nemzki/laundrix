"""Dashboard presentation must display backend verification decisions without changing them."""
import re

import pytest

from app.extensions import db
from app.identity import services
from app.identity.statuses import STATUS_COPY
from app.models import IdentityVerification


@pytest.mark.parametrize("status", tuple(STATUS_COPY))
def test_admin_banner_preserves_backend_status_and_eligibility(app, admin_client, admin, status):
    if status != "not_started":
        db.session.add(IdentityVerification(
            user_id=admin.id, provider="didit", environment="sandbox", purpose="kyc", status=status,
        ))
        db.session.commit()
    expected = services.summary_for(admin)
    original_count = db.session.scalar(db.select(db.func.count(IdentityVerification.id)))
    html = admin_client.get("/dashboard/admin").get_data(as_text=True)
    banner = re.search(r'<section class="dashboard-identity".*?</section>', html, re.S).group()
    assert f'data-idv-status="{status}"' in banner
    assert STATUS_COPY[status]["label"].title() in banner
    assert f'data-idv-can-start="{str(expected["can_start"]).lower()}"' in banner
    assert 'href="/identity/"' in banner
    if expected["can_start"]:
        assert STATUS_COPY[status]["start_label"].title() in banner
    else:
        assert "View Verification" in banner if status == "verified" else "View Status" in banner
    assert admin_client.get("/identity/").status_code == 200
    assert db.session.scalar(db.select(db.func.count(IdentityVerification.id))) == original_count
    assert services.summary_for(admin)["status"] == status


def test_dashboard_feature_gate_and_staff_identity_card_remain_original(app, admin_client, staff_client):
    staff_html = staff_client.get("/dashboard/staff").get_data(as_text=True)
    assert 'class="idv-card"' in staff_html
    assert 'class="dashboard-identity"' not in staff_html
    app.config["IDV_ENABLED"] = False
    html = admin_client.get("/dashboard/admin").get_data(as_text=True)
    assert 'class="dashboard-identity"' not in html
    assert staff_client.get("/dashboard/admin").status_code == 403
