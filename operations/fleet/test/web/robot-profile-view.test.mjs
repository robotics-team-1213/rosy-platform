import test from 'node:test';
import assert from 'node:assert/strict';
import {analysisText, profileBindingMismatch} from '../../../../applications/fleet/web/devices/robot-profile-view.js';

test('captured evidence expires even when assessment is recent', () => {
  const report = {status: 'observing', reasons: [], fresh: true, age_s: .01, evidence_age_s: .19, max_age_s: .2};
  assert.match(analysisText(report, 0), /관측 중/);
  assert.match(analysisText(report, .02), /현재 상태 미확인/);
  assert.match(analysisText({...report, fresh: false}), /현재 상태 미확인/);
  assert.equal(analysisText(null), '최근 하중 분석 없음');
});

test('a newly assessed missing capture remains unknown without calling the assessment old', () => {
  const report = {status: 'hold_for_owner_review', reasons: ['feedback_gap'], fresh: false,
    age_s: 0, evidence_age_s: 1, max_age_s: .2};
  assert.match(analysisText(report), /근거 만료·누락/);
  assert.match(analysisText(report), /0초 전 분석/);
  assert.doesNotMatch(analysisText(report), /오래된 분석/);
});

test('a current Cell registration masks a cached profile from another owner or configuration', () => {
  const saved = {owner_id: 'arm-a', sha256: 'a'.repeat(64)};
  const profile = {source_binding: saved};
  assert.equal(profileBindingMismatch(profile, saved), null);
  assert.equal(profileBindingMismatch(profile, {...saved, owner_id: 'arm-b'}), 'owner_changed');
  assert.equal(profileBindingMismatch(profile, {...saved, sha256: 'b'.repeat(64)}), 'registration_changed');
  assert.equal(profileBindingMismatch({}, saved), 'unverified_link');
  assert.equal(profileBindingMismatch(profile, {owner_id: 'arm-a'}), 'unverified_link');
  assert.equal(profileBindingMismatch(profile, null), null);
});

test('a manifest mismatch cannot read as current observation even with a fresh timestamp', () => {
  const report = {status: 'observing', reasons: [], fresh: true, source_binding_status: 'owner_changed',
    age_s: 0, evidence_age_s: 0, max_age_s: 1};
  assert.match(analysisText(report), /관측원 연결 미확인/);
  assert.doesNotMatch(analysisText(report), /관측 중/);
});
