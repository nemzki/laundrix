"""SMS notification rules for the "ready for pickup" message.

Safety design (nothing here retries by itself):

* ONE notification row per order (unique constraint). Re-entering Ready for Pickup finds the row and does
  nothing, so a customer is texted at most once for the ready transition.
* The order-status change and the notification row are committed together. The provider is contacted only
  AFTER that commit, never inside a transaction or while a row lock is held. A provider outage can never
  roll back or block a status change.
* Before any HTTP call the row is moved to `unknown` ("attempt in flight") and committed, then updated
  from the provider's answer. So a crash, timeout or dropped connection leaves an honest `unknown`, a
  second concurrent submit is refused, and nothing is ever re-sent automatically.
* Only a definite failure (`failed`) or a never-submitted `pending` row may be sent again, and only by a
  signed-in staff/admin pressing a CSRF-protected button.
* A provider status of `sent` is shown as "Sent by provider": it is not proof the handset received it.
"""
import re
from dataclasses import dataclass

from flask import current_app

from app.extensions import db
from app.models import Order, SMSNotification, SMSStatus
from app.models.staff_credential import utcnow
from app.sms import provider as prov
from app.sms.phone import mask_phone, normalize_ph_mobile

TEMPLATE = "ready_for_pickup"
MESSAGE = ("Wash Up! Laundry Shop: Hi {customer_name}, your laundry order {order_reference} is ready for "
           "pickup. Please present your order stub when claiming. Thank you.")
SUBMITTABLE = (SMSStatus.PENDING, SMSStatus.FAILED)
REFRESHABLE = (SMSStatus.QUEUED, SMSStatus.RETRYING, SMSStatus.UNKNOWN)
IN_FLIGHT_NOTE = "Submission started; the outcome has not been confirmed."
FROM_PROVIDER = {
    "pending": SMSStatus.QUEUED, "retrying": SMSStatus.RETRYING,
    "sent": SMSStatus.SENT, "failed": SMSStatus.FAILED,
}
_PLACEHOLDER = re.compile(r"^(paste|your|changeme|xxx)", re.I)


@dataclass
class Outcome:
    ok: bool
    message: str
    status: str = None


# ----------------------------------------------------------------------------- configuration
def sms_enabled() -> bool:
    """SMS is on only when explicitly enabled AND fully configured (secret present, HTTPS endpoint)."""
    cfg = current_app.config
    key = cfg.get("UNISMS_API_SECRET_KEY") or ""
    return bool(
        cfg.get("SMS_ENABLED") and key and not _PLACEHOLDER.match(key)
        and str(cfg.get("UNISMS_API_BASE_URL", "")).startswith("https://")
    )


def get_client():
    """The UniSMS client. Tests may inject a stub via app.extensions['sms_client']."""
    injected = current_app.extensions.get("sms_client")
    if injected is not None:
        return injected
    cfg = current_app.config
    return prov.UniSMSClient(
        api_key=cfg["UNISMS_API_SECRET_KEY"], sender_id=cfg.get("UNISMS_SENDER_ID") or "Unisoft",
        base_url=cfg["UNISMS_API_BASE_URL"], connect_timeout=cfg["SMS_CONNECT_TIMEOUT"],
        read_timeout=cfg["SMS_READ_TIMEOUT"],
    )


# ----------------------------------------------------------------------------- message
def _clean_name(name) -> str:
    text = re.sub(r"[^\w .,'\-]", "", str(name or ""), flags=re.UNICODE)
    return " ".join(text.split())[:60] or "Customer"


def build_message(order) -> str:
    """Built from the order-time snapshots only: no prices, payments or identity details."""
    return MESSAGE.format(customer_name=_clean_name(order.customer_name), order_reference=order.reference)


# ----------------------------------------------------------------------------- creation (inside the status transaction)
def create_ready_notification(order):
    """Create the single notification row for `order` (no commit; the caller commits with the status
    change). Returns (notification, created). If one already exists nothing is created."""
    existing = db.session.scalar(db.select(SMSNotification).filter_by(order_id=order.id))
    if existing is not None:
        return existing, False
    recipient = normalize_ph_mobile(order.customer_contact)
    if not order.sms_consent:
        status, stored = SMSStatus.SKIPPED_NO_CONSENT, None            # no consent: keep no number
    elif recipient is None:
        status, stored = SMSStatus.SKIPPED_INVALID_RECIPIENT, None
    else:
        status, stored = SMSStatus.PENDING, recipient
    notification = SMSNotification(order_id=order.id, status=status, recipient=stored)
    db.session.add(notification)
    return notification, True


