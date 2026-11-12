"""The React island must preserve Flask's authorized, formatted order view."""
import json
import re

from tests.laundry.test_orders import order_by, place, ref_from


def _view(response):
    match = re.search(r'<script type="application/json" id="laundrix-orders-data">(.*?)</script>',
                      response.get_data(as_text=True), re.S)
    assert match, "Admin response must include the escaped React view model"
    return json.loads(match.group(1))


def test_react_view_matches_existing_order_summary(admin_client, catalog):
    reference = ref_from(place(admin_client))
    response = admin_client.get('/orders/')
    data = _view(response)
    order = order_by(reference)
    row = next(row for row in data['orders'] if row['reference'] == reference)
    assert row['customer'] == order.customer_name
    assert row['contact'] == order.customer_contact
    assert row['total'] == f"₱{order.total:,.2f}"
    assert row['detailUrl'] == f'/orders/{reference}'
    assert row['stubUrl'] == f'/orders/{reference}/stub'
    assert row['awaiting'] == (not order.received_at)
    assert 'tracking_token' not in row and 'qr_code' not in row
    assert 'data-orders-jinja' in response.get_data(as_text=True)


def test_react_view_escapes_customer_content(admin_client, catalog):
    name = '</script><img src=x onerror=alert(1)>'
    ref_from(place(admin_client, customer={'new': {'full_name': name, 'contact_number': '09171234567'}}))
    response = admin_client.get('/orders/')
    assert _view(response)['orders'][0]['customer'] == name
    assert name not in response.get_data(as_text=True)


def test_jinja_override_and_staff_keep_existing_page(admin_client, staff_client):
    for response in [admin_client.get('/orders/?ui=jinja'), staff_client.get('/orders/')]:
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'laundrix-orders-data' not in html
        assert 'react/orders.js' not in html
        assert 'data-orders-filters' in html


def test_react_search_uses_existing_server_query(admin_client, catalog):
    reference = ref_from(place(admin_client))
    data = _view(admin_client.get('/orders/?q=' + reference))
    assert data['term'] == reference and data['total'] == 1
    assert data['orders'][0]['reference'] == reference
    assert all('q=' in row['url'] for row in data['filters'])
    assert _view(admin_client.get('/orders/?q=definitely-missing'))['orders'] == []


def test_react_assets_are_served_by_existing_flask_static_route(admin_client):
    for suffix, content_type in [('orders.js', 'javascript'), ('orders.css', 'text/css')]:
        response = admin_client.get('/core/static/react/' + suffix)
        assert response.status_code == 200
        assert content_type in response.content_type


def test_first_paint_is_the_final_seven_column_listing(admin_client, catalog):
    reference = ref_from(place(admin_client))
    html = admin_client.get('/orders/').get_data(as_text=True)
    server = html.split('<div id="laundrix-react-orders"', 1)[1].split('<div data-orders-jinja', 1)[0]
    assert 'data-renderer="server"' in server
    assert reference in server
    headings = re.findall(r'<th\b[^>]*>(.*?)</th>', server)
    assert headings == ['Order Reference', 'Customer', 'Contact Number', 'Date Created', 'Laundry Status', 'Payment Status', 'Action']
    assert '<div data-orders-jinja hidden>' in html
    assert _view(admin_client.get('/orders/'))['orders'][0]['total'] == '₱160.00'
