/* Display only: reuse the existing backend-rendered stub QR, never generate one. */
(function () {
  "use strict";
  var root = document.querySelector("[data-order-tracking]");
  if (!root) return;
  var image = root.querySelector("[data-tracking-image]");
  var status = root.querySelector("[data-qr-status]");
  function unavailable() {
    image.hidden = true;
    status.textContent = "Tracking QR unavailable. Use Print Stub or Open tracking.";
  }
  image.addEventListener("error", unavailable);
  image.addEventListener("load", function () { image.hidden = false; status.textContent = "Scan to view this order's public tracking page."; });
  fetch(root.dataset.stubUrl, { credentials: "same-origin" }).then(function (response) {
    if (!response.ok) throw new Error("Stub unavailable");
    return response.text();
  }).then(function (html) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var expectedAlt = image.getAttribute("alt");
    var original = Array.from(doc.querySelectorAll("img")).find(function (candidate) { return candidate.getAttribute("alt") === expectedAlt; });
    var source = original && original.getAttribute("src");
    if (!source || !/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(source)) throw new Error("Original QR unavailable");
    image.src = source;
  }).catch(unavailable);

  var field = document.getElementById("order-tracking-link");
  var copyStatus = root.querySelector("[data-copy-status]");
  function fallbackCopy() {
    field.focus(); field.select();
    var copied = false;
    try { copied = document.execCommand("copy"); } catch { /* Manual copy remains available. */ }
    copyStatus.textContent = copied ? "Tracking link copied." : "Select and copy the tracking link above.";
  }
  root.querySelector("[data-copy-tracking]").addEventListener("click", function () {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(field.value).then(function () { copyStatus.textContent = "Tracking link copied."; }).catch(fallbackCopy);
    } else fallbackCopy();
  });

  var details = document.querySelector(".order-detail");
  var toast = document.querySelector("[data-detail-toast]");
  function notify(title, message, success) {
    toast.querySelector("[data-toast-title]").textContent = title;
    toast.querySelector("[data-toast-message]").textContent = message;
    toast.classList.toggle("is-success", Boolean(success));
    toast.hidden = false;
  }
  toast.querySelector("[data-toast-close]").addEventListener("click", function () { toast.hidden = true; });
  var noticeKey = "laundrix-payment-notice:" + details.dataset.ref;
  try {
    var savedNotice = sessionStorage.getItem(noticeKey);
    sessionStorage.removeItem(noticeKey);
    if (savedNotice) notify("Payment recorded", savedNotice, true);
  } catch { /* Payment saving does not depend on browser storage. */ }

  function releaseTarget(value) { return value === "picked_up" || value === "completed"; }
  function unpaid(saved) {
    if (Number(saved.dataset.balance) <= 0) return false;
    notify("Settle the remaining balance first", saved.dataset.balanceLabel + " is still unpaid. Record the payment before releasing or completing this order.");
    return true;
  }
  // This is a UI safeguard only. Server enforcement requires a separately approved backend change.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-status-update]");
    if (button && releaseTarget(button.dataset.status) && unpaid(details)) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  var statusForm = document.getElementById("statusUpdateForm");
  var checked = false;
  var checking = false;
  statusForm.addEventListener("submit", function (event) {
    if (!releaseTarget(document.getElementById("statusUpdateValue").value)) return;
    if (checked) { checked = false; return; }
    event.preventDefault(); event.stopImmediatePropagation();
    if (checking) return;
    checking = true;
    fetch(details.dataset.detailUrl, { credentials: "same-origin", cache: "no-store" }).then(function (response) {
      if (!response.ok || response.redirected) throw new Error("Cannot check balance");
      return response.text();
    }).then(function (html) {
      var saved = new DOMParser().parseFromString(html, "text/html").querySelector(".order-detail");
      if (!saved || !Number.isFinite(Number(saved.dataset.balance))) throw new Error("Cannot check balance");
      if (!unpaid(saved)) { checked = true; statusForm.requestSubmit(); }
    }).catch(function () { notify("Could not verify the balance", "Reload this order and try again. No status change was submitted."); })
      .finally(function () { checking = false; });
  }, true);

  window.LaundrixPayments.mount(document.getElementById("recordPaymentModal"), {
    balance: details.dataset.balance, reference: details.dataset.ref, notify: notify
  });
})();
