/* Toast handoff is UI state only; the page and all totals come from the saved order. */
(function () {
  "use strict";
  var toast = document.getElementById("order-created-toast");
  if (!toast) return;
  try {
    var pending = JSON.parse(sessionStorage.getItem("laundrix.order-created") || "null");
    if (pending && pending.path === window.location.pathname) {
      sessionStorage.removeItem("laundrix.order-created");
      if (Date.now() - pending.at >= 0 && Date.now() - pending.at < 300000) toast.hidden = false;
    }
  } catch { /* The saved-order screen remains usable with storage disabled. */ }
  var timeout = window.setTimeout(function () { toast.hidden = true; }, 6000);
  document.querySelector("[data-dismiss-created-toast]").addEventListener("click", function () { toast.hidden = true; window.clearTimeout(timeout); });
  window.addEventListener("pagehide", function () { toast.hidden = true; });
})();
