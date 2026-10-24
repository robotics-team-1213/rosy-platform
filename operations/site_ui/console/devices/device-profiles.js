import {createPollGate} from '/console/assets/poll-gate.js';

const FIELDS = ['device_id', 'display_name', 'manufacturer', 'model', 'device_kind', 'arm_count', 'hardware_ids'];

export function profilePayload(values) {
  const hardware_ids = String(values.hardware_ids).split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  if (new Set(hardware_ids).size !== hardware_ids.length) throw new Error('장치 식별값이 중복됐습니다. 한 줄에 하나씩 입력하세요.');
  const count = String(values.arm_count ?? '').trim();
  if (count && (!/^\d+$/.test(count) || Number(count) > 16)) throw new Error('팔 수는 0~16의 정수 또는 빈칸으로 입력하세요.');
  const result = Object.fromEntries(FIELDS.slice(0, 5).map(key => [key, String(values[key] ?? '').trim()]));
  if (!result.device_id || !result.display_name) throw new Error('장치 ID와 표시 이름을 입력하세요.');
  if (result.device_kind === 'manipulator' && count && Number(count) === 0) throw new Error('로봇 팔의 팔 수는 1 이상이거나 빈칸이어야 합니다.');
  return {...result, arm_count: count ? Number(count) : null, hardware_ids};
}

export function createDeviceProfiles({root, scope, call, identity}) {
  const el = key => root.querySelector(`[data-profile="${key}"]`);
  const gate = createPollGate();
  let selected = '', dirty = false, busy = false, loading = false;
  const canEdit = () => identity()?.role === 'operator' && Boolean(identity()?.principal_id)
    && identity().principal_id !== 'site-console';
  function updateAuthorization() {
    const allowed = canEdit();
    for (const key of FIELDS) el(key).disabled = busy || !allowed || (key === 'device_id' && Boolean(selected));
    el('save').disabled = busy || !allowed;
    el('new').disabled = busy || !allowed;
    el('list').disabled = busy;
    el('permission').hidden = allowed;
    if (allowed && !busy) el('save').removeAttribute('reason');
    else el('save').setAttribute('reason', busy ? '저장 확인 중' : '이름 있는 운영자 계정이 필요합니다');
  }
  function fill(row = {}) {
    selected = row.device_id || '';
    for (const key of FIELDS) el(key).value = key === 'hardware_ids' ? (row[key] || []).join('\n')
      : row[key] ?? (key === 'device_kind' ? 'manipulator' : '');
    el('list').value = selected;
    el('saved').textContent = selected
      ? `${row.display_name} · ${row.manufacturer || '제조사 미입력'} · ${row.model || '모델 미입력'} · 팔 ${row.arm_count ?? '미입력'} · 연결 미확인 · 운용 권한 없음`
      : '저장된 장치 정보를 선택하거나 새 정보를 입력하세요.';
    dirty = false;
    updateAuthorization();
  }
  async function refresh() {
    if (loading || busy || !identity()?.role || !gate.due()) return;
    loading = true;
    try {
      const {profiles} = await call('/api/fleet/device-profiles');
      gate.ok();
      const option = root.ownerDocument.createElement('option');
      option.value = ''; option.textContent = profiles.length ? '저장된 장치 선택' : '저장된 장치가 없습니다';
      const options = profiles.map(row => {
        const node = root.ownerDocument.createElement('option');
        node.value = row.device_id; node.textContent = `${row.display_name} (${row.device_id})`;
        return node;
      });
      el('list').replaceChildren(option, ...options);
      el('list').value = selected;
      // Polling refreshes the chooser, never the user's editable draft.
    } catch (error) {
      if (error.name === 'AbortError') return;
      const absent = gate.fail(error.status, error.code) === 'absent';
      el('status').textContent = error.status === 401 ? '다시 접속한 뒤 장치 정보를 확인하세요.'
        : absent ? '이 Fleet에는 장치 정보 저장이 설정되지 않았습니다.' : '장치 정보를 읽지 못했습니다. 다시 확인하세요.';
    } finally { loading = false; updateAuthorization(); }
  }
  scope.listen(el('list'), 'change', async () => {
    if (busy) return;
    if (dirty) {
      el('list').value = selected;
      el('status').textContent = '수정 내용을 저장하거나 입력 지우기를 누른 뒤 다른 장치를 선택하세요.';
      return;
    }
    if (!el('list').value) return;
    busy = true; updateAuthorization();
    try { fill(await call(`/api/fleet/device-profiles/${encodeURIComponent(el('list').value)}`)); }
    catch (error) {
      if (error.name !== 'AbortError') el('status').textContent = '장치 정보를 읽지 못했습니다. 다시 선택하세요.';
    } finally { busy = false; updateAuthorization(); }
  });
  for (const key of FIELDS) scope.listen(el(key), 'input', () => { dirty = true; });
  scope.listen(el('new'), 'click', () => {
    if (busy || !canEdit()) return;
    fill(); el('status').textContent = '새 장치 정보를 입력하세요.'; el('device_id').focus();
  });
  scope.listen(el('refresh'), 'click', () => { gate.reset(); return refresh(); });
  scope.listen(el('save'), 'click', async () => {
    if (busy || !canEdit()) return;
    let payload;
    try { payload = profilePayload(Object.fromEntries(FIELDS.map(key => [key, el(key).value]))); }
    catch (error) { el('status').textContent = error.message; return; }
    busy = true; updateAuthorization();
    el('status').textContent = '장치 정보를 저장하고 있습니다.';
    try {
      const {device_id, ...body} = payload;
      const path = `/api/fleet/device-profiles/${encodeURIComponent(device_id)}`;
      await call(path, {method: 'PUT', body: JSON.stringify(body)});
      const saved = await call(path);
      if (JSON.stringify(profilePayload({...saved, hardware_ids: saved.hardware_ids.join('\n')})) !== JSON.stringify(payload)) {
        throw new Error('SAVED_VALUES_DIFFER');
      }
      fill(saved);
      el('status').textContent = '장치 정보를 저장하고 다시 확인했습니다. 연결은 별도 확인이 필요합니다.';
    } catch (error) {
      if (error.name !== 'AbortError') el('status').textContent = error.status === 401
        ? '접속이 만료됐습니다. 다시 접속한 뒤 저장 내용을 확인하세요.'
        : error.status === 422 ? '입력값을 확인하세요. 이름·제조사·모델은 80자, 식별값은 200자씩 최대 16개입니다.'
          : '저장 결과를 확인하지 못했습니다. 입력을 유지했습니다. 다시 확인한 뒤 저장하세요.';
    } finally { busy = false; updateAuthorization(); }
    await refresh();
  });
  scope.onDispose(() => { loading = false; busy = false; });
  updateAuthorization();
  return {refresh, updateAuthorization, resetPolling: () => gate.reset()};
}
