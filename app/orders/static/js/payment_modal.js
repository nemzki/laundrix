/* Shared original payment form: server-authoritative validation and one transaction. */
(function () {
  "use strict";
  window.LaundrixPayments = { mount: function (modal, options) {
    if (!modal || modal.dataset.paymentMounted) return;
    if (modal.paymentDispose) modal.paymentDispose();
    var lifecycle = new AbortController();
    modal.paymentDispose = function () { lifecycle.abort(); delete modal.dataset.paymentMounted; };
    modal.dataset.paymentMounted = "true";
    var paymentForm = modal.querySelector("[data-payment-form]");
    if (!paymentForm) return;
    function field(id) { return modal.querySelector("#" + id); }
    var primary = field("pm-1");
    var secondary = field("pm-2");
    var methodButtons = paymentForm.querySelector("[data-method-buttons]");
    Array.from(primary.options).forEach(function (option) {
      var button = document.createElement("button");
      button.type = "button"; button.className = "btn btn-outline"; button.textContent = option.textContent;
      button.dataset.method = option.value;
      if (option.value === "cash" || option.value === "gcash") {
        var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("width", "16"); svg.setAttribute("height", "16");
        svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "1.75"); svg.setAttribute("aria-hidden", "true");
        var shape = document.createElementNS(svg.namespaceURI, "path");
        shape.setAttribute("d", option.value === "cash" ? "M3 6h18v12H3z M7 10h.01 M17 14h.01 M14 12a2 2 0 1 1-4 0 2 2 0 0 1 4 0" : "M7 2h10a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1 M12 18h.01");
        svg.appendChild(shape); button.prepend(svg);
      }
      button.addEventListener("click", function () { primary.value = option.value; primary.dispatchEvent(new Event("change", { bubbles: true })); });
      methodButtons.appendChild(button);
    });
    primary.classList.add("visually-hidden");
    primary.tabIndex = -1;
    var configArea = paymentForm.querySelector("[data-payment-gcash]");
    var configStatus = paymentForm.querySelector("[data-payment-config-status]");
    var qr = paymentForm.querySelector("[data-payment-qr]");
    var qrLink = paymentForm.querySelector("[data-payment-qr-link]");
    var loaded = false, loading = false;
    async function loadConfiguration() {
      if (loaded || loading) return;
      loading = true;
      qr.hidden = true; qrLink.hidden = true;
      paymentForm.querySelector("[data-payment-account]").replaceChildren();
      paymentForm.querySelector("[data-payment-instructions]").textContent = "";
      configStatus.textContent = "Loading configured GCash details...";
      try {
        // Reuse the existing Staff-authorized HTML settings projection; no new API or settings store.
        var response = await fetch(paymentForm.dataset.settingsUrl, { credentials: "same-origin", cache: "no-store" });
        if (!response.ok || response.redirected) throw new Error("GCash settings are unavailable. Check Payment Settings before collecting a payment.");
        var doc = new DOMParser().parseFromString(await response.text(), "text/html");
        var source = doc.getElementById("gcash-box");
        if (!source) throw new Error("GCash is no longer available. Reload this order to refresh enabled methods.");
        var account = paymentForm.querySelector("[data-payment-account]");
        account.replaceChildren();
        source.querySelectorAll(".gcash-info dl dt, .gcash-info dl dd").forEach(function (item) {
          var node = document.createElement(item.tagName.toLowerCase()); node.textContent = item.textContent; account.appendChild(node);
        });
        paymentForm.querySelector("[data-payment-instructions]").textContent = source.querySelector(".gcash-instructions")?.textContent || "";
        var url = source.dataset.qrUrl;
        if (!url) configStatus.textContent = "GCash QR code is not configured. Please check Payment Settings.";
        else {
          var imageURL = new URL(url, location.origin);
          if (imageURL.origin !== location.origin) throw new Error("Configured payment QR is unavailable.");
          var imageResponse = await fetch(imageURL, { credentials: "same-origin", cache: "no-store" });
          if (!imageResponse.ok || !imageResponse.headers.get("Content-Type")?.includes("image/png")) throw new Error("Configured GCash QR is unavailable. Ask an Admin to check Payment Settings.");
          qr.addEventListener("load", function () { qr.hidden = false; qrLink.hidden = false; configStatus.textContent = "Use the configured GCash payment QR."; }, { once: true });
          qr.addEventListener("error", function () { qr.hidden = true; qrLink.hidden = true; configStatus.textContent = "GCash QR could not be displayed. Check Payment Settings."; }, { once: true });
          qr.src = imageURL.href; qrLink.href = imageURL.href;
        }
        if (!account.children.length) configStatus.textContent += " Account details have not been configured.";
        loaded = true;
      } catch (error) { configStatus.textContent = error.message; }
      finally { loading = false; }
    }
    function updatePayment() {
      Array.from(methodButtons.children).forEach(function (button) { button.setAttribute("aria-pressed", String(button.dataset.method === primary.value)); });
      var selections = [primary, secondary];
      selections.forEach(function (select, index) {
        var reference = field("pr-" + (index + 1));
        var option = select.selectedOptions[0];
        reference.required = select.value === "gcash" || Boolean(option && option.dataset.requiresReference === "1");
        reference.setCustomValidity(reference.required && !reference.value.trim() ? "Enter a reference number for this payment method." : "");
        var label = paymentForm.querySelector('label[for="' + reference.id + '"]');
        label.textContent = (select.value === "gcash" ? "GCash Reference No." : "Reference No.") + (reference.required ? " (Required)" : " (Optional)");
      });
      var duplicate = Boolean(secondary.value && secondary.value === primary.value);
      secondary.setCustomValidity(duplicate ? "Choose a different payment method for the second amount." : "");
      field("pa-2").required = Boolean(secondary.value);
      var gcashSelected = selections.some(function (select) { return select.value === "gcash"; });
      configArea.hidden = !gcashSelected;
      if (gcashSelected) loadConfiguration();
      var amounts = [field("pa-1"), field("pa-2")];
      var cents = amounts.reduce(function (sum, input) { return sum + (input.value && Number.isFinite(Number(input.value)) ? Math.round(Number(input.value) * 100) : 0); }, 0);
      var balance = Math.round(Number(options.balance) * 100);
      var fmt = function (amount) { return (amount / 100).toLocaleString("en-PH", { style: "currency", currency: "PHP" }); };
      paymentForm.querySelector("[data-payment-preview]").textContent = "Total to record: " + fmt(cents) + " | Remaining after payment: " + fmt(balance - cents);
      amounts[0].setCustomValidity(cents > balance ? "The combined payment exceeds the remaining balance." : "");
    }
    paymentForm.addEventListener("input", updatePayment);
    paymentForm.addEventListener("change", updatePayment);
    modal.addEventListener("show.bs.modal", function () { loaded = false; updatePayment(); }, { signal:lifecycle.signal });
    updatePayment();
    var sending = false;
    var submit = paymentForm.querySelector("button[type=submit]");
    var errors = paymentForm.querySelector("[data-payment-errors]");
    if (!primary.options.length) {
      submit.disabled = true; errors.hidden = false;
      errors.textContent = "No payment methods are enabled. Please check Payment Settings.";
    }
    modal.addEventListener("hide.bs.modal", function (event) { if (sending) event.preventDefault(); }, { signal:lifecycle.signal });
    paymentForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (sending || !paymentForm.reportValidity()) return;
      var data = new FormData(paymentForm);
      var methods = data.getAll("method"), amounts = data.getAll("amount"), refs = data.getAll("reference");
      var entries = methods.map(function (method, index) { return { method: method, amount: amounts[index], reference: refs[index], notes: data.get("notes") }; })
        .filter(function (entry) { return entry.method || entry.amount; });
      sending = true; submit.disabled = true; submit.textContent = "Recording...";
      errors.hidden = true;
      fetch(paymentForm.action, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": data.get("csrf_token") },
        body: JSON.stringify({ entries: entries, idempotency_key: data.get("idempotency_key") })
      }).then(async function (response) {
        var saved = await response.json();
        if (!response.ok || !saved.ok) {
          var messages = saved.errors ? Object.values(saved.errors).flat().join(" ") : "Payment was not confirmed. Reload and check the payment history before retrying.";
          throw new Error(messages);
        }
        var message = saved.duplicate ? "This payment was already recorded. No duplicate payment was added." : "Payment saved successfully. Remaining balance: " + saved.balance;
        sending = false;
        if (options.onSuccess) await options.onSuccess(saved, message);
        else {
          try { sessionStorage.setItem("laundrix-payment-notice:" + options.reference, message); } catch { /* Ledger remains authoritative. */ }
          window.location.reload();
        }
      }).catch(function (error) {
        errors.textContent = error instanceof SyntaxError ? "Payment could not be confirmed. Check payment history before retrying." : error.message;
        errors.hidden = false; if (options.notify) options.notify("Payment not confirmed", errors.textContent);
        sending = false; submit.disabled = false; submit.textContent = "Record Payment";
      });
    });
  } };
})();
