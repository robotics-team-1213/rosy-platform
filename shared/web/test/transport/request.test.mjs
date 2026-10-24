import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequest} from '../../../../operations/site_ui/console/shared/request.js';

for (const abortParent of [false, true]) {
  test(`page and caller cancellation compose: ${abortParent ? 'caller' : 'page'}`, async () => {
    const parent = new AbortController();
    const page = new AbortController();
    let release;
    let sentSignal;
    const request = createRequest({origin: 'https://fleet.test', fetchImpl: (_url, options) => {
      sentSignal = options.signal;
      return new Promise(resolve => { release = resolve; });
    }});
    const pending = request('/read', {signal: parent.signal, signals: [page.signal]});
    (abortParent ? parent : page).abort();
    assert.equal(sentSignal.aborted, true);
    release(new Response('{}'));
    await assert.rejects(pending, {name: 'AbortError'});
  });
}

const origin = 'https://robot.test';
const json = (body, status = 200) => new Response(JSON.stringify(body), {status});

test('authenticated binary reads keep JSON errors and request scope', async () => {
  let authorization;
  const request = createRequest({origin, credential: () => 'viewer', fetchImpl: async (_url, init) => {
    authorization = init.headers.get('Authorization');
    assert.equal(init.credentials, 'same-origin');
    assert.equal('responseType' in init, false);
    return new Response('pixels', {headers: {'Content-Type': 'image/png'}});
  }});
  const got = await request('/render', {responseType: 'blob'});
  assert.equal(authorization, 'Bearer viewer');
  assert.equal(await got.body.text(), 'pixels');
  const failed = createRequest({origin, fetchImpl: async () => json({detail: {code: 'DENIED'}}, 403)});
  assert.deepEqual((await failed('/render', {responseType: 'blob'})).body, {detail: {code: 'DENIED'}});
  await assert.rejects(request('/render', {responseType: 'script'}), /response type/);
});

test('two concurrent audiences remain separate and credential is read per request', async () => {
  const calls = [];
  let coreToken = 'core-one';
  const fetchImpl = async (url, options) => {
    calls.push({url, headers: new Headers(options.headers)});
    return json({detail: 'temporarily unavailable'}, 503);
  };
  const core = createRequest({origin, credential: () => coreToken, fetchImpl});
  const fleet = createRequest({origin: 'https://fleet.test', credential: () => 'fleet-one', fetchImpl});
  const results = await Promise.all([core('/command', {method: 'POST'}), fleet('/state')]);
  assert.deepEqual(results.map(row => row.status), [503, 503]);
  assert.deepEqual(calls.map(row => row.headers.get('Authorization')), ['Bearer core-one', 'Bearer fleet-one']);
  coreToken = 'core-two';
  await core('/state');
  assert.equal(calls[2].headers.get('Authorization'), 'Bearer core-two');
  assert.equal(calls.length, 3);
});

for (const path of ['https://fleet.test/state', '//fleet.test/state', 'data:text/plain,hello',
                    'javascript:alert(1)', 'https://user:password@robot.test/state']) {
  test(`unsafe destination is rejected before credential or fetch: ${path}`, async () => {
    let credentials = 0;
    let sends = 0;
    const request = createRequest({origin, credential: () => { credentials++; return 'core-one'; },
      fetchImpl: async () => { sends++; return json({}); }});
    await assert.rejects(request(path), /origin|credential/);
    assert.equal(credentials, 0);
    assert.equal(sends, 0);
  });
}

test('caller header casing cannot replace scoped Bearer, follow redirects, or send cross-origin cookies', async () => {
  let sent;
  const request = createRequest({origin, credential: () => 'scoped-token',
    fetchImpl: async (url, options) => { sent = options; return json({}); }});
  await request('/state', {headers: new Headers({'authorization': 'Bearer foreign', 'X-Trace': 'local'}),
    credentials: 'include', redirect: 'follow'});
  assert.equal(new Headers(sent.headers).get('Authorization'), 'Bearer scoped-token');
  assert.equal(new Headers(sent.headers).get('X-Trace'), 'local');
  assert.equal(sent.credentials, 'same-origin');
  assert.equal(sent.redirect, 'error');
});

