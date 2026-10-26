import test from 'node:test';
import assert from 'node:assert/strict';
import {loginReturn, loginHref} from '../../../../applications/fleet/web/shared/login-return.js';

const origin = 'https://fleet.test';
test('neutral ARM login handoff preserves exactly one bounded job ID in the work document', () => {
  const id = 'arm:' + 'x'.repeat(188);
  const target = '/console?view=work&arm_transfer=' + encodeURIComponent(id);
  assert.equal(loginReturn(target, origin), target);
  assert.equal(loginHref({origin, href: origin + target}), '/console/login?return=' + encodeURIComponent(target));
  for (const suffix of ['arm_transfer=x&arm_transfer=y', 'arm_transfer=../secret', 'arm_transfer=' + id + 'x']) {
    assert.equal(loginReturn('/console?view=work&' + suffix, origin), '/console?view=work');
  }
  assert.equal(loginReturn('/console?view=records&arm_transfer=x', origin), '/console?view=records');
});
test('Account authorization returns preserve only bounded protocol fields on this origin', () => {
  const target = '/api/fleet/auth/authorize?response_type=code&client_id=pilot&redirect_uri=https%3A%2F%2Frobot.test%2Fcallback&scope=robot%3Ar1&state=s&code_challenge=' + 'x'.repeat(43) + '&code_challenge_method=S256';
  assert.equal(loginReturn(target, origin), target);
  assert.equal(loginReturn(target + '&token=secret', origin), '/console');
  assert.equal(loginReturn('/console/accounts', origin), '/console/accounts');
  assert.equal(loginReturn('https://evil.test' + target, origin), '/console');
});
test('return restores Fleet documents and existing work/inbox readers', () => {
  for (const path of ['/console', '/console/install', '/console/site-map', '/console/cell']) {
    assert.equal(loginReturn(path, origin), path);
  }
  assert.equal(loginReturn('/console?view=work&inbox=1', origin), '/console?view=work&inbox=1');
  assert.equal(loginReturn('/console?view=work&show=pending', origin), '/console?view=work&show=pending');
  assert.equal(loginReturn('/console?view=records&show=facts', origin), '/console?view=records&show=facts');
  assert.equal(loginReturn('/console?view=work&show=new', origin), '/console?view=work&show=new');  // D-763 새 작업
  assert.equal(loginReturn('/console?show=done', origin), '/console');
  assert.equal(loginReturn('/console?view=work&show=__proto__', origin), '/console?view=work');
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
