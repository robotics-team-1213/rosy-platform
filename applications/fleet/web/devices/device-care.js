import {paintProfile} from '/console/assets/robot-profile-view.js';

const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).sort()) : item);

export function createDeviceCare({root, scope, call, identity}) {
  const field = key => root.querySelector(`[data-care="${key}"]`);
  let selected = '', saved = null, document = null, dirty = false, busy = false, epoch = 0;
  let importedText = null;
  const allowed = () => identity()?.role === 'operator' && Boolean(identity()?.principal_id)
    && identity().principal_id !== 'site-console';
  function authorization() {
    const reason = !selected ? '장치 정보를 먼저 선택하세요.' : busy ? '기록을 확인하고 있습니다.'
      : !allowed() ? '이름 있는 운영자 계정이 필요합니다.' : '';
    field('permission').textContent = reason;
    for (const key of ['source', 'caution', 'file', 'remove', 'kind', 'text', 'save', 'add']) {
      const input = field(key);
      input.disabled = Boolean(reason);
      if (input.localName === 'ui-button') input.setAttribute('reason', reason);
      else input.setAttribute('aria-describedby', 'device-care-permission');
    }
    field('export').disabled = !document;
    field('export').setAttribute('reason', document ? '' : '내보낼 특성 JSON이 없습니다.');
  }
  function preview() {
    field('document').textContent = document
      ? `${document.revision} · ${document.status} · 계산용 JSON (관절 ${Object.keys(document.joints || {}).length}개)`
      : '특성 JSON 미등록';
  }
  async function select(row = {}) {
    if (selected && row.device_id === selected && (dirty || busy)) return;
    const current = ++epoch;
    busy = false;
    selected = row.device_id || ''; saved = null; document = null; dirty = false;
    importedText = null;
    field('caution').value = ''; field('text').value = ''; field('file').value = '';
    field('source').replaceChildren(new Option('연결 안 함', ''));
    field('history').replaceChildren(); preview(); authorization();
    if (!selected) { field('status').textContent = '장치 정보를 먼저 저장하세요.'; return; }
    busy = true; authorization();
    try {
      const [care, catalog] = await Promise.all([call(`/api/fleet/device-profiles/${encodeURIComponent(selected)}/care`),
        call('/api/fleet/device-profile-sources')]);
      if (current !== epoch) return;
      saved = care; document = care.characteristics;
      for (const source of catalog.sources) field('source').append(new Option(
        `${source.label} (${source.source_kind}: ${source.source_id})`, JSON.stringify([source.source_kind, source.source_id])));
      if (care.source_id && !catalog.sources.some(s => s.source_kind === care.source_kind && s.source_id === care.source_id))
        field('source').append(new Option(`등록에서 제외된 관측원: ${care.source_id}`, JSON.stringify([care.source_kind, care.source_id])));
      field('source').value = care.source_id ? JSON.stringify([care.source_kind, care.source_id]) : '';
      field('caution').value = care.caution;
      paintProfile(field('history'), {...row, ...care});
      field('status').textContent = '저장된 기록을 읽었습니다. 실시간 고장 상태는 로봇 상세에서 확인하세요.';
      preview();
    } catch (error) {
      if (current === epoch) field('status').textContent = '기록을 읽지 못했습니다. 다시 선택하세요.';
    } finally { if (current === epoch) { busy = false; authorization(); } }
  }
  for (const key of ['source', 'caution', 'text', 'kind']) scope.listen(field(key), 'input', () => { dirty = true; });
  scope.listen(field('file'), 'change', async () => {
    const current = epoch, file = field('file').files[0];
    if (!file || !allowed() || busy) return;
    try {
      if (file.size > 1_000_000) throw new Error('TOO_LARGE');
      const raw = await file.text(), imported = JSON.parse(raw);
      if (current !== epoch) return;
      document = imported; importedText = raw; dirty = true; preview();
      field('status').textContent = 'JSON을 읽었습니다. 저장할 때 계산기와 같은 규칙으로 검증합니다.';
    } catch { field('status').textContent = '1 MB 이하의 올바른 특성 JSON을 선택하세요.'; }
  });
  scope.listen(field('remove'), 'click', () => {
    if (!allowed() || busy) return;
    document = null; importedText = null; dirty = true; preview();
  });
  scope.listen(field('export'), 'click', () => {
    if (!document) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2)], {type: 'application/json'}));
    const anchor = root.ownerDocument.createElement('a'); anchor.href = url; anchor.download = `${selected}-characteristics.json`;
    anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  async function write(event) {
    if (!selected || !saved || !allowed() || busy) return;
    busy = true; authorization();
    try {
      const [source_kind, source_id] = field('source').value ? JSON.parse(field('source').value) : [null, null];
      const body = event ? {kind: field('kind').value, text: field('text').value}
        : {source_kind, source_id, caution: field('caution').value, characteristics: importedText ?? document};
      const path = `/api/fleet/device-profiles/${encodeURIComponent(selected)}`;
      await call(path + (event ? '/events' : '/care'), {method: event ? 'POST' : 'PUT', body: JSON.stringify(body)});
      const readback = await call(path + '/care');
      if (!event && (canonical(readback.characteristics) !== canonical(document)
          || readback.caution !== body.caution || readback.source_kind !== source_kind
          || readback.source_id !== source_id)) throw new Error('READBACK');
      saved = readback;
      if (event) field('text').value = '';
      dirty = event ? dirty : Boolean(field('text').value);
      paintProfile(field('history'), {...readback, display_name: selected});
      field('status').textContent = '저장하고 다시 확인했습니다. 실시간 고장이나 운용 권한은 바뀌지 않습니다.';
    } catch (error) {
      field('status').textContent = error.status === 422 ? '관측원·장치 ID·특성 JSON을 확인하세요. 입력을 유지했습니다.'
        : '저장 결과를 확인하지 못했습니다. 입력을 유지했습니다.';
    } finally { busy = false; authorization(); }
  }
  scope.listen(field('save'), 'click', () => write(false));
  scope.listen(field('add'), 'click', () => write(true));
  authorization();
  return {select, authorization, isDirty: () => dirty || busy};
}