test('anonymous scope removes caller-provided Authorization', async () => {
  const request = createRequest({origin, credential: () => '', fetchImpl: async (url, options) => {
    assert.equal(new Headers(options.headers).get('Authorization'), null);
    return json({});
  }});
  await request('/pair', {headers: {Authorization: 'Bearer foreign'}});
});

test('HTTP errors are returned once for the service adapter to interpret', async () => {
  let sends = 0;
  const request = createRequest({origin, fetchImpl: async () => { sends++; return json({error: {code: 'DENIED'}}, 403); }});
  assert.deepEqual(await request('/write', {method: 'POST'}),
    {status: 403, ok: false, body: {error: {code: 'DENIED'}}});
  assert.equal(sends, 1);
});

test('204 and non-JSON success keep status and use a null body', async () => {
  const queue = [new Response(null, {status: 204}), new Response('not JSON', {status: 200})];
  const request = createRequest({origin, fetchImpl: async () => queue.shift()});
  assert.deepEqual(await request('/empty'), {status: 204, ok: true, body: null});
  assert.deepEqual(await request('/text'), {status: 200, ok: true, body: null});
});

test('network failure is propagated without replaying a write', async () => {
  const failure = new TypeError('connection lost');
  let sends = 0;
  const request = createRequest({origin, fetchImpl: async () => { sends++; throw failure; }});
  await assert.rejects(request('/write', {method: 'POST'}), error => error === failure);
  assert.equal(sends, 1);
});

test('already aborted parent does not fetch or read credential', async () => {
  const parent = new AbortController();
  parent.abort();
  let credentials = 0;
  let sends = 0;
  const request = createRequest({origin, credential: () => { credentials++; return 'core-one'; },
    fetchImpl: async () => { sends++; return json({}); }});
  await assert.rejects(request('/write', {method: 'POST', signal: parent.signal}), {name: 'AbortError'});
  assert.equal(credentials, 0);
  assert.equal(sends, 0);
});

test('timeout aborts the in-flight fetch once', async () => {
  let signal;
  let sends = 0;
  const request = createRequest({origin, fetchImpl: async (url, options) => {
    sends++;
    signal = options.signal;
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), {once: true}));
  }});
  await assert.rejects(request('/write', {method: 'POST', timeoutMs: 5}), {name: 'AbortError'});
  assert.equal(signal.aborted, true);
  assert.equal(sends, 1);
});

test('parent abort and timeout compose without replacing the parent lifetime', async () => {
  const parent = new AbortController();
  let signal;
  const request = createRequest({origin, fetchImpl: async (url, options) => {
    signal = options.signal;
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), {once: true}));
  }});
  const pending = request('/state', {signal: parent.signal, timeoutMs: 10_000});
  parent.abort();
  await assert.rejects(pending, {name: 'AbortError'});
  assert.equal(signal.aborted, true);
});

test('aborted scope cannot accept a late fetch result even if the fetch double ignores abort', async () => {
  const parent = new AbortController();
  let finish;
  const request = createRequest({origin, fetchImpl: () => new Promise(resolve => { finish = resolve; })});
  const pending = request('/state', {signal: parent.signal});
  parent.abort();
  finish(json({stale: true}));
  await assert.rejects(pending, {name: 'AbortError'});
});

test('response body cancellation is not swallowed as an invalid JSON body', async () => {
  const parent = new AbortController();
  let finish;
  const request = createRequest({origin, fetchImpl: async () => ({status: 200, ok: true,
    json: () => new Promise(resolve => { finish = resolve; })})});
  const pending = request('/state', {signal: parent.signal});
  await Promise.resolve();
  parent.abort();
  finish({stale: true});
  await assert.rejects(pending, {name: 'AbortError'});
});

