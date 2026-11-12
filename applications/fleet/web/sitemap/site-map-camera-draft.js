// 카메라로 초안 만들기 — Vision의 draft-map 제안을 Fleet이 검증한 초안 본문으로 (v1.385).
// 브라우저가 Fleet 발급 lease로 Vision에서 파생 JSON을 직접 가져오는 D-375 패턴을 따른다.
// 저장은 기존 PUT 초안 경로: 이 패널은 후보를 만들 뿐 쓰지 않는다.
import {confirmIrreversible} from '/common/ui.js';

const VERDICT = {  // POST reality-check의 camera 판정 (site-map-reality 패널과 같은 어휘)
  agree: '지도·카메라·운행 기록이 모두 일치합니다',
  map_offset: '운행과 카메라가 일치합니다 — 지도 초안 보정을 권장합니다',
  camera_drift: '지도와 운행이 일치합니다 — 카메라 보정(추적 보정 화면)을 권장합니다',
  drive_outlier: '지도와 카메라가 일치합니다 — 운행 기록을 확인하세요',
  unknown: '셋의 어긋남이 둘 이상이라 자동 판정할 수 없습니다',
  no_evidence_drive: '이 구간에 운행 기록이 없습니다',
};

export function createCameraDraftPanel(host) {
  const $ = id => document.getElementById(id);
  let sources = [], lease = null, leaseExpiresAt = 0, busy = false, loading = false, unavailable = false;

  async function refreshSources() {
    if (sources.length) return;
    const result = await host.request('/api/fleet/vision/sources');
    sources = result.sources || [];
    const keep = $('camera-draft-source').value;
    $('camera-draft-source').replaceChildren(new Option('카메라를 고르세요', ''),
      ...sources.map(source => new Option(source, source)));
    if ([...$('camera-draft-source').options].some(option => option.value === keep)) {
      $('camera-draft-source').value = keep;
    }
    host.sync();
  }

  async function fetchDraftMap() {
    const source = $('camera-draft-source').value;
    if (!source) throw new Error('보정된 카메라를 먼저 선택하세요.');
    if (!lease || lease.source !== source || Date.now() >= leaseExpiresAt) {
      lease = await host.request('/api/fleet/vision/lease', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source_id: source})});
      lease.source = source;
      leaseExpiresAt = Date.now() + 45000;
    }
    const path = lease.frame_path.replace(/\/frame$/, '/draft-map');
    const response = await fetch(path, {credentials: 'omit', redirect: 'error',
      headers: {Authorization: `Bearer ${lease.lease}`}, cache: 'no-store'});
    if (response.status === 429) throw new Error('Vision이 프레임을 읽는 중입니다. 잠시 뒤 다시 누르세요.');
    if (response.status === 409) throw new Error('이 카메라에는 승인된 추적 보정이 없습니다. 먼저 보정하세요.');
    if (!response.ok) throw new Error(`Vision 응답 ${response.status}`);
    return response.json();
  }

  async function run() {
    if (host.reason()) return;
    busy = true;
    host.status('camera-draft-status', '프레임을 읽고 후보를 뽑는 중…', 'pending');
    try {
      await refreshSources();
      const proposal = await fetchDraftMap();
      const made = await host.request('/api/fleet/site-map/draft-from-camera', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source_id: proposal.source, plane: {
          bounds_m: proposal.plane.bounds_m, px_per_m: proposal.plane.px_per_m,
          calibration_revision: proposal.plane.calibration_revision},
          detector: proposal.detector, lanes: proposal.lanes, zones: proposal.zones,
          ...(proposal.places ? {places: proposal.places} : {}),
          ...(proposal.edges ? {edges: proposal.edges} : {}),
          ...(proposal.map_id ? {map_id: proposal.map_id} : {})})});
      const {map, provenance} = made;
      if (!map.edges.length && !map.facilities.length) {
        throw new Error('이 프레임에서 차로·구역 후보를 찾지 못했습니다. 카메라 각도·조명을 확인하세요.');
      }
      const draft = host.draft();
      if (draft?.revision || host.dirty()) {
        const allowed = await confirmIrreversible({
          message: '기존 초안을 카메라 초안으로 바꿀까요? 지금 고친 내용은 사라집니다.',
          action: '카메라 초안으로 교체', opener: $('camera-draft-run')});
        if (!allowed) throw new Error('교체를 취소했습니다. 기존 초안은 그대로입니다.');
      }
      await host.request('/api/fleet/site-map/draft', {
        method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({map, expected_revision: draft?.revision || null})});
      await host.reload();
      host.status('camera-draft-status',
        `카메라 초안 저장 · 차로 ${provenance.lanes}개·구역 ${provenance.zones}개`, 'ready');
      host.notice(`카메라 초안을 저장했습니다 · 차로 ${provenance.lanes}개·구역 ${provenance.zones}개`
        + (provenance.skipped.length ? ` · 건너뜀 ${provenance.skipped.length}개` : '')
        + '. 검토하고 활성화하세요.');
    } catch (error) {
      host.status('camera-draft-status', error.message, 'error');
      host.notice(error.message);
      busy = false;
      host.sync();
      return;
    }
    busy = false;
    host.sync();
  }

  $('camera-draft-run').addEventListener('click', () => host.guarded(run));

  return {
    sync() {
      if (!sources.length && !unavailable && !host.reason() && !loading) {   // populate once connected (C1)
        loading = true;
        refreshSources().then(() => { loading = false; host.sync(); })
          .catch(error => {
            loading = false;
            if (error.status === 503) {          // Vision preview is not configured on this Fleet
              unavailable = true;
              host.status('camera-draft-status', '카메라 미리보기가 꺼져 있습니다(vision 설정)', 'error');
            }
          });
      }
      host.gate('camera-draft-run', busy ? '작업 중입니다'
        : unavailable ? '카메라 미리보기가 꺼져 있습니다'
        : $('camera-draft-source').value ? '' : '카메라를 고르세요');
    },
    refreshSources,
  };
}

export const CAMERA_VERDICT_TEXT = verdict => VERDICT[verdict] || `카메라 판정 ${verdict}`;
