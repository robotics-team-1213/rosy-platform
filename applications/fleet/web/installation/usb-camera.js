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
  const rows = new Map();
  let rowSerial = 0;
  const bearer = () => headers().Authorization || headers().authorization || '';
  const canDecide = () => {
    const principal = identity();
    return !locked() && principal?.role === 'operator'
      && typeof principal.principal_id === 'string' && Boolean(principal.principal_id.trim());
  };
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
    if (busy || !canDecide() || !body) {if (!body) notice('역할 이름은 영문자·숫자·_·-로 64자 이내여야 합니다.'); return;}
    const life = scope.capture(); life.check(); busy = true;
    try {
      const allowed = await dialogs.confirmIrreversible({
        message: `USB 카메라(${candidate.usb_id})에 역할 "${body.role}"을 줄까요? 제어 PC가 20초 안에 적용하고 그 역할의 카메라 서비스를 시작합니다.`,
        action: '역할 승인', signal: life.signal});
      life.check();
      if (!allowed || !canDecide()) return;
      await call(`${BASE}/${encodeURIComponent(workcell.workcell_id)}/usb-devices/${candidate.key}/decision`,
        {method: 'POST', body});
      life.check(); notice('승인했습니다. 제어 PC가 곧 적용합니다.');
    } catch (error) {if (error.name !== 'AbortError') notice(error.message);}
    finally {if (life.current()) {busy = false; await refresh();}}
  }
  function render(workcells) {
    const list = el('usb-camera-list'), current = new Set(), items = [];
    const focused = document.activeElement;
    const selection = focused?.tagName === 'INPUT' ? [focused.selectionStart, focused.selectionEnd] : null;
    for (const workcell of workcells) {
      for (const candidate of workcell.candidates) {
        const key = JSON.stringify([identity()?.principal_id, workcell.workcell_id, candidate.key]);
        current.add(key);
        let row = rows.get(key);
        if (row && row.decided !== Boolean(candidate.decision)) {row.item.remove(); rows.delete(key); row = null;}
        if (!row) {
          const item = document.createElement('li');
          item.append(text('strong', `${workcell.workcell_id} · USB ${candidate.usb_id}`));
          row = {item, decided: Boolean(candidate.decision), dirty: false};
          if (candidate.decision) {row.status = text('p', ''); item.append(row.status);}
          else {
            const names = document.createElement('datalist'); names.id = `usb-roles-${++rowSerial}`;
            const input = document.createElement('input'); input.className = 'ui-field'; input.setAttribute('list', names.id);
            input.setAttribute('aria-label', `USB ${candidate.usb_id}의 역할`);
            input.placeholder = '역할 이름 (새 이름도 가능)';
            input.addEventListener('input', () => {row.dirty = true;});
            const approve = document.createElement('ui-button'); approve.textContent = '역할 승인';
            approve.setAttribute('type', 'button'); approve.setAttribute('kind', 'primary');
            approve.addEventListener('click', scope.guard(() => decide(row.workcell, row.candidate, input.value)));
            const actions = document.createElement('div'); actions.className = 'camera-actions';
            actions.append(input, names, approve);
            row.input = input; row.names = names; row.hint = text('p', '');
            item.append(row.hint, actions);
          }
          rows.set(key, row);
        }
        row.workcell = workcell; row.candidate = candidate;
        if (candidate.decision) row.status.textContent = `승인됨: ${candidate.decision.role} (${candidate.decision.principal_id}) · 적용 대기`;
        else {
          if (!row.dirty) row.input.value = candidate.suggest || '';
          const hint = suggestionText(candidate);
          row.hint.hidden = !hint; row.hint.textContent = hint ? `추천: ${candidate.suggest} · ${hint}` : '';
          const choices = [...new Set([candidate.suggest, ...candidate.roles, ...workcell.roles].filter(Boolean))];
          row.names.replaceChildren(...choices.map(name => {const option = document.createElement('option'); option.value = name; return option;}));
        }
        items.push(row.item);
      }
    }
    for (const [key, row] of rows) if (!current.has(key)) {row.item.remove(); rows.delete(key);}
    if (!items.length) list.replaceChildren(text('li', '역할이 없는 USB 카메라가 없습니다. 새 카메라를 제어 PC에 꽂으면 20초 안에 이곳에 나타납니다.'));
    else {
      for (let index = 0; index < items.length; index++) if (list.children[index] !== items[index]) list.insertBefore(items[index], list.children[index] || null);
      while (list.children.length > items.length) list.lastChild.remove();
    }
    if (focused?.isConnected && selection && document.activeElement !== focused) {focused.focus(); focused.setSelectionRange(...selection);}
  }
  async function refresh() {
    const panel = el('usb-camera-panel');
    if (!panel || !canDecide()) {
      if (panel) {panel.hidden = true; el('usb-camera-list').replaceChildren(); rows.clear();} return;
    }
    if (inFlight || busy || document.visibilityState === 'hidden') return;
    inFlight = true; panel.setAttribute('aria-busy', 'true'); const life = scope.capture();
    try {
      const {workcells} = await call(`${BASE}/usb-devices`);
      life.check(); panel.hidden = false; render(workcells);
    } catch (error) {if (error.name !== 'AbortError') panel.hidden = true;}  // no observation service: nothing to approve
    finally {if (life.current()) {inFlight = false; panel.setAttribute('aria-busy', 'false');}}
  }
  scope.interval(refresh, 5000);
  scope.onDispose(() => {inFlight = false; busy = false; rows.clear();});
  return {refresh};
}
