const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('app.js', 'utf8').split("$('refresh').onclick")[0];
const context = {
  Date, Intl, JSON, Map, Math, Set,
  localStorage: { getItem: () => null },
  document: { getElementById: () => ({}) },
};
vm.createContext(context);
vm.runInContext(source, context);
vm.runInContext(`data=${fs.readFileSync('data/market.json', 'utf8')}`, context);

const first = vm.runInContext("hkdModel('2026-11-10')", context);
assert.equal(first.shares, 82);
assert.equal(first.cost, 1000);
assert.equal(first.priced, 1);
assert.equal(first.marketValue.toFixed(2), '982.36');
assert.equal(first.cash.toFixed(2), '17.64');

const later = vm.runInContext("hkdModel('2026-11-13')", context);
assert.equal(later.shares, 82);
assert.equal(later.marketValue.toFixed(2), '987.28');
assert.equal(later.value.toFixed(2), '1004.92');

vm.runInContext("data.hk3195.push({date:'2026-12-10',close:12.34})", context);
const second = vm.runInContext("hkdModel('2026-12-10')", context);
assert.equal(second.shares, 163);
assert.equal(second.cost, 2000);
assert.equal(second.priced, 2);
assert.equal(second.cash.toFixed(2), '18.10');

console.log('HK share and valuation model passed');
