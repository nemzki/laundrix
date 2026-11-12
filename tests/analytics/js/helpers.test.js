// Optional: unit tests for the pure helpers in analytics.js.   Run:  node tests/analytics/js/helpers.test.js
'use strict';
const assert = require('assert');
const h = require('../../../app/analytics/static/js/analytics.js');

assert.strictEqual(h.peso('980'), '\u20b1980.00');
assert.strictEqual(h.peso('1234.5'), '\u20b11,234.50');
assert.strictEqual(h.peso('-100'), '-\u20b1100.00');
assert.strictEqual(h.peso(null), '\u2014');
assert.strictEqual(h.integer(1234), '1,234');
assert.strictEqual(h.percent('25.0'), '25.0%');
assert.strictEqual(h.share(1, 4), '25.0%');
assert.strictEqual(h.share(1, 0), '\u2014');
assert.strictEqual(h.trimQty('4.00'), '4');
assert.strictEqual(h.trimQty('2.50'), '2.5');
assert.strictEqual(h.sumMoney([{ a: '0.10' }, { a: '0.20' }], 'a'), 0.3);   // no floating point drift

const up = h.changeView({ direction: 'up', percent: '308.3', absolute: '740.00' }, { money: true });
assert.deepStrictEqual([up.arrow, up.text, up.tone], ['\u25b2', '308.3%', 'good']);
const owed = h.changeView({ direction: 'up', percent: '725.0', absolute: '290.00' }, { money: true, invert: true });
assert.strictEqual(owed.tone, 'bad');                                          // more owed is not good news
const zero = h.changeView({ direction: 'up', percent: null, absolute: '1' }, {});
assert.strictEqual(zero.text, '+1'); assert(zero.hint);                        // zero baseline: no percentage
assert.strictEqual(h.changeView({ direction: 'flat', percent: '0.0', absolute: '0' }).text, 'No change');
assert.strictEqual(h.changeView(null).text, 'No comparison');
assert.strictEqual(h.changeView({ direction: 'down', percent: '-12.0', absolute: '-5' }).text, '12.0%');

const line = h.lineConfig(['a', 'b'], [{ label: 'X', data: [1, 2], color: '#000', dashed: true }], { money: true });
assert.strictEqual(line.type, 'line'); assert.deepStrictEqual(line.data.datasets[0].borderDash, [6, 4]);
assert.strictEqual(line.options.plugins.tooltip.callbacks.label({ dataset: { label: 'X' }, parsed: { y: 1.5 } }), 'X: \u20b11.50');
assert.strictEqual(h.lineConfig([], [], { reduceMotion: true }).options.animation, false);
const bar = h.barConfig(['a'], [{ label: 'Orders', data: [3], color: '#000' }], { horizontal: true });
assert.strictEqual(bar.options.indexAxis, 'y');
assert.strictEqual(bar.options.plugins.tooltip.callbacks.label({ dataset: { label: 'Orders' }, parsed: { x: 3 } }), 'Orders: 3');
const dn = h.doughnutConfig(['Cash', 'GCash'], [200, 50], ['#1', '#2', '#3'], { money: true });
assert.strictEqual(dn.data.datasets[0].backgroundColor.length, 2);
assert.strictEqual(dn.options.plugins.tooltip.callbacks.label({ label: 'Cash', parsed: 200 }), 'Cash: \u20b1200.00 (80.0%)');
console.log('analytics.js helper tests: OK');
