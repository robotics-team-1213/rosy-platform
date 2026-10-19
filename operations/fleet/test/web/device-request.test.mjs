import test from 'node:test';
import assert from 'node:assert/strict';

test('device transport preserves complete Fleet error detail and current credentials', async () => {
  const {createDeviceRequest} = await import('../../../site_ui/console/shared/device-request.js');
  const originalFetch = globalThis.fetch, originalLocation = globalThis.location;
  const detail = {code: 'CONFLICT', message: 'retained', detail: {revision: 3}, request_id: 'request'};
  const seen = [];
  let token = 'first';
  globalThis.location = {origin: 'https://fleet.test'};
  globalThis.fetch = async (url, options) => {
    seen.push({url, options});
    return new Response(JSON.stringify({detail}), {status: 409});
  };
  try {
    const request = createDeviceRequest({headers: () => ({Authorization: `Bearer ${token}`}),
      scope: {capture: () => ({check() {}, signal: new AbortController().signal})}});
    token = 'current';
    const result = await request('/api/fleet/pairing/v2/requests', {method: 'POST', body: {action: 'approve'}});
    assert.equal(result.status, 409);
    assert.equal(result.ok, false);
    assert.deepEqual(result.body.detail, detail);
    assert.equal(new Headers(seen[0].options.headers).get('Authorization'), 'Bearer current');
    assert.equal(seen[0].options.body, '{"action":"approve"}');
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.location = originalLocation;
  }
});
