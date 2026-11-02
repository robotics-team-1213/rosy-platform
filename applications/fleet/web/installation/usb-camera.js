// D-963: approve the role of a USB camera plugged into a control PC. Fleet stores the decision; the PC applies it.
import {createRequest} from '/common/request.js';
const BASE = '/api/fleet/workcell-observations';
const ROLE = /^[A-Za-z_][A-Za-z0-9_-]{0,63}$/;

export function decisionBody(role) {
  return typeof role === 'string' && ROLE.test(role.trim()) ? {role: role.trim()} : null;
}

export function suggestionText(candidate) {
  if (!candidate.suggest) return '';
  if (candidate.hub_arm) return '같은 USB 허브의 팔';
  return candidate.roles.includes(candidate.suggest) ? '같은 모델이 빠진 역할' : '추천 역할';
}

export function createUsbCameraPanel({scope, headers, identity, locked, dialogs, onUnauthorized = () => {}}) {
  const el = id => document.getElementById(id);
  let inFlight = false, busy = false;
  const bearer = () => headers().Authorization || headers().authorization || '';
  async function call(path, {method = 'GET', body} = {}) {
    const life = scope.capture(); life.check();
    const requestHeaders = {...headers(), ...(body ? {'Content-Type': 'application/json'} : {})};
    const request = createRequest({
      credential: () => bearer().slice(7),
      readResponse: async response => {
        life.check();
        if (response.status === 401) onUnauthorized();
        if (!response.ok) {
          const error = new Error(response.status === 403 ? '현재 운영자에게 USB 카메라 승인 권한이 없습니다.'
            : response.status === 404 ? '이 카메라는 더 이상 보고되지 않습니다. 목록을 다시 확인하세요.'
            : 'USB 카메라 요청을 처리하지 못했습니다. 목록을 다시 확인하세요.');
          error.status = response.status; throw error;
        }
        return response.json();
      },
    });
    const {body: value} = await request(path, {method, headers: requestHeaders, signal: life.signal,
      ...(body ? {body: JSON.stringify(body)} : {})});
    life.check(); return value;
  }
  const text = (tag, value) => {const node = document.createElement(tag); node.textContent = value; return node;};
  const notice = message => {el('usb-camera-status').textContent = message;};
  async function decide(workcell, candidate, role) {
    const body = decisionBody(role);
    if (busy || locked() || !body) {if (!body) notice('역할 이름은 영문자·숫자·_·-로 64자 이내여야 합니다.'); return;}
    const life = scope.capture(); life.check(); busy = true;
    try {
      const allowed = await dialogs.confirmIrreversible({
        message: `USB 카메라(${candidate.usb_id})에 역할 "${body.role}"을 줄까요? 제어 PC가 20초 안에 적용하고 그 역할의 카메라 서비스를 시작합니다.`,
        action: '역할 승인', signal: life.signal});
      life.check();
      if (!allowed || locked()) return;
      await call(`${BASE}/${encodeURIComponent(workcell.workcell_id)}/usb-devices/${candidate.key}/decision`,
        {method: 'POST', body});
      life.check(); notice('승인했습니다. 제어 PC가 곧 적용합니다.');
    } catch (error) {if (error.name !== 'AbortError') notice(error.message);}
    finally {if (life.current()) {busy = false; await refresh();}}
  }
  function render(workcells) {
    const list = el('usb-camera-list'); list.replaceChildren();
    for (const workcell of workcells) {
      for (const candidate of workcell.candidates) {
        const item = document.createElement('li');
        item.append(text('strong', `${workcell.workcell_id} · USB ${candidate.usb_id}`));
        const hint = suggestionText(candidate);
        if (candidate.decision) item.append(text('p', `승인됨: ${candidate.decision.role} (${candidate.decision.principal_id}) · 적용 대기`));
        else {
          const choices = [...new Set([candidate.suggest, ...candidate.roles, ...workcell.roles].filter(Boolean))];
          const names = document.createElement('datalist'); names.id = `usb-roles-${candidate.key}`;
          for (const name of choices) {const option = document.createElement('option'); option.value = name; names.append(option);}
          const input = document.createElement('input'); input.className = 'ui-field'; input.setAttribute('list', names.id);
          input.setAttribute('aria-label', `USB ${candidate.usb_id}의 역할`); input.value = candidate.suggest || '';
          input.placeholder = '역할 이름 (새 이름도 가능)';
          const approve = document.createElement('ui-button'); approve.textContent = '역할 승인';
          approve.setAttribute('type', 'button'); approve.setAttribute('kind', 'primary');
          approve.addEventListener('click', scope.guard(() => decide(workcell, candidate, input.value)));
          const actions = document.createElement('div'); actions.className = 'camera-actions';
          actions.append(input, names, approve);
          item.append(...(hint ? [text('p', `추천: ${candidate.suggest} · ${hint}`)] : []), actions);
        }
        list.append(item);
      }
    }
    if (!list.children.length) list.append(text('li', '역할이 없는 USB 카메라가 없습니다. 새 카메라를 제어 PC에 꽂으면 20초 안에 이곳에 나타납니다.'));
  }
  async function refresh() {
    const panel = el('usb-camera-panel');
    if (!panel || locked() || identity()?.role !== 'operator' || !/^Bearer\s+\S+$/.test(bearer())) {
      if (panel) panel.hidden = true; return;
    }
    if (inFlight || busy || document.visibilityState === 'hidden') return;
    inFlight = true; const life = scope.capture();
    try {
      const {workcells} = await call(`${BASE}/usb-devices`);
      life.check(); panel.hidden = false; render(workcells);
    } catch (error) {if (error.name !== 'AbortError') panel.hidden = true;}  // no observation service: nothing to approve
    finally {if (life.current()) inFlight = false;}
  }
  scope.interval(refresh, 5000);
  scope.onDispose(() => {inFlight = false; busy = false;});
  return {refresh};
}
