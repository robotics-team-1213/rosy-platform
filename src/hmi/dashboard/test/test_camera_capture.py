"""Camera evidence records only bounded operational events, never credentials."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


MODULE = Path(__file__).resolve().parents[1] / "camera-capture.js"


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


def test_recorded_video_and_operation_manifest_can_be_saved_together():
    result = _run_js("""
globalThis.MediaRecorder = class {
  static isTypeSupported(type) { return type === 'video/webm'; }
  constructor() { this.state = 'inactive'; }
  start() { this.state = 'recording'; }
  stop() { this.state = 'inactive'; this.ondataavailable({data:new Blob(['WEBM'])}); this.onstop(); }
};
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
