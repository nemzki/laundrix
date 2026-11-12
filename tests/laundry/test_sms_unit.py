"""SMS unit tests: phone numbers, the UniSMS client, configuration and the migration. No network."""
import importlib.util
import pathlib

import pytest
import requests

from app.sms import provider as prov
from app.sms.phone import mask_phone, normalize_ph_mobile
from config import BaseConfig, TestingConfig, _float

sa = pytest.importorskip("sqlalchemy")
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("A real HTTP request was attempted during a test.")
    monkeypatch.setattr("requests.sessions.Session.request", blocked)


# ----------------------------------------------------------------------------- phone numbers
@pytest.mark.parametrize("raw", ["09171234567", "+639171234567", "639171234567", "0917 123 4567",
                                 "(0917) 123-4567", "+63 917 123 4567", "  09171234567  "])
def test_valid_philippine_mobile_numbers_normalise_to_e164(raw):
    assert normalize_ph_mobile(raw) == "+639171234567"


@pytest.mark.parametrize("raw", ["9171234567", "0817123456", "09171234", "091712345678", "+6391712345678", "+14155550123",
                                 "0281234567", "abc", "", None, 9171234567, "0917123456a", "+63917123456", "639171234"])
def test_invalid_or_incomplete_numbers_are_rejected(raw):
    assert normalize_ph_mobile(raw) is None


def test_numbers_are_masked_for_display():
    assert mask_phone("+639171234567") == "+63917\u2022\u2022\u20224567"
    assert mask_phone(None) == "\u2014" and mask_phone("") == "\u2014"


# ----------------------------------------------------------------------------- provider client
class Resp:
    def __init__(self, code, body=None, bad_json=False):
        self.status_code, self._body, self._bad = code, body, bad_json

    def json(self):
        if self._bad:
            raise ValueError("no json")
        return self._body


@pytest.fixture()
def client(monkeypatch):
    c = prov.UniSMSClient("KEY-123", "Unisoft", "https://unismsapi.com/api/", 3.05, 10)
    c.calls = []

    def post(url, json=None, auth=None, timeout=None):
        c.calls.append(("POST", url, json, auth, timeout))
        if isinstance(c.reply, Exception):
            raise c.reply
        return c.reply

    def get(url, auth=None, timeout=None):
        c.calls.append(("GET", url, None, auth, timeout))
        if isinstance(c.reply, Exception):
            raise c.reply
        return c.reply
    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("requests.get", get)
    return c


def ok_body(status="pending", ref="msg_abc", reason=None):
    return {"message": {"status": status, "reference_id": ref, "recipient": "+639171234567",
                        "sender_id": "Unisoft", "fail_reason": reason}}


def test_send_uses_basic_auth_with_an_empty_password_and_documented_fields(client):
    client.reply = Resp(201, ok_body())
    result = client.send("+639171234567", "hello", {"order_id": 5, "template": "ready_for_pickup"})
    method, url, body, auth, timeout = client.calls[0]
    assert (result.outcome, result.provider_status, result.reference_id) == (prov.ACCEPTED, "pending", "msg_abc")
    assert url == "https://unismsapi.com/api/sms" and timeout == (3.05, 10)
    assert (auth.username, auth.password) == ("KEY-123", "")
    assert body == {"recipient": "+639171234567", "content": "hello", "sender_id": "Unisoft",
                    "metadata": {"order_id": "5", "template": "ready_for_pickup"}}


@pytest.mark.parametrize("code,outcome", [(401, prov.REJECTED), (403, prov.REJECTED), (402, prov.REJECTED), (429, prov.REJECTED),
                                          (400, prov.REJECTED), (422, prov.REJECTED), (500, prov.AMBIGUOUS), (502, prov.AMBIGUOUS),
                                          (503, prov.AMBIGUOUS)])
def test_http_errors_are_classified(client, code, outcome):
    client.reply = Resp(code, {"message": "bad number +639171234567, key KEY-123"})
    result = client.send("+639171234567", "x")
    assert result.outcome == outcome and result.error
    assert "KEY-123" not in result.error and "639171234567" not in result.error


