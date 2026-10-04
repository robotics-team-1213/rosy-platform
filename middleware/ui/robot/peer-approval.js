// Existing administrator session owns consent; this module never stores credentials.
import {confirmIrreversible} from '/common/ui.js';

export function createReceiverApprovals({root, api, isAdmin, captureLifetime, runConfirmed}) {
  let generation = 0, busy = false, deciding = false;
  const message = root.querySelector('[data-peer-message]');
  const list = root.querySelector('[data-peer-list]');
  const anchor = document.createElement('p'); anchor.className='host-note'; anchor.dataset.peerAnchor='';
  root.insertBefore(anchor, list);
  const clear = () => { generation++; list.replaceChildren(); anchor.textContent=''; root.hidden = true; };
  async function refresh(owner = captureLifetime(), suppliedRows) {
    if (!isAdmin() || !owner.current()) { clear(); return; }
    root.hidden = false;
    if (location.protocol !== 'https:') {
      list.replaceChildren(); message.textContent = '기기 승인에는 신뢰할 수 있는 HTTPS 연결이 필요합니다.'; return;
    }
    if (busy || deciding) return;
    busy = true;
    const epoch = ++generation;
    try {
      const identity = await api('/api/v1/auth/peer-pairing/identity', {signal: owner.signal});
      if (!owner.current() || !isAdmin() || generation !== epoch) return;
      anchor.textContent = identity.tls_ca_sha256 && /^[a-f0-9]{64}$/.test(identity.tls_ca_sha256)
        ? `이 수신 기기의 인증서 확인 값 · ${identity.tls_hostname}\n${identity.tls_ca_sha256.match(/.{4}/g).join(' ')}`
        : '별도 인증서 확인 값이 없습니다. 요청 기기에서 기존에 신뢰한 HTTPS 연결인지 확인하세요.';
      const rows = suppliedRows ?? await api('/api/v1/auth/peer-pairing/pending', {signal: owner.signal});
      if (!owner.current() || !isAdmin() || generation !== epoch) return;
      list.replaceChildren();
      if (!Array.isArray(rows) || rows.length > 16) throw new Error('연결 요청을 확인할 수 없습니다.');
      message.textContent = rows.length ? '요청한 기기의 표시 번호와 이름을 확인한 뒤 승인하세요.' : '현재 기다리는 연결 요청이 없습니다.';
      for (const row of rows) {
        const item = document.createElement('li');
        const title = document.createElement('strong');
        title.textContent = `${row.label} · ${row.display_code}`;
        const detail = document.createElement('p');
        detail.className = 'host-note';
        detail.textContent = `${row.client_id} · ${row.role === 'operator' ? '조작 권한' : '조회 권한'} · 키 ${row.client_key_sha256.match(/.{1,4}/g).join(' ')}`;
        const label = document.createElement('label'); label.className = 'ui-check';
        const remember = document.createElement('input');
        remember.type = 'checkbox'; remember.className='ui-field'; remember.checked = true;
        label.append(remember, document.createTextNode(' 연결 기억'));
        const act = action => {
          const button = document.createElement('ui-button');
          button.setAttribute('kind', 'quiet');
          if (action === 'approve') button.setAttribute('kind', 'primary');
          button.setAttribute('type', 'button'); button.textContent = action === 'approve' ? '승인' : '거절';
          button.addEventListener('click', async () => {
            if (deciding) return;
            deciding = true;
            const requested = remember.checked;
            const active = () => owner.current() && isAdmin() && generation === epoch && item.isConnected && item.getClientRects().length > 0;
            try { await runConfirmed(`${row.label} (${row.display_code}) 연결을 ${action === 'approve' ? '승인' : '거절'}하시겠습니까?`,
              button, active, async (_current, ticket) => {
                const result = await api(`/api/v1/auth/peer-pairing/requests/${encodeURIComponent(row.request_id)}/decision`,
                  {method: 'POST', signal: ticket.signal, body: JSON.stringify({action, revision: row.revision, persist_requested: requested})});
                if (!ticket.current() || !active()) return;
                list.replaceChildren(); generation++;
                message.textContent = action === 'reject' ? '요청을 거절했습니다.' : result.persistent
                  ? '연결을 승인하고 기억했습니다. 요청한 기기에서 연결을 마무리하세요.'
                  : `연결을 승인했습니다. 현재 승인 권한은 ${result.authorization_expires_at}까지 유효합니다.`;
              }, error => { if (active()) message.textContent = error.message || '승인을 완료하지 못했습니다. 다시 확인하세요.'; },
              pending => { button.disabled = pending; if(pending)button.setAttribute('reason','승인 요청 처리 중');else button.removeAttribute('reason'); }, 'peer-approval', action === 'approve' ? '연결 승인' : '요청 거절');
            } finally { deciding = false; }
          });
          return button;
        };
        const actions=document.createElement('ui-actions'); actions.append(act('approve'),act('reject'));
        item.append(title, detail, label, actions); list.append(item);
      }
    } catch (error) {
      if (owner.current() && generation === epoch) { list.replaceChildren(); message.textContent = '연결 요청을 가져오지 못했습니다. 잠시 후 다시 확인합니다.'; }
    } finally { busy = false; }
  }
  return {refresh, clear};
}

// Normal /device security procedure, not only the legacy dashboard.
export function mountReceiverApprovals(parent, ctx) {
  const root=document.createElement('section'); root.className='ui-readback';
  const heading=document.createElement('h3'); heading.textContent='기기 연결 승인';
  const message=document.createElement('ui-status'); message.dataset.peerMessage=''; message.setAttribute('role','status');
  const list=document.createElement('ul'); list.className='diagnostic-list'; list.dataset.peerList=''; list.setAttribute('aria-label','기기 연결 요청');
  root.append(heading,message,list); parent.append(root);
  const lifetime=new AbortController(); let disposed=false;
  const current=()=>!disposed&&ctx.role==='administrator';
  const ticket=()=>({current,signal:lifetime.signal});
  const runConfirmed=async(message,opener,eligible,run,fail,pending,_kind,action)=>{
    const owner=ticket();
    try {
      if(!current()||!eligible()||!await confirmIrreversible({message,opener,signal:owner.signal,action})||!current()||!eligible())return;
      pending(true);await run(current,owner);
    } catch(error) {if(current())fail(error);} finally {pending(false);}
  };
  const panel=createReceiverApprovals({root,api:ctx.api,isAdmin:current,captureLifetime:ticket,runConfirmed});
  let stop=()=>{};
  if(location.protocol==='https:') stop=ctx.store.poll('/api/v1/auth/peer-pairing/pending',5000,
    rows=>panel.refresh(ticket(),rows),()=>{if(current())message.textContent='연결 요청을 가져오지 못했습니다. 잠시 후 다시 확인합니다.';});
  else panel.refresh();
  return ()=>{disposed=true;lifetime.abort();stop();panel.clear();};
}
