"""The Manage Orders page is server-rendered (the React island was retired), and must keep showing
only the authorized, formatted order view. Same coverage as before, aimed at the current page."""
import re

from markupsafe import escape

from tests.laundry.test_orders import order_by, place, ref_from


def test_orders_list_matches_the_existing_order_summary(admin_client, catalog):
    reference = ref_from(place(admin_client))
    html = admin_client.get('/orders/').get_data(as_text=True)
    order = order_by(reference)
    row = re.search(r'<tr data-ref="%s".*?</tr>' % re.escape(reference), html, re.S).group(0)
    assert str(escape(order.customer_name)) in row
    assert order.customer_contact in row
    assert f'href="/orders/{reference}"' in row                               # link to the order page
    # Scoped to this order's row: the page also holds a hidden summary-dialog placeholder with the same words.
    assert ('Awaiting receipt' in row) == (not order.received_at)
    assert 'tracking_token' not in html and 'qr_code' not in html
    assert 'laundrix-orders-data' not in html and 'react/orders.js' not in html


def test_orders_list_escapes_customer_content(admin_client, catalog):
    name = '</script><img src=x onerror=alert(1)>'
    ref_from(place(admin_client, customer={'new': {'full_name': name, 'contact_number': '09171234567'}}))
    html = admin_client.get('/orders/').get_data(as_text=True)
    assert name not in html
    assert str(escape(name)) in html


def test_admin_and_staff_get_the_same_manage_orders_page(admin_client, staff_client):
    for response in [admin_client.get('/orders/'), staff_client.get('/orders/')]:
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'data-manage-orders' in html and 'data-orders-results' in html
        assert 'laundrix-orders-data' not in html


def test_search_uses_the_server_query(admin_client, catalog):
    reference = ref_from(place(admin_client))
    html = admin_client.get('/orders/?q=' + reference).get_data(as_text=True)
    assert reference in html and 'data-total="1"' in html
    assert f'q={reference}' in html                                           # filter tabs keep the search term
    missing = admin_client.get('/orders/?q=definitely-missing').get_data(as_text=True)
    assert 'No orders match your filters.' in missing and 'data-total="0"' in missing


def test_react_assets_are_served_by_existing_flask_static_route(admin_client):
    for suffix, content_type in [('orders.js', 'javascript'), ('orders.css', 'text/css')]:
        response = admin_client.get('/core/static/react/' + suffix)
        assert response.status_code == 200
        assert content_type in response.content_type


def test_first_paint_is_the_final_seven_column_listing(admin_client, catalog):
    reference = ref_from(place(admin_client))
    html = admin_client.get('/orders/').get_data(as_text=True)
    table = html.split('<table class="mo-table">', 1)[1].split('</table>', 1)[0]
    assert reference in table
    headings = re.findall(r'<th\b[^>]*>(.*?)</th>', table)
    assert headings == ['Order Reference', 'Customer', 'Contact Number', 'Date Created', 'Laundry Status', 'Payment Status', 'Action']
