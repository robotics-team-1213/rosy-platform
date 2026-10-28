import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../../../../applications/fleet/web/calibration/measured-calibration-view.js', import.meta.url), 'utf8');
const {isMeasuredFrame} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const valid = {'Content-Type':'image/jpeg', 'X-Frame-Rectified':'measured-map',
  'X-Frame-Calibration':'measured-current', 'X-Frame-Session':'boot:2'};

test('only the requested measured revision and current camera session can be displayed', () => {
  assert.equal(isMeasuredFrame(new Headers(valid), 'measured-current', 'boot:2'), true);
  for (const [key,value] of [['X-Frame-Rectified','map'], ['X-Frame-Rectified','false'],
    ['X-Frame-Calibration','old'], ['X-Frame-Session','boot:1'], ['Content-Type','text/html']]) {
    assert.equal(isMeasuredFrame(new Headers({...valid,[key]:value}), 'measured-current', 'boot:2'), false);
  }
});
