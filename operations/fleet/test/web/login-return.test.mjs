import test from 'node:test';
import assert from 'node:assert/strict';
import {loginReturn, loginHref} from '../../../site_ui/console/shared/login-return.js';

const origin = 'https://fleet.test';
test('return restores Fleet documents and existing work/inbox readers', () => {
  for (const path of ['/console', '/console/install', '/console/site-map', '/console/cell']) {
    assert.equal(loginReturn(path, origin), path);
  }
  assert.equal(loginReturn('/console?view=work&inbox=1', origin), '/console?view=work&inbox=1');
});
test('return rejects external destinations credentials login loops and unknown paths', () => {
  for (const path of ['https://other.test/console', '//other.test/console',
    'https://user:password@fleet.test/console', '/console/login', '/pilot', '/console/../login']) {
    assert.equal(loginReturn(path, origin), '/console');
  }
});
test('return strips unrecognized query and fragment data', () => {
  assert.equal(loginReturn('/console?token=secret&view=inbox#password', origin), '/console');
  assert.equal(loginReturn('/console/cell?return=https://other.test&inbox=1', origin), '/console/cell');
  assert.equal(loginHref({origin, href: origin + '/console?view=work'}),
    '/console/login?return=%2Fconsole%3Fview%3Dwork');
});
test('profile return preserves one allowed work destination and rejects nested loops', () => {
  assert.equal(loginReturn('/console/profile?return=%2Fconsole%3Fview%3Dwork', origin),
    '/console/profile?return=%2Fconsole%3Fview%3Dwork');
  for (const back of ['https://other.test/console', '/console/profile?return=/console/profile', '/console/login']) {
    assert.equal(loginReturn('/console/profile?return=' + encodeURIComponent(back), origin),
      '/console/profile?return=%2Fconsole');
  }
});
