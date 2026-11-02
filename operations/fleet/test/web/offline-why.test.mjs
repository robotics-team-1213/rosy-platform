import test from 'node:test';
import assert from 'node:assert/strict';
import { offlineWhy } from '../../../../applications/fleet/web/roster-presentation.js';

test("Fleet's own hold is not shown as a robot refusal or as unreachable", () => {
  const held = { held: true, reachable: null, code: 'ADDRESS_UNVERIFIED' };
  assert.equal(offlineWhy({ held: 'needs_new_code', error: held }),
    'Fleet이 정지 요청만 보냄 · 등록 자격 만료 · 로봇 화면의 새 코드로 다시 등록');
  assert.match(offlineWhy({ held: 'address_changed', error: held }), /주소 바뀜/);
  assert.equal(offlineWhy({ held: null, error: held }), 'Fleet이 정지 요청만 보냄 · 주소 미확인');
  assert.equal(offlineWhy({ error: { reachable: true, code: 'X' } }), '로봇이 거절: X');
  assert.equal(offlineWhy({ error: { reachable: false, code: 'ConnectError' } }), '닿지 않음: 접속 실패');
});
