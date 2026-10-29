import {randomUUID} from "/console/assets/uuid.js";
// Candidate review only; accepting changes a local draft after server geometry validation.
import {appendSurveyElement} from '/console/assets/site-map-edit.js';
import {rasterMapPoint} from '/console/assets/drawing-import.js';
import {svgElement} from '/console/assets/map-editor.js';
import {siteMapErrorText} from '/console/assets/site-map-model.js';

const clone = value => JSON.parse(JSON.stringify(value));
export function createExtractionReview({request, context, changed}) {
  let result = null, selected = null, geometry = [], snapshot = null, generation = 0, controller = null, busy = false;
  const touch = () => { generation++; controller?.abort(); busy = false; };
  const cancel = () => { touch(); result = null; selected = null; geometry = []; snapshot = null; };
  function check(before) {
    const now = context();
    if (!before || now.reason || now.draft !== before.draft || now.epoch !== before.epoch
        || now.projection?.projection_sha256 !== before.projection?.projection_sha256)
      throw new Error('편집 기준이 바뀌었습니다. 후보를 다시 추출하세요');
  }
  return {
    cancel,
    state: () => ({result, selected, geometry: clone(geometry), busy}),
    sync() { if (snapshot) { try { check(snapshot); } catch { cancel(); } } },
    async run(spec) {
      cancel();
      const before = context();
      if (before.reason) throw new Error(before.reason);
      if (before.projection?.kind !== 'raster' || !before.draft?.survey
          || before.draft.drawing?.projection_sha256 !== before.projection.projection_sha256)
        throw new Error('먼저 이미지 도면을 초안 좌표에 맞추세요');
      snapshot = before; busy = true; controller = new AbortController();
      const attempt = generation;
      try {
        const response = await request(`/api/fleet/site-map/drawing-projections/${before.projection.projection_sha256}/extractions`,
          {method: 'POST', body: JSON.stringify(spec), headers: {'Content-Type': 'application/json'},
            signal: controller.signal, timeoutMs: 15000});
        check(before);
        if (attempt !== generation) throw new Error('요청이 바뀌었습니다. 후보를 다시 추출하세요');
        if (response.projection_sha256 !== before.projection.projection_sha256
            || response.asset_sha256 !== before.projection.asset_sha256) throw new Error('후보의 도면 기준이 다릅니다');
        result = response;
        return result;
      } finally { if (attempt === generation) busy = false; }
    },
    select(id) {
      check(snapshot);
      const candidate = result?.candidates.find(c => c.candidate_id === id);
      if (!candidate) throw new Error('추출 후보를 고르세요');
      touch(); selected = id; geometry = clone(candidate.geometry_px);
    },
    update(points) {
      check(snapshot);
      if (!selected || !Array.isArray(points) || points.length < 2 || points.length > 32
          || !points.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite)))
        throw new Error('후보 꼭짓점은 유한한 픽셀 좌표 2~32개로 입력하세요');
      touch(); geometry = clone(points);
    },
    async accept(item) {
      check(snapshot);
      if (!selected || !['road', 'stop_line', 'exclusion'].includes(item.kind)) throw new Error('후보와 용도를 고르세요');
      const before = snapshot, attempt = generation, id = `e_${randomUUID().replaceAll('-', '').slice(0, 12)}`;
      const next = appendSurveyElement(before.draft, {...item, id,
        geometry: geometry.map(p => rasterMapPoint(p, before.projection.transform))});
      const row = item.kind === 'road' ? next.edges.find(e => e.id === id) : next.facilities.find(f => f.id === id);
      row.evidence = {source: 'operator', status: 'observed', reference_revision: before.projection.projection_sha256,
        note: `extraction:${result.extraction_sha256} candidate:${selected}`};
      controller = new AbortController(); busy = true;
      try {
        const checked = await request(`/api/fleet/site-map/drawing-extractions/${result.extraction_sha256}/validate`,
          {method: 'POST', body: JSON.stringify({map: next}), headers: {'Content-Type': 'application/json'},
            signal: controller.signal, timeoutMs: 10000});
        check(before);
        if (attempt !== generation) throw new Error('후보가 바뀌었습니다. 다시 확인하세요');
        cancel(); changed(checked.map);
      } finally { if (attempt === generation) busy = false; }
    },
  };
}

