// D-655 survey drafting UI; it changes the local draft and never commands a robot.
import {confirmIrreversible} from '/common/ui.js';
import {createSurveyDraft, appendSurveyElement, editSurveyElement, removeSurveyElement, reviewSurveyDraft} from '/console/assets/site-map-edit.js';
import {PLACE_KIND_LABEL} from '/console/assets/site-map-model.js';

const KINDS = {...PLACE_KIND_LABEL, road: '도로', traffic_signal: '신호등', stop_line: '정지선', landmark: '기준 표식', exclusion: '금지 구역'};

export function createSurveyPanel(host) {
  const $ = id => document.getElementById(id);
  let points = [], picking = false, editing = false, editingKind = null, mapId = null, loadedApproaches = [], approachEdited = false, lastMapId = null;
  const rows = () => [...(host.map()?.places || []).map(p => ({...p, category: 'places', geometry: [[p.x, p.y]]})),
    ...(host.map()?.edges || []).map(e => ({...e, category: 'edges', name: e.name || e.id, kind: 'road', geometry: e.polyline})),
    ...(host.map()?.facilities || []).map(f => ({...f, category: 'facilities'}))];
  const message = text => { $('survey-status').textContent = text; };
  const number = id => {
    if (!$(id).value.trim()) throw new Error('좌표·방향·폭의 숫자를 입력하세요');
    return Number($(id).value);
  };
  function act(action) {
    if (host.reason()) return;
    try { action(); sync(); } catch (error) { message(error.message); }
  }
  function gate(id, reason) {
    $(id).disabled = Boolean(reason);
    if (reason) $(id).setAttribute('reason', reason); else $(id).removeAttribute('reason');
  }
  function options(id, values) {
    const field = $(id), selected = new Set([...field.selectedOptions].map(o => o.value));
    const key = JSON.stringify(values);
    if (field.dataset.options === key) return;
    field.dataset.options = key;
    field.replaceChildren(...values.map(([value, name]) => new Option(name, value, false, selected.has(value))));
  }
  function geometry() {
    $('element-points').textContent = points.length ? points.map(([x, y], i) => `${i + 1}: ${x}, ${y} m`).join(' · ') : '찍은 좌표 없음';
    $('element-pick').setAttribute('aria-pressed', String(picking));
    host.render();
  }
  function clear() {
    points = []; picking = false; editing = false;
    loadedApproaches = []; approachEdited = false;
    gate('element-id', '');
    $('element-id').value = `e_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`;
    geometry();
  }
  function addPoint(x, y) {
    if (![x, y].every(v => Number.isFinite(v) && Math.abs(v) <= 1000) || points.length >= 32)
      throw new Error('좌표는 유한한 ±1000 m, 요소는 최대 32점입니다');
    points.push([Math.round(x * 1000) / 1000, Math.round(y * 1000) / 1000]);
    geometry();
  }
  function sync() {
    const map = host.map(), reason = host.reason();
    if ((map?.map_id || null) !== lastMapId) {
      lastMapId = map?.map_id || null;
      points = []; picking = false; editing = false; loadedApproaches = []; approachEdited = false;
      gate('element-id', ''); $('element-id').value = `e_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`;
      $('element-points').textContent = '찍은 좌표 없음'; $('element-pick').setAttribute('aria-pressed', 'false');
    }
    const draftReason = reason || (host.source() !== 'draft' ? '초안 보기로 바꾸세요' : '') || (!map?.survey ? '조사 기준이 있는 초안을 만드세요' : '');
    if (picking && (draftReason || mapId !== map?.map_id)) { picking = false; $('element-pick').setAttribute('aria-pressed', 'false'); }
    gate('survey-new', reason);
    for (const id of ['element-pick', 'element-point', 'element-clear', 'element-save']) gate(id, draftReason);
    gate('survey-review', reason || (host.source() !== 'draft' ? '초안 보기로 바꾸세요' : '')
      || (!map?.survey && !map?.edges?.some(e => e.evidence) ? '검토할 조사 또는 관측 도로가 없습니다' : ''));
    options('element-from', [['', '시작 장소 선택'], ...(map?.places || []).map(p => [p.id, p.name])]);
    options('element-to', [['', '끝 장소 선택'], ...(map?.places || []).map(p => [p.id, p.name])]);
    options('element-lanes', (map?.edges || []).map(e => [e.id, `${e.id} · ${e.from} → ${e.to}`]));
    options('element-existing', [['', '기존 요소 선택'], ...rows().map((row, i) => [`${row.category}:${row.id}`, `${i + 1} · ${row.name} · ${KINDS[row.kind] || row.kind}`])]);
    const selected = $('element-existing').value;
    for (const id of ['element-load', 'element-delete']) gate(id, draftReason || (!selected ? '기존 요소를 고르세요' : ''));
    gate('element-endpoints', draftReason || (!$('element-from').value || !$('element-to').value ? '시작·끝 장소를 고르세요' : ''));
    const kind = $('element-kind').value;
    $('element-road').hidden = kind !== 'road';
    $('element-signal').hidden = kind !== 'traffic_signal';
    $('element-approach').hidden = !['traffic_signal', 'stop_line'].includes(kind);
    $('element-heading').hidden = kind !== 'start';
    $('element-save').textContent = editing ? '초안 요소 수정' : '초안에 요소 추가';
    const reference = map?.survey;
    $('survey-reference').textContent = reference ? `${reference.reviewed ? '검토됨' : '검토 전'} · 원점 ${reference.origin.join(', ')} m · 방향 ${Math.round(reference.heading_rad * 180 / Math.PI)}° · ${reference.scale_source === 'measured' ? `실측 ${reference.measured_distance_m} m` : '장치 odom 축척'} · ${reference.description}` : '조사 기준 없음';
    $('survey-odometry-note').hidden = $('survey-scale').value !== 'odometry';
    gate('survey-distance', $('survey-scale').value !== 'measured' ? '실측 축척에서 입력합니다' : reason);
    const list = $('survey-elements');
    list.replaceChildren(...rows().map((row, i) => {
      const li = document.createElement('li');
      const evidence = row.evidence ? ` · ${{observed: '관측', inferred: '추정', reviewed: '검토됨'}[row.evidence.status]}` : '';
      const connections = row.approaches?.map(a => `${a.edge_id} ${a.forward ? '정방향' : '역방향'}${a.stop_s_m == null ? '' : ` ${a.stop_s_m} m`}`).join(', ');
      li.textContent = `${i + 1} · ${row.name} · ${KINDS[row.kind] || row.kind}${evidence}${connections ? ` · ${connections}` : ''}${row.signal_id ? ` · ${row.signal_kind === 'physical' ? '물리' : '가상'} ${row.signal_id}` : ''}`;
      return li;
    }));
  }
  $('survey-new').addEventListener('click', async () => {
    if (host.reason()) return;
    if (host.hasDraft() && !await confirmIrreversible({message: '기존 초안의 작업 내용을 빈 조사 초안으로 바꿀까요? 활성 지도는 유지됩니다.',
      action: '빈 조사 초안 만들기', opener: $('survey-new')})) return;
    act(() => {
      const id = `survey_${crypto.randomUUID()}`;
      host.changed(createSurveyDraft(id, {revision: id, origin: [number('survey-x'), number('survey-y')],
        heading_rad: number('survey-yaw') * Math.PI / 180, scale_source: $('survey-scale').value,
        measured_distance_m: $('survey-scale').value === 'measured' ? number('survey-distance') : null,
        description: $('survey-description').value.trim()}));
      clear(); message('빈 조사 초안을 만들었습니다. 요소를 추가한 뒤 초안을 저장하세요. 활성 지도는 유지됩니다.');
    });
  });
  $('element-pick').addEventListener('click', () => act(() => {
    picking = !picking; mapId = host.map().map_id;
    if (picking) host.begin();
    geometry(); message(picking ? '지도에서 위치를 찍으세요. 좌표 입력으로도 점을 추가할 수 있습니다.' : '점 찍기를 마쳤습니다.');
  }));
  $('element-point').addEventListener('click', () => act(() => addPoint(number('element-x'), number('element-y'))));
  $('element-clear').addEventListener('click', () => act(clear));
  $('element-endpoints').addEventListener('click', () => act(() => {
    const map = host.map(), a = map.places.find(p => p.id === $('element-from').value), b = map.places.find(p => p.id === $('element-to').value);
    if (!a || !b || a.id === b.id) throw new Error('서로 다른 시작·끝 장소를 고르세요');
    points = [[a.x, a.y], [b.x, b.y]]; geometry(); message('선택한 두 장소 사이의 직선입니다. 실제 도로 모양을 확인하고 추가하세요.');
  }));
  $('element-load').addEventListener('click', () => act(() => {
    const row = rows().find(r => `${r.category}:${r.id}` === $('element-existing').value);
    if (!row) return;
    editing = true; editingKind = row.kind; picking = false; points = row.geometry.map(p => [...p]);
    $('element-id').value = row.id; gate('element-id', '불러온 요소의 ID는 유지됩니다');
    $('element-name').value = row.name; $('element-kind').value = row.kind;
    $('element-from').value = row.from || ''; $('element-to').value = row.to || '';
    $('element-width').value = row.width_m || .2; $('element-direction').value = row.direction || 'one_way';
    $('element-yaw').value = (row.yaw || 0) * 180 / Math.PI;
    $('element-signal-id').value = row.signal_id || ''; $('element-signal-kind').value = row.signal_kind || 'virtual';
    const approaches = row.approaches || [];
    loadedApproaches = approaches; approachEdited = false;
    for (const option of $('element-lanes').options) option.selected = approaches.some(a => a.edge_id === option.value);
    $('element-forward').value = approaches[0]?.forward === false ? 'reverse' : 'forward';
    $('element-stop').value = approaches[0]?.stop_s_m ?? '';
    geometry(); message('기존 요소를 불러왔습니다. ID는 유지됩니다. 수정 후 다시 검토하세요.');
  }));
  $('element-delete').addEventListener('click', async () => {
    if (host.reason() || host.source() !== 'draft') return;
    const selected = $('element-existing').value, [category, id] = selected.split(':');
    if (!id || !await confirmIrreversible({message: '선택한 요소를 초안에서 삭제할까요? 연결된 도로·시설이 있으면 거절합니다.', action: '초안 요소 삭제', opener: $('element-delete')})) return;
    act(() => { host.changed(removeSurveyElement(host.map(), id, category)); clear(); message('초안 요소를 삭제했습니다. 변경 내용을 저장하세요.'); });
  });
  $('element-save').addEventListener('click', () => act(() => {
    if (host.source() !== 'draft') return;
    if (editing && $('element-kind').value !== editingKind) throw new Error('기존 요소의 종류를 유지하세요');
    const stop = $('element-stop').value;
    const item = {id: $('element-id').value, name: $('element-name').value, kind: $('element-kind').value, geometry: points,
      from: $('element-from').value, to: $('element-to').value, width_m: number('element-width'), direction: $('element-direction').value,
      yaw: $('element-kind').value === 'start' ? number('element-yaw') * Math.PI / 180 : undefined,
      signal_id: $('element-signal-id').value, signal_kind: $('element-signal-kind').value,
      approaches: [...$('element-lanes').selectedOptions].flatMap(o => {
        const existing = editing && !approachEdited ? loadedApproaches.filter(a => a.edge_id === o.value) : [];
        return existing.length ? existing : [{edge_id: o.value, forward: $('element-forward').value === 'forward', ...(stop === '' ? {} : {stop_s_m: Number(stop)})}];
      })};
    host.changed((editing ? editSurveyElement : appendSurveyElement)(host.map(), item));
    clear(); message('요소를 초안에 반영했습니다. 저장·검토·활성화는 각각 별도입니다.');
  }));
  $('survey-review').addEventListener('click', () => act(() => {
    if (host.source() !== 'draft') return;
    host.changed(reviewSurveyDraft(host.map(), $('survey-review-note').value));
    message('검토 근거를 초안에 반영했습니다. 초안을 저장한 뒤 활성화를 선택하세요.');
  }));
  for (const id of ['element-kind', 'element-from', 'element-to', 'element-existing', 'survey-scale']) $(id).addEventListener('change', sync);
  for (const id of ['element-forward', 'element-stop']) $(id).addEventListener('input', () => { approachEdited = true; });
  $('element-id').value = `e_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`;
  return {sync, cancel: clear, points: () => picking ? points : [], picking: () => picking,
    pick(event) {
      if (!picking || host.reason() || host.source() !== 'draft' || !host.view()) return false;
      const at = new DOMPoint(event.clientX, event.clientY).matrixTransform(event.currentTarget.getScreenCTM().inverse());
      act(() => addPoint(...host.view().toMap(at.x, at.y)));
      return true;
    }};
}
