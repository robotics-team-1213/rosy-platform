import {test} from 'node:test';
import assert from 'node:assert/strict';

// /console/assets 절대 경로 import 를 단독 node --test 에서도 풀도록 로더를 먼저 건다.
const { register } = await import('node:module');
register('./resolve-console-assets.mjs', import.meta.url);
const geometry = await import('/console/assets/geometry-edit.js');

test('explicit split and join preserve inputs and reject invented connections', () => {
  const line = [[0, 0], [2, 0], [3, 1]];
  const [a, b] = geometry.splitPolyline(line, 0, [1, 0]);
  assert.deepEqual(a, [[0, 0], [1, 0]]);
  assert.deepEqual(b, [[1, 0], [2, 0], [3, 1]]);
  const combined = [[0, 0], [1, 0], [2, 0], [3, 1]];
  assert.deepEqual(geometry.joinPolylines(a, b), combined);
  assert.deepEqual(geometry.joinPolylines([...a].reverse(), b, true), combined);
  assert.deepEqual(line, [[0, 0], [2, 0], [3, 1]]);
  assert.throws(() => geometry.splitPolyline(line, 0, [1, 1]));
  assert.throws(() => geometry.splitPolyline(line, 0, [0, 0]));
  assert.throws(() => geometry.joinPolylines(a, [[1.01, 0], [2, 0]]));
  assert.throws(() => geometry.joinPolylines([[0, 0], [0, 0]], b));
  assert.throws(() => geometry.splitPolyline(line, 8, [NaN, 0]));
});

test('snap distance is measured in screen pixels with no ambiguous tie', () => {
  assert.equal(geometry.nearestVertex([10, 10], [[17, 10], [30, 10]]), 0);
  assert.equal(geometry.nearestVertex([10, 10], [[19, 10]]), null);
  assert.equal(geometry.nearestVertex([10, 10], [[9, 10], [11, 10]]), null);
  assert.equal(geometry.nearestVertex([10, 10], []), null);
  assert.throws(() => geometry.nearestVertex([10, 10], [[NaN, 0]]));
  assert.throws(() => geometry.nearestVertex([0, 0], [], Infinity));
});
