// D-655 camera import and reviewed endpoint connections; draft writes only.
import {confirmIrreversible} from '/common/ui.js';
import {cameraConnectionCandidates, mergeCameraMap} from '/console/assets/site-map-edit.js';

export function createCameraMapPanel(host) {
  const $ = id => document.getElementById(id);
  let revision = null, file = null, epoch = 0, context = '';
  const fields = () => [...$('camera-connections').querySelectorAll('select')];
  function reset() {
    epoch++;
    $('camera-connections').replaceChildren();
    $('camera-connect-check').hidden = true; $('camera-connect-confirm').checked = false;
  }
  function gate(id, reason) {
    $(id).disabled = Boolean(reason);
    if (reason) $(id).setAttribute('reason', reason); else $(id).removeAttribute('reason');
  }
  function sync() {
    const current = $('camera-map-file').files[0], draft = host.draft();
    if (current !== file || draft?.revision !== revision) { reset(); file = current; revision = draft?.revision; }
    const nextContext = JSON.stringify([draft, host.dirty(), host.reason(), host.context()]);
    if (nextContext !== context) { epoch++; context = nextContext; }
    const source = host.reason() || (!current ? '카메라 관측 JSON 파일을 고르세요' : '');
    const survey = source || (host.dirty() ? '수정한 초안을 먼저 저장하세요' : '')
      || (!draft?.map?.survey ? '조사 기준이 있는 초안을 먼저 저장하세요' : '');
    gate('import-camera-map', source);
    gate('preview-camera-connections', survey);
    gate('merge-camera-map', survey || (fields().length &&
      (!fields().every(field => field.value) || !$('camera-connect-confirm').checked) ? '연결 장소를 선택하고 실제 연결을 확인하세요' : ''));
  }
  async function read(current) {
    if (!current || current.size > 2 * 1024 * 1024 - 1024) throw new Error('지도 초안 파일은 2 MiB보다 작아야 합니다.');
    const map = JSON.parse(await current.text());
    if (map?.schema !== 'rosy.site_map/1') throw new Error('rosy.site_map/1 지도 초안 파일이 필요합니다.');
    return map;
  }
  $('camera-map-file').addEventListener('change', sync);
  $('preview-camera-connections').addEventListener('click', () => host.guarded(async () => {
    if (host.reason() || host.dirty()) return;
    sync(); reset();
    const current = file, expected = revision, requestEpoch = epoch;
    const observation = await read(current);
    sync();
    if (epoch !== requestEpoch || current !== $('camera-map-file').files[0] || expected !== host.draft()?.revision) return;
    const candidates = cameraConnectionCandidates(host.draft()?.map, observation);
    for (const row of candidates) {
      const label = document.createElement('label');
      label.textContent = `${row.name} · 관측 ${row.x}, ${row.y} m → `;
      const select = document.createElement('select');
      select.className = 'ui-field'; select.dataset.observationId = row.observation_id;
      select.append(new Option('연결할 기존 장소를 확인해 선택', ''), ...row.candidates.map(p =>
        new Option(`${p.name} · ${p.x}, ${p.y} m · 거리 ${p.distance_m.toFixed(3)} m`, p.id)));
      select.addEventListener('change', () => { epoch++; $('camera-connect-confirm').checked = false; sync(); });
      label.append(select); $('camera-connections').append(label);
    }
    $('camera-connect-check').hidden = !candidates.length;
    host.notice(candidates.length ? '후보 장소와 실제 도로 연결을 확인하세요. 접합은 추정 근거로 저장됩니다.' : '가까운 연결 후보가 없습니다. 관측을 별도 차로로 누적할 수 있습니다.');
    sync();
  }));
  $('camera-connect-confirm').addEventListener('change', () => { epoch++; sync(); });
  for (const button of ['import-camera-map', 'merge-camera-map']) $(button).addEventListener('click', () => host.guarded(async () => {
    if (host.reason()) return;
    sync();
    const accumulate = button === 'merge-camera-map', expected = host.draft()?.revision || null, base = host.draft()?.map;
    if (accumulate && (host.dirty() || !base?.survey)) throw new Error('조사 기준이 있는 초안을 먼저 저장하세요');
    const current = $('camera-map-file').files[0];
    if (!current) return;
    const requestEpoch = epoch, joins = Object.fromEntries(fields().map(field => [field.dataset.observationId, field.value]));
    const confirmed = !fields().length || (Object.values(joins).every(Boolean) && $('camera-connect-confirm').checked);
    const checkContext = () => {
      sync();
      if (epoch !== requestEpoch || host.reason() || current !== $('camera-map-file').files[0])
        throw new Error('초안·파일·연결 선택이 바뀌었습니다 · 다시 확인하세요');
    };
    let map = await read(current);
    checkContext();
    if (current !== $('camera-map-file').files[0] || expected !== (host.draft()?.revision || null))
      throw new Error('초안 또는 파일이 바뀌었습니다 · 연결을 다시 확인하세요');
    if (accumulate) {
      if (host.dirty()) throw new Error('수정한 초안을 먼저 저장하세요');
      if (!confirmed)
        throw new Error('연결 장소를 선택하고 실제 연결을 확인하세요');
      map = mergeCameraMap(base, map, joins);
    } else if (host.dirty() || expected) {
      if (!await confirmIrreversible({message: '기존 초안을 카메라 지도 초안으로 바꿀까요? 활성 지도는 바뀌지 않습니다.',
        action: '카메라 초안 가져오기', opener: $(button)})) return;
    }
    checkContext();
    await host.request('/api/fleet/site-map/draft', {method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({map, expected_revision: expected})});
    await host.reload();
    host.notice(accumulate ? '카메라 관측을 초안에 누적했습니다. 연결·통행 방향을 검토하세요.' : '카메라 지도 초안을 가져왔습니다. 차로 연결·통행 방향을 검토한 뒤 활성화하세요.');
  }));
  return {sync};
}
