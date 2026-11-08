/* Manage Orders: original authenticated HTML queries and Bootstrap modals. */
(function () {
  "use strict";
  var root = document.querySelector("[data-manage-orders]");
  if (!root || !window.fetch || !window.AbortController) return;
  var form = root.querySelector(".mo-filters");
  var search = form.querySelector("[name=q]");
  var statusInput = form.querySelector("[name=status]");
  var paymentInput = form.querySelector("[name=payment]");
  var controller, debounce, lastURL = new URL(location.href);
  var index = new URL(root.dataset.indexUrl, location.origin);
  function requestURL(page) {
    var url = new URL(index);
    if (search.value.trim()) url.searchParams.set("q", search.value.trim());
    if (statusInput.value) url.searchParams.set("status", statusInput.value);
    if (paymentInput.value) url.searchParams.set("payment", paymentInput.value);
    if (page && page > 1) url.searchParams.set("page", page);
    return url;
  }
  function syncControls(url) {
    search.value = url.searchParams.get("q") || "";
    statusInput.value = url.searchParams.get("status") || "";
    paymentInput.value = url.searchParams.get("payment") || "";
    root.querySelector("[data-clear-search]").hidden = !search.value;
    root.querySelectorAll("[data-clear-filters]").forEach(function (link) { link.hidden = !search.value && !statusInput.value && !paymentInput.value; });
  }
  async function load(url, push, clamp) {
    lastURL = new URL(url);
    clearTimeout(debounce);
    if (controller) controller.abort();
    var current = new AbortController(); controller = current;
    var timer = setTimeout(function () { current.abort(); }, 12000);
    root.dataset.state = "loading"; root.setAttribute("aria-busy", "true");
    try {
      var response = await fetch(url, { credentials: "same-origin", cache: "no-store", signal: current.signal });
      if (!response.ok || response.redirected) throw new Error("Orders unavailable");
      var doc = new DOMParser().parseFromString(await response.text(), "text/html");
      if (controller !== current) return;
      var results = doc.querySelector("[data-orders-results]"), tabs = doc.querySelector(".mo-tabs");
      if (!results || !tabs) throw new Error("Orders unavailable");
      var pages = Number(results.dataset.pages), page = Number(results.dataset.page);
      if (!clamp && page > Math.max(1, pages)) {
        if (pages > 1) url.searchParams.set("page", pages);
        else url.searchParams.delete("page");
        return load(url, push, true);
      }
      root.querySelector("[data-orders-results]").replaceWith(results);
      root.querySelector(".mo-tabs").replaceWith(tabs);
      syncControls(url);
      root.dataset.state = "ready";
      root.querySelector("[data-orders-announcement]").textContent = results.dataset.total + " matching orders loaded.";
      if (push) history.pushState(null, "", url);
      else if (clamp) history.replaceState(null, "", url);
    } catch {
      if (controller === current) root.dataset.state = "error";
    } finally {
      clearTimeout(timer);
      if (controller === current) root.removeAttribute("aria-busy");
    }
  }
  form.addEventListener("submit", function (event) { event.preventDefault(); load(requestURL(1), true); });
  paymentInput.addEventListener("change", function () { load(requestURL(1), true); });
  search.addEventListener("input", function () {
    root.querySelector("[data-clear-search]").hidden = !search.value;
    clearTimeout(debounce); debounce = setTimeout(function () { load(requestURL(1), true); }, 350);
  });
  root.addEventListener("click", function (event) {
    var clearSearch = event.target.closest("[data-clear-search]");
    if (clearSearch) { search.value = ""; search.focus(); load(requestURL(1), true); return; }
    if (event.target.closest("[data-orders-retry]")) { load(new URL(lastURL), lastURL.href !== location.href); return; }
    var link = event.target.closest(".mo-tab, .mo-pagination a, [data-clear-filters]");
    if (link && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button === 0) {
      event.preventDefault(); var url = new URL(link.href); syncControls(url); load(url, true);
    }
  });
  window.addEventListener("popstate", function () { var url = new URL(location.href); syncControls(url); load(url, false); });
  document.addEventListener("visibilitychange", function () { if (!document.hidden) load(new URL(location.href), false); });

  function setText(container, name, value) {
    container.querySelector('[data-field="' + name + '"]').textContent = value == null ? "Not tracked" : value;
  }
  function setStatus(container, name, label, tone) {
    var node = container.querySelector('[data-field="' + name + '"]');
    node.textContent = label; node.className = "status status-" + tone;
  }
  var summaryEl = document.getElementById("orderSummaryModal");
  var summary = bootstrap.Modal.getOrCreateInstance(summaryEl);
  var summaryURL, expectedRef, summaryController, summaryTrigger;
  async function loadSummary() {
    var restoreFocus = summaryEl.contains(document.activeElement);
    if (summaryController) summaryController.abort();
    var current = new AbortController(); summaryController = current;
    var timer = setTimeout(function () { current.abort(); }, 12000);
    summaryEl.querySelector("[data-summary-content]").hidden = true;
    summaryEl.querySelector("[data-summary-footer]").hidden = true;
    summaryEl.querySelector("[data-summary-error]").hidden = true;
    summaryEl.querySelector("[data-summary-loading]").hidden = false;
    try {
      var response = await fetch(summaryURL, { credentials: "same-origin", cache: "no-store", signal: current.signal });
      if (!response.ok || response.redirected) throw new Error("Summary unavailable");
      var doc = new DOMParser().parseFromString(await response.text(), "text/html");
      var projection = doc.getElementById("order-summary-data");
      if (!projection) throw new Error("Summary unavailable");
      var data = JSON.parse(projection.textContent);
      if (current !== summaryController) return;
      if (data.reference !== expectedRef) throw new Error("Wrong order");
      ["ref", "customer", "contact", "created", "total", "paid", "balance"].forEach(function (name) { setText(summaryEl, name, data[name === "ref" ? "reference" : name]); });
      setStatus(summaryEl, "laundry", data.laundry, data.laundryTone);
      setStatus(summaryEl, "payment", data.payment, data.paymentTone);
      summaryEl.querySelector('[data-field="laundry"]').dataset.laundryStatus = data.laundryValue;
      summaryEl.querySelector('[data-field="payment"]').dataset.paymentStatus = data.paymentValue;
      summaryEl.querySelector('[data-field="balance"]').classList.toggle("is-unpaid", data.owing);
      summaryEl.querySelector('[data-field="awaiting"]').hidden = !data.awaiting;
      summaryEl.querySelector('[data-field="detail"]').href = data.detailUrl;
      summaryEl.querySelector('[data-field="stub"]').href = data.stubUrl;
      var receipt = summaryEl.querySelector("[data-confirm-received]");
      receipt.dataset.action = data.receiptUrl; receipt.dataset.ref = data.reference;
      summaryEl.querySelector("[data-summary-receipt]").hidden = !data.awaiting;
      summaryEl.querySelector("[data-summary-content]").hidden = false;
      summaryEl.querySelector("[data-summary-footer]").hidden = false;
    } catch {
      if (current === summaryController) summaryEl.querySelector("[data-summary-error]").hidden = false;
    } finally {
      clearTimeout(timer);
      if (current === summaryController) {
        summaryEl.querySelector("[data-summary-loading]").hidden = true;
        if (restoreFocus && summaryEl.classList.contains("show")) summaryEl.focus({ preventScroll: true });
      }
    }
  }
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-order-summary]");
    if (!button || event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault(); summaryTrigger = button; summaryURL = button.href; expectedRef = button.closest("[data-ref]").dataset.ref;
    loadSummary(); summary.show();
  });
  summaryEl.querySelector("[data-summary-retry]").addEventListener("click", loadSummary);
  summaryEl.addEventListener("hidden.bs.modal", function () { if (summaryController) summaryController.abort(); summaryController = null; if (summaryTrigger && summaryTrigger.isConnected) summaryTrigger.focus({ preventScroll: true }); });
  function initConfirmModal() {
    var modalEl = document.getElementById("confirmReceivedModal");
    var form = document.getElementById("confirmReceivedForm");
    if (!modalEl || !form || typeof bootstrap === "undefined") return;

    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    var refEl = modalEl.querySelector("[data-confirm-ref]");
    var submitBtn = form.querySelector("[data-confirm-submit]");
    var label = submitBtn && submitBtn.querySelector("[data-label]");
    var busy = submitBtn && submitBtn.querySelector("[data-busy]");
    var submitting = false;

    function setBusy(on) {
      submitting = on;
      if (!submitBtn) return;
      submitBtn.disabled = on;
      if (label) label.hidden = on;
      if (busy) busy.hidden = !on;
    }

    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-confirm-received]");
      if (!btn) return;
      var action = btn.getAttribute("data-action");
      var ref = btn.getAttribute("data-ref");
      if (!action || !ref) return;
      form.setAttribute("action", action);
      if (refEl) refEl.textContent = ref;
      setBusy(false);
      var summary = document.getElementById("orderSummaryModal");
      if (summary.classList.contains("show")) {
        summary.addEventListener("hidden.bs.modal", function () { modal.show(); }, { once: true });
        bootstrap.Modal.getOrCreateInstance(summary).hide();
      } else modal.show();
    });

    form.addEventListener("submit", function (e) {
      if (submitting) {
        e.preventDefault();
        return;
      }
      if (!form.getAttribute("action") || form.getAttribute("action") === "#") {
        e.preventDefault();
        return;
      }
      setBusy(true);
    });

    modalEl.addEventListener("hidden.bs.modal", function () {
      if (!submitting) {
        form.setAttribute("action", "#");
        if (refEl) refEl.textContent = "—";
        setBusy(false);
      }
    });
  }


  initConfirmModal();
  window.laundrixOrdersReady = true;
  load(new URL(location.href), false);
})();
