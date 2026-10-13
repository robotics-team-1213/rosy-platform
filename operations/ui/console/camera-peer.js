// D456 receiver-screen approval. A remembered camera is not a running stream or lease.
const BASE = '/api/fleet/pairing/v2';

export function approvalBody(row, source, remember, who) {
  if (row?.state !== 'pending' || !Number.isInteger(row.revision) || row.revision < 0
      || who?.role !== 'operator' || !who.principal_id
      || !/^[A-Za-z0-9_-]{1,32}$/.test(source) || typeof remember !== 'boolean') return null;
  return {action:'approve',revision:row.revision,source_id:source,persist_requested:remember};
}

export function relationshipText(row) {
  if (row.state === 'revoked') return '연결 해제됨';
  if (!row.authorization_available) return '연결 기록 보존 · 현재 자격을 갱신할 수 없음';
  return row.persistent ? '연결 기억 중 · 다시 켜도 승인 유지' : '승인 기한 안에서 연결 유지';
}

export function createCameraPeerPanel({scope,headers,identity,locked,dialogs,onUnauthorized=()=>{}}) {
  const el = id => document.getElementById(id);
  let inFlight = false, busy = false, inView=true, deniedOwner='', pending = [], sources = [];
  const ownerKey = () => `${identity()?.principal_id || ''}:${identity()?.role || ''}:${headers().Authorization || headers().authorization || ''}`;
  async function call(path,{method='GET',body}={}) {
    const life = scope.capture();
    life.check();
    const response = await fetch(path,{method,headers:{...headers(),...(body ? {'Content-Type':'application/json'} : {})},
      signal:life.signal, ...(body ? {body:JSON.stringify(body)} : {})});
    life.check();
    if (response.status===401 || response.status===403 || response.status===404) {
      deniedOwner=ownerKey(); clear();
      if (response.status===401) onUnauthorized();
    }
    if (!response.ok) { const error = new Error('카메라 연결 요청을 처리하지 못했습니다. 목록을 다시 확인하세요.'); error.status = response.status;
      if (error.status===401) error.message='현재 인증을 확인할 수 없습니다. 로그인 정보를 다시 확인하세요.';
      if (error.status===403) error.message='현재 운영자에게 카메라 연결 승인 권한이 없습니다.';
      throw error; }
    const value = await response.json(); life.check(); return value;
  }
  const text = (tag,value) => {const node = document.createElement(tag); node.textContent=value; return node;};
  function button(label,action) {
    const node = document.createElement('ui-button'); node.textContent=label;
    node.setAttribute('type','button'); node.setAttribute('kind','quiet');
    node.addEventListener('click',scope.guard(action)); return node;
  }
  function notice(message) {el('camera-peer-status').textContent=message;}
  async function decide(row,source,remember) {
    if (busy || locked()) return;
    const body = approvalBody(row,source,remember,identity()); if (!body) return;
    const life=scope.capture(), owner=ownerKey(); life.check(); busy=true;
    try {
      const allowed = await dialogs.confirmIrreversible({
        message:`기기 "${row.label}"의 확인 문자 ${row.display_code}가 폰과 일치하는지 확인하고 카메라 자리 "${source}"의 연결을 승인할까요? ${remember ? '이 연결을 기억합니다.' : '승인 기한 안에서 연결합니다.'}`,
        action:'연결 승인',signal:life.signal});
      life.check();
      if (!allowed || owner !== ownerKey() || locked() || !pending.some(item =>
          item.request_id===row.request_id && item.revision===row.revision && item.client_key_sha256===row.client_key_sha256)
          || !sources.includes(source)) return;
      await call(`${BASE}/requests/${encodeURIComponent(row.request_id)}/decision`,{method:'POST',body});
      life.check(); notice('연결을 승인했습니다. 카메라 앱에서 연결을 마무리하세요.');
    } catch(error) {if (error.name !== 'AbortError') notice(error.message);}
    finally {if (life.current()) {busy=false; await refresh();}}
  }
  async function revoke(row) {
    if (busy || locked()) return;
    const life=scope.capture(), owner=ownerKey(); life.check(); busy=true;
    try {
      const allowed=await dialogs.confirmIrreversible({
        message:`"${row.label}"의 기억한 연결과 영상 자격을 해제할까요? 다시 사용하려면 이 화면에서 승인해야 합니다.`,
        action:'연결 해제',signal:life.signal}); life.check();
      if (!allowed || owner!==ownerKey() || locked()) return;
      await call(`${BASE}/relationships/${encodeURIComponent(row.relationship_id)}/revoke`,{method:'POST'});
      life.check(); notice('연결을 해제했습니다. 다음 정상 동기화부터 영상 자격이 거부됩니다.');
    } catch(error) {if (error.name !== 'AbortError') notice(error.message);}
    finally {if (life.current()) {busy=false; await refresh();}}
  }
  function render(requests,relationships) {
    pending=requests;
    const waiting=el('camera-peer-requests'); waiting.replaceChildren();
    for (const row of requests) {
      const item=document.createElement('li'); item.append(text('strong',`${row.label} · ${row.display_code}`));
      const select=document.createElement('select'); select.className='ui-field'; select.setAttribute('aria-label',`${row.label}의 카메라 자리`);
      for (const source of sources) {const option=text('option',source); option.value=source; select.append(option);}
      const label=document.createElement('label'), remember=document.createElement('input');
      label.className='ui-check'; remember.className='ui-field';
      remember.type='checkbox'; remember.checked=true; label.append(remember,document.createTextNode(' 이 연결 기억'));
      const approve=button('연결 승인',()=>decide(row,select.value,remember.checked));
      approve.setAttribute('kind','primary');
      if (!sources.length) {approve.disabled=true; approve.setAttribute('reason','빈 카메라 자리가 없습니다. 먼저 기억한 연결을 해제하세요.');}
      const actions=document.createElement('div'); actions.className='camera-actions'; actions.append(select,label,approve);
      item.append(actions); waiting.append(item);
    }
    if (!requests.length) waiting.append(text('li','대기 중인 요청이 없습니다. 같은 LAN의 카메라 앱에서 이 장비를 선택하세요.'));
    const remembered=el('camera-peer-relationships'); remembered.replaceChildren();
    for (const row of relationships) {
      const item=document.createElement('li'); item.append(text('strong',`${row.label} · ${row.source_id}`),text('p',relationshipText(row)));
      if (row.state!=='revoked') item.append(button('연결 해제',()=>revoke(row)));
      remembered.append(item);
    }
    if (!relationships.length) remembered.append(text('li','처음 승인한 카메라 연결이 이곳에 남습니다.'));
  }
  function clear() {
    pending=[]; sources=[];
    if (el('camera-peer-panel')) el('camera-peer-panel').hidden=true;
    if (el('camera-peer-fingerprint')) el('camera-peer-fingerprint').textContent='';
    for (const id of ['camera-peer-requests','camera-peer-relationships']) el(id)?.replaceChildren();
  }
  async function refresh() {
    if (locked() || identity()?.role!=='operator') {clear(); return;}
    if (deniedOwner && deniedOwner===ownerKey()) return;
    if (inFlight || !inView || document.visibilityState==='hidden' || locked()
        || identity()?.role!=='operator' || !el('camera-peer-panel')) return;
    inFlight=true; const life=scope.capture(), owner=ownerKey();
    try {
      const [requests,relationships,anchor]=await Promise.all([
        call(BASE+'/pending'),call(BASE+'/relationships'),call(BASE+'/identity')]);
      life.check();
      if (owner!==ownerKey() || locked()) {clear(); return;}
      const listing=await call('/api/fleet/pairing/v1/pending');
      life.check();
      if (owner!==ownerKey() || locked()) {clear(); return;}
      sources=(listing.paired_sources || []).filter(row=>!row.has_credential).map(row=>row.source_id);
      el('camera-peer-panel').hidden=false;
      const fingerprint = anchor.tls_ca_sha256.match(/.{1,4}/g).join(' ').toUpperCase();
      el('camera-peer-fingerprint').textContent=`수신 장비 CA 지문: ${fingerprint}`;
      if (!busy) render(requests,relationships);
    } catch(error) {
      if (error.name!=='AbortError') {el('camera-peer-panel').hidden=false;
        notice(error.status===404 ? '이 수신 장비는 기억한 카메라 연결을 지원하지 않습니다. 아래 기존 연결 방식을 사용할 수 있습니다.' : error.message);}
    } finally {if (life.current()) inFlight=false;}
  }
  scope.interval(refresh,2500);
  if (el('camera-link') && typeof IntersectionObserver==='function') scope.subscribe?.(()=>{
    const observer=new IntersectionObserver(scope.guard(entries=>{
      const wasOut=!inView; inView=entries.some(entry=>entry.isIntersecting);
      if (wasOut && inView) refresh();
    })); observer.observe(el('camera-link')); return ()=>observer.disconnect();
  });
  scope.onDispose(()=>{inFlight=false;busy=false;deniedOwner='';clear();});
  return {refresh};
}