@pytest.mark.parametrize("reply", [Resp(201, None, bad_json=True), Resp(201, {"x": 1}), Resp(201, {"message": {"status": "pending"}}),
                                   Resp(201, {"message": {"reference_id": "../bad id"}}), Resp(302, {})])
def test_unreadable_or_unexpected_replies_are_ambiguous(client, reply):
    client.reply = reply
    assert client.send("+639171234567", "x").outcome == prov.AMBIGUOUS


@pytest.mark.parametrize("exc", [requests.exceptions.ReadTimeout(), requests.exceptions.ConnectTimeout(),
                                 requests.exceptions.ConnectionError("KEY-123")])
def test_timeouts_and_dropped_connections_are_ambiguous_and_leak_nothing(client, exc):
    client.reply = exc
    result = client.send("+639171234567", "x")
    assert result.outcome == prov.AMBIGUOUS and "KEY-123" not in result.error


@pytest.mark.parametrize("status", ["pending", "retrying", "sent", "failed"])
def test_all_documented_statuses_are_understood_on_send_and_status_calls(client, status):
    client.reply = Resp(201, ok_body(status, reason="No credit"))
    assert client.send("+639171234567", "x").provider_status == status
    client.reply = Resp(200, ok_body(status, reason="No credit"))
    result = client.get_status("msg_abc")
    assert (result.ok, result.provider_status) == (True, status)
    assert client.calls[-1][1] == "https://unismsapi.com/api/sms/msg_abc"
    assert (client.calls[-1][3].username, client.calls[-1][3].password) == ("KEY-123", "")


def test_an_unknown_provider_status_on_send_is_treated_as_merely_queued(client):
    client.reply = Resp(201, ok_body("mystery"))
    assert client.send("+639171234567", "x").provider_status == "pending"


def test_status_failures_never_raise(client):
    for reply in (Resp(404, {}), Resp(401, {}), Resp(500, {}), Resp(200, None, bad_json=True), Resp(200, {"message": {"status": "??"}}),
                  requests.exceptions.ConnectionError()):
        client.reply = reply
        assert client.get_status("msg_abc").ok is False
    client.reply = Resp(404, {})
    assert client.get_status("msg_abc").not_found is True
    assert client.get_status("../etc").ok is False and client.get_status(None).ok is False


def test_provider_text_is_scrubbed():
    text = prov.safe_text("Call +639171234567 with key KEY-123\n\tnow", secret="KEY-123")
    assert "639171234567" not in text and "KEY-123" not in text and "\n" not in text and "[number]" in text
    assert len(prov.safe_text("x" * 500)) == 140


# ----------------------------------------------------------------------------- configuration
def test_sms_is_off_by_default_and_never_on_in_tests():
    assert TestingConfig.SMS_ENABLED is False and TestingConfig.UNISMS_API_SECRET_KEY is None
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in ("SMS_ENABLED=false", "UNISMS_API_BASE_URL=https://unismsapi.com/api", "UNISMS_API_SECRET_KEY=",
                 "UNISMS_SENDER_ID=Unisoft", "SMS_CONNECT_TIMEOUT=3.05", "SMS_READ_TIMEOUT=10"):
        assert line in example, line
    assert "UNISMS_API_SECRET_KEY=paste" not in example                             # no placeholder that looks like a key


@pytest.mark.parametrize("value,expected", [("2.5", 2.5), ("7", 7.0), ("", 5.0), ("abc", 5.0), ("-3", 5.0), ("0", 5.0), ("nan", 5.0), ("inf", 5.0), ("-inf", 5.0)])
def test_timeouts_are_parsed_safely(monkeypatch, value, expected):
    monkeypatch.setenv("SMS_TEST_TIMEOUT", value)
    assert _float("SMS_TEST_TIMEOUT", 5.0) == expected


