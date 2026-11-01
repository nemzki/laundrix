/* Shared behaviour (CSP-safe: external file, no inline handlers). */
(function () {
  "use strict";
  var body = document.body;
  var toggle = document.getElementById("nav-toggle");
  var scrim = document.getElementById("scrim");

  function setNav(open) {
    body.classList.toggle("nav-open", open);
    if (toggle) toggle.setAttribute("aria-expanded", String(open));
    if (scrim) scrim.hidden = !open;
  }
  if (toggle) toggle.addEventListener("click", function () { setNav(!body.classList.contains("nav-open")); });
  if (scrim) scrim.addEventListener("click", function () { setNav(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") setNav(false); });

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
