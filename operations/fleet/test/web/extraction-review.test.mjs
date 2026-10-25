import {test} from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {createExtractionReview} from '/console/assets/extraction-review.js';
globalThis.crypto ??= webcrypto;

const hash = 'b'.repeat(64), asset = 'a'.repeat(64), extraction = 'c'.repeat(64);
const projection = {kind: 'raster', projection_sha256: hash, asset_sha256: asset,
  transform: {source_origin_px: [0, 0], map_origin_m: [0, 0], heading_rad: 0, meters_per_pixel: .01}};
const initial = () => ({map_id: 'generic', drawing: {asset_sha256: asset, projection_sha256: hash},
  places: [], edges: [], survey: {revision: hash, reviewed: false}});
const result = {projection_sha256: hash, asset_sha256: asset, extraction_sha256: extraction,
  candidates: [{candidate_id: 'candidate', closed: false, geometry_px: [[0, 0], [100, 0]]}]};

test('candidate preview is read only; explicit acceptance records provenance as one draft change', async () => {
  let draft = initial(), changes = 0;
  const before = draft;
  const review = createExtractionReview({context: () => ({draft, epoch: 1, projection, reason: ''}),
    changed: next => { draft = next; changes++; }, request: async (path, init) =>
      path.endsWith('/extractions') ? result : JSON.parse(init.body)});
  await review.run({method: 'lines', crop_px: [0, 0, 160, 120]});
  assert.equal(draft, before);
  review.select('candidate');
  review.update([[0, 0], [90, 0]]);
  await review.accept({kind: 'stop_line', name: '선택한 선'});
  assert.equal(changes, 1);
  assert.deepEqual(draft.facilities[0].geometry, [[0, 0], [.9, 0]]);
  assert.match(draft.facilities[0].evidence.note, new RegExp(extraction));
  assert.equal(draft.survey.reviewed, false);
  assert.equal(review.state().result, null);
});

test('late extraction, changed draft, expired session and canceled validation cannot overwrite edits', async () => {
  let draft = initial(), epoch = 1, resolve, changed = false;
  const review = createExtractionReview({context: () => ({draft, epoch, projection, reason: ''}),
    changed: () => { changed = true; }, request: () => new Promise(done => { resolve = done; })});
  const pending = review.run({method: 'lines', crop_px: [0, 0, 160, 120]});
  draft = {...draft}; resolve(result);
  await assert.rejects(pending, /바뀌|다시/);
  const fresh = review.run({method: 'lines', crop_px: [0, 0, 160, 120]}); resolve(result); await fresh;
  review.select('candidate');
  const accepted = review.accept({kind: 'stop_line', name: 'line'});
  epoch++; resolve({map: draft});
  await assert.rejects(accepted, /바뀌|다시/);
  assert.equal(changed, false);
  review.cancel();
  assert.equal(review.state().result, null);
});

test('canceling a pending validation keeps the draft unchanged', async () => {
  const draft = initial(); let release, changed = false;
  const review = createExtractionReview({context: () => ({draft, epoch: 1, projection, reason: ''}),
    changed: () => { changed = true; }, request: async path => path.endsWith('/extractions') ? result
      : new Promise(done => { release = done; })});
  await review.run({method: 'lines', crop_px: [0, 0, 160, 120]}); review.select('candidate');
  const pending = review.accept({kind: 'stop_line', name: 'line'});
  review.cancel(); release({map: draft});
  await assert.rejects(pending, /바뀌|다시/);
  assert.equal(changed, false);
});