test('settled request removes its parent listener', async () => {
  const parent = new AbortController();
  const add = parent.signal.addEventListener.bind(parent.signal);
  const remove = parent.signal.removeEventListener.bind(parent.signal);
  let listeners = 0;
  parent.signal.addEventListener = (...args) => { listeners++; add(...args); };
  parent.signal.removeEventListener = (...args) => { listeners--; remove(...args); };
  const request = createRequest({origin, fetchImpl: async () => json({done: true})});
  await request('/state', {signal: parent.signal, timeoutMs: 10_000});
  assert.equal(listeners, 0);
});

test('browser default origin is resolved when the client is constructed', async () => {
  const before = globalThis.location;
  globalThis.location = {origin};
  try {
    const request = createRequest({fetchImpl: async url => {
      assert.equal(new URL(url).origin, origin);
      return json({});
    }});
    await request('/state');
  } finally { globalThis.location = before; }
});

for (const timeoutMs of [-1, Infinity, NaN]) {
  test(`invalid timeout is rejected: ${timeoutMs}`, async () => {
    let sends = 0;
    const request = createRequest({origin, fetchImpl: async () => { sends++; return json({}); }});
    await assert.rejects(request('/state', {timeoutMs}), /timeout/);
    assert.equal(sends, 0);
  });
}

test('custom response reader preserves its result and the HTTP envelope', async () => {
  const request = createRequest({origin, fetchImpl: async () => new Response('plain text'),
    readResponse: response => response.text()});
  assert.deepEqual(await request('/state'), {status: 200, ok: true, body: 'plain text'});
});

test('custom header-first denial preserves the error without reading or replaying a write', async () => {
  const parent = new AbortController();
  const failure = Object.assign(new Error('service denied'), {status: 403});
  let reads = 0, sends = 0, listeners = 0;
  const add = parent.signal.addEventListener.bind(parent.signal);
  const remove = parent.signal.removeEventListener.bind(parent.signal);
  parent.signal.addEventListener = (...args) => { listeners++; add(...args); };
  parent.signal.removeEventListener = (...args) => { listeners--; remove(...args); };
  const request = createRequest({origin, fetchImpl: async () => {
    sends++;
    return {status: 403, ok: false, json: async () => { reads++; return {}; }};
  }, readResponse: response => {
    if (!response.ok) throw failure;
    return response.json();
  }});
  await assert.rejects(request('/write', {method: 'POST', signal: parent.signal, timeoutMs: 10_000}),
    error => error === failure);
  assert.equal(reads, 0);
  assert.equal(sends, 1);
  assert.equal(listeners, 0);
});

for (const [status, body] of [[200, 'not JSON'], [200, ''], [204, null]]) {
  test(`strict response reader propagates invalid JSON for ${status}/${body}`, async () => {
    let reads = 0;
    const request = createRequest({origin, fetchImpl: async () => new Response(body, {status}),
      readResponse: response => { reads++; return response.json(); }});
    await assert.rejects(request('/write', {method: 'POST'}), SyntaxError);
    assert.equal(reads, 1);
  });
}

for (const timeout of [false, true]) {
  test(`custom body reader remains inside ${timeout ? 'timeout' : 'parent cancellation'}`, async () => {
    const parent = new AbortController();
    let finish;
    const request = createRequest({origin, fetchImpl: async () => json({}),
      readResponse: () => new Promise(resolve => { finish = resolve; })});
    const pending = request('/state', {signal: parent.signal, timeoutMs: timeout ? 5 : 0});
    await Promise.resolve();
    assert.equal(typeof finish, 'function');
    if (timeout) await new Promise(resolve => setTimeout(resolve, 20));
    else parent.abort();
    finish({late: true});
    await assert.rejects(pending, {name: 'AbortError'});
  });
}

test('default binary reader still returns the blob and response headers', async () => {
  const response = new Response(new Uint8Array([1, 2, 3]), {headers: {'Content-Type': 'image/png'}});
  const request = createRequest({origin, fetchImpl: async () => response});
  const result = await request('/image', {blob: true});
  assert.equal(result.body.headers.get('Content-Type'), 'image/png');
  assert.deepEqual(new Uint8Array(await result.body.blob.arrayBuffer()), new Uint8Array([1, 2, 3]));
});