def test_half_configured_sms_fails_fast_without_echoing_the_secret():
    class NoKey(BaseConfig):
        SMS_ENABLED, UNISMS_API_SECRET_KEY, UNISMS_API_BASE_URL = True, None, "https://unismsapi.com/api"

    class Insecure(BaseConfig):
        SMS_ENABLED, UNISMS_API_SECRET_KEY, UNISMS_API_BASE_URL = True, "KEY-123", "http://unismsapi.com/api"

    class Off(BaseConfig):
        SMS_ENABLED, UNISMS_API_SECRET_KEY = False, None
    with pytest.raises(RuntimeError, match="UNISMS_API_SECRET_KEY"):
        NoKey._validate_sms()
    with pytest.raises(RuntimeError) as err:
        Insecure._validate_sms()
    assert "https" in str(err.value) and "KEY-123" not in str(err.value)
    Off._validate_sms()


# ----------------------------------------------------------------------------- migration
def _load(rev):
    path = next((ROOT / "migrations" / "versions").glob(f"{rev}_*.py"))
    spec = importlib.util.spec_from_file_location(f"mig_{rev}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    with Operations.context(MigrationContext.configure(conn)):
        fn()


@pytest.fixture()
def conn():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(sa.text("CREATE TABLE orders (id INTEGER PRIMARY KEY, reference VARCHAR(24) NOT NULL, created_at DATETIME NOT NULL)"))
        c.execute(sa.text("INSERT INTO orders VALUES (1, 'LX-OLD-1', '2026-10-01 08:00:00'), (2, 'LX-OLD-2', '2026-10-02 08:00:00')"))
        yield c


def _cols(conn, table):
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def test_the_migration_chains_from_the_current_head_without_a_second_head():
    import re
    graph = {}
    for path in (ROOT / "migrations" / "versions").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        rev = re.search(r"^revision\s*=\s*['\"](\w+)['\"]", text, re.M).group(1)
        down = re.search(r"^down_revision\s*=\s*(?:None|['\"](\w+)['\"])", text, re.M).group(1)
        graph[rev] = down
    heads = [r for r in graph if r not in graph.values()]
    assert len(heads) == 1  # still exactly one head: no second branch
    assert graph["f2b7d4c9a1e3"] == "e7b3c9a4d1f6"  # the SMS migration still chains from its parent
    chain, rev = [], heads[0]
    while rev is not None:
        chain.append(rev)
        rev = graph[rev]
    assert "f2b7d4c9a1e3" in chain  # and is still on the line of history leading to the head


def test_existing_orders_migrate_with_consent_false(conn):
    _run(conn, _load("f2b7d4c9a1e3").upgrade)
    rows = conn.execute(sa.text("SELECT reference, sms_consent, sms_consent_at FROM orders ORDER BY id")).all()
    assert [(r[0], bool(r[1]), r[2]) for r in rows] == [("LX-OLD-1", False, None), ("LX-OLD-2", False, None)]
    assert {"id", "order_id", "provider", "status", "provider_message_id", "recipient", "attempt_count", "last_error",
            "created_at", "updated_at", "last_attempt_at", "accepted_at", "provider_sent_at"} == _cols(conn, "sms_notifications")


def test_one_notification_per_order_and_only_valid_statuses(conn):
    _run(conn, _load("f2b7d4c9a1e3").upgrade)
    insert = ("INSERT INTO sms_notifications (order_id, provider, status, attempt_count, created_at, updated_at) "
              "VALUES (:o, 'unisms', :s, 0, '2026-11-01', '2026-11-01')")
    conn.execute(sa.text(insert), {"o": 1, "s": "pending"})
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(sa.text(insert), {"o": 1, "s": "failed"})                      # second row for the same order
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(sa.text(insert), {"o": 2, "s": "delivered"})                   # not a defined status
    conn.execute(sa.text(insert), {"o": 2, "s": "skipped_no_consent"})


def test_downgrade_restores_the_orders_table_and_is_repeatable(conn):
    mod = _load("f2b7d4c9a1e3")
    before = _cols(conn, "orders")
    _run(conn, mod.upgrade)
    _run(conn, mod.downgrade)
    assert _cols(conn, "orders") == before and "sms_notifications" not in sa.inspect(conn).get_table_names()
    assert conn.execute(sa.text("SELECT COUNT(*) FROM orders")).scalar() == 2
    _run(conn, mod.upgrade)
    assert "sms_consent" in _cols(conn, "orders")
