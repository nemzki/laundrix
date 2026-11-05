/* Copy-link button for the one-time enrollment URL (external file: the CSP forbids inline scripts). */
(function () {
  "use strict";
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-copy-target]");
    if (!btn) return;
    var input = document.querySelector(btn.dataset.copyTarget);
    if (!input) return;
    var label = btn.querySelector("span");
    function done(ok) {
      if (!label) return;
      var original = label.dataset.original || label.textContent;
      label.dataset.original = original;
      label.textContent = ok ? "Copied" : "Press Ctrl+C to copy";
      setTimeout(function () { label.textContent = original; }, 2500);
    }
    input.focus();
    input.select();
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(input.value).then(function () { done(true); }, function () { done(legacy()); });
    } else {
      done(legacy());
    }
    function legacy() {
      try { return document.execCommand("copy"); } catch (err) { return false; }
    }
  });
})();
