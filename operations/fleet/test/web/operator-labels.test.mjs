// D-540 6: the console's lane-follow, formation and mode words come from one table (core_ui_logic.js).
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  FORMATION_SHAPE_LABEL, FORMATION_STATE_LABEL, LINE_FOLLOW_MODE_LABEL, LINE_STATE_LABEL, enumLabel, operatorModeLabel,
} from '../../../../shared/web/core_ui_logic.js';

const RAW = /\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b|\b(?:IDLE|RUNNING|HOLDING|COLUMN|GRID|CIRCLE|TRAIL|FOLLOW|TRACKING|WAITING|LOST)\b/;

test('every formation shape the Fleet geometry knows has operator words', () => {
  // fleet/formation/geometry.py Formation
  for (const shape of ['FOLLOW', 'COLUMN', 'LINE', 'V', 'GRID', 'CIRCLE', 'TRAIL']) {
    assert.ok(Object.hasOwn(FORMATION_SHAPE_LABEL, shape), shape);
  }
  // fleet/swarm/session.py SessionState
  for (const state of ['IDLE', 'ARMING', 'RUNNING', 'HOLDING', 'STOPPED']) {
    assert.ok(Object.hasOwn(FORMATION_STATE_LABEL, state), state);
  }
  assert.equal(enumLabel(FORMATION_STATE_LABEL, 'HOLDING'), '멈춤 · 재개 대기');
});

test('lane following is one word on every surface: 차선 추종', () => {
  for (const mode of ['CAMERA_LINE', 'IR_LINE', 'OFF']) assert.match(LINE_FOLLOW_MODE_LABEL[mode], /차선 추종/);
  assert.equal(operatorModeLabel('LINE_FOLLOW'), '차선 추종');
  assert.equal(enumLabel(LINE_STATE_LABEL, 'TRACKING'), '추종 중');
});

test('no operator word in these tables is a raw enum or English', () => {
  for (const table of [FORMATION_SHAPE_LABEL, FORMATION_STATE_LABEL, LINE_FOLLOW_MODE_LABEL, LINE_STATE_LABEL]) {
    for (const [key, word] of Object.entries(table)) {
      assert.doesNotMatch(word, RAW, `${key} → ${word}`);
      assert.doesNotMatch(word, /line-follow|motion|leader|follower/i, `${key} → ${word}`);
    }
  }
  assert.equal(enumLabel(FORMATION_SHAPE_LABEL, 'NEW_SHAPE'), 'NEW_SHAPE');  // unknown stays visible
});
