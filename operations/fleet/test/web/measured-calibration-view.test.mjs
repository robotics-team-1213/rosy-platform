import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const causeLine = new URL('../../../../shared/web/cause-line.js', import.meta.url);
const auth = new URL('../../../../applications/fleet/web/shared/authorization.js', import.meta.url);
const source = readFileSync(new URL('../../../../applications/fleet/web/calibration/measured-calibration-view.js', import.meta.url), 'utf8')
  .replaceAll('/common/cause-line.js', causeLine.href)
  .replaceAll('/console/assets/authorization.js', auth.href);
const {createMeasuredCalibrationView,isMeasuredFrame} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const valid = {'Content-Type':'image/jpeg', 'X-Frame-Rectified':'measured-map',
  'X-Frame-Calibration':'measured-current', 'X-Frame-Session':'boot:2'};

test('only the requested measured revision and current camera session can be displayed', () => {
  assert.equal(isMeasuredFrame(new Headers(valid), 'measured-current', 'boot:2'), true);
  for (const [key,value] of [['X-Frame-Rectified','map'], ['X-Frame-Rectified','false'],
    ['X-Frame-Calibration','old'], ['X-Frame-Session','boot:1'], ['Content-Type','text/html']]) {
    assert.equal(isMeasuredFrame(new Headers({...valid,[key]:value}), 'measured-current', 'boot:2'), false);
  }
});


test('tracking save uses the approved bundle and cannot use an uploaded candidate', async (t) => {
  const previousDocument = globalThis.document;
  const previousFetch = globalThis.fetch;
  const previousLocation = globalThis.location;
  globalThis.document = {getElementById: () => ({})};
  globalThis.location = new URL('http://console.test');
  globalThis.fetch = async () => Response.json({source_id:'camera',calibration_revision:'preview',state:'ready'});
  t.after(() => {
    globalThis.document = previousDocument;
    globalThis.fetch = previousFetch;
    globalThis.location = previousLocation;
  });

  const nodes = new Map(), handlers = new Map(), writes = [];
  const element = (id) => {
    if (!nodes.has(id)) {
      const attrs = new Map();
      nodes.set(id, {
        disabled:false, valueAsNumber:NaN, files:[],
        set value(value) { if (value === '') this.files = []; },
        dispatchEvent(event) { handlers.get(this)?.(event); },
        closest: () => ({hidden:false}),
        getAttribute: (key) => attrs.get(key) ?? null,
        setAttribute: (key,value) => attrs.set(key,value),
        removeAttribute: (key) => attrs.delete(key),
        hasAttribute: (key) => attrs.has(key),
        toggleAttribute: (key) => attrs.has(key) ? attrs.delete(key) : attrs.set(key,''),
      });
    }
    return nodes.get(id);
  };
  const physicalLens = {kind:'wide',focal_mm:2.2,hfov_deg:104.1};
  const bundle = {
    schema:'rosy.measured-calibration/1', source_id:'camera', map_id:'map', evidence_kind:'measured',
    capture:{signature:'capture',lens:physicalLens}, bounds_m:[-1,-1,1,1],
    lens:{image_size:[640,480],model:'pinhole',K:[[500,0,320],[0,500,240],[0,0,1]],D:[0,0,0,0]},
    floor:{undistorted_to_map:[[1,0,0],[0,1,0],[0,0,1]],validation:{p95_m:0.01,max_m:0.02}},
  };
  let saved = null, listingFailed = false;
  const view = createMeasuredCalibrationView({
    scope:{
      listen: (node,event,handler) => handlers.set(node,handler),
      capture: () => ({signal:new AbortController().signal,current:() => true,check() {}}),
      interval() {}, onResume() {}, onDispose() {},
    },
    root:{querySelector:element,closest:() => ({hidden:false})}, auth:{role:'operator',principal:'operator',token:'token'},
    visionView:{currentSource:() => 'camera'},
    call:async (path,opts) => {
      if (path.endsWith('?purpose=preview')) {
        if (listingFailed) throw new Error('Unavailable');
        return {use:'preview-only',calibrations:saved ? [saved] : []};
      }
      if (path.endsWith('/lease')) return {frame_path:'/api/vision/sources/camera/frame',lease:'token'};
      assert.equal(path,'/api/fleet/calibrations');
      const body = JSON.parse(opts.body);
      if (body.purpose === 'preview') {
        saved = {source_id:'camera',calibration_revision:'new-preview',persistent:true,bundle:body.bundle};
        return saved;
      }
      writes.push(body);
      return {calibration_revision:'tracking-new'};
    },
  });

  const upload = (value) => {
    const file = element('#measured-bundle');
    file.files = value ? [{size:1000,text:async () => JSON.stringify(value)}] : [];
    return handlers.get(file)();
  };
  const promote = element('#measured-promote');
  const firePromote = () => handlers.get(promote)();
  await view.refresh();
  await upload({...bundle,map_id:'unverified'});
  assert.equal(promote.disabled,true);
  await firePromote();
  assert.equal(writes.length,0);

  saved = {source_id:'camera',calibration_revision:'preview',persistent:true,bundle};
  await view.refresh();
  assert.equal(promote.disabled,true);
  await firePromote();
  assert.equal(writes.length,0);

  await upload({source_id:'another-camera'});
  assert.equal(promote.disabled,true);
  await firePromote();
  assert.equal(writes.length,0);

  await upload(null);
  assert.equal(promote.disabled,false);
  await firePromote();
  assert.equal(writes.length,1);
  assert.equal(writes[0].map_id,'map');
  assert.equal(writes[0].method,'measured');
  assert.deepEqual(writes[0].lens,physicalLens);
  assert.deepEqual(writes[0].lens_profile.K,bundle.lens.K);
  assert.deepEqual(writes[0].lens_profile.D,bundle.lens.D);
  assert.equal(element('#measured-state').textContent,'추적 보정 저장 완료 (tracking-new)');

  const current = saved;
  saved = null;
  await firePromote();
  assert.equal(writes.length,1);
  assert.equal(promote.disabled,true);

  saved = current;
  await view.refresh();
  saved = {...current,readback:{state:'invalid',reason:'map_changed'}};
  await firePromote();
  assert.equal(writes.length,1);
  assert.equal(promote.disabled,true);

  saved = current;
  await view.refresh();
  assert.equal(promote.disabled,false);
  listingFailed = true;
  await view.refresh();
  assert.equal(promote.disabled,true);
  await firePromote();
  assert.equal(writes.length,1);

  listingFailed = false;
  saved = {...current,readback:{state:'invalid',reason:'readback_stale'}};
  await view.refresh();
  assert.equal(promote.disabled,false);
  await firePromote();
  assert.equal(writes.length,2);

  await upload({...bundle,floor:{...bundle.floor,validation:{p95_m:0.015,max_m:0.02}}});
  element('#measured-p95').valueAsNumber = 0.02;
  element('#measured-max').valueAsNumber = 0.03;
  await handlers.get(element('#measured-approve'))();
  assert.equal(element('#measured-bundle').files.length,0);
  assert.equal(promote.disabled,false);
  await firePromote();
  assert.equal(writes.length,3);
  assert.equal(writes[2].metrics.p95_m,0.015);
});
