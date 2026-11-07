(function () {
  "use strict";

  function initWorkflow() {
    var root = document.querySelector("[data-workflow]");
    if (!root) return;
    var steps = root.querySelectorAll(".lp-workflow__step");
    var titleEl = root.querySelector("[data-wf-title]");
    var blurbEl = root.querySelector("[data-wf-blurb]");
    var panel = root.querySelector("#wf-panel");
    if (!steps.length || !titleEl || !blurbEl) return;

    function activate(btn) {
      steps.forEach(function (step) {
        var on = step === btn;
        step.classList.toggle("is-active", on);
        step.setAttribute("aria-selected", on ? "true" : "false");
        step.tabIndex = on ? 0 : -1;
      });
      titleEl.textContent = btn.getAttribute("data-title") || "";
      blurbEl.textContent = btn.getAttribute("data-blurb") || "";
      if (panel) panel.setAttribute("aria-labelledby", btn.id);
    }

    steps.forEach(function (step, index) {
      step.tabIndex = index === 0 ? 0 : -1;
      step.addEventListener("click", function () {
        activate(step);
      });
      step.addEventListener("keydown", function (event) {
        var key = event.key;
        var current = Array.prototype.indexOf.call(steps, step);
        var next = current;
        if (key === "ArrowRight" || key === "ArrowDown") next = (current + 1) % steps.length;
        else if (key === "ArrowLeft" || key === "ArrowUp") next = (current - 1 + steps.length) % steps.length;
        else if (key === "Home") next = 0;
        else if (key === "End") next = steps.length - 1;
        else return;
        event.preventDefault();
        steps[next].focus();
        activate(steps[next]);
      });
    });
  }

  function initRoles() {
    var buttons = document.querySelectorAll("[data-role]");
    var panels = document.querySelectorAll("[data-role-panel]");
    if (!buttons.length || !panels.length) return;

    function show(role) {
      buttons.forEach(function (btn) {
        var on = btn.getAttribute("data-role") === role;
        btn.classList.toggle("is-active", on);
        btn.setAttribute("aria-selected", on ? "true" : "false");
      });
      panels.forEach(function (panel) {
        var on = panel.getAttribute("data-role-panel") === role;
        panel.classList.toggle("is-active", on);
        if (on) panel.removeAttribute("hidden");
        else panel.setAttribute("hidden", "");
      });
    }

    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        show(btn.getAttribute("data-role"));
      });
      btn.addEventListener("keydown", function (event) {
        if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
        event.preventDefault();
        var list = Array.prototype.slice.call(buttons);
        var i = list.indexOf(btn);
        var next = event.key === "ArrowRight" ? (i + 1) % list.length : (i - 1 + list.length) % list.length;
        list[next].focus();
        show(list[next].getAttribute("data-role"));
      });
    });
  }

  initWorkflow();
  initRoles();
})();
