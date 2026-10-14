import {test} from 'node:test';
import assert from 'node:assert/strict';
import {profileView, renderAccountProfile} from '../account-profile.js';

const session = {authenticated:true, account_id:'alice', profile_url:'https://account.example/console/profile',
  profile:{account_id:'alice', login:'alice', display_name:'작업자 🤖'}};
test('profile is bound to authenticated subject; profile failures clear the name', () => {
  assert.equal(profileView(session).label, '작업자 🤖 · 내 계정');
  assert.equal(profileView({...session, profile:null}).label, '내 계정 · 이름 확인 불가');
  assert.equal(profileView({...session, profile:{...session.profile, account_id:'bob'}}).label, '내 계정 · 이름 확인 불가');
  assert.equal(profileView({...session, authenticated:false}), null);
  for (const name of ['bad\nname', '\ud800', 'a'.repeat(81)]) {
    assert.equal(profileView({...session, profile:{...session.profile, display_name:name}}).label, '내 계정 · 이름 확인 불가');
  }
});
test('only fixed HTTPS profile URLs are shown', () => {
  for (const profile_url of ['javascript:alert(1)', 'http://account.example/console/profile',
    'https://a:b@account.example/console/profile', 'https://account.example/console/profile?return=evil',
    'https://account.example/other', 'https://account.example/console/profile#token']) {
    assert.equal(profileView({...session, profile_url}), null);
  }
});
test('renderer uses literal text and removes stale navigation on logout/native shell', () => {
  const link = {removeAttribute(key) { delete this[key]; }};
  const root = {documentElement:{dataset:{}}, querySelectorAll:() => [link]};
  renderAccountProfile({...session, profile:{...session.profile, display_name:'<img onerror=alert(1)>'}}, root);
  assert.equal(link.textContent, '<img onerror=alert(1)> · 내 계정');
  assert.equal(link.rel, 'noopener noreferrer');
  renderAccountProfile(null, root);
  assert.equal(link.hidden, true); assert.equal(link.href, undefined); assert.equal(link.textContent, '');
  root.documentElement.dataset.pilotShell = 'android';
  renderAccountProfile(session, root); assert.equal(link.hidden, true);
});
