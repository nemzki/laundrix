/* Manage Orders list: summary modal + confirm-received modal. External JS (CSP). */
(function () {
  "use strict";

  function closestSource(el) {
    return el.closest("[data-ref][data-detail-url]") || el.closest(".orders-row, .orders-card");
  }

  function setText(root, selector, value) {
    var node = root.querySelector(selector);
    if (node) node.textContent = value || "—";
  }

  function setStatus(el, label, tone) {
    if (!el) return;
    el.textContent = label || "—";
    el.className = "status" + (tone ? " status-" + tone : "");
  }

  function initSummaryModal() {
    var modalEl = document.getElementById("orderSummaryModal");
    if (!modalEl || typeof bootstrap === "undefined") return;
    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);

    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-order-summary]");
      if (!btn) return;
      var source = closestSource(btn);
      if (!source) return;

      setText(modalEl, '[data-field="ref"]', source.dataset.ref);
      setText(modalEl, '[data-field="customer"]', source.dataset.customer);
      setText(modalEl, '[data-field="contact"]', source.dataset.contact);
      setText(modalEl, '[data-field="created"]', source.dataset.created);
      setText(modalEl, '[data-field="total"]', source.dataset.total);
      setText(modalEl, '[data-field="paid"]', source.dataset.paid);
      setText(modalEl, '[data-field="balance"]', source.dataset.balance);

      setStatus(
        modalEl.querySelector('[data-field="laundry"]'),
        source.dataset.laundry,
        source.dataset.laundryTone
      );
      setStatus(
        modalEl.querySelector('[data-field="payment"]'),
        source.dataset.payment,
        source.dataset.paymentTone
      );

      var awaiting = modalEl.querySelector('[data-field="awaiting"]');
      if (awaiting) awaiting.hidden = source.dataset.awaiting !== "1";

      var detail = modalEl.querySelector('[data-field="detail"]');
      if (detail) detail.setAttribute("href", source.dataset.detailUrl || "#");

      modal.show();
    });
  }

  function initConfirmModal() {
    var modalEl = document.getElementById("confirmReceivedModal");
    var form = document.getElementById("confirmReceivedForm");
    if (!modalEl || !form || typeof bootstrap === "undefined") return;

    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    var refEl = modalEl.querySelector("[data-confirm-ref]");
    var submitBtn = form.querySelector("[data-confirm-submit]");
    var label = submitBtn && submitBtn.querySelector("[data-label]");
    var busy = submitBtn && submitBtn.querySelector("[data-busy]");
    var submitting = false;

    function setBusy(on) {
      submitting = on;
      if (!submitBtn) return;
      submitBtn.disabled = on;
      if (label) label.hidden = on;
      if (busy) busy.hidden = !on;
    }

    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-confirm-received]");
      if (!btn) return;
      var action = btn.getAttribute("data-action");
      var ref = btn.getAttribute("data-ref");
      if (!action || !ref) return;
      form.setAttribute("action", action);
      if (refEl) refEl.textContent = ref;
      setBusy(false);
      modal.show();
    });

    form.addEventListener("submit", function (e) {
      if (submitting) {
        e.preventDefault();
        return;
      }
      if (!form.getAttribute("action") || form.getAttribute("action") === "#") {
        e.preventDefault();
        return;
      }
      setBusy(true);
    });

    modalEl.addEventListener("hidden.bs.modal", function () {
      if (!submitting) {
        form.setAttribute("action", "#");
        if (refEl) refEl.textContent = "—";
        setBusy(false);
      }
    });
  }

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  ready(function () {
    initSummaryModal();
    initConfirmModal();
  });
})();
