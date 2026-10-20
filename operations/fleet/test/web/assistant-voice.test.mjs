import test from 'node:test';
import assert from 'node:assert/strict';
import { createVoice } from '../../../../applications/fleet/web/assistant/assistant-voice.js';

function platform() {
  const instances = [], spoken = [];
  class Recognition {
    constructor() { instances.push(this); }
    start() { this.started = true; }
    stop() { this.onend?.(); }
    abort() { this.aborted = true; }
    static async available(options) { assert.equal(options.processLocally, true); return 'available'; }
  }
  Recognition.prototype.processLocally = false;
  class Utterance { constructor(text) { this.text = text; } }
  return {SpeechRecognition:Recognition, SpeechSynthesisUtterance:Utterance,
    speechSynthesis:{cancel(){}, getVoices:()=>[{lang:'ko-KR',localService:true}], speak:v=>spoken.push(v)},
    isSecureContext:true, setTimeout, clearTimeout, instances, spoken};
}

test('missing local recognition never starts a cloud recognizer', async () => {
  let created = false;
  class CloudRecognition { constructor() { created = true; } }
  const voice = createVoice({platform:{SpeechRecognition:CloudRecognition,isSecureContext:true},onText(){},onState(){}});
  assert.equal(await voice.available(), 'unavailable');
  assert.equal(await voice.start(), false);
  assert.equal(created, false);
});

test('only final recognized text reaches the editable draft', async () => {
  const env = platform(), text = [];
  const voice = createVoice({platform:env,onText:t=>text.push(t),onState(){}});
  assert.equal(await voice.start(), true);
  const recognition = env.instances[0];
  assert.equal(recognition.processLocally, true);
  assert.equal(recognition.lang, 'ko-KR');
  recognition.onresult({results:[Object.assign([{transcript:'중간'}],{isFinal:false})]});
  assert.deepEqual(text, []);
  recognition.onresult({results:[Object.assign([{transcript:'로봇 상태 알려줘'}],{isFinal:true})]});
  voice.stop();
  assert.deepEqual(text, ['로봇 상태 알려줘']);
});

test('cancel discards a late recognition result after an account change', async () => {
  const env = platform(), text = [];
  const voice = createVoice({platform:env,onText:t=>text.push(t),onState(){}});
  await voice.start();
  const recognition = env.instances[0];
  voice.cancel();
  recognition.onresult({results:[Object.assign([{transcript:'private'}],{isFinal:true})]});
  recognition.onend();
  assert.deepEqual(text, []);
  assert.equal(recognition.aborted, true);
});

test('reading uses only a local Korean voice and stops before recording', async () => {
  const env = platform(); let cancelled = 0;
  env.speechSynthesis.cancel = () => cancelled++;
  const voice = createVoice({platform:env,onText(){},onState(){}});
  assert.equal(voice.speak('현재 관제 상태입니다.'), true);
  assert.equal(env.spoken[0].voice.localService, true);
  await voice.start();
  assert.ok(cancelled >= 2);
  voice.cancel();
  env.speechSynthesis.getVoices = () => [{lang:'ko-KR',localService:false}];
  assert.equal(voice.speak('안녕'), false);
});

test('English selection uses local English recognition and playback', async () => {
  const env = platform();
  env.speechSynthesis.getVoices = () => [{lang:'en-US',localService:true}];
  const voice = createVoice({platform:env,locale:'en-US',onText(){},onState(){}});
  await voice.start();
  assert.equal(env.instances[0].lang, 'en-US');
  voice.cancel();
  assert.equal(voice.speak('Robot status'), true);
  assert.equal(env.spoken[0].lang, 'en-US');
});