export function createExtractionPanel(host) {
  const $ = id => document.getElementById(id), status = text => { $('extract-status').textContent = text; };
  const review = createExtractionReview(host);
  let lastResult = null, lastProjection = null, placeSignature = null;
  const act = async operation => {
    try { const pending = operation(); sync(); await pending; }
    catch (error) { if (error.name !== 'AbortError') status(siteMapErrorText(error)); }
    sync(); host.render();
  };
  $('extract-run').addEventListener('click', () => act(async () => {
    status('선·윤곽 후보를 찾고 있습니다');
    const number = id => { if (!$(id).value.trim()) throw new Error('추출 범위와 설정을 입력하세요'); return Number($(id).value); };
    const response = await review.run({method: $('extract-method').value,
      crop_px: ['extract-x0', 'extract-y0', 'extract-x1', 'extract-y1'].map(number),
      settings: {min_line_length_px: number('extract-min-length'), tolerance_px: number('extract-tolerance')}});
    status(response.candidates.length ? `${response.candidates.length}개 후보 · 용도를 정하고 필요한 후보만 확인하세요`
      : '선택한 범위에서 후보를 찾지 못했습니다. 범위·설정을 바꾸거나 직접 그리세요');
  }));
  $('extract-cancel').addEventListener('click', () => { review.cancel(); status('후보를 취소했습니다. 초안은 그대로입니다'); sync(); host.render(); });
  $('extract-candidate').addEventListener('change', () => act(() => {
    review.select($('extract-candidate').value);
    $('extract-geometry').value = review.state().geometry.map(p => p.join(',')).join('\n');
  }));
  const update = () => review.update($('extract-geometry').value.trim().split('\n').map(row => row.split(',').map(v => {
    if (!v.trim()) throw new Error('한 줄에 x,y 픽셀 좌표를 입력하세요'); return Number(v);
  })));
  $('extract-preview').addEventListener('click', () => act(update));
  $('extract-accept').addEventListener('click', () => act(async () => {
    update();
    await review.accept({kind: $('extract-kind').value, name: $('extract-name').value,
      from: $('extract-from').value, to: $('extract-to').value,
      width_m: Number($('extract-width').value), direction: $('extract-direction').value});
    status('선택한 후보를 초안에 반영했습니다. 실행 취소할 수 있으며 저장·검토·활성화는 별도입니다');
  }));
  function sync() {
    review.sync();
    const {result, busy, selected} = review.state(), context = host.context(), projection = context.projection;
    const reason = context.reason || (projection?.kind !== 'raster' ? '이미지 도면을 초안 좌표에 먼저 맞추세요' : '');
    for (const [id, blocked] of [['extract-run', reason || (busy ? '추출 또는 검증 중입니다' : '')],
      ['extract-preview', reason || (!selected ? '후보를 고르세요' : busy ? '처리 중입니다' : '')],
      ['extract-accept', reason || (!selected ? '후보를 고르세요' : busy ? '처리 중입니다' : '')]]) {
      $(id).disabled = Boolean(blocked); $(id).title = blocked;
      if (blocked) $(id).setAttribute('reason', blocked); else $(id).removeAttribute('reason');
    }
    if (projection?.projection_sha256 !== lastProjection) {
      lastProjection = projection?.projection_sha256;
      $('extract-x0').value = 0; $('extract-y0').value = 0;
      $('extract-x1').value = projection?.width_px || 1; $('extract-y1').value = projection?.height_px || 1;
    }
    if (result !== lastResult) {
      lastResult = result;
      $('extract-candidate').replaceChildren(new Option('후보 선택', ''), ...(result?.candidates || [])
        .map((c, i) => new Option(`${i + 1} · ${c.closed ? '윤곽' : '선'} · ${c.geometry_px.length}점${c.is_hole ? ' · 구멍 경계' : ''}`, c.candidate_id)));
      $('extract-geometry').value = '';
    }
    const places = context.draft?.places || [], signature = JSON.stringify(places.map(p => [p.id, p.name]));
    if (signature !== placeSignature) {
      placeSignature = signature;
      for (const id of ['extract-from', 'extract-to']) {
        const value = $(id).value;
        $(id).replaceChildren(new Option('장소 선택', ''), ...places.map(p => new Option(p.name, p.id)));
        $(id).value = value;
      }
    }
  }
  return {sync, destroy: review.cancel,
    paint(svg, view) {
      const {geometry, result, selected} = review.state(), projection = host.context().projection;
      if (!geometry.length || !view || !projection) return;
      const closed = result?.candidates.find(c => c.candidate_id === selected)?.closed;
      svgElement(closed ? 'polygon' : 'polyline', {class: 'extraction-preview', points: geometry
        .map(p => view.toPx(...rasterMapPoint(p, projection.transform)).join(',')).join(' ')}, svg);
    },
  };
}
