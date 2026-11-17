import test from 'node:test';
import assert from 'node:assert/strict';
import {createFleetClient} from '../../../../shared/web/fleet-client.js';
import {createPollGate} from '../../../../applications/fleet/web/shared/poll-gate.js';

function clientFor(status, body) {
  const calls = [];
  const client = createFleetClient({origin: 'https://fleet.test', credential: () => 'fleet-token',
    fetchImpl: async (url, options) => {
      calls.push({url, options});
      return new Response(status === 204 ? null : JSON.stringify(body), {status});
    }});
  return {client, calls};
}

test('success and empty bodies retain the Console contract', async () => {
  const {client, calls} = clientFor(200, {robots: []});
  assert.deepEqual(await client('/api/fleet/state'), {robots: []});
  assert.equal(new Headers(calls[0].options.headers).get('Authorization'), 'Bearer fleet-token');
  assert.equal(await clientFor(204, null).client('/api/fleet/state'), null);
});

test('401 retains the login message and exposes status for the document lock', async () => {
  const {client, calls} = clientFor(401, {detail: 'unauthorized'});
  await assert.rejects(client('/api/fleet/state'), error =>
    error.status === 401 && error.message === '관제 인증이 필요합니다 — 로그인하거나 고급 접속을 확인하세요');
  assert.equal(calls.length, 1);
});

for (const [body, message, code] of [
  [{detail: {message: 'operator required', code: 'OPERATOR_REQUIRED'}}, 'operator required', 'OPERATOR_REQUIRED'],
  [{detail: {code: 'NOT_FOUND'}}, 'NOT_FOUND', 'NOT_FOUND'],
  [{detail: 'unavailable'}, '관제 서버 응답을 확인하지 못했습니다. 연결을 확인한 뒤 현재 상태를 다시 조회하세요.', undefined],
  [null, '관제 서버 응답을 확인하지 못했습니다. 연결을 확인한 뒤 현재 상태를 다시 조회하세요.', undefined],
]) {
  test(`Fleet detail interpretation: ${message}`, async () => {
    const {client, calls} = clientFor(503, body);
    await assert.rejects(client('/api/fleet/estop', {method: 'POST'}), error =>
      error.status === 503 && error.code === code && error.message === message);
    assert.equal(calls.length, 1, 'commands must never be replayed');
  });
}

test('404 disables optional polling until the owner resets its gate', async () => {
  const {client} = clientFor(404, {detail: 'Not Found'});
  const gate = createPollGate();
  try { await client('/api/fleet/discovery'); }
  catch (error) { assert.equal(gate.fail(error.status, error.code), 'absent'); }
  assert.equal(gate.due(), false);
  gate.reset();
  assert.equal(gate.due(), true);
});

test('credential is read per request and never sent to another origin', async () => {
  let token = 'old';
  const seen = [];
  const client = createFleetClient({origin: 'https://fleet.test', credential: () => token,
    fetchImpl: async (_url, options) => {
      seen.push(new Headers(options.headers).get('Authorization'));
      return new Response('{}');
    }});
  await client('/api/fleet/session');
  token = 'new';
  await client('/api/fleet/session');
  await assert.rejects(client('https://robot.test/api/v1/teleop'), /origin/);
  assert.deepEqual(seen, ['Bearer old', 'Bearer new']);
});

test('abort propagates without being converted to an authentication failure', async () => {
  const controller = new AbortController();
  controller.abort();
  let sent = 0;
  const client = createFleetClient({origin: 'https://fleet.test',
    fetchImpl: async () => { sent += 1; return new Response('{}'); }});
  await assert.rejects(client('/api/fleet/estop', {method: 'POST', signal: controller.signal}),
    {name: 'AbortError'});
  assert.equal(sent, 0);
});

test('lost network explains readback and never replays a command', async () => {
  let sent = 0;
  const failure = new TypeError('Failed to fetch');
  const client = createFleetClient({origin: 'https://fleet.test',
    fetchImpl: async () => { sent += 1; throw failure; }});
  await assert.rejects(client('/api/fleet/estop', {method: 'POST'}), error =>
    error === failure && /관제 연결을 확인하지 못했습니다/.test(error.message)
      && /현재 상태를 다시 조회/.test(error.message) && error.status === undefined);
  assert.equal(sent, 1);
});

test('null abort reason remains the original cancellation without sending', async () => {
  const controller = new AbortController();
  controller.abort(null);
  let sent = 0;
  const client = createFleetClient({origin: 'https://fleet.test',
    fetchImpl: async () => { sent += 1; return new Response('{}'); }});
  await assert.rejects(client('/api/fleet/estop', {method: 'POST', signal: controller.signal}),
    reason => reason === null);
  assert.equal(sent, 0);
});

for (const failure of [Object.freeze(new TypeError('Failed to fetch')),
  new DOMException('NetworkError when attempting to fetch resource.', 'NetworkError')]) {
  test(`immutable ${failure.name} remains the original network failure without replay`, async () => {
    let sent = 0;
    const client = createFleetClient({origin: 'https://fleet.test',
      fetchImpl: async () => { sent += 1; throw failure; }});
    await assert.rejects(client('/api/fleet/estop', {method: 'POST'}), reason => reason === failure);
    assert.equal(sent, 1);
  });
}

test('401 preserves detail/code and top-level {code, message} errors expose code and message', async () => {
  const {client: c401} = clientFor(401, {detail: {code: 'SESSION_EXPIRED', detail: 're-login'}});
  await assert.rejects(c401('/api/fleet/state'), error =>
    error.status === 401
    && error.code === 'SESSION_EXPIRED'
    && error.detail === 're-login'
    && error.message === '관제 인증이 필요합니다 — 로그인하거나 고급 접속을 확인하세요');

  const {client: c422} = clientFor(422, {code: 'INVALID_SETTING', message: 'out of range'});
  await assert.rejects(c422('/api/fleet/admin/db-settings', {method: 'PUT'}), error =>
    error.status === 422
    && error.code === 'INVALID_SETTING'
    && error.message === 'out of range');

  const {client: c422List} = clientFor(422, {detail: [{loc: ['body', 'workcell_id'], msg: 'Field required'}]});
  await assert.rejects(c422List('/api/fleet/arm-transfers/jobs', {method: 'POST'}), error =>
    error.status === 422
    && error.message === 'workcell_id: Field required'
    && Array.isArray(error.detail)
    && error.detail[0].msg === 'Field required');

  const {client: c409Str} = clientFor(409, {detail: 'ARM_BUSY_CONFLICT'});
  await assert.rejects(c409Str('/api/fleet/arm-transfers/jobs', {method: 'POST'}), error =>
    error.status === 409
    && error.message === 'ARM_BUSY_CONFLICT'
    && error.detail === 'ARM_BUSY_CONFLICT');
});
