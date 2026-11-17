import test from 'node:test';
import assert from 'node:assert/strict';
import {register} from 'node:module';

const shared = new URL('../../../../shared/web/', import.meta.url).href;
register('data:text/javascript,' + encodeURIComponent(`export async function resolve(specifier, context, next) {
  return next(specifier.startsWith('/common/') ? new URL(specifier.slice(8), ${JSON.stringify(shared)}).href : specifier, context);
}`));
const {createNotice} = await import('../client.js');

function fixture() {
  const attrs = new Map();
  const line = {textContent: '', dataset: {}, removeAttribute(name) { attrs.delete(name); if (name === 'data-stop-state') delete this.dataset.stopState; }};
  const items = [];
  const center = {
    publish: (e) => { if (!items.some((i) => i.key === e.key)) items.push(e); },
    resolve: (key) => { const i = items.findIndex((x) => x.key === key); if (i !== -1) items.splice(i, 1); },
    getItems: () => items,
  };
  return {line, notice: createNotice({line, center})};
}

test('a success message never hides an active safety warning', () => {
  const {line, notice} = fixture();
  notice.alert('estop-release', 'crit', '비상 정지 해제 보류');
  assert.equal(notice.say('조종 준비 완료'), false);
  assert.equal(line.textContent, '');
  assert.equal(notice.blocked(), true);
  notice.clear('estop-release');
  assert.equal(notice.say('조종 준비 완료'), true);
  assert.equal(line.textContent, '조종 준비 완료');
});

test('a stop result on the line is not overwritten by an info message, but an empty text clears it', () => {
  const {line, notice} = fixture();
  line.dataset.stopState = 'refused'; line.textContent = '비상 정지 요청 거절';
  assert.equal(notice.say('조종 준비 완료'), false);
  assert.equal(line.textContent, '비상 정지 요청 거절');
  line.dataset.stopState = 'pending';
  assert.equal(notice.say('연결 확인 중'), true);
  notice.say('');
  assert.equal(line.textContent, '');
});
