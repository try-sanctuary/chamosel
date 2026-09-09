// Executed by test_controller.py with the rendered dashboard on stdin.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

const html = fs.readFileSync(0, 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function dashboard(refresh = '5') {
  const timers = new Map();
  const buttons = Array.from({ length: 6 }, () => ({ disabled: false }));
  const elements = {
    refreshSeconds: { value: '' },
    autoRepairState: { textContent: 'OFF' },
    actionStatus: { textContent: '' },
  };
  const requests = [];
  let nextTimer = 0;
  let reloads = 0;
  const context = vm.createContext({
    window: {
      setTimeout(callback, delay) {
        timers.set(++nextTimer, { callback, delay });
        return nextTimer;
      },
      clearTimeout(id) { timers.delete(id); },
    },
    location: { reload() { reloads++; } },
    localStorage: { getItem() { return refresh; }, setItem() {} },
    document: {
      getElementById(id) { return elements[id]; },
      querySelector() { return { value: 'vpn_0' }; },
      querySelectorAll() { return buttons; },
    },
    fetch(path, options) {
      return new Promise((resolve, reject) => requests.push({ path, options, resolve, reject }));
    },
  });
  vm.runInContext(script, context);
  return { context, timers, buttons, elements, requests, reloads: () => reloads };
}

test('all actions suspend refresh, prevent duplicate POSTs, and wait for the body', async () => {
  for (const [action, path] of [
    ['repairSelected', '/repair/vpn_0'],
    ['rotateSelected', '/rotate/vpn_0?force=0'],
    ['rotateAny', '/rotate'],
    ['toggleAutoRepair', '/repair/auto?enabled=1'],
  ]) {
    const d = dashboard();
    assert.equal(d.timers.size, 1);
    const pending = d.context[action]();
    assert.equal(d.timers.size, 0);
    assert.ok(d.buttons.every(button => button.disabled));
    await d.context[action]();
    assert.equal(d.requests.length, 1);
    assert.equal(d.requests[0].path, path);
    assert.equal(d.requests[0].options.method, 'POST');
    assert.equal(d.requests[0].options.headers['X-Chamosel-CSRF'], '1');
    let resolveBody;
    d.requests[0].resolve({ ok: true, json: () => new Promise(resolve => { resolveBody = resolve; }) });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(d.reloads(), 0);
    assert.equal(d.timers.size, 0);
    resolveBody({ ok: true });
    await pending;
    assert.equal(d.reloads(), 1);
    assert.ok(d.buttons.every(button => !button.disabled));
  }
});

test('network, HTTP, and operation failures restore controls without retrying', async () => {
  for (const failure of ['network', 'http', 'operation', 'json']) {
    const d = dashboard();
    const pending = d.context.repairSelected();
    const request = d.requests[0];
    if (failure === 'network') request.reject(new Error('connection lost'));
    if (failure === 'http') request.resolve({ ok: false, status: 503 });
    if (failure === 'operation') request.resolve({
      ok: true, json: async () => ({ ok: false, rotation: { message: 'VPN recovery timed out' } }),
    });
    if (failure === 'json') request.resolve({ ok: true, json: async () => { throw new Error('invalid JSON'); } });
    await pending;
    assert.equal(d.reloads(), 0);
    assert.equal(d.requests.length, 1);
    assert.equal(d.timers.size, 1);
    assert.ok(d.buttons.every(button => !button.disabled));
    assert.match(d.elements.actionStatus.textContent, /^Operation failed: /);
    if (failure === 'operation') assert.match(d.elements.actionStatus.textContent, /VPN recovery timed out/);
    const timer = [...d.timers.values()][0];
    assert.equal(timer.delay, 5000);
    timer.callback();
    assert.equal(d.reloads(), 1);
    assert.equal(d.requests.length, 1);
  }
});

test('disabled auto-refresh stays disabled after failure', async () => {
  const d = dashboard('0');
  const pending = d.context.rotateAny();
  d.requests[0].reject(new Error('offline'));
  await pending;
  assert.equal(d.timers.size, 0);
  assert.equal(d.reloads(), 0);
});
