import test from 'node:test';
import assert from 'node:assert/strict';
import {analysisText} from '../../../../applications/fleet/web/devices/robot-profile-view.js';

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
