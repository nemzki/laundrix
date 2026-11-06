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
  var TOTAL_STEPS = 6;
  var step = 1;
  var custMode = "existing";
  var customer = null;            // {id, full_name, contact_number} when an existing one is picked
  var confirmDuplicate = false;
  var busy = false;
  var dueRaw = null;              // server total as a plain number string, for display/prefill only

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

  // ---------------------------------------------------------------- navigation
  function show(n) {
    step = n;
    $$(".wstep").forEach(function (s) { s.hidden = Number(s.dataset.step) !== n; });
    $$(".step-pill").forEach(function (p) {
      var i = Number(p.dataset.pill);
      p.classList.toggle("is-current", i === n);
      p.classList.toggle("is-done", i < n);
    });
    $("#btn-back").hidden = n === 1;
    $("#btn-next").hidden = n === TOTAL_STEPS;
    $("#btn-confirm").hidden = n !== TOTAL_STEPS;
    clearErrors();
    if (n === 5) syncPayment();
    window.scrollTo({ top: 0, behavior: "smooth" });
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
      var s = k.indexOf("addon:") === 0 ? 3
            : (k.indexOf("customer") === 0 || k === "sms_consent") ? 4
            : k.indexOf("payment") === 0 ? 5
            : (k === "notes" || k === "submission_token") ? 6 : 2;
      if (target) { target.textContent = errors[k].join(" "); target.hidden = false; }
      else { general = general.concat(errors[k]); }
      if (k === "_general") s = 1;
      lowest = Math.min(lowest, s);
    });
    if (general.length) showAlert(general);
    return lowest;
  }

  // ---------------------------------------------------------------- step 1: selection
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
      else if (unitMissing) { avail.textContent = "Unavailable: unit not set by Admin"; avail.className = "avail no"; }
      else { avail.textContent = "Available"; avail.className = "avail ok"; }
    });
  }

  function renderSide() {
    var list = $("#side-list"); list.textContent = "";
    var boxes = selectedBoxes();
    $$('.extra').forEach(function (x) {
      var m = $('input[type=radio]:checked', x);
      if (m && m.value) boxes.push({ dataset: { name: x.dataset.name + (m.value === "customer_supplied" ? " (customer-supplied)" : "") } });
    });
    if (!boxes.length) { list.appendChild(el("li", { "class": "muted" }, "Nothing selected yet.")); return; }
    boxes.forEach(function (b) { list.appendChild(el("li", {}, b.dataset.name)); });
  }

  // ---------------------------------------------------------------- step 2: details
  function buildDetails() {
    var host = $("#details-list");
    var kept = {};
    $$("[data-detail]", host).forEach(function (i) { kept[i.dataset.detail] = i.value; });
    host.textContent = "";
    selectedBoxes().forEach(function (cb) {
      var k = key(cb), isPkg = cb.dataset.kind === "package";
      var card = el("div", { "class": "detail-card", "data-card": k });
      card.appendChild(el("h3", {}, cb.dataset.name));
      var grid = el("div", { "class": "form-grid" });

      function field(id, label, attrs, hint) {
        var wrap = el("div", { "class": "field" });
        var l = el("label", { "for": "d-" + id }, label);
        var i = el("input", Object.assign({ "class": "input", id: "d-" + id, "data-detail": id, autocomplete: "off" }, attrs));
        if (kept[id] !== undefined) i.value = kept[id];
        wrap.appendChild(l); wrap.appendChild(i);
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
          { type: "number", inputmode: "decimal", min: u === "kg" ? "0.1" : "1", step: u === "kg" ? "0.01" : "1", required: "required" },
          "Billed " + cb.dataset.unitLabel));
      }
      var instr = field(k + ":instructions", "Special instructions (optional)", { type: "text", maxlength: "255" });
      instr.classList.add("span-2");
      grid.appendChild(instr);
      card.appendChild(grid);
      card.appendChild(el("p", { "class": "field-error", "data-error-for": k, hidden: "hidden" }));
      host.appendChild(card);
    });
  }

  function val(id) { var i = $('[data-detail="' + id + '"]'); return i ? i.value.trim() : ""; }

  // ---------------------------------------------------------------- step 5: payment (display helpers only)
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
    $$(".pay-entry").forEach(function (e) { e.hidden = !takesMoney || picked.indexOf(e.dataset.entry) === -1; });
    var gc = $("#gcash-box"); if (gc) gc.hidden = !takesMoney || picked.indexOf("gcash") === -1;

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

  function buildPayment() {
    var a = arrangement(), entries = [];
    if (a === "full" || a === "partial") {
      pickedMethods().forEach(function (code) {
        var ref = $('[data-pay-ref="' + code + '"]');
        entries.push({ method: code, amount: $('[data-pay-amount="' + code + '"]').value.trim(), reference: ref ? ref.value.trim() : "" });
      });
    }
    return { arrangement: a, entries: entries };
  }

  // ---------------------------------------------------------------- payload
  function buildPayload(withCustomer, withPayment) {
    var items = selectedBoxes().map(function (cb) {
      var k = key(cb);
      var base = { kind: cb.dataset.kind, id: cb.dataset.id, quantity: val(k + ":quantity"), instructions: val(k + ":instructions") };
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
      payload.sms_consent = !!($("#sms-consent") && $("#sms-consent").checked);   // a real boolean, per order
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
    ["#btn-next", "#btn-confirm", "#btn-back"].forEach(function (s) { $(s).disabled = b; });
  }

  function guarded(promise) {
    setBusy(true);
    return promise.then(function (r) { setBusy(false); return r; }, function () {
      setBusy(false);
      showAlert(["Could not reach the server. Check your connection and try again."]);
      return null;
    });
  }

  // ---------------------------------------------------------------- step 4: customer
  var searchTimer = null;
  function runSearch() {
    var q = $("#cust-search").value.trim(), list = $("#cust-results");
    list.textContent = "";
    if (q.length < 2) return;
    fetch(URLS.search + "?q=" + encodeURIComponent(q), { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        list.textContent = "";
        if (!j.results.length) { list.appendChild(el("li", { "class": "muted" }, "No matching customers. Use \u201cNew customer\u201d to register one.")); return; }
        j.results.forEach(function (c) { list.appendChild(customerButton(c, pick)); });
      });
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
  }
  function setMode(m) {
    custMode = m;
    $$("[data-cust-mode]").forEach(function (b) { b.classList.toggle("is-on", b.dataset.custMode === m); });
    $("#cust-existing").hidden = m !== "existing";
    $("#cust-new").hidden = m !== "new";
    if (m === "new") { customer = null; $("#cust-picked").hidden = true; confirmDuplicate = false; }
  }
  function showDuplicates(dupes, message) {
    if (!dupes || !dupes.length) return;
    $("#dupe-text").textContent = message;
    var list = $("#dupe-list"); list.textContent = "";
    dupes.forEach(function (c) { list.appendChild(customerButton(c, pick)); });
    $("#dupe-box").hidden = false;
  }

  // ---------------------------------------------------------------- step 6: review
  function kv(dl, term, value) { dl.appendChild(el("dt", {}, term)); dl.appendChild(el("dd", {}, value)); }

  function renderReview(data) {
    var c = custMode === "existing" && customer ? customer.full_name + " \u00b7 " + customer.contact_number
      : $("#new-name").value.trim() + " \u00b7 " + $("#new-contact").value.trim() + " (new customer)";
    $("#rev-customer").textContent = c + " \u00b7 SMS when ready: " + ($("#sms-consent").checked ? "Yes" : "No");
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
      if (p.entries.length) {
        p.entries.forEach(function (e) { kv(dl, e.method, e.amount + (e.reference ? " (ref. " + e.reference + ")" : "")); });
      } else { kv(dl, "Payment method", "None (nothing collected now)"); }
      kv(dl, "Amount received", p.received);
      kv(dl, "Remaining balance", p.balance);
      kv(dl, "Payment status", p.status_label);
    }
  }

  // ---------------------------------------------------------------- actions
  function next() {
    if (busy) return;
    if (step === 1) {
      if (!selectedBoxes().length) { clearErrors(); showAlert(["Select at least one service or package."]); return; }
      buildDetails(); show(2); return;
    }
    if (step === 2 || step === 3) {
      guarded(post(URLS.quote, buildPayload(false, false))).then(function (r) {
        if (!r) return;
        if (!r.body.ok) {
          var lowest = applyErrors(r.body.errors);
          if (lowest < step) { show(lowest); applyErrors(r.body.errors); }
          return;
        }
        show(step + 1);
      });
      return;
    }
    if (step === 4) {
      guarded(post(URLS.quote, buildPayload(true, false))).then(function (r) {
        if (!r) return;
        if (!r.body.ok) {
          var lowest = applyErrors(r.body.errors);
          if (r.body.duplicates && r.body.duplicates.length) showDuplicates(r.body.duplicates, (r.body.errors.customer_duplicate || [""])[0]);
          if (lowest < 4) { show(lowest); applyErrors(r.body.errors); }
          return;
        }
        dueRaw = r.body.total_raw;                       // the SERVER total (shown, never sent back)
        $("#pay-due").textContent = r.body.total;
        show(5);
      });
      return;
    }
    if (step === 5) {
      if (!arrangement()) { clearErrors(); showAlert(["Choose Full Payment, Partial Payment or Pay Later."]); return; }
      if (arrangement() !== "pay_later" && !pickedMethods().length) {
        clearErrors(); showAlert(["Choose at least one payment method."]); return;
      }
      guarded(post(URLS.quote, buildPayload(true, true))).then(function (r) {
        if (!r) return;
        if (!r.body.ok) {
          var lowest = applyErrors(r.body.errors);
          if (lowest < 5) { var errs = r.body.errors; show(lowest); applyErrors(errs); }
          return;
        }
        renderReview(r.body); show(6);
      });
    }
  }

  function back() { if (!busy && step > 1) show(step - 1); }

  function confirmOrder() {
    if (busy) return;
    var payload = buildPayload(true, true);
    payload.submission_token = TOKEN;
    guarded(post(URLS.confirm, payload)).then(function (r) {
      if (!r) return;
      if (r.body.ok) { setBusy(true); window.location.assign(r.body.redirect); return; }
      var errs = r.body.errors || { _general: ["Something went wrong."] };
      var lowest = applyErrors(errs);
      if (r.body.duplicates && r.body.duplicates.length) { show(4); applyErrors(errs); showDuplicates(r.body.duplicates, (errs.customer_duplicate || [""])[0]); return; }
      if (lowest < 6) { show(lowest); applyErrors(errs); }
    });
  }

  // ---------------------------------------------------------------- wiring
  $("#btn-next").addEventListener("click", next);
  $("#btn-back").addEventListener("click", back);
  $("#btn-confirm").addEventListener("click", confirmOrder);
  $$("[data-goto]").forEach(function (b) { b.addEventListener("click", function () { show(Number(b.dataset.goto)); if (b.dataset.goto === "1") refreshCompatibility(); }); });

  $$('input[data-kind]').forEach(function (cb) {
    cb.addEventListener("change", function () { refreshCompatibility(); renderSide(); });
  });
  $$(".extra").forEach(function (x) {
    var qty = $(".extra-qty", x);
    $$("input[type=radio]", x).forEach(function (r) {
      r.addEventListener("change", function () { qty.hidden = !$("input[type=radio]:checked", x).value; renderSide(); });
    });
  });

  $("#cust-search").addEventListener("input", function () { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 250); });
  $$("[data-cust-mode]").forEach(function (b) { b.addEventListener("click", function () { setMode(b.dataset.custMode); }); });
  $("#new-name").addEventListener("input", function () { confirmDuplicate = false; });
  $("#new-contact").addEventListener("input", function () { confirmDuplicate = false; });
  $("#dupe-create").addEventListener("click", function () {
    setMode("new"); confirmDuplicate = true; $("#dupe-box").hidden = true; next();
  });

  $$('input[name="arrangement"]').forEach(function (r) { r.addEventListener("change", syncPayment); });
  $$("[data-pay-method]").forEach(function (c) { c.addEventListener("change", syncPayment); });
  $$("[data-pay-amount]").forEach(function (i) {
    i.addEventListener("input", function () { i.dataset.auto = "0"; syncPayment(); });
  });

  refreshCompatibility();
  show(1);
})();
