(function () {
  "use strict";

  function setRole(role) {
    var tabs = document.querySelectorAll("[data-auth-role]");
    var panels = document.querySelectorAll("[data-auth-panel]");
    tabs.forEach(function (tab) {
      var on = tab.getAttribute("data-auth-role") === role;
      tab.classList.toggle("is-active", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
    });
    panels.forEach(function (panel) {
      var on = panel.getAttribute("data-auth-panel") === role;
      panel.classList.toggle("is-active", on);
      if (on) panel.removeAttribute("hidden");
      else panel.setAttribute("hidden", "");
      panel.querySelectorAll("input, button[type='submit']").forEach(function (el) {
        if (el.hasAttribute("data-password-toggle")) return;
        if (el.classList.contains("lx-auth__toggle")) return;
        el.disabled = !on;
      });
      // Password toggles stay enabled only on the active panel
      panel.querySelectorAll("[data-password-toggle]").forEach(function (btn) {
        btn.disabled = !on;
      });
    });
  }

  function initRoles() {
    var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-auth-role]"));
    if (!tabs.length) return;

    tabs.forEach(function (tab, index) {
      tab.tabIndex = tab.classList.contains("is-active") ? 0 : -1;
      tab.addEventListener("click", function () {
        setRole(tab.getAttribute("data-auth-role"));
      });
      tab.addEventListener("keydown", function (event) {
        var key = event.key;
        var next = index;
        if (key === "ArrowRight" || key === "ArrowDown") next = (index + 1) % tabs.length;
        else if (key === "ArrowLeft" || key === "ArrowUp") next = (index - 1 + tabs.length) % tabs.length;
        else if (key === "Home") next = 0;
        else if (key === "End") next = tabs.length - 1;
        else return;
        event.preventDefault();
        tabs[next].focus();
        setRole(tabs[next].getAttribute("data-auth-role"));
      });
    });
  }

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

  function initGoogle() {
    var btn = document.getElementById("googleBtn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      btn.classList.add("is-loading");
      var span = btn.querySelector("span");
      if (span) span.textContent = "Redirecting to Google…";
    });
    window.addEventListener("pageshow", function (event) {
      if (!event.persisted) return;
      btn.classList.remove("is-loading");
      var span = btn.querySelector("span");
      if (span) span.textContent = "Continue with Google";
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

  initRoles();
  initPasswordToggles();
  initSubmitLoading();
  initGoogle();
})();
