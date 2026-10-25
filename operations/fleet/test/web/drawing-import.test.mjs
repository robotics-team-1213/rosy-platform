import {test} from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {createDrawingImport, copyMapTemplate} from '/console/assets/drawing-import.js';
globalThis.crypto ??= webcrypto;

const transform = {plane: 'xy', unit: 'm', source_origin: [0, 0], map_origin_m: [0, 0], heading_rad: 0, scale: 1};
const reference = {measured_distance_m: 1, description: 'measured baseline'};
const asset = 'a'.repeat(64), hash = 'b'.repeat(64);
const result = {asset_sha256: asset, projection_sha256: hash};
const source = () => ({map_id: 'old-site', places: [{id: 'a', x: 4, y: 5}],
  edges: [{id: 'ab', polyline: [[4, 5], [6, 7]], evidence: {source: 'camera', status: 'reviewed', note: 'old'}}]});

test('raster registration uses normalized pixels and explicit content type', async () => {
  let map = source(), uploaded;
  const importer = createDrawingImport({map: () => map, replaceDraft: next => { map = next; },
    confirmDiscard: async () => true, request: async (path, init) => {
      if (path.endsWith('/projections')) return {...result, kind: 'raster'};
      uploaded = init.headers['Content-Type'];
      return {asset_sha256: asset, format: 'png', width_px: 100, height_px: 50};
    }});
  await importer.load({size: 5, type: 'image/png'});
  assert.equal(uploaded, 'image/png');
  await importer.register({source_origin_px: [0, 0], map_origin_m: [2, 3], heading_rad: 0,
    meters_per_pixel: .02}, reference);
  assert.deepEqual(map.survey.origin, [2, 3]);
  assert.equal(map.survey.reviewed, false);
  assert.notEqual(map.map_id, 'old-site');
});

test('registration preserves geometry and starts a fresh site frame and review', async () => {
  const original = source(); let map = original;
  const importer = createDrawingImport({map: () => map, replaceDraft: next => { map = next; },
    confirmDiscard: async () => true, request: async path => path.endsWith('/projections') ? result : {asset_sha256: asset}});
  await importer.load({size: 1});
  await importer.register(transform, reference);
  assert.notEqual(map.map_id, original.map_id);
  assert.deepEqual(map.places, original.places);
  assert.deepEqual(map.edges[0].polyline, original.edges[0].polyline);
  assert.equal(map.survey.reviewed, false);
  assert.equal(map.survey.revision, hash);
  assert.equal(map.edges[0].evidence.status, 'observed');
  assert.equal(original.edges[0].evidence.status, 'reviewed');
  const copy = copyMapTemplate({...map, survey: {...map.survey, reviewed: true, review_note: 'old'}});
  assert.notEqual(copy.map_id, map.map_id);
  assert.equal(copy.survey.reviewed, false);
  assert.equal(copy.survey.review_note, '');
});

test('late projection and declined replacement cannot overwrite another edit', async () => {
  let map = source(), finish;
  const importer = createDrawingImport({map: () => map, replaceDraft: next => { map = next; },
    confirmDiscard: async () => true,
    request: async path => path.endsWith('/projections') ? new Promise(resolve => { finish = resolve; }) : {asset_sha256: asset}});
  await importer.load({size: 1});
  const pending = importer.register(transform, reference);
  await Promise.resolve();
  const edited = {...map, map_id: 'another-edit'}; map = edited;
  finish(result);
  await assert.rejects(pending, /다시 확인/);
  assert.equal(map, edited);
  let replaced = false;
  const declined = createDrawingImport({map: () => map, replaceDraft: () => { replaced = true; },
    confirmDiscard: async () => false, request: async () => ({asset_sha256: asset})});
  await declined.load({size: 1});
  assert.equal(await declined.register(transform, reference), null);
  assert.equal(replaced, false);
});

test('a late first upload cannot replace the second input adapter result', async () => {
  let finish, calls = 0, map = null, projectionSource;
  const second = 'c'.repeat(64);
  const importer = createDrawingImport({map: () => map, replaceDraft: next => { map = next; },
    confirmDiscard: async () => true, request: async path => {
      if (path.endsWith('/projections')) { projectionSource = path; return {...result, asset_sha256: second}; }
      return ++calls === 1 ? new Promise(resolve => { finish = resolve; }) : {asset_sha256: second};
    }});
  const first = importer.load({size: 1});
  await importer.load({size: 1});
  finish({asset_sha256: asset});
  assert.equal(await first, null);
  await importer.register(transform, reference);
  assert.ok(projectionSource.includes(second));
  assert.equal(map.drawing.asset_sha256, second);
});

test('editing registration fields does not cancel an independent source upload', async () => {
  let finish, map = null;
  const importer = createDrawingImport({map: () => map, replaceDraft: next => { map = next; },
    confirmDiscard: async () => true, request: async path => path.endsWith('/projections')
      ? result : new Promise(resolve => { finish = resolve; })});
  const loading = importer.load({size: 1});
  importer.cancelRegistration();
  finish({asset_sha256: asset});
  assert.deepEqual(await loading, {asset_sha256: asset});
  await importer.register(transform, reference);
  assert.equal(map.drawing.asset_sha256, asset);
});
