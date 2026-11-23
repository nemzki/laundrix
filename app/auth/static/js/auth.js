/* Connect password visibility and submission feedback to the sign-in page. */
(function () {
  "use strict";

  function initPasswordToggles() {
    document.querySelectorAll("[data-password-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var input = document.getElementById(btn.getAttribute("data-password-toggle"));
        if (!input) return;
        var show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.textContent = show ? "Hide" : "Show";
        btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
        btn.setAttribute("aria-pressed", show ? "true" : "false");
      });
    });
  }

  function initSubmitLoading() {
    document.querySelectorAll("[data-auth-form]").forEach(function (form) {
      /* Show immediate feedback while the browser submits the sign-in form. */
      form.addEventListener("submit", function () {
        if (form.dataset.submitting === "1") {
          return;
        }
        form.dataset.submitting = "1";
        var submit = form.querySelector("[data-auth-submit]");
        var label = form.querySelector("[data-auth-submit-label]");
        if (submit) {
          submit.disabled = true;
          submit.classList.add("is-loading");
        }
        if (label) label.textContent = "Signing in…";
      });
    });
  }

  /* Show Google redirect feedback and reset it if the browser restores this page. */
  function initGoogle() {
    var buttons = document.querySelectorAll("[data-google-btn]");
    if (!buttons.length) return;
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        btn.classList.add("is-loading");
        var span = btn.querySelector("span");
        if (span) span.textContent = "Redirecting to Google…";
      });
    });
    window.addEventListener("pageshow", function (event) {
      if (!event.persisted) return;
      buttons.forEach(function (btn) {
        btn.classList.remove("is-loading");
        var span = btn.querySelector("span");
        if (span) span.textContent = "Continue with Google";
      });
      document.querySelectorAll("[data-auth-form]").forEach(function (form) {
        form.dataset.submitting = "";
        var submit = form.querySelector("[data-auth-submit]");
        var label = form.querySelector("[data-auth-submit-label]");
        if (submit) {
          submit.disabled = false;
          submit.classList.remove("is-loading");
        }
        if (label) label.textContent = "Sign In";
      });
    });
  }

  initPasswordToggles();
  initSubmitLoading();
  initGoogle();
})();