# ----------------------------------------------------------------------------- eligibility
def ineligible_reason(notification, order):
    """Why this notification may not be (re)submitted now, or None if it may. Re-checked on every attempt."""
    s = notification.status
    if s == SMSStatus.SENT:
        return "This message was already reported as sent by the provider."
    if s == SMSStatus.UNKNOWN:
        return ("The outcome of the previous attempt is unknown. Check the UniSMS dashboard before taking any "
                "action. It is never retried automatically.")
    if s in (SMSStatus.QUEUED, SMSStatus.RETRYING):
        return "The provider has already accepted this message."
    if s in (SMSStatus.SKIPPED_NO_CONSENT, SMSStatus.SKIPPED_INVALID_RECIPIENT):
        return "This notification was skipped (no consent or invalid number) and cannot be sent."
    if s not in SUBMITTABLE:
        return "This notification cannot be sent."
    if s == SMSStatus.PENDING and (notification.attempt_count or notification.provider_message_id):
        return "This notification was already submitted."
    if notification.provider_sent_at is not None:
        return "This message was already reported as sent by the provider."
    if not order.sms_consent:
        return "The customer did not consent to an SMS for this order."
    if normalize_ph_mobile(order.customer_contact) is None:
        return "The contact number saved on this order is not a valid Philippine mobile number."
    if not sms_enabled():
        return "SMS is disabled or not fully configured."
    return None


