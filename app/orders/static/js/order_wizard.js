/* New Order wizard. The browser only sends WHAT was chosen (ids, measurements, quantities, the
   amounts staff typed as received). The server prices the order and validates the payment against
   its own total; figures shown here are for convenience only. All DOM text is inserted with
   textContent (no HTML injection). */
(function () {
  "use strict";
  var root = document.getElementById("wizard");
  if (!root) return;

  var URLS = { quote: root.dataset.quoteUrl, confirm: root.dataset.confirmUrl, search: root.dataset.searchUrl };
  var CSRF = root.dataset.csrf;
  var TOKEN = root.dataset.token;      // one-time token: a double-clicked confirm saves one order
  var TOTAL_STEPS = 5;
  var step = 1;
  var custMode = "existing";
  var customer = null;            // {id, full_name, contact_number} when an existing one is picked
  var confirmDuplicate = false;
  var busy = false;
  var submitting = false;
  var dueRaw = null;              // server total as a plain number string, for display/prefill only
  var shown = false;
  var sideQuote = null;
  var localEstimates = {};
  var quoteRevision = 0;
  var quoteTimer;
  var lockedControls = [];

  var $ = function (sel, ctx) { return (ctx || root).querySelector(sel); };
  var $$ = function (sel, ctx) { return Array.prototype.slice.call((ctx || root).querySelectorAll(sel)); };

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function key(cb) { return cb.dataset.kind + ":" + cb.dataset.id; }
  function selectedBoxes() { return $$('input[data-kind]:checked'); }

  var STEP_TITLES = {
    1: "Customer", 2: "Services", 3: "Details", 4: "Payment", 5: "Review"
  };
  var NEXT_LABELS = {
    1: "Continue to services",
    2: "Continue to details",
    3: "Continue to payment",
    4: "Continue to review"
  };

  // ---------------------------------------------------------------- navigation
  function syncProgress(n) {
    $$(".wiz-step").forEach(function (p) {
      var i = Number(p.dataset.pill);
      p.classList.toggle("is-current", i === n);
      p.classList.toggle("is-done", i < n);
      if (i === n) p.setAttribute("aria-current", "step");
      else p.removeAttribute("aria-current");
    });
    var num = $("#wiz-step-num");
    var title = $("#wiz-step-title");
    var fill = $("#wiz-step-fill");
    if (num) num.textContent = String(n);
    if (title) title.textContent = STEP_TITLES[n] || "";
    if (fill) fill.style.width = ((n / TOTAL_STEPS) * 100).toFixed(3) + "%";
    var nextLabel = $("[data-next-label]");
    if (nextLabel) nextLabel.textContent = NEXT_LABELS[n] || "Next";
    $("#side-step").textContent = "Step " + n + " of " + TOTAL_STEPS;
  }

  function show(n) {
    quoteRevision += 1; clearTimeout(quoteTimer);
    step = n;
    $$(".wstep").forEach(function (s) { s.hidden = Number(s.dataset.step) !== n; });
    // Legacy class support if old markup remains
    $$(".step-pill").forEach(function (p) {
      var i = Number(p.dataset.pill);
      p.classList.toggle("is-current", i === n);
      p.classList.toggle("is-done", i < n);
    });
    syncProgress(n);
    $("#btn-back").hidden = n === 1;
    $("#btn-next").hidden = n === TOTAL_STEPS;
    $("#btn-confirm").hidden = n !== TOTAL_STEPS;
    clearErrors();
    if (n === 4) syncPayment();
    if (shown) {
      var heading = $('.wstep[data-step="' + n + '"] .wiz-heading');
      if (heading) { heading.setAttribute("tabindex", "-1"); heading.focus({ preventScroll: true }); }
      root.scrollIntoView({ block: "start", behavior: "auto" });
    }
    shown = true;
    if (n === 3) queueDetailsQuote();
  }

  function clearErrors() {
    var box = $("#step-alert");
    box.hidden = true; box.textContent = "";
    $$("[data-error-for]").forEach(function (e) { e.hidden = true; e.textContent = ""; });
    var d = $("#dupe-box"); if (d) d.hidden = true;
  }

  function showAlert(messages) {
    var box = $("#step-alert");
    box.textContent = "";
    if (messages.length === 1) { box.textContent = messages[0]; }
    else {
      var ul = el("ul");
      messages.forEach(function (m) { ul.appendChild(el("li", {}, m)); });
      box.appendChild(ul);
    }
    box.hidden = false;
  }

  // Place server errors next to their field; anything else goes in the top alert.
  // Returns the lowest step number that has an error (so we can send the user there).
  function applyErrors(errors) {
    clearErrors();
    var general = [], lowest = 99;
    Object.keys(errors || {}).forEach(function (k) {
      var target = $('[data-error-for="' + k + '"]');
      var s = k.indexOf("addon:") === 0 ? 2
            : (k.indexOf("customer") === 0 || k === "sms_consent") ? 1
            : k.indexOf("payment") === 0 ? 4
            : k === "submission_token" ? 5 : k === "items" || k === "extras" ? 2 : 3;
      if (target) { target.textContent = errors[k].join(" "); target.hidden = false; }
      else { general = general.concat(errors[k]); }
      if (k === "_general") s = step;
      lowest = Math.min(lowest, s);
    });
    if (general.length) showAlert(general);
    return lowest;
  }

  // ---------------------------------------------------------------- step 2: selection
  function refreshCompatibility() {
    var covered = {};
    $$('input[data-kind="package"]:checked').forEach(function (p) {
      (p.dataset.covers || "").split(",").forEach(function (c) { if (c) covered[c] = p.dataset.name; });
    });
    $$('input[data-kind="service"]').forEach(function (cb) {
      var unitMissing = !cb.dataset.unit;
      var inPkg = Object.prototype.hasOwnProperty.call(covered, cb.dataset.code);
      if (inPkg) cb.checked = false;
      cb.disabled = unitMissing || inPkg;
      var label = cb.closest(".choice");
      label.classList.toggle("is-disabled", cb.disabled);
      var avail = $("[data-avail]", label);
      if (inPkg) { avail.textContent = "Included in " + covered[cb.dataset.code]; avail.className = "avail no"; }
      else if (unitMissing) { avail.textContent = "Unavailable — pricing unit needs configuration."; avail.className = "avail no"; }
      else { avail.textContent = "Available"; avail.className = "avail ok"; }
    });
  }

  function renderSide() {
    $("#side-customer").textContent = custMode === "existing" && customer ? customer.full_name : custMode === "new" ? ($("#new-name").value.trim() || "Not selected") : "Not selected";
    $("#side-contact").textContent = custMode === "existing" && customer ? customer.contact_number : custMode === "new" ? $("#new-contact").value.trim() : "";
    var list = $("#side-list"); list.textContent = "";
    function line(name, detail, amount) {
      var row = el("li"), text = el("span", { "class": "side-item-name" }, name);
      if (detail) text.appendChild(el("small", {}, detail));
      row.appendChild(text);
      if (amount) row.appendChild(el("span", { "class": "side-item-amount" }, amount));
      list.appendChild(row);
    }
    if (sideQuote) {
      sideQuote.forEach(function (item) {
        line(item.name, item.quantity + " " + item.unit + (item.measurement ? " · " + item.measurement + " " + item.measurement_unit : ""), item.customer_supplied ? "Customer-supplied" : item.line_total);
      });
      $("#side-count").textContent = sideQuote.length + (sideQuote.length === 1 ? " item" : " items");
      return;
    }
    var boxes = selectedBoxes();
    $$('.extra').forEach(function (x) {
      var m = $('input[type=radio]:checked', x);
      if (m && m.value) boxes.push({ dataset: { name: x.dataset.name + (m.value === "customer_supplied" ? " (customer-supplied)" : "") } });
    });
    var count = $("#side-count");
    if (!boxes.length) {
      list.appendChild(el("li", { "class": "muted" }, "Nothing selected yet."));
      if (count) count.textContent = "Nothing selected";
      return;
    }
    boxes.forEach(function (b) {
      var estimate = b.dataset.kind === "service" && localEstimates[key(b)];
      if (estimate) { line(b.dataset.name, "Estimate · " + estimate.quantity + " " + b.dataset.unit, estimate.amount); return; }
      var card = b.closest ? b.closest(".choice") : null;
      var price = card && $(".choice-price", card);
      line(b.dataset.name, price ? "Catalog rate · quantities in Details" : "", price ? price.textContent.trim() : "");
    });
    if (count) count.textContent = boxes.length + (boxes.length === 1 ? " item" : " items");
  }

  // ---------------------------------------------------------------- step 3: details
  function buildDetails() {
    var host = $("#details-list");
    var kept = {};
    $$("[data-detail]", host).forEach(function (i) { kept[i.dataset.detail] = i.value; });
    host.textContent = "";
    selectedBoxes().forEach(function (cb) {
      var k = key(cb), isPkg = cb.dataset.kind === "package";
      var card = el("div", { "class": "detail-card", "data-card": k });
      var identity = el("div", { "class": "detail-identity" });
      identity.appendChild(el("h3", {}, cb.dataset.name));
      identity.appendChild(el("p", { "class": "muted small" }, $(".choice-price", cb.closest(".choice")).textContent.trim()));
      card.appendChild(identity);
      var grid = el("div", { "class": "form-grid" });

      function field(id, label, attrs, hint) {
        var wrap = el("div", { "class": "field" });
        var l = el("label", { "for": "d-" + id }, label);
        var i = el("input", Object.assign({ "class": "input", id: "d-" + id, "data-detail": id, autocomplete: "off" }, attrs));
        if (kept[id] !== undefined) i.value = kept[id];
        else if (attrs.type === "number" && attrs.value === undefined) {
          // Start at one in the original unit, respecting catalog package bounds.
          i.value = String(Math.min(i.max ? Number(i.max) : Infinity, Math.max(1, i.min ? Number(i.min) : 1)));
        }
        wrap.appendChild(l); wrap.appendChild(i);
        if (attrs.type === "number") {
          var control = el("div", { "class": "detail-quantity" });
          var minus = el("button", { type: "button", "aria-label": "Decrease " + cb.dataset.name + " " + label }, "−");
          var plus = el("button", { type: "button", "aria-label": "Increase " + cb.dataset.name + " " + label }, "+");
          function change(direction) {
            if (!i.value || !isFinite(Number(i.value))) i.value = i.min || "1";
            else if (attrs.step === "0.01") {
              // Kilogram buttons move by 1kg; step=0.01 still validates typed
              // decimal weights. Integer hundredths avoid addition artifacts.
              if (!i.checkValidity()) { i.reportValidity(); return; }
              var nextWeight = Math.round(Number(i.value) * 100) + direction * 100;
              if (i.min && nextWeight < Math.round(Number(i.min) * 100)) return;
              if (i.max && nextWeight > Math.round(Number(i.max) * 100)) return;
              i.value = String(nextWeight / 100);
            }
            else if (direction > 0) i.stepUp(); else i.stepDown();
            if (i.min && Number(i.value) < Number(i.min)) i.value = i.min;
            if (i.max && Number(i.value) > Number(i.max)) i.value = i.max;
            i.dispatchEvent(new Event("input", { bubbles: true }));
          }
          minus.addEventListener("click", function () { change(-1); });
          plus.addEventListener("click", function () { change(1); });
          control.appendChild(minus); control.appendChild(i); control.appendChild(plus); wrap.appendChild(control);
        }
        if (hint) wrap.appendChild(el("p", { "class": "hint" }, hint));
        return wrap;
      }

      if (isPkg) {
        var pieces = cb.dataset.measure === "pieces";
        grid.appendChild(field(k + ":measurement", pieces ? "Number of pieces" : "Weight (kg)",
          { type: "number", inputmode: "decimal", min: cb.dataset.min, max: cb.dataset.max, step: pieces ? "1" : "0.01", required: "required" },
          "Allowed range: " + cb.dataset.min + (cb.dataset.min === cb.dataset.max ? "" : "\u2013" + cb.dataset.max) + " " + cb.dataset.unitLabel));
        grid.appendChild(field(k + ":quantity", "Number of packages",
          { type: "number", min: "1", max: "20", step: "1", value: "1" }));
      } else {
        var u = cb.dataset.unit;
        var label = u === "kg" ? "Weight (kg)" : u === "load" ? "Number of loads" : "Number of pieces";
        grid.appendChild(field(k + ":quantity", label,
          { type: "number", inputmode: "decimal", min: u === "kg" ? "0.1" : "1", max: u === "kg" ? "200" : u === "load" ? "50" : "500", step: u === "kg" ? "0.01" : "1", required: "required" },
          "Billed " + cb.dataset.unitLabel));
      }
      card.appendChild(grid);
      card.appendChild(el("strong", { "class": "detail-line-total", "data-line-total": k, "aria-label": cb.dataset.name + " quoted line total" }, "—"));
      card.appendChild(el("p", { "class": "field-error", "data-error-for": k, hidden: "hidden" }));
      host.appendChild(card);
    });
  }

  function val(id) { var i = $('[data-detail="' + id + '"]'); return i ? i.value.trim() : ""; }

  // ---------------------------------------------------------------- step 4: payment (display helpers only)
  function arrangement() { var r = $('input[name="arrangement"]:checked'); return r ? r.value : null; }
  function pickedMethods() { return $$("input[data-pay-method]:checked").map(function (i) { return i.value; }); }
  function cents(v) { var n = parseFloat(v); return isFinite(n) ? Math.round(n * 100) : 0; }
  function peso(c) {
    return "\u20b1" + (c / 100).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function syncPayment() {
    var a = arrangement();
    var takesMoney = a === "full" || a === "partial";
    $("#pay-methods-block").hidden = !takesMoney;
    $("#pay-later-note").hidden = a !== "pay_later";
    var picked = pickedMethods();
    var gcash = $("#gcash-box");
    if (gcash) {
      gcash.hidden = !takesMoney || picked.indexOf("gcash") === -1;
      if (!gcash.hidden) loadGcashQR(gcash);
    }
    $$(".pay-entry").forEach(function (e) { e.hidden = !takesMoney || picked.indexOf(e.dataset.entry) === -1; });

    $$("[data-pay-amount]").forEach(function (inp) {
      var isOnlyMethod = a === "full" && picked.length === 1 && picked[0] === inp.dataset.payAmount;
      if (isOnlyMethod && dueRaw && (!inp.value || inp.dataset.auto === "1")) { inp.value = dueRaw; inp.dataset.auto = "1"; }
      else if (!isOnlyMethod && inp.dataset.auto === "1") { inp.value = ""; inp.dataset.auto = "0"; }
    });

    var summary = $("#pay-summary");
    if (a && dueRaw !== null) {
      var received = 0;
      if (takesMoney) picked.forEach(function (code) { received += cents($('[data-pay-amount="' + code + '"]').value); });
      $("#pay-received").textContent = peso(received);
      $("#pay-balance").textContent = peso(cents(dueRaw) - received);
      summary.hidden = false;
    } else { summary.hidden = true; }
  }

  function loadGcashQR(box) {
    if (!box.dataset.qrUrl || box.dataset.qrStarted) return;
    box.dataset.qrStarted = "true";
    var image = $("#gcash-qr-image"), link = $("#gcash-qr-link"), status = $("#gcash-qr-status");
    function unavailable() {
      link.hidden = true;
      status.textContent = "The configured QR image could not be loaded. Ask an Admin to check Payment Settings.";
    }
    image.addEventListener("error", unavailable);
    image.addEventListener("load", function () {
      link.hidden = false;
      status.textContent = "Select the QR to view the full-size image.";
    });
    // The existing route normalizes uploads to PNG. Its SVG response is only a
    // not-configured placeholder, never a real payment QR; do not display it.
    fetch(box.dataset.qrUrl, { credentials: "same-origin", cache: "no-cache" }).then(function (response) {
      if (!response.ok || (response.headers.get("Content-Type") || "").split(";")[0].trim() !== "image/png") { unavailable(); return; }
      image.src = box.dataset.qrUrl;
    }).catch(unavailable);
  }

  function buildPayment() {
    var a = arrangement(), entries = [];
    if (a === "full" || a === "partial") {
      pickedMethods().forEach(function (code) {
        var ref = $('[data-pay-ref="' + code + '"]');
        var notes = $('[data-pay-notes="' + code + '"]');
        entries.push({ method: code, amount: $('[data-pay-amount="' + code + '"]').value.trim(), reference: ref ? ref.value.trim() : "", notes: notes ? notes.value.trim() : "" });
      });
    }
    return { arrangement: a, entries: entries };
  }

  // ---------------------------------------------------------------- payload
  function buildPayload(withCustomer, withPayment) {
    var items = selectedBoxes().map(function (cb) {
      var k = key(cb);
      var base = { kind: cb.dataset.kind, id: cb.dataset.id, quantity: val(k + ":quantity") };
      if (cb.dataset.kind === "package") base.measurement = val(k + ":measurement");
      return base;
    });
    var extras = [];
    $$(".extra").forEach(function (x) {
      var m = $("input[type=radio]:checked", x);
      if (m && m.value) extras.push({ id: x.dataset.id, mode: m.value, quantity: $("[data-extra-qty]", x).value });
    });
    var payload = { items: items, extras: extras };
    if (withCustomer) {
      payload.require_customer = true;
      if (custMode === "existing" && customer) payload.customer = { id: customer.id };
      else if (custMode === "new") payload.customer = {
        new: { full_name: $("#new-name").value, contact_number: $("#new-contact").value },
        confirm_duplicate: confirmDuplicate,
      };
      else payload.customer = null;
      payload.sms_consent = $("#sms-consent").checked; // Explicit Boolean, specific to this order only.
      var notes = $("#order-notes"); if (notes && notes.value.trim()) payload.notes = notes.value.trim();
    }
    if (withPayment) payload.payment = buildPayment();
    return payload;
  }

  function post(url, payload) {
    return fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF, "Accept": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); });
  }

  function setBusy(b) {
    busy = b;
    $("[data-confirm-label]").textContent = submitting && b ? "Creating order…" : "Confirm Order";
    root.setAttribute("aria-busy", String(b));
    if (b) {
      lockedControls = $$("input, textarea, button").filter(function (control) { return !control.disabled; });
      lockedControls.forEach(function (control) { control.disabled = true; });
    } else {
      lockedControls.forEach(function (control) { control.disabled = false; });
      lockedControls = [];
    }
  }

  function guarded(promise) {
    setBusy(true);
    return promise.then(function (r) { setBusy(false); return r; }, function () {
      setBusy(false);
      showAlert(["Could not reach the server. Check your connection and try again."]);
      return null;
    });
  }

  // ---------------------------------------------------------------- step 1: customer
  var searchTimer = null;
  function runSearch() {
    var q = $("#cust-search").value.trim(), list = $("#cust-results");
    clearErrors();
    list.textContent = "";
    if (q.length < 2) return;
    fetch(URLS.search + "?q=" + encodeURIComponent(q), { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("Lookup failed"); return r.json(); })
      .then(function (j) {
        if ($("#cust-search").value.trim() !== q || custMode !== "existing") return;
        list.textContent = "";
        if (!j.results.length) { list.appendChild(el("li", { "class": "muted" }, "No matching customers. Use \u201cNew customer\u201d to register one.")); return; }
        j.results.forEach(function (c) { list.appendChild(customerButton(c, pick)); });
      }).catch(function () { if (step === 1 && custMode === "existing" && $("#cust-search").value.trim() === q) showAlert(["Customer search is unavailable. Please try again."]); });
  }
  function customerButton(c, handler) {
    var li = el("li"), b = el("button", { type: "button" });
    b.appendChild(el("strong", {}, c.full_name));
    b.appendChild(el("span", { "class": "sub" }, c.contact_number));
    b.addEventListener("click", function () { handler(c); });
    li.appendChild(b); return li;
  }
  function pick(c) {
    setMode("existing"); customer = c;
    var box = $("#cust-picked");
    box.textContent = "Selected: " + c.full_name + " (" + c.contact_number + ")";
    box.hidden = false; $("#cust-results").textContent = "";
    $("#dupe-box").hidden = true;
    renderSide();
  }
  function setMode(m) {
    clearErrors();
    custMode = m;
    $$("[data-cust-mode]").forEach(function (b) { b.classList.toggle("is-on", b.dataset.custMode === m); b.setAttribute("aria-pressed", String(b.dataset.custMode === m)); });
    $("#cust-existing").hidden = m !== "existing";
    $("#cust-new").hidden = m !== "new";
    if (m === "new") { customer = null; $("#cust-picked").hidden = true; confirmDuplicate = false; }
    renderSide();
  }
  function showDuplicates(dupes, message) {
    if (!dupes || !dupes.length) return;
    $("#dupe-text").textContent = message;
    var list = $("#dupe-list"); list.textContent = "";
    dupes.forEach(function (c) { list.appendChild(customerButton(c, pick)); });
    $("#dupe-box").hidden = false;
  }

  // ---------------------------------------------------------------- step 5: review
  function syncReviewConsent() {
    $("#rev-sms").textContent = $("#sms-consent").checked ? "Enabled" : "Not enabled";
  }
  function kv(dl, term, value) { dl.appendChild(el("dt", {}, term)); dl.appendChild(el("dd", {}, value)); }

  function renderReview(data) {
    var c = custMode === "existing" && customer ? customer.full_name + " \u00b7 " + customer.contact_number
      : $("#new-name").value.trim() + " \u00b7 " + $("#new-contact").value.trim() + " (new customer)";
    $("#rev-customer").textContent = c;
    syncReviewConsent();
    $("#rev-notes").textContent = $("#order-notes").value.trim() || "None";
    var details = $("#rev-details"); details.textContent = "";
    data.lines.forEach(function (line) {
      kv(details, line.name, line.quantity + " " + line.unit + (line.measurement ? " · " + line.measurement + " " + line.measurement_unit : ""));
    });
    var body = $("#rev-lines"); body.textContent = "";
    data.lines.forEach(function (l) {
      var tr = el("tr"), td = el("td");
      td.appendChild(el("strong", {}, l.name));
      var detail = l.description || "";
      if (l.measurement) detail += (detail ? " \u00b7 " : "") + l.measurement + " " + l.measurement_unit;
      if (detail) td.appendChild(el("span", { "class": "sub" }, detail));
      if (l.instructions) td.appendChild(el("span", { "class": "sub" }, "Note: " + l.instructions));
      tr.appendChild(td);
      tr.appendChild(el("td", { "class": "num" }, l.quantity + " " + l.unit));
      tr.appendChild(el("td", { "class": "num" }, l.customer_supplied ? "Customer-supplied" : l.unit_price));
      tr.appendChild(el("td", { "class": "num" }, l.line_total));
      body.appendChild(tr);
    });
    $("#rev-subtotal").textContent = data.subtotal;
    $("#rev-total").textContent = data.total;

    var p = data.payment, dl = $("#rev-payment");
    dl.textContent = "";
    if (p) {
      kv(dl, "Arrangement", p.arrangement_label);
      kv(dl, "Total Amount", data.total);
      if (p.entries.length) {
        var entered = buildPayment().entries;
        p.entries.forEach(function (e, i) {
          kv(dl, e.method, e.amount + (e.reference ? " (ref. " + e.reference + ")" : ""));
          if (entered[i] && entered[i].notes) kv(dl, e.method + " notes", entered[i].notes);
        });
      } else { kv(dl, "Payment Method", "None (nothing collected now)"); }
      kv(dl, "Amount Received", p.received);
      kv(dl, "Remaining Balance", p.balance);
      kv(dl, "Payment Status", p.status_label);
    }
  }

  // ---------------------------------------------------------------- actions
  function showQuoteErrors(result) {
    var errors = result.body.errors || { _general: ["The server could not validate this order."] };
    var lowest = applyErrors(errors);
    if (lowest >= 1 && lowest <= TOTAL_STEPS && lowest !== step) { show(lowest); applyErrors(errors); }
    if (result.body.duplicates && result.body.duplicates.length) {
      showDuplicates(result.body.duplicates, (errors.customer_duplicate || [""])[0]);
    }
  }
  function acceptQuote(data) {
    localEstimates = {};
    sideQuote = data.lines;
    dueRaw = data.total_raw;
    $("#pay-due").textContent = data.total;
    $("#side-total").textContent = data.total;
    $("#side-quote-status").textContent = "Prices checked against the current catalog.";
    data.lines.forEach(function (line) {
      var target = $('[data-line-total="' + line.key + '"]');
      if (target) { target.textContent = line.line_total; target.removeAttribute("data-estimated"); target.setAttribute("aria-label", line.name + " line total " + line.line_total); }
    });
    renderSide();
  }
  function invalidateQuote() {
    quoteRevision += 1; clearTimeout(quoteTimer);
    sideQuote = null;
    localEstimates = {};
    dueRaw = null;
    $("#side-total").textContent = "\u2014";
    $("#pay-due").textContent = "\u2014";
    $("#side-quote-status").textContent = "Enter valid quantities for a quote.";
    $$("[data-line-total]").forEach(function (line) { line.textContent = "—"; line.removeAttribute("data-estimated"); line.setAttribute("aria-label", "Line total unavailable"); });
    renderSide();
  }
  function queueDetailsQuote() {
    clearTimeout(quoteTimer);
    if (step !== 3 || busy) return;
    if (!sideQuote) renderLinearEstimates();
    var fields = $$('.wstep[data-step="3"] input, .wstep[data-step="3"] textarea');
    if (fields.some(function (field) { return !field.checkValidity(); })) return;
    var revision = quoteRevision;
    $("#side-quote-status").textContent = Object.keys(localEstimates).length ? "Local estimates; checking server quote…" : "Updating quote…";
    quoteTimer = setTimeout(function () {
      post(URLS.quote, buildPayload(true, false)).then(function (result) {
        if (revision !== quoteRevision || step !== 3 || busy) return;
        if (result.status === 200 && result.body.ok) { clearErrors(); acceptQuote(result.body); }
        else {
          invalidateQuote();
          $("#side-quote-status").textContent = "Check service details to get a quote.";
          if (result.body.errors) applyErrors(result.body.errors);
        }
      }).catch(function () {
        if (revision === quoteRevision && step === 3) {
          invalidateQuote();
          $("#side-quote-status").textContent = "Quote unavailable. Continue to retry validation.";
        }
      });
    }, 350);
  }
  function renderLinearEstimates() {
    // Display-only estimates for the original linear service rule. Packages and
    // extras remain server-priced; no estimated amount enters the payload.
    localEstimates = {};
    function hundredths(text) {
      if (!/^\d+(?:\.\d{1,2})?$/.test(text)) return null;
      var parts = text.split(".");
      return BigInt(parts[0]) * 100n + BigInt(((parts[1] || "") + "00").slice(0, 2));
    }
    selectedBoxes().forEach(function (box) {
      if (box.dataset.kind !== "service" || ["kg", "load", "piece"].indexOf(box.dataset.unit) === -1) return;
      var input = $('[data-detail="' + key(box) + ':quantity"]');
      if (!input || !input.value || !input.checkValidity()) return;
      var rate = hundredths(box.dataset.unitPrice || ""), quantity = hundredths(input.value);
      if (rate === null || quantity === null) return;
      var centsValue = Number((rate * quantity + 50n) / 100n);
      if (!Number.isSafeInteger(centsValue)) return;
      var amount = peso(centsValue);
      localEstimates[key(box)] = { amount: amount, quantity: input.value };
      var target = $('[data-line-total="' + key(box) + '"]');
      if (target) { target.textContent = amount; target.setAttribute("data-estimated", "true"); target.setAttribute("aria-label", box.dataset.name + " estimated line total " + amount); }
    });
    renderSide();
  }
  function next() {
    if (busy) return;
    quoteRevision += 1; clearTimeout(quoteTimer);
    if (step === 1) {
      // The existing quote route independently validates customers. Item errors are
      // deliberately deferred until Services/Details; no price is accepted here.
      guarded(post(URLS.quote, buildPayload(true, false))).then(function (r) {
        if (!r) return;
        if (r.status !== 200 || !r.body || !r.body.errors) { showAlert(["Customer validation is unavailable. Please try again."]); return; }
        var customerErrors = {};
        Object.keys(r.body.errors).forEach(function (k) { if (k.indexOf("customer") === 0) customerErrors[k] = r.body.errors[k]; });
        if (Object.keys(customerErrors).length) {
          applyErrors(customerErrors);
          showDuplicates(r.body.duplicates, (customerErrors.customer_duplicate || [""])[0]);
          return;
        }
        show(2);
      });
      return;
    }
    if (step === 2) {
      if (!selectedBoxes().length) { clearErrors(); showAlert(["Select at least one service or package."]); return; }
      buildDetails(); show(3); return;
    }
    if (step === 3) {
      guarded(post(URLS.quote, buildPayload(true, false))).then(function (r) {
        if (!r) return;
        if (!r.body.ok) { showQuoteErrors(r); return; }
        acceptQuote(r.body); show(4);
      });
      return;
    }
    if (step === 4) {
      if (!arrangement()) { clearErrors(); showAlert(["Choose Full Payment, Partial Payment or Pay Later."]); return; }
      if (arrangement() !== "pay_later" && !pickedMethods().length) {
        clearErrors(); showAlert(["Choose at least one payment method."]); return;
      }
      guarded(post(URLS.quote, buildPayload(true, true))).then(function (r) {
        if (!r) return;
        if (!r.body.ok) { showQuoteErrors(r); return; }
        acceptQuote(r.body); renderReview(r.body); show(5);
      });
    }
  }

  function back() { if (!busy && step > 1) show(step - 1); }

  function confirmOrder() {
    if (busy) return;
    if (!window.confirm("Create this order and generate the stub? Prices and payment will be saved as shown.")) return;
    var payload = buildPayload(true, true);
    payload.submission_token = TOKEN;
    submitting = true;
    guarded(post(URLS.confirm, payload)).then(function (r) {
      if (!r) { submitting = false; return; }
      if (r.status === 200 && r.body.ok === true && typeof r.body.redirect === "string") {
        try { sessionStorage.setItem("laundrix.order-created", JSON.stringify({ path: new URL(r.body.redirect, window.location.href).pathname, at: Date.now() })); } catch { /* Toast is optional; saving and navigation must still work. */ }
        setBusy(true); window.location.assign(r.body.redirect); return;
      }
      submitting = false;
      var errs = r.body.errors || { _general: ["Something went wrong."] };
      applyErrors(errs);
      // Submission failures remain on Review. Change/Edit actions retain data
      // and allow correction; always surface even hidden-field errors here.
      var messages = [];
      Object.keys(errs).forEach(function (key) { messages = messages.concat(errs[key]); });
      showAlert(messages);
    });
  }

  // ---------------------------------------------------------------- wiring
  $("#btn-next").addEventListener("click", next);
  $("#btn-back").addEventListener("click", back);
  $("#btn-confirm").addEventListener("click", confirmOrder);
  $("#sms-consent").addEventListener("change", syncReviewConsent);
  $$("[data-review-step]").forEach(function (button) {
    button.addEventListener("click", function () {
      if (!busy && step === 5) show(Number(button.dataset.reviewStep));
    });
  });

  $$('input[data-kind]').forEach(function (cb) {
    cb.addEventListener("change", function () {
      refreshCompatibility();
      var active = selectedBoxes().map(key);
      $$("#details-list [data-card]").forEach(function (card) {
        if (active.indexOf(card.dataset.card) === -1) card.remove();
      });
      invalidateQuote(); renderSide();
    });
  });
  $$(".extra").forEach(function (x) {
    var qty = $(".extra-qty", x);
    $$("input[type=radio]", x).forEach(function (r) {
      r.addEventListener("change", function () { qty.hidden = !$("input[type=radio]:checked", x).value; invalidateQuote(); renderSide(); });
    });
  });

  $("#cust-search").addEventListener("input", function () { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 250); });
  $$("[data-cust-mode]").forEach(function (b) { b.addEventListener("click", function () { setMode(b.dataset.custMode); }); });
  $("#new-name").addEventListener("input", function () { confirmDuplicate = false; renderSide(); });
  $("#new-contact").addEventListener("input", function () { confirmDuplicate = false; renderSide(); });
  $("#dupe-create").addEventListener("click", function () {
    setMode("new"); confirmDuplicate = true; $("#dupe-box").hidden = true; next();
  });

  $$('input[name="arrangement"]').forEach(function (r) { r.addEventListener("change", syncPayment); });
  $$("[data-pay-method]").forEach(function (c) { c.addEventListener("change", syncPayment); });
  $$("[data-pay-amount]").forEach(function (i) {
    i.addEventListener("input", function () { i.dataset.auto = "0"; syncPayment(); });
  });

  root.addEventListener("input", function (event) {
    if (event.target.id === "order-notes") $("#order-notes-count").textContent = event.target.value.length + "/500";
    if (event.target.matches("[data-detail], [data-extra-qty], #order-notes")) { invalidateQuote(); queueDetailsQuote(); }
  });
  refreshCompatibility();
  renderSide();
  show(1);
})();
