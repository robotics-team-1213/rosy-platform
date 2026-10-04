"""Camera evidence records only bounded operational events, never credentials."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


MODULE = Path(__file__).resolve().parents[3] / "hmi" / "web_common" / "evidence.js"  # D-323 T9 승격


def _run_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
const source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8');
const camera = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
{body}
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_only_known_operational_actions_enter_camera_evidence():
    events = _run_js("""
const {classifyOperation} = camera;
console.log(JSON.stringify([
  classifyOperation('POST', '/api/v1/mode', 200),
  classifyOperation('POST', '/api/v1/teleop', 200),
  classifyOperation('POST', '/api/v1/auth/pair', 201),
  classifyOperation('POST', '/api/v1/system/tokens', 200),
  classifyOperation('GET', '/api/v1/teleop', 200),
]));
""")
    assert events[:2] == [
        {"action": "운전 모드 변경", "result": "accepted"},
        {"action": "수동 운전", "result": "accepted"},
    ]
    assert events[2:] == [None, None, None]


def test_teleop_events_are_bounded_and_repeat_requests_are_coalesced():
    events = _run_js("""
const timeline = camera.createOperationTimeline({limit: 3});
timeline.add({action:'수동 운전', result:'accepted'}, 1000);
timeline.add({action:'수동 운전', result:'accepted'}, 1200);
timeline.add({action:'모드 변경', result:'accepted'}, 2000);
timeline.add({action:'도킹 요청', result:'failed'}, 3000);
timeline.add({action:'정지', result:'accepted'}, 4000);
console.log(JSON.stringify(timeline.snapshot()));
""")
    assert [event["action"] for event in events] == ["모드 변경", "도킹 요청", "정지"]
    assert all(set(event) == {"action", "result", "elapsed_ms"} for event in events)
    assert events[-1]["elapsed_ms"] == 4000


def test_robot_upload_body_keeps_metadata_separate_from_media_bytes():
    result = _run_js("""
const body = camera.evidenceBody({schema_version:1, kind:'screenshot'},
  new Blob([new Uint8Array([255,216,255,217])], {type:'image/jpeg'}));
const bytes = new Uint8Array(await body.arrayBuffer());
const length = new DataView(bytes.buffer).getUint32(0, true);
console.log(JSON.stringify({metadata:JSON.parse(new TextDecoder().decode(bytes.slice(4, 4+length))),
  media:Array.from(bytes.slice(4+length))}));
""")
    assert result == {"metadata": {"schema_version": 1, "kind": "screenshot"},
                      "media": [255, 216, 255, 217]}


def test_paired_frame_fetch_verifies_variant_stamp_and_never_falls_back():
    result = _run_js("""
const calls = [];
let failure = '', mismatch = false, wrongVariant = false;
const fetchFrame = async path => {
  calls.push(path);
  const annotated = path.endsWith('overlay=true');
  return new Response(new Blob(['JPEG'],{type:'image/jpeg'}), {status:failure ? 429 : 200,
    headers:{'X-Rosy-Camera-Variant':wrongVariant ? 'annotated' : annotated?'annotated':'raw',
      'X-Rosy-Camera-Sequence':'7', 'X-Rosy-Camera-Captured-At':mismatch && annotated?'12':'11',
      'X-Rosy-Camera-Frame-Id':'front'}});
};
const status = {sequence:7,raw_sequence:7,raw_available:true};
const raw = await camera.fetchCameraPair(status,{fetchFrame});
const pair = await camera.fetchCameraPair(status,{fetchFrame,previewMode:'annotated'});
const errors = [];
for (const kind of ['missing','mismatch','rate','legacy']) {
  mismatch = kind === 'mismatch'; failure = kind === 'rate'; wrongVariant = kind === 'legacy';
  try { await camera.fetchCameraPair(kind==='missing'?{sequence:7}:status,{fetchFrame,previewMode:'annotated'}); }
  catch (error) { errors.push({kind,message:error.message}); }
}
console.log(JSON.stringify({calls,raw:raw.previewMode,pair:pair.previewMode,
  hasRaw:pair.rawBlob.type,errors}));
""")
    assert result['calls'][:3] == [
        '/api/v1/vision/front/frame?sequence=7&overlay=false',
        '/api/v1/vision/front/frame?sequence=7&overlay=false',
        '/api/v1/vision/front/frame?sequence=7&overlay=true']
    assert result['raw'] == 'raw' and result['pair'] == 'annotated'
    assert result['hasRaw'] == 'image/jpeg'
    assert [error['kind'] for error in result['errors']] == ['missing','mismatch','rate','legacy']


@pytest.mark.parametrize('mode', ['raw', 'annotated'])
def test_capture_keeps_raw_pixels_unlabelled_and_saves_both_variant_files(mode):
    result = _run_js("""
