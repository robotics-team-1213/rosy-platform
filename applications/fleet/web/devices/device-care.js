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
    for (const key of ['source', 'caution', 'file', 'remove', 'kind', 'text', 'save', 'add'])
      field(key).disabled = !selected || busy || !allowed();
    field('export').disabled = !document;
  }
  function preview() {
    field('document').textContent = document
      ? `${document.revision} · ${document.status} · 計算用 JSON (${Object.keys(document.joints || {}).length}関節)`
      : '特性 JSON 未登録';
  }
  async function select(row = {}) {
    if (selected && row.device_id === selected && (dirty || busy)) return;
    const current = ++epoch;
    busy = false;
    selected = row.device_id || ''; saved = null; document = null; dirty = false;
    importedText = null;
    field('caution').value = ''; field('text').value = ''; field('file').value = '';
    field('source').replaceChildren(new Option('未接続', ''));
    field('history').replaceChildren(); preview(); authorization();
    if (!selected) { field('status').textContent = '先に装置情報を保存してください。'; return; }
    busy = true; authorization();
    try {
      const [care, catalog] = await Promise.all([call(`/api/fleet/device-profiles/${encodeURIComponent(selected)}/care`),
        call('/api/fleet/device-profile-sources')]);
      if (current !== epoch) return;
      saved = care; document = care.characteristics;
      for (const source of catalog.sources) field('source').append(new Option(
        `${source.label} (${source.source_kind}: ${source.source_id})`, JSON.stringify([source.source_kind, source.source_id])));
      if (care.source_id && !catalog.sources.some(s => s.source_kind === care.source_kind && s.source_id === care.source_id))
        field('source').append(new Option(`登録から外れた観測元: ${care.source_id}`, JSON.stringify([care.source_kind, care.source_id])));
      field('source').value = care.source_id ? JSON.stringify([care.source_kind, care.source_id]) : '';
      field('caution').value = care.caution;
      paintProfile(field('history'), {...row, ...care});
      field('status').textContent = '保存済み記録を読みました。実時間の故障状態はロボット詳細で確認してください。';
      preview();
    } catch (error) {
      if (current === epoch) field('status').textContent = '記録を読み込めません。再選択してください。';
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
      field('status').textContent = 'JSONを読みました。保存時に計算器と同じ規則で検証します。';
    } catch { field('status').textContent = '1 MB以下の有効な特性JSONを選んでください。'; }
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
      field('status').textContent = '保存と再読込を確認しました。実時間の故障や運用権限は変わりません。';
    } catch (error) {
      field('status').textContent = error.status === 422 ? '観測元・装置ID・特性JSONを確認してください。入力は保持しました。'
        : '保存結果を確認できません。入力は保持しました。';
    } finally { busy = false; authorization(); }
  }
  scope.listen(field('save'), 'click', () => write(false));
  scope.listen(field('add'), 'click', () => write(true));
  authorization();
  return {select, authorization, isDirty: () => dirty || busy};
}