# ----------------------------------------------------------------------------- sending
def _lock(notification_id):
    return db.session.execute(
        db.select(SMSNotification).where(SMSNotification.id == notification_id)
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()


def submit_after_commit(order_id):
    """Called right after the Ready-for-Pickup commit. Never raises: the order change is already saved."""
    try:
        n = db.session.scalar(db.select(SMSNotification).filter_by(order_id=order_id))
        if n is None or n.status != SMSStatus.PENDING or not sms_enabled():
            return                                                       # stays pending for a manual send
        submit_notification(n.id)
    except Exception as exc:                                             # noqa: BLE001 - log type only, no details
        db.session.rollback()
        current_app.logger.error("SMS submission for order %s failed unexpectedly (%s).", order_id, type(exc).__name__)


def submit_notification(notification_id) -> Outcome:
    """Send (first time, or manual retry of a definite failure). One provider call at most."""
    n = _lock(notification_id)
    if n is None:
        db.session.rollback()
        return Outcome(False, "SMS notification not found.")
    order = db.session.get(Order, n.order_id)
    reason = ineligible_reason(n, order)
    if reason:
        status = n.status
        db.session.rollback()
        return Outcome(False, reason, status)

    recipient = normalize_ph_mobile(order.customer_contact)
    content = build_message(order)
    metadata = {"order_id": str(order.id), "template": TEMPLATE}
    nid = n.id

    # Claim the attempt BEFORE the network call: a crash or timeout leaves an honest "unknown", and a
    # concurrent submit sees "unknown" and is refused. Then release the row lock (commit).
    n.status, n.last_error = SMSStatus.UNKNOWN, IN_FLIGHT_NOTE
    n.attempt_count = (n.attempt_count or 0) + 1
    n.last_attempt_at, n.recipient = utcnow(), recipient
    db.session.commit()

    try:
        result = get_client().send(recipient, content, metadata)
    except Exception as exc:                                             # noqa: BLE001
        current_app.logger.error("SMS client error for notification %s (%s).", nid, type(exc).__name__)
        result = prov.SendResult(prov.AMBIGUOUS, error="Unexpected error while contacting the SMS provider. "
                                                        "The message may or may not have been queued.")
    return _apply_send_result(nid, result)


def _apply_send_result(nid, result) -> Outcome:
    n = _lock(nid)
    now = utcnow()
    if result.outcome == prov.ACCEPTED:
        n.provider_message_id, n.accepted_at = result.reference_id, now
        n.status, n.last_error = FROM_PROVIDER[result.provider_status], None
        if n.status == SMSStatus.SENT:
            n.provider_sent_at = now
        if n.status == SMSStatus.FAILED:
            n.last_error = result.error or "The SMS provider reported a failure."
        message = {
            SMSStatus.QUEUED: "SMS accepted by the provider and queued. Delivery is not confirmed yet.",
            SMSStatus.RETRYING: "SMS accepted; the provider is retrying it.",
            SMSStatus.SENT: "The provider reports the SMS as sent.",
            SMSStatus.FAILED: n.last_error,
        }[n.status]
        ok = n.status != SMSStatus.FAILED
    elif result.outcome == prov.REJECTED:
        n.status, n.last_error = SMSStatus.FAILED, result.error
        message, ok = result.error, False
    else:
        n.status, n.last_error = SMSStatus.UNKNOWN, result.error
        message = (result.error or "The outcome is unknown.") + " Check the UniSMS dashboard before sending again."
        ok = False
    status = n.status
    db.session.commit()
    return Outcome(ok, message, status)


# ----------------------------------------------------------------------------- status refresh
def refresh_status(notification_id) -> Outcome:
    """Ask UniSMS for the latest status of the stored reference. Never sends a message."""
    n = db.session.get(SMSNotification, notification_id)
    if n is None:
        return Outcome(False, "SMS notification not found.")
    if not n.provider_message_id:
        return Outcome(False, "No provider reference is stored for this message, so there is nothing to refresh.")
    if n.status not in REFRESHABLE:
        return Outcome(False, "This message's status is final and does not need refreshing.", n.status)
    if not sms_enabled():
        return Outcome(False, "SMS is disabled or not fully configured.", n.status)
    reference = n.provider_message_id
    db.session.rollback()                                                # no DB resources held during HTTP

    try:
        result = get_client().get_status(reference)
    except Exception as exc:                                             # noqa: BLE001
        current_app.logger.error("SMS status check error for notification %s (%s).", notification_id, type(exc).__name__)
        result = prov.StatusResult(False, error="The SMS provider could not be reached. Try again later.")
    if not result.ok:
        return Outcome(False, result.error or "The status could not be refreshed.")

    n = _lock(notification_id)
    if n is None or n.provider_message_id != reference or n.status not in REFRESHABLE:
        db.session.rollback()
        return Outcome(False, "The notification changed while refreshing. Reload the page.")
    n.status = FROM_PROVIDER[result.provider_status]
    n.last_error = None
    if n.status == SMSStatus.SENT and n.provider_sent_at is None:
        n.provider_sent_at = utcnow()
    if n.status == SMSStatus.FAILED:
        n.last_error = result.fail_reason or "The SMS provider reported a failure."
    status = n.status
    db.session.commit()
    return Outcome(True, f"Status updated: {SMSStatus.LABELS[status]}.", status)


# ----------------------------------------------------------------------------- presentation (no secrets, no full numbers)
def view(order) -> dict:
    n = order.sms_notification
    enabled = sms_enabled()
    data = {
        "enabled": enabled, "consent": bool(order.sms_consent), "consent_at": order.sms_consent_at,
        "notification": n, "can_retry": False, "can_refresh": False, "help": None,
    }
    if n is None:
        return data
    reason = ineligible_reason(n, order)
    data.update(
        label=SMSStatus.LABELS[n.status], tone=SMSStatus.TONES[n.status],
        masked=mask_phone(n.recipient) if n.recipient else "\u2014",
        can_retry=reason is None,
        retry_label="Send SMS" if n.status == SMSStatus.PENDING else "Retry SMS",
        can_refresh=bool(n.provider_message_id and n.status in REFRESHABLE and enabled),
    )
    if n.status == SMSStatus.UNKNOWN:
        data["help"] = ("The outcome of the last attempt is not known. Check the UniSMS dashboard"
                        + (" using the reference below" if n.provider_message_id else "")
                        + " before deciding. This message is never retried automatically.")
    elif n.status == SMSStatus.PENDING and not enabled:
        data["help"] = "SMS is disabled. Nothing has been sent; it can be sent once SMS is enabled."
    elif n.status == SMSStatus.SENT:
        data["help"] = "The provider reports this as sent. That does not confirm the customer's phone received it."
    return data