const mode = """ + json.dumps(mode) + """;
const draws = [], stopped = [], saved = [], uploads = [];
const realCrypto=globalThis.crypto;
Object.defineProperty(globalThis,'crypto',{value:{getRandomValues:values=>realCrypto.getRandomValues(values)}});
globalThis.MediaRecorder = class {
  static isTypeSupported(type){return type==='video/webm';}
  constructor(){this.state='inactive';}
  start(){this.state='recording';}
  stop(){this.state='inactive';this.ondataavailable({data:new Blob(['VIDEO'])});this.onstop();}
};
globalThis.window={RosyPalette:{cssColor(){return 'ink';},canvasFont(){return '14px body';}}};
globalThis.document={createElement(){const id=draws.length;draws.push([]);return {
  getContext(){return {drawImage(image){draws[id].push(image.id);},fillRect(){draws[id].push('strip');},fillText(){draws[id].push('text');}};},
  captureStream(){return {getTracks(){return [{stop(){stopped.push(id);}}];}};}
};}};
const capture=camera.createCameraCapture({now:()=>1000,save:(blob,name)=>saved.push(name),
 storeOnRobot:async(blob,metadata)=>{uploads.push(metadata);return {file_name:'saved.webm'};}});
capture.setPreviewMode(mode);
const blob=new Blob(['JPEG'],{type:'image/jpeg'});
capture.acceptFrame({image:{id:mode==='raw'?'raw':'annotated',naturalWidth:320,naturalHeight:240},blob,
 rawImage:{id:'raw',naturalWidth:320,naturalHeight:240},rawBlob:blob,previewMode:mode,sequence:1});
const started=capture.start(), locked=capture.setPreviewMode('raw');
capture.recordAction({action:'manual',result:'accepted'});
capture.dispose(); await capture.saveVideo('both');
console.log(JSON.stringify({started,locked,draws,stopped,saved,uploads,state:capture.state()}));
""")
    assert result['started'] and result['locked'] is False
    assert set(result['draws'][0]) == {'raw'}
    assert result['saved'][0].endswith('-raw.webm')
    assert result['uploads'][0]['preview_mode'] == 'raw'
    assert len(result['uploads'][0]['pair_group_id']) == 32
    assert len(result['stopped']) == (2 if mode == 'annotated' else 1)
    if mode == 'annotated':
        assert 'text' in result['draws'][1] and 'annotated' in result['draws'][1]
        assert result['saved'][1].endswith('-annotated.webm')
        assert result['uploads'][1]['preview_mode'] == 'annotated'
        assert result['uploads'][0]['pair_group_id'] == result['uploads'][1]['pair_group_id']
    assert result['state']['recording'] is False


def test_recorded_video_and_operation_manifest_can_be_saved_together():
    result = _run_js("""
globalThis.MediaRecorder = class {
  static isTypeSupported(type) { return type === 'video/webm'; }
  constructor() { this.state = 'inactive'; }
  start() { this.state = 'recording'; }
  stop() { this.state = 'inactive'; this.ondataavailable({data:new Blob(['WEBM'])}); this.onstop(); }
};
// D-359 §4: 오버레이 색·글꼴은 ui.js의 window.RosyPalette가 푼다.
globalThis.window = {RosyPalette: {
  cssColor(name) { return ({'--scrim':'rgba(8, 9, 11, 0.84)', '--ink':'rgba(238, 238, 239, 1)'}[name]); },
  canvasFont(size, family) { return `${Math.max(12, size)}px ${family}`; },
}};
globalThis.document = {createElement() { return {
  getContext() { return {drawImage(){},fillRect(){},fillText(){}}; },
  captureStream() { return {getTracks(){ return [{stop(){}}]; }}; }
}; }};
const saved = [];
let clock = 1000;
const capture = camera.createCameraCapture({now:()=>clock,
  save:(blob,name)=>saved.push({name,blob}), onComplete:()=>{}});
capture.acceptFrame({image:{naturalWidth:320,naturalHeight:240},
  blob:new Blob([new Uint8Array([255,216,255,217])],{type:'image/jpeg'}),
  sequence:1,source:'PINKY'});
capture.start();
clock += 500;
capture.recordAction({action:'수동 운전',result:'accepted'});
capture.stop();
await capture.saveVideo('pc');
capture.saveOperations();
console.log(JSON.stringify({saved:saved.map(({name,blob})=>({name,size:blob.size})),
  operations:JSON.parse(await saved[1].blob.text()).operations, state:capture.state()}));
""")
    assert len(result["saved"]) == 2
    assert result["saved"][0]["name"].endswith(".webm")
    assert result["saved"][1]["name"].endswith(".json")
    assert result["operations"] == [{"action": "수동 운전", "result": "accepted", "elapsed_ms": 500}]
    assert result["state"]["saved"] is True


def test_screenshot_both_destinations_keeps_original_jpeg_and_safe_metadata():
    result = _run_js("""
const local = [], remote = [];
const capture = camera.createCameraCapture({now:()=>1000,
  save:(blob,name)=>local.push({bytes:blob.size,name}),
  storeOnRobot:async(blob,metadata)=>{remote.push({bytes:blob.size,metadata}); return {file_name:'saved.jpg'};}});
capture.acceptFrame({image:{naturalWidth:320,naturalHeight:240},
  blob:new Blob([new Uint8Array([255,216,255,217])],{type:'image/jpeg'}),
  sequence:9,source:'PINKY'});
await capture.screenshot('both');
console.log(JSON.stringify({local,remote}));
""")
    assert result["local"][0]["bytes"] == 4
    assert result["local"][0]["name"].endswith(".jpg")
    assert result["remote"][0]["metadata"]["sequence"] == 9
    assert "token" not in result["remote"][0]["metadata"]
