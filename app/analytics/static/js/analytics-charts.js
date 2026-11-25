/* Read report data and draw the analytics charts. */
/* Draws the Analytics charts with the Chart.js copy that ships with Laundrix (no CDN).
   Data comes from a JSON block in the page; there is no inline script (the site's CSP forbids it). */
(function () {
  "use strict";
  var dataEl = document.getElementById("analytics-chart-data");
  if (!dataEl || typeof Chart === "undefined") { return; }

  var data;
  try { data = JSON.parse(dataEl.textContent); } catch (e) { return; }

  var root = document.getElementById("laundrix-analytics") || document.documentElement;
  var charts = [];
  Chart.defaults.font.family = getComputedStyle(root).fontFamily;

  /* Look up a CSS value so chart colors can match the page theme. */
  function css(name, fallback) {
    var v = getComputedStyle(root).getPropertyValue(name).trim();
    return v || fallback;
  }

  function palette() {
    return {
      primary: css("--primary", "#2563eb"),
      text: css("--muted-foreground", "#64748b"),
      grid: css("--border", "#e2e8f0")
    };
  }

  /* Format a number as a Philippine peso amount for display. */
  function peso(v) { return "\u20B1" + Number(v).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

  /* Set chart options shared by the charts in this file. */
  function baseOptions(p) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: p.text, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
        y: { beginAtZero: true, grid: { color: p.grid }, ticks: { color: p.text, precision: 0 } }
      }
    };
  }

  function make(id, config) {
    var canvas = document.getElementById(id);
    if (!canvas) { return; }
    charts.push(new Chart(canvas, config));
  }

  // API: Draw reports using server data
  function build() {
    var p = palette();
    charts.forEach(function (c) { c.destroy(); });
    charts = [];

    var ordersOpts = baseOptions(p);
    make("chart-orders", {
      type: "bar",
      data: { labels: data.orders.labels, datasets: [{ label: "Orders", data: data.orders.values, backgroundColor: p.primary, borderRadius: 4 }] },
      options: ordersOpts
    });

    var revOpts = baseOptions(p);
    revOpts.scales.y.ticks.precision = undefined;
    revOpts.scales.y.ticks.callback = function (v) { return peso(v).replace(".00", ""); };
    revOpts.plugins.tooltip = { callbacks: { label: function (c) { return " " + peso(c.parsed.y); } } };
    make("chart-revenue", {
      type: "line",
      data: { labels: data.revenue.labels, datasets: [{ label: "Revenue", data: data.revenue.values, borderColor: p.primary, backgroundColor: p.primary, tension: 0.25, pointRadius: 2, fill: false }] },
      options: revOpts
    });

    make("chart-status", {
      type: "doughnut",
      data: { labels: data.status.labels, datasets: [{ data: data.status.values, backgroundColor: ["#94a3b8", "#d97706", "#7c3aed", "#0891b2", "#2563eb", "#059669"], borderWidth: 0 }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, cutout: "62%",
        plugins: { legend: { position: "right", labels: { color: p.text, boxWidth: 10, boxHeight: 10, usePointStyle: true } } }
      }
    });

    var svcOpts = baseOptions(p);
    svcOpts.indexAxis = "y";
    svcOpts.scales.x = { beginAtZero: true, grid: { color: p.grid }, ticks: { color: p.text, precision: 0 } };
    svcOpts.scales.y = { grid: { display: false }, ticks: { color: p.text } };
    make("chart-services", {
      type: "bar",
      data: { labels: data.services.labels, datasets: [{ label: "Orders", data: data.services.values, backgroundColor: p.primary, borderRadius: 4 }] },
      options: svcOpts
    });
  }

  document.fonts.ready.then(build);
  // Redraw with the right colours when the light/dark theme is switched.
  new MutationObserver(build).observe(document.documentElement, { attributes: true, attributeFilter: ["data-lx-theme"] });
})();
