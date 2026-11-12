/* Admin dashboard charts — Chart.js, CSP-safe external file. */
(function () {
  "use strict";

  function readJson(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (err) {
      return null;
    }
  }

  function peso(n) {
    var value = Number(n) || 0;
    return "\u20b1" + value.toLocaleString("en-PH", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  function baseOptions() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            boxWidth: 12,
            boxHeight: 12,
            usePointStyle: true,
            pointStyle: "circle",
            color: "#64748b",
            font: { family: "Plus Jakarta Sans, system-ui, sans-serif", size: 12 }
          }
        },
        tooltip: {
          backgroundColor: "#0f172a",
          titleFont: { family: "Plus Jakarta Sans, system-ui, sans-serif", size: 12 },
          bodyFont: { family: "Plus Jakarta Sans, system-ui, sans-serif", size: 12 }
        }
      }
    };
  }

  function initStatusChart(payload) {
    var canvas = document.getElementById("dashStatusChart");
    if (!canvas || typeof Chart === "undefined" || !payload) return;
    var labels = payload.labels || [];
    var values = payload.values || [];
    var colors = payload.colors || [];
    var total = values.reduce(function (sum, n) { return sum + (Number(n) || 0); }, 0);
    if (!total) return;

    new Chart(canvas.getContext("2d"), {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [{
          data: values,
          backgroundColor: colors,
          borderColor: "#ffffff",
          borderWidth: 2,
          hoverOffset: 2
        }]
      },
      options: Object.assign(baseOptions(), {
        cutout: "62%",
        plugins: Object.assign(baseOptions().plugins, {
          tooltip: Object.assign(baseOptions().plugins.tooltip, {
            callbacks: {
              label: function (ctx) {
                var v = Number(ctx.raw) || 0;
                var pct = total ? Math.round((v / total) * 100) : 0;
                return " " + ctx.label + ": " + v + " (" + pct + "%)";
              }
            }
          })
        })
      })
    });
  }

  function initPopularChart(payload) {
    var canvas = document.getElementById("dashPopularChart");
    if (!canvas || typeof Chart === "undefined" || !payload) return;
    var labels = payload.labels || [];
    var values = payload.values || [];
    if (!labels.length) return;

    new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: "Order lines",
          data: values,
          backgroundColor: "#2563eb",
          borderRadius: 6,
          maxBarThickness: 28
        }]
      },
      options: Object.assign(baseOptions(), {
        indexAxis: "y",
        plugins: Object.assign(baseOptions().plugins, {
          legend: { display: false },
          tooltip: Object.assign(baseOptions().plugins.tooltip, {
            callbacks: {
              label: function (ctx) {
                var v = Number(ctx.raw) || 0;
                return " " + v + " order line" + (v === 1 ? "" : "s");
              }
            }
          })
        }),
        scales: {
          x: {
            beginAtZero: true,
            ticks: {
              precision: 0,
              color: "#64748b",
              font: { family: "Plus Jakarta Sans, system-ui, sans-serif", size: 11 }
            },
            grid: { color: "#e2e8f0" }
          },
          y: {
            ticks: {
              color: "#0f172a",
              font: { family: "Plus Jakarta Sans, system-ui, sans-serif", size: 12 }
            },
            grid: { display: false }
          }
        }
      })
    });
  }

  // Expose peso helper for future financial charts without inventing data now.
  window.lxDashFormatPeso = peso;

  initStatusChart(readJson("dash-status-data"));
  initPopularChart(readJson("dash-popular-data"));
})();
