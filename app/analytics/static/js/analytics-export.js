/* Export form: switches filters/columns per dataset, applies column presets, remembers the last column
   choice, shows a live "N records match" count and blocks obviously empty/too-large downloads.
   The data (columns, presets, filters) comes from a JSON block in the page; there is no inline script
   (the site's CSP forbids it). The server re-validates everything, so this file is convenience only. */
(function () {
  "use strict";
  var form = document.getElementById("export-form");
  var cfgEl = document.getElementById("analytics-export-config");
  if (!form || !cfgEl) { return; }

  var config;
  try { config = JSON.parse(cfgEl.textContent); } catch (e) { return; }

  var datasetSelect = document.getElementById("export-dataset");
  var startInput = document.getElementById("export-start");
  var endInput = document.getElementById("export-end");
  var summary = document.getElementById("export-summary");
  var countLabel = document.getElementById("export-column-count");
  var submitBtn = document.getElementById("export-submit");
  var previewUrl = form.getAttribute("data-preview-url");
  var STORE = "laundrix.export.columns.";
  var lastPreview = null;      // { ok, rows, too_many, limit } for the current form values
  var timer = null;
  var controller = null;

  function all(selector, root) { return Array.prototype.slice.call((root || form).querySelectorAll(selector)); }
  function dataset() { return datasetSelect.value; }
  function format() { var r = form.querySelector('input[name="format"]:checked'); return r ? r.value : "csv"; }
  function columnSet() { return form.querySelector('.export-columnset[data-dataset="' + dataset() + '"]'); }
  function columnBoxes() { return all('input[name="columns"]', columnSet()); }
  function checkedKeys() { return columnBoxes().filter(function (b) { return b.checked; }).map(function (b) { return b.value; }); }

  /* ---------- remember the last column choice (per dataset, per browser) ---------- */
  function save() {
    try { localStorage.setItem(STORE + dataset(), JSON.stringify(checkedKeys())); } catch (e) { /* private mode */ }
  }
  function restore(ds) {
    try {
      var saved = JSON.parse(localStorage.getItem(STORE + ds) || "null");
      if (!Array.isArray(saved) || !saved.length) { return; }
      var set = form.querySelector('.export-columnset[data-dataset="' + ds + '"]');
      all('input[name="columns"]', set).forEach(function (b) { b.checked = saved.indexOf(b.value) !== -1; });
    } catch (e) { /* ignore a corrupt value */ }
  }

  function setColumns(keys) {
    columnBoxes().forEach(function (b) { b.checked = keys.indexOf(b.value) !== -1; });
    columnsChanged();
  }

  function columnsChanged() {
    var total = columnBoxes().length, picked = checkedKeys().length;
    countLabel.textContent = picked + " of " + total + " selected";
    save();
    schedulePreview();
  }

  /* ---------- show only the parts that belong to the chosen dataset ---------- */
  function toggle(el, on) {
    el.hidden = !on;
    if (el.tagName === "FIELDSET") { el.disabled = !on; }
  }
  function showDataset() {
    var ds = dataset();
    all(".export-filterset, .export-columnset, .export-preset-set").forEach(function (el) {
      var on = el.getAttribute("data-dataset") === ds;
      toggle(el, on);
      if (el.classList.contains("export-filterset")) {
        all("fieldset", el).forEach(function (fs) { fs.disabled = !on; });   // disabled = not submitted
      }
    });
    restore(ds);
    columnsChanged();
  }

  function updateButton() {
    submitBtn.textContent = format() === "xlsx" ? "Download Excel (.xlsx)" : "Download CSV";
  }

  /* ---------- quick date ranges ---------- */
  function iso(d) {
    var m = String(d.getMonth() + 1).padStart(2, "0"), day = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + m + "-" + day;
  }
  function setRange(spec) {
    var end = endInput.max ? new Date(endInput.max + "T00:00:00") : new Date();   // "today" in the shop, from the server
    var start = new Date(end);
    if (spec === "month") { start = new Date(end.getFullYear(), end.getMonth(), 1); }
    else { start.setDate(start.getDate() - (parseInt(spec, 10) - 1)); }
    startInput.value = iso(start);
    endInput.value = iso(end);
    schedulePreview();
  }

  /* ---------- live record count ---------- */
  function say(text, tone) {
    summary.textContent = text;
    summary.setAttribute("data-tone", tone || "");
  }
  function schedulePreview() {
    lastPreview = null;
    say("Checking how many records match…");
    clearTimeout(timer);
    timer = setTimeout(runPreview, 300);
  }
  function runPreview() {
    if (controller) { controller.abort(); }
    if (typeof AbortController !== "undefined") { controller = new AbortController(); }
    var params = new URLSearchParams(new FormData(form));        // disabled (hidden) fields are left out
    var opts = { credentials: "same-origin", headers: { "Accept": "application/json" } };
    if (controller) { opts.signal = controller.signal; }
    fetch(previewUrl + "?" + params.toString(), opts)
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
      .then(function (res) {
        var j = res.body;
        lastPreview = j;
        if (!j.ok) { say(j.error || "That selection is not valid.", "error"); return; }
        var n = j.rows.toLocaleString();
        if (j.too_many) { say(n + " rows match, which is over the " + j.limit.toLocaleString() + "-row limit. Shorten the date range or add filters.", "error"); }
        else if (j.rows === 0) { say("No records match this date range and these filters.", "warn"); }
        else { say(n + (j.rows === 1 ? " row" : " rows") + " will be exported.", "ok"); }
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") { return; }
        say("Could not check the record count. You can still try the download.", "warn");
      });
  }

  /* ---------- events ---------- */
  datasetSelect.addEventListener("change", showDataset);
  all('input[name="format"]').forEach(function (r) { r.addEventListener("change", updateButton); });
  form.addEventListener("change", function (e) {
    var t = e.target;
    if (t.name === "columns") { columnsChanged(); }
    else if (t === startInput || t === endInput || t.type === "checkbox") { schedulePreview(); }
  });
  all("[data-range-days]").forEach(function (b) {
    b.addEventListener("click", function () { setRange(b.getAttribute("data-range-days")); });
  });
  all("[data-preset]").forEach(function (b) {
    b.addEventListener("click", function () {
      var cfg = config[dataset()], id = b.getAttribute("data-preset");
      if (id === "all") { setColumns(cfg.all); }
      else if (id === "none") { setColumns([]); }
      else if (id === "defaults") { setColumns(cfg.defaults); }
      else {
        var p = cfg.presets.filter(function (x) { return x.id === id; })[0];
        if (p) { setColumns(p.columns); }
      }
    });
  });

  form.addEventListener("submit", function (e) {
    if (!checkedKeys().length) {
      e.preventDefault();
      say("Please tick at least one column to export.", "error");
      return;
    }
    if (startInput.value && endInput.value && startInput.value > endInput.value) {
      e.preventDefault();
      say("The start date must be on or before the end date.", "error");
      return;
    }
    if (lastPreview && lastPreview.ok && (lastPreview.rows === 0 || lastPreview.too_many)) {
      e.preventDefault();   // the message is already showing; nothing useful to download
    }
  });

  updateButton();
  showDataset();
})();
