/* Reveal the existing official artwork only after it loads; keep the text header as fallback. */
(function () {
  "use strict";
  document.querySelectorAll("[data-stub-logo]").forEach(function (logo) {
    function update() {
      logo.hidden = !(logo.complete && logo.naturalWidth > 0 && logo.naturalHeight > 0);
    }
    logo.addEventListener("load", update);
    logo.addEventListener("error", update);
    update();
  });
})();
