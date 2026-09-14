'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../app.js'), 'utf8');
const helper = source.slice(source.indexOf('  function niceAxis('), source.indexOf('  function charts('));
const context = vm.createContext({});
vm.runInContext(helper, context);
for (const unit of ['min', 'h']) {
  for (const values of [[], [null], [0], [0.1], [1], [5], [17], [35], [94], [295], [1000], [1000000]]) {
    const axis = context.niceAxis(values, unit);
    assert.equal(axis.ticks[0], 0);
    assert.ok(axis.ticks.length >= 4 && axis.ticks.length <= 6);
    assert.ok(axis.max >= Math.max(0, ...values.filter(Number.isFinite)));
    assert.equal(axis.max, axis.ticks.at(-1));
    assert.ok(Number.isFinite(axis.max));
    axis.ticks.forEach((tick, i) => {
      assert.equal(tick, i * axis.step);
      assert.ok(Number.isInteger(tick * 2), `awkward decimal: ${tick}`);
    });
  }
}
assert.deepEqual(Array.from(context.niceAxis([295], 'min').ticks), [0,60,120,180,240,300]);
assert.deepEqual(Array.from(context.niceAxis([35], 'min').ticks), [0,10,20,30,40]);
assert.deepEqual(Array.from(context.niceAxis([2.5], 'h').ticks), [0,.5,1,1.5,2,2.5]);
console.log('PASS nice axes: empty, null, zero, small, typical, large; rounded bounds and 4–6 evenly spaced ticks');
