/* Laundrix Analytics dashboard.
   CSP-safe: no inline script/style, no eval, DOM built with safe text insertion only.
   Part 1 = pure helpers (unit-tested under Node). Part 2 = browser wiring. */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ */
  /* Part 1: pure helpers                                                */
  /* ------------------------------------------------------------------ */
  const PESO = new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP', minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const PESO_TICK = new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP', maximumFractionDigits: 0 });
  const MINUS = '\u2212';

  function isBlank(v) { return v === null || v === undefined || v === ''; }
  function peso(v) { return isBlank(v) ? '\u2014' : PESO.format(Number(v)); }
  function integer(v) { return isBlank(v) ? '\u2014' : Number(v).toLocaleString('en-PH'); }
  function percent(v) { return isBlank(v) ? '\u2014' : Number(v).toFixed(1) + '%'; }
  function share(part, whole) { return whole > 0 ? (part / whole * 100).toFixed(1) + '%' : '\u2014'; }
  function trimQty(v) {
    const n = Number(v);
    return Number.isInteger(n) ? String(n) : String(parseFloat(n.toFixed(2)));
  }
  // Sum money as whole centavos so floating point never drifts.
  function sumMoney(rows, key) { return rows.reduce((t, r) => t + Math.round(Number(r[key]) * 100), 0) / 100; }
  function sumInt(rows, key) { return rows.reduce((t, r) => t + Number(r[key]), 0); }

  // Mirrors services.present_kpis (Python) so tiles and server-rendered cards read the same.
  function changeView(change, opts) {
    opts = opts || {};
    if (!change) return { arrow: '\u2013', text: 'No comparison', tone: 'neutral', hint: 'A comparison needs at least one order in both periods.', label: null };
    if (change.direction === 'flat') return { arrow: '\u2013', text: 'No change', tone: 'neutral', hint: null, label: null };
    const up = change.direction === 'up';
    let text, hint = null;
    if (!isBlank(change.percent)) {
      text = Math.abs(Number(change.percent)).toFixed(1) + '%';
    } else {
      const abs = Math.abs(Number(change.absolute));
      text = (up ? '+' : MINUS) + (opts.money ? peso(abs) : integer(abs));
      hint = 'No percentage is shown because the previous value was zero.';
    }
    return {
      arrow: up ? '\u25b2' : '\u25bc', text: text, hint: hint,
      tone: (up !== !!opts.invert) ? 'good' : 'bad',
      label: up ? 'Increase' : 'Decrease',
    };
  }

  function baseOptions(o, extra) {
    const opts = {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'bottom' } },
    };
    if (o.reduceMotion) opts.animation = false;
    Object.keys(extra || {}).forEach(function (k) { opts[k] = extra[k]; });
    return opts;
  }

  function valueAxis(o, horizontalValue) {
    const axis = { beginAtZero: true, ticks: { precision: 0 }, grid: { color: o.grid } };
    if (o.money) axis.ticks = { callback: function (v) { return PESO_TICK.format(v); } };
    return horizontalValue ? { x: axis, y: { grid: { display: false } } } : { y: axis, x: { grid: { display: false } } };
  }

  // series: [{label, data, color, dashed?}]
  function lineConfig(labels, series, o) {
    o = o || {};
    const fmt = o.money ? peso : integer;
    const options = baseOptions(o, { scales: valueAxis(o, false) });
    options.plugins.tooltip = { callbacks: { label: function (c) { return c.dataset.label + ': ' + fmt(c.parsed.y); } } };
    return {
      type: 'line',
      data: {
        labels: labels,
        datasets: series.map(function (s) {
          return {
            label: s.label, data: s.data, borderColor: s.color, backgroundColor: s.color,
            borderWidth: s.dashed ? 2 : 3, borderDash: s.dashed ? [6, 4] : [],
            pointRadius: labels.length > 40 ? 0 : 3, pointHoverRadius: 5, tension: 0.25, fill: false,
          };
        }),
      },
      options: options,
    };
  }

  function barConfig(labels, series, o) {
    o = o || {};
    const fmt = o.money ? peso : integer;
    const horizontal = !!o.horizontal;
    const options = baseOptions(o, { scales: valueAxis(o, horizontal) });
    if (horizontal) options.indexAxis = 'y';
    options.plugins.legend = { display: series.length > 1, position: 'bottom' };
    options.plugins.tooltip = { callbacks: { label: function (c) { return c.dataset.label + ': ' + fmt(horizontal ? c.parsed.x : c.parsed.y); } } };
    return {
      type: 'bar',
      data: { labels: labels, datasets: series.map(function (s) { return { label: s.label, data: s.data, backgroundColor: s.color, borderRadius: 4 }; }) },
      options: options,
    };
  }

  function doughnutConfig(labels, data, colors, o) {
    o = o || {};
    const fmt = o.money ? peso : integer;
    const total = data.reduce(function (a, b) { return a + b; }, 0);
    const options = baseOptions(o, { cutout: '60%', interaction: { mode: 'nearest', intersect: true } });
    options.plugins.tooltip = {
      callbacks: { label: function (c) { return c.label + ': ' + fmt(c.parsed) + ' (' + share(c.parsed, total) + ')'; } },
    };
    return {
      type: 'doughnut',
      data: { labels: labels, datasets: [{ data: data, backgroundColor: colors.slice(0, data.length), borderWidth: 2, borderColor: '#ffffff' }] },
      options: options,
    };
  }

  const helpers = {
    peso: peso, integer: integer, percent: percent, share: share, trimQty: trimQty,
    sumMoney: sumMoney, sumInt: sumInt, changeView: changeView,
    lineConfig: lineConfig, barConfig: barConfig, doughnutConfig: doughnutConfig,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = helpers;
  if (typeof document === 'undefined') return;

  /* ------------------------------------------------------------------ */
  /* Part 2: browser wiring                                              */
  /* ------------------------------------------------------------------ */
  const root = document.getElementById('analytics-root');
  if (!root) return;

  const API_BASE = root.dataset.apiBase;
  const QUERY = root.dataset.query;
  const SECTIONS = ['sales', 'orders', 'services', 'customers', 'payments', 'balances'];
  const DEFAULT_SECTION = 'sales';
  const hasChart = typeof Chart !== 'undefined';
  const reduceMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  function cssVar(name, fallback) {
    const v = window.getComputedStyle(root).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }
  const FALLBACK = ['#2563eb', '#15803d', '#0891b2', '#b45309', '#7c3aed', '#be185d', '#475569', '#0b1f4a'];
  const PAL = FALLBACK.map(function (c, i) { return cssVar('--an-' + (i + 1), c); });
  const GRID = cssVar('--an-grid', '#e2e8f0');
  const OPTS = { reduceMotion: reduceMotion, grid: GRID };

  if (hasChart) {
    Chart.defaults.font.family = window.getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = '#475569';
  }

  /* ---- tiny DOM helpers (textContent only) ---- */
  function el(tag, props, children) {
    const n = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      const v = props[k];
      if (v === null || v === undefined) return;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else n.setAttribute(k, v);
    });
    (children || []).forEach(function (c) { n.append(c); });
    return n;
  }
  function slot(panel, name) { return panel.querySelector('[data-slot="' + name + '"]'); }

  function tile(o) {
    const t = el('div', { class: 'stat' + (o.aside ? ' an-aside' : '') });
    t.append(el('div', { class: 'stat-label', text: o.label, title: o.title }));
    t.append(el('div', { class: 'stat-value', text: o.value }));
    if (o.change) {
      const v = changeView(o.change, { money: o.money, invert: o.invert });
      const d = el('div', { class: 'an-delta an-' + v.tone, title: v.hint });
      d.append(el('span', { 'aria-hidden': 'true', text: v.arrow }), document.createTextNode(' ' + v.text));
      if (v.label) d.append(el('span', { class: 'sr-only', text: ' ' + v.label + ' compared with the previous period' }));
      t.append(d);
      t.append(el('div', { class: 'an-sub', text: 'vs ' + (o.money ? peso(o.change.previous) : integer(o.change.previous)) + ' in the previous period' }));
    }
    if (o.sub) t.append(el('div', { class: 'an-sub', text: o.sub }));
    return t;
  }

  // columns: [{label, num?, cls?}], rows: [[string,...]], footer: [string,...] | null
  function table(columns, rows, footer) {
    const head = el('tr', null, columns.map(function (c) { return el('th', { scope: 'col', class: c.num ? 'num' : '', text: c.label }); }));
    const body = rows.map(function (r) {
      return el('tr', null, r.map(function (cell, i) {
        const c = columns[i];
        return el('td', { class: [c.num ? 'num' : '', c.cls || ''].join(' ').trim(), text: cell });
      }));
    });
    const t = el('table', { class: 'table' }, [el('thead', null, [head]), el('tbody', null, body)]);
    if (footer) {
      t.append(el('tfoot', null, [el('tr', null, footer.map(function (cell, i) { return el('td', { class: columns[i].num ? 'num' : '', text: cell }); }))]));
    }
    return t;
  }
  function emptyBlock(title, message) {
    return el('div', { class: 'empty' }, [el('strong', { text: title }), document.createTextNode(message)]);
  }
  function setTable(panel, name, columns, rows, footer, emptyTitle, emptyMsg) {
    const host = slot(panel, name);
    if (!host) return;
    host.replaceChildren(rows.length ? table(columns, rows, footer) : emptyBlock(emptyTitle || 'Nothing to show', emptyMsg || 'No data in this period.'));
  }

  /* ---- charts ---- */
  const charts = {};
  function chartMessage(id, message) {
    const canvas = document.getElementById('chart-' + id);
    if (!canvas) return;
    const box = canvas.parentElement;
    Array.prototype.slice.call(box.querySelectorAll('.an-empty-chart')).forEach(function (n) { n.remove(); });
    canvas.hidden = !!message;
    if (message) box.append(el('div', { class: 'an-empty-chart muted', text: message }));
  }
  function draw(panel, id, config, ariaLabel) {
    const canvas = document.getElementById('chart-' + id);
    if (!canvas) return;
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
    if (!hasChart) {
      chartMessage(id, 'The chart library is not installed, so this chart cannot be drawn. The data table below has the same figures.');
      const details = slot(panel, 'details-' + id);
      if (details) details.open = true;
      return;
    }
    chartMessage(id, null);
    if (ariaLabel) canvas.setAttribute('aria-label', ariaLabel);
    charts[id] = new Chart(canvas, config);
  }
  function noChart(id, message) {
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
    chartMessage(id, message);
  }
  function note(panel, id, text) {
    const n = slot(panel, 'note-' + id);
    if (!n) return;
    n.textContent = text || '';
    n.hidden = !text;
  }

  /* ---- section renderers ---- */
  function renderSales(panel, d) {
    const g = d.comparison.gross_order_value, c = d.comparison.payments_collected;
    slot(panel, 'tiles').replaceChildren(
      tile({ label: 'Gross order value', title: d.definitions.gross_order_value, value: peso(g.current), change: g, money: true, sub: 'Billed to customers. Not money received.' }),
      tile({ label: 'Payments collected', title: d.definitions.payments_collected, value: peso(c.current), change: c, money: true, sub: 'Money received, net of reversals.' })
    );
    const pts = d.points;
    const labels = pts.map(function (p) { return p.label + (p.partial ? ' *' : ''); });
    const active = pts.some(function (p) { return p.orders > 0 || Number(p.payments) > 0 || Number(p.reversals) > 0; });
    if (active) {
      draw(panel, 'sales', lineConfig(labels, [
        { label: 'Gross order value', data: pts.map(function (p) { return Number(p.gross_order_value); }), color: PAL[0], dashed: true },
        { label: 'Payments collected (net)', data: pts.map(function (p) { return Number(p.net_collections); }), color: PAL[1] },
      ], Object.assign({ money: true }, OPTS)),
      'Line chart of gross order value and net payments collected, ' + d.period.label + ', grouped by ' + d.granularity);
    } else {
      noChart('sales', 'No sales activity in this period.');
    }
    setTable(panel, 'table-sales',
      [{ label: 'Period' }, { label: 'Orders', num: 1 }, { label: 'Gross order value', num: 1 }, { label: 'Payments received', num: 1 }, { label: 'Reversals', num: 1 }, { label: 'Net collections', num: 1 }],
      pts.map(function (p, i) { return [labels[i], integer(p.orders), peso(p.gross_order_value), peso(p.payments), peso(p.reversals), peso(p.net_collections)]; }),
      ['Total', integer(sumInt(pts, 'orders')), peso(sumMoney(pts, 'gross_order_value')), peso(sumMoney(pts, 'payments')), peso(sumMoney(pts, 'reversals')), peso(sumMoney(pts, 'net_collections'))]);
    note(panel, 'sales', pts.some(function (p) { return p.partial; }) ? '* This group is only partly inside the selected dates.' : '');
    slot(panel, 'definitions').textContent = d.definitions.gross_order_value + ' ' + d.definitions.payments_collected;
  }

  function renderOrders(panel, d) {
    const grp = {};
    d.groups.forEach(function (g) { grp[g.key] = g.count; });
    slot(panel, 'tiles').replaceChildren(
      tile({ label: 'Total orders', value: integer(d.total), change: d.comparison }),
      tile({ label: 'Pending', value: integer(grp.pending), sub: 'Received or awaiting processing' }),
      tile({ label: 'Processing', value: integer(grp.processing) }),
      tile({ label: 'Ready for pickup', value: integer(grp.ready) }),
      tile({ label: 'Completed / released', value: integer(grp.completed) }),
      tile({ label: 'Awaiting receipt', value: integer(d.awaiting_receipt), sub: 'Order slip issued, laundry not yet confirmed received', aside: true })
    );
    const shown = d.by_status.filter(function (s) { return s.count > 0; });
    if (shown.length) {
      draw(panel, 'orders-status', doughnutConfig(shown.map(function (s) { return s.label; }), shown.map(function (s) { return s.count; }), PAL, OPTS),
        'Doughnut chart of orders by status, ' + d.period.label);
    } else {
      noChart('orders-status', 'No orders in this period.');
    }
    setTable(panel, 'table-orders-status', [{ label: 'Status' }, { label: 'Orders', num: 1 }, { label: 'Share', num: 1 }],
      d.by_status.map(function (s) { return [s.label, integer(s.count), share(s.count, d.total)]; }),
      ['Total', integer(d.total), d.total > 0 ? '100.0%' : '\u2014']);

    const v = d.volume;
    if (d.total > 0) {
      draw(panel, 'orders-volume', barConfig(v.map(function (p) { return p.label + (p.partial ? ' *' : ''); }),
        [{ label: 'Orders', data: v.map(function (p) { return p.orders; }), color: PAL[0] }], OPTS),
      'Bar chart of orders per ' + d.granularity + ', ' + d.period.label);
    } else {
      noChart('orders-volume', 'No orders in this period.');
    }
    setTable(panel, 'table-orders-volume', [{ label: 'Period' }, { label: 'Orders', num: 1 }],
      v.map(function (p) { return [p.label + (p.partial ? ' *' : ''), integer(p.orders)]; }), ['Total', integer(sumInt(v, 'orders'))]);
    note(panel, 'orders-volume', v.some(function (p) { return p.partial; }) ? '* This group is only partly inside the selected dates.' : '');
  }

  function typeLabel(t) { return t === 'package' ? 'Package' : t === 'addon' ? 'Add-on' : 'Service'; }
  function qtyCell(r) { return trimQty(r.quantity) + ' ' + r.unit; }

  function renderServices(panel, d) {
    slot(panel, 'notes').textContent = d.notes.revenue + ' ' + d.notes.scope;
    const top = d.most_ordered;
    if (top.length) {
      draw(panel, 'services-top', barConfig(top.map(function (r) { return r.name; }),
        [{ label: 'Orders', data: top.map(function (r) { return r.orders; }), color: PAL[0] }], Object.assign({ horizontal: true }, OPTS)),
      'Bar chart of the most frequently ordered services and packages, ' + d.period.label);
    } else {
      noChart('services-top', 'No services or packages were ordered in this period.');
    }
    setTable(panel, 'table-services-top', [{ label: 'Service / package' }, { label: 'Orders', num: 1 }],
      top.map(function (r) { return [r.name, integer(r.orders)]; }), null, 'No services ordered', 'Nothing was ordered in this period.');

    const series = d.trend.series, pts = d.trend.points;
    if (series.length) {
      draw(panel, 'services-trend', lineConfig(pts.map(function (p) { return p.label + (p.partial ? ' *' : ''); }),
        series.map(function (name, i) { return { label: name, data: pts.map(function (p) { return p[name]; }), color: PAL[i % PAL.length] }; }), OPTS),
      'Line chart of orders over time for the most ordered services, grouped by ' + d.granularity);
    } else {
      noChart('services-trend', 'No service demand to chart in this period.');
    }
    setTable(panel, 'table-services-trend', [{ label: 'Period' }].concat(series.map(function (s) { return { label: s, num: 1 }; })),
      pts.map(function (p) { return [p.label + (p.partial ? ' *' : '')].concat(series.map(function (s) { return integer(p[s]); })); }), null);

    const cols = [{ label: '#', cls: 'an-rank' }, { label: 'Name' }, { label: 'Type' }, { label: 'Quantity', num: 1 }, { label: 'Orders', num: 1 }, { label: 'Item revenue', num: 1 }];
    const row = function (r) { return [String(r.rank), r.name, typeLabel(r.item_type), qtyCell(r), integer(r.orders), peso(r.item_revenue)]; };
    setTable(panel, 'table-services', cols, d.services.map(row), null, 'No services ordered', 'Nothing was ordered in this period.');
    setTable(panel, 'table-least', cols, d.least_ordered.map(row), null, 'Not enough variety', 'Shown once more than five services or packages were ordered.');
    setTable(panel, 'table-addons', cols, d.addons.map(row), null, 'No add-ons ordered', 'No add-ons were ordered in this period.');
  }

  function renderCustomers(panel, d) {
    slot(panel, 'tiles').replaceChildren(
      tile({ label: 'Registered customers', value: integer(d.registered), sub: 'Total, up to the end of the period' }),
      tile({ label: 'New customers', value: integer(d.new_registered), sub: 'Registered within the period' }),
      tile({ label: 'Active customers', value: integer(d.active), sub: 'Placed an order in the period' }),
      tile({ label: 'Returning customers', title: d.definitions.returning_customers, value: integer(d.returning), change: d.returning_comparison }),
      tile({ label: 'Repeat-customer rate', title: d.definitions.repeat_customer, value: percent(d.repeat_rate),
        sub: integer(d.repeat) + ' of ' + integer(d.with_orders) + ' customers with orders' })
    );
    setTable(panel, 'table-top', [{ label: '#', cls: 'an-rank' }, { label: 'Customer' }, { label: 'Orders', num: 1 }, { label: 'Total order value', num: 1 }],
      d.top_customers.map(function (c, i) { return [String(i + 1), c.name, integer(c.orders), peso(c.total)]; }),
      null, 'No customer orders', 'No customers placed orders in this period.');
    slot(panel, 'definitions').replaceChildren(
      el('li', { text: 'Returning: ' + d.definitions.returning_customers }),
      el('li', { text: 'Repeat: ' + d.definitions.repeat_customer + ' The rate is repeat customers divided by all customers with at least one order.' }),
      el('li', { text: 'New: customers whose record was created within the period. Phone numbers are not shown in analytics.' })
    );
  }

  function renderPayments(panel, d) {
    const s = d.summary;
    slot(panel, 'tiles').replaceChildren(
      tile({ label: 'Net collections', title: d.definition, value: peso(s.net), sub: 'Payments minus reversals' }),
      tile({ label: 'Payments received', value: peso(s.payments), sub: integer(s.payment_count) + ' transactions' }),
      tile({ label: 'Reversals', value: peso(s.reversals), sub: integer(s.reversal_count) + ' reversed transactions' }),
      tile({ label: 'Payment transactions', value: integer(s.payment_count) }),
      tile({ label: 'Reversed transactions', value: integer(s.reversal_count) })
    );
    const methods = d.methods;
    const positive = methods.filter(function (m) { return Number(m.net) > 0; });
    if (positive.length) {
      draw(panel, 'payments-methods', doughnutConfig(positive.map(function (m) { return m.label; }), positive.map(function (m) { return Number(m.net); }), PAL, Object.assign({ money: true }, OPTS)),
        'Doughnut chart of net collections by payment method, ' + d.period.label);
    } else {
      noChart('payments-methods', 'No collections in this period.');
    }
    const cols = [{ label: 'Method' }, { label: 'Payments', num: 1 }, { label: 'Reversals', num: 1 }, { label: 'Net collected', num: 1 }, { label: 'Share', num: 1 }, { label: 'Transactions', num: 1 }];
    const rows = methods.map(function (m) { return [m.label, peso(m.payments), peso(m.reversals), peso(m.net), percent(m.share), integer(m.payment_count)]; });
    setTable(panel, 'table-payments-methods', cols, rows, null, 'No collections', 'No payments were recorded in this period.');
    setTable(panel, 'table-methods', cols, rows,
      ['Total', peso(s.payments), peso(s.reversals), peso(s.net), '', integer(s.payment_count)], 'No collections', 'No payments were recorded in this period.');
    slot(panel, 'definitions').textContent = 'Methods come from the payment ledger, so any method you add appears here. ' + d.definition;
  }

  function renderBalances(panel, d) {
    slot(panel, 'tiles').replaceChildren(
      tile({ label: 'Total outstanding', value: peso(d.balance_total), sub: 'Confirmed unpaid or partly paid orders' }),
      tile({ label: 'Customers with a balance', value: integer(d.customers_owing) }),
      tile({ label: 'Unpaid orders', value: integer(d.unpaid_orders), sub: peso(d.unpaid_amount) + ' owed' }),
      tile({ label: 'Partially paid orders', value: integer(d.partial_orders), sub: peso(d.partial_amount) + ' still owed' }),
      tile({ label: 'Payment not tracked', value: integer(d.untracked_orders), sub: peso(d.untracked_order_value) + ' in order value. Not counted above.', aside: true })
    );
    let asOf = '';
    try { asOf = ' As of ' + new Date(d.as_of).toLocaleString('en-PH', { timeZone: 'Asia/Manila', dateStyle: 'medium', timeStyle: 'short' }) + ' (Philippine time).'; } catch (e) { asOf = ''; }
    slot(panel, 'notes').textContent = d.notes.scope + ' ' + d.notes.untracked + asOf;
  }

  const RENDERERS = { sales: renderSales, orders: renderOrders, services: renderServices, customers: renderCustomers, payments: renderPayments, balances: renderBalances };

  /* ---- loading, caching, errors ---- */
  const cache = new Map();
  const tokens = {};
  const granPick = {};

  async function fetchSection(section, gran) {
    const key = section + '|' + (gran || '');
    if (cache.has(key)) return cache.get(key);
    let url = API_BASE + section + '?' + QUERY;
    if (gran) url += '&granularity=' + encodeURIComponent(gran);
    const res = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    const type = (res.headers && res.headers.get('content-type')) || '';
    if (res.redirected || type.indexOf('application/json') === -1) throw new Error('Your session may have expired. Reload the page to sign in again.');
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || 'This section could not be loaded.');
    cache.set(key, body);
    return body;
  }

  function syncGran(panel, current) {
    Array.prototype.slice.call(panel.querySelectorAll('[data-gran]')).forEach(function (b) {
      const on = b.dataset.gran === current;
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.classList.toggle('active', on);
    });
  }

  async function load(section) {
    const panel = document.getElementById('panel-' + section);
    if (!panel) return;
    const status = slot(panel, 'status'), body = slot(panel, 'body');
    const token = (tokens[section] = (tokens[section] || 0) + 1);
    const firstTime = body.hidden;
    status.replaceChildren(el('div', { class: 'an-loading', text: 'Loading ' + section + '\u2026' }));
    try {
      const data = await fetchSection(section, granPick[section]);
      if (token !== tokens[section]) return;
      status.replaceChildren();
      body.hidden = false;
      RENDERERS[section](panel, data);
      syncGran(panel, data.granularity);
    } catch (err) {
      if (token !== tokens[section]) return;
      if (firstTime) body.hidden = true;
      const retry = el('button', { class: 'btn btn-outline btn-sm', type: 'button', text: 'Try again' });
      retry.addEventListener('click', function () { load(section); });
      status.replaceChildren(el('div', { class: 'alert alert-error', role: 'alert' }, [
        el('strong', { text: 'Could not load ' + section + '. ' }), document.createTextNode(err.message + ' '), retry,
      ]));
    }
  }

  /* ---- tabs ---- */
  const tabs = Array.prototype.slice.call(root.querySelectorAll('[data-tab]'));
  function activate(section, updateHash) {
    if (SECTIONS.indexOf(section) === -1) section = DEFAULT_SECTION;
    tabs.forEach(function (t) {
      const on = t.dataset.tab === section;
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.setAttribute('tabindex', on ? '0' : '-1');
    });
    SECTIONS.forEach(function (s) {
      const p = document.getElementById('panel-' + s);
      if (p) p.hidden = s !== section;
    });
    if (updateHash && window.history && window.history.replaceState) window.history.replaceState(null, '', '#' + section);
    load(section);
  }
  tabs.forEach(function (t, i) {
    t.addEventListener('click', function () { activate(t.dataset.tab, true); });
    t.addEventListener('keydown', function (e) {
      const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      const next = tabs[(i + step + tabs.length) % tabs.length];
      next.focus();
      activate(next.dataset.tab, true);
      e.preventDefault();
    });
  });
  SECTIONS.forEach(function (section) {
    const panel = document.getElementById('panel-' + section);
    if (!panel) return;
    Array.prototype.slice.call(panel.querySelectorAll('[data-gran]')).forEach(function (b) {
      b.addEventListener('click', function () { granPick[section] = b.dataset.gran; load(section); });
    });
  });
  window.addEventListener('hashchange', function () { activate(window.location.hash.slice(1), false); });
  activate(window.location.hash.slice(1), false);
})();
