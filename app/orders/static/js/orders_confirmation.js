/* Laundry-received confirmation. Receipt preview uses Bootstrap's modal data API. */
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
    return window.LaundrixModals.bindForm(form, submitBtn);
  }

  function initConfirmReceivedModal() {
    var modalEl = document.getElementById("confirmReceivedModal");
    var form = document.getElementById("confirmReceivedForm");
    if (!modalEl || !form || typeof bootstrap === "undefined") return;

    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    var submitBtn = form.querySelector("[data-submit-btn]");
    var busy = bindBusySubmit(form, submitBtn);
    var defaultAction = form.getAttribute("action") || "#";

    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-confirm-received]");
      if (!btn) return;
      var action = btn.getAttribute("data-action") || defaultAction;
      if (!action || action === "#") return;
      form.setAttribute("action", action);
      if (busy) busy.setBusy(false);
      modal.show(btn);
    });

    modalEl.addEventListener("hidden.bs.modal", function () {
      if (busy) busy.setBusy(false);
    });
  }

  ready(function () {
    initConfirmReceivedModal();
  });
})();
