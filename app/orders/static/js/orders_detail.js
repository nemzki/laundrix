/* Order detail: status / receipt / SMS / reverse-payment modals. External JS (CSP). */
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  function bindBusySubmit(form, submitBtn) {
    if (!form || !submitBtn) return;
    var label = submitBtn.querySelector("[data-label]");
    var busy = submitBtn.querySelector("[data-busy]");
    var submitting = false;

    function setBusy(on) {
      submitting = on;
      submitBtn.disabled = on;
      if (label) label.hidden = on;
      if (busy) busy.hidden = !on;
    }

    form.addEventListener("submit", function (e) {
      if (submitting) {
        e.preventDefault();
        return;
      }
      var action = form.getAttribute("action");
      if (!action || action === "#") {
        e.preventDefault();
        return;
      }
      setBusy(true);
    });

    return { setBusy: setBusy };
  }

  function initStatusModal() {
    var modalEl = document.getElementById("statusUpdateModal");
    var form = document.getElementById("statusUpdateForm");
    if (!modalEl || !form || typeof bootstrap === "undefined") return;

    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    var valueInput = document.getElementById("statusUpdateValue");
    var noteInput = document.getElementById("statusUpdateNote");
    var noteOptional = modalEl.querySelector("[data-note-optional]");
    var noteRequired = modalEl.querySelector("[data-note-required]");
    var noteHint = modalEl.querySelector("[data-note-hint]");
    var newLabel = modalEl.querySelector("[data-status-new]");
    var message = modalEl.querySelector("[data-status-message]");
    var submitBtn = form.querySelector("[data-submit-btn]");
    var busy = bindBusySubmit(form, submitBtn);

    function configureNote(needsNote) {
      if (!noteInput) return;
      noteInput.required = needsNote;
      noteInput.placeholder = needsNote
        ? "Reason for moving this order back"
        : "Add a short note";
      if (noteOptional) noteOptional.hidden = needsNote;
      if (noteRequired) noteRequired.hidden = !needsNote;
      if (noteHint) {
        noteHint.textContent = needsNote
          ? "A note is required when moving an order back."
          : "Optional note for this status change.";
      }
    }

    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-status-update]");
      if (!btn) return;
      var status = btn.getAttribute("data-status");
      var label = btn.getAttribute("data-label") || status;
      var needsNote = btn.getAttribute("data-needs-note") === "1";
      if (!status) return;

      if (valueInput) valueInput.value = status;
      if (newLabel) newLabel.textContent = label;
      if (message) {
        message.textContent = needsNote
          ? "Move this order back to " + label + "? A note is required. Previously sent SMS messages and recorded payments will not be undone."
          : "Are you sure you want to update this order to " + label + "?";
      }
      if (noteInput) noteInput.value = "";
      configureNote(needsNote);
      if (busy) busy.setBusy(false);
      modal.show();
      if (needsNote && noteInput) {
        window.setTimeout(function () { noteInput.focus(); }, 200);
      }
    });

    modalEl.addEventListener("hidden.bs.modal", function () {
      if (valueInput) valueInput.value = "";
      if (noteInput) noteInput.value = "";
      configureNote(false);
      if (busy) busy.setBusy(false);
      if (newLabel) newLabel.textContent = "—";
      if (message) {
        message.textContent = "Are you sure you want to update this order?";
      }
    });
  }

  function initConfirmReceivedModal() {
    var modalEl = document.getElementById("confirmReceivedModal");
    var form = document.getElementById("confirmReceivedForm");
    if (!modalEl || !form || typeof bootstrap === "undefined") return;

    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    var submitBtn = form.querySelector("[data-submit-btn]");
    var busy = bindBusySubmit(form, submitBtn);

    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-confirm-received]");
      if (!btn) return;
      var action = btn.getAttribute("data-action");
      if (!action) return;
      form.setAttribute("action", action);
      if (busy) busy.setBusy(false);
      modal.show();
    });

    modalEl.addEventListener("hidden.bs.modal", function () {
      form.setAttribute("action", "#");
      if (busy) busy.setBusy(false);
    });
  }

  function initSmsRetryModal() {
    var modalEl = document.getElementById("smsRetryModal");
    var form = document.getElementById("smsRetryForm");
    if (!modalEl || !form || typeof bootstrap === "undefined") return;

    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    var title = document.getElementById("smsRetryModalLabel");
    var submitBtn = form.querySelector("[data-submit-btn]");
    var label = submitBtn && submitBtn.querySelector("[data-label]");
    var busy = bindBusySubmit(form, submitBtn);

    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-sms-retry]");
      if (!btn) return;
      var action = btn.getAttribute("data-action");
      var text = btn.getAttribute("data-title") || "Send SMS";
      if (!action) return;
      form.setAttribute("action", action);
      if (title) title.textContent = text;
      if (label) label.textContent = text;
      if (busy) busy.setBusy(false);
      modal.show();
    });

    modalEl.addEventListener("hidden.bs.modal", function () {
      form.setAttribute("action", "#");
      if (busy) busy.setBusy(false);
    });
  }

  function initReversePaymentModal() {
    var modalEl = document.getElementById("reversePaymentModal");
    var form = document.getElementById("reversePaymentForm");
    if (!modalEl || !form || typeof bootstrap === "undefined") return;

    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    var amountEl = modalEl.querySelector("[data-reverse-amount]");
    var methodEl = modalEl.querySelector("[data-reverse-method]");
    var reason = document.getElementById("reverseReason");
    var submitBtn = form.querySelector("[data-submit-btn]");
    var busy = bindBusySubmit(form, submitBtn);

    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-reverse-payment]");
      if (!btn) return;
      var action = btn.getAttribute("data-action");
      if (!action) return;
      form.setAttribute("action", action);
      if (amountEl) amountEl.textContent = btn.getAttribute("data-amount") || "—";
      if (methodEl) {
        var method = btn.getAttribute("data-method") || "";
        methodEl.textContent = method ? "(" + method + ")" : "";
      }
      if (reason) reason.value = "";
      if (busy) busy.setBusy(false);
      modal.show();
      if (reason) window.setTimeout(function () { reason.focus(); }, 200);
    });

    modalEl.addEventListener("hidden.bs.modal", function () {
      form.setAttribute("action", "#");
      if (reason) reason.value = "";
      if (busy) busy.setBusy(false);
    });
  }

  ready(function () {
    initStatusModal();
    initConfirmReceivedModal();
    initSmsRetryModal();
    initReversePaymentModal();
  });
})();
