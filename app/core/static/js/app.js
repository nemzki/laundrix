/* Set up dialogs, confirmation prompts, and other behavior shared across pages. */
/* Shared behaviour (CSP-safe: external file, no inline handlers). */
(function () {
  "use strict";

  var dialogs = new WeakMap();
  /* Keep the interface in sync with the dialog. */
  function syncDialog(element) {
    element.classList.toggle("show", element.open);
    document.body.classList.toggle("modal-open", !!document.querySelector("dialog:is(.modal,.offcanvas)[open]"));
    document.querySelectorAll("[data-dialog-target]").forEach(function (trigger) {
      if (trigger.dataset.dialogTarget === "#" + element.id && trigger.hasAttribute("aria-expanded")) {
        trigger.setAttribute("aria-expanded", String(element.open));
      }
    });
  }
  window.laundrixDialog = function (element) {
    if (dialogs.has(element)) return dialogs.get(element);
    function emit(name, cancelable) {
      return element.dispatchEvent(new Event("dialog:" + name, { cancelable: cancelable }));
    }
    var dialog = {
      show: function () {
        if (element.open || !emit("show", true)) return;
        element.showModal();
        element.focus({ preventScroll: true });
        syncDialog(element);
        emit("shown");
      },
      hide: function () {
        if (!element.open || !emit("hide", true)) return;
        element.close();
        syncDialog(element);
        emit("hidden");
      },
      toggle: function () {
        if (element.open) dialog.hide();
        else dialog.show();
      },
    };
    dialogs.set(element, dialog);
    element.addEventListener("cancel", function (event) {
      event.preventDefault();
      dialog.hide();
    });
    var pressedBackdrop = false;
    function onBackdrop(event) {
      if (event.target !== element) return false;
      if (element.classList.contains("modal")) return true;
      var bounds = element.getBoundingClientRect();
      return event.clientX < bounds.left || event.clientX >= bounds.right ||
        event.clientY < bounds.top || event.clientY >= bounds.bottom;
    }
    element.addEventListener("pointerdown", function (event) { pressedBackdrop = onBackdrop(event); });
    element.addEventListener("click", function (event) {
      if (pressedBackdrop && onBackdrop(event)) dialog.hide();
      pressedBackdrop = false;
    });
    return dialog;
  };

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-dialog-target]");
    if (trigger) {
      var element = document.getElementById(trigger.dataset.dialogTarget.slice(1));
      if (element) window.laundrixDialog(element).show();
      return;
    }
    var dismiss = event.target.closest("[data-dialog-dismiss], #appNavDrawer a.lx-nav__link");
    if (dismiss) {
      var dialog = dismiss.closest("dialog");
      if (dialog) window.laundrixDialog(dialog).hide();
    }
  });

  // Confirmation dialog: <form data-confirm="Message" data-confirm-title="Title">
  var dlg = null;
  function ensureDialog() {
    if (dlg) return dlg;
    if (typeof HTMLDialogElement === "undefined") return null;
    dlg = document.createElement("dialog");
    dlg.className = "confirm";
    dlg.innerHTML = '<h2></h2><p class="muted"></p><div class="btn-row">' +
      '<button type="button" class="btn btn-outline" data-act="cancel">Cancel</button>' +
      '<button type="button" class="btn btn-primary" data-act="ok">Confirm</button></div>';
    document.body.appendChild(dlg);
    return dlg;
  }
  /* Run this handler when the form is submitted. */
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.matches || !form.matches("form[data-confirm]") || form.dataset.confirmed) return;
    var d = ensureDialog();
    if (!d) { if (!window.confirm(form.dataset.confirm)) e.preventDefault(); return; }
    e.preventDefault();
    d.querySelector("h2").textContent = form.dataset.confirmTitle || "Please confirm";
    d.querySelector("p").textContent = form.dataset.confirm;
    d.onclick = function (ev) {
      var act = ev.target.getAttribute && ev.target.getAttribute("data-act");
      if (act === "ok") { form.dataset.confirmed = "1"; d.close(); form.submit(); }
      else if (act === "cancel") { d.close(); }
    };
    d.showModal();
  });

  // Print buttons: <button data-print>
  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-print]");
    if (t) window.print();
  });
})();
