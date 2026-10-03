import test from 'node:test';
import assert from 'node:assert/strict';
import {createFleetClient} from '../../../../hmi/web_common/fleet-client.js';
import {createPollGate} from '../../fleet/server/web/poll-gate.js';

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
    error.status === 401 && error.message === '관제 토큰이 필요합니다 — 상단에 입력하고 접속을 누르세요');
  assert.equal(calls.length, 1);
});

for (const [body, message, code] of [
  [{detail: {message: 'operator required', code: 'OPERATOR_REQUIRED'}}, 'operator required', 'OPERATOR_REQUIRED'],
  [{detail: {code: 'NOT_FOUND'}}, 'NOT_FOUND', 'NOT_FOUND'],
  [{detail: 'unavailable'}, 'HTTP 503', undefined],
  [null, 'HTTP 503', undefined],
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
