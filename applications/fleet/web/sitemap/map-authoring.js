// Page composition: input adapter, local history and Fleet geometry adapter.
import {confirmIrreversible} from '/common/ui.js';
import {createEditHistory} from '/console/assets/edit-history.js';
import {createDrawingImport, rasterMapPoint} from '/console/assets/drawing-import.js';
import {createMapEditor, svgElement} from '/console/assets/map-editor.js';
import {createExtractionPanel} from '/console/assets/extraction-review.js';
import {siteMapErrorText} from '/console/assets/site-map-model.js';
import {ensureSurvey} from '/console/assets/site-map-edit.js';
import {fetchMapPlane} from '/console/assets/vision-view.js';

const $ = id => document.getElementById(id);
export function createMapAuthoring(host) {
  const history = createEditHistory(null);
  let projection = null, loadingHash = null, cacheController = null, rasterUrl = null;
  const message = text => { $('drawing-status').textContent = text; };
  const changed = next => { ensureSurvey(next); history.apply(next); host.changed(history.current()); };
  const importer = createDrawingImport({request: host.request, map: host.draft,
    replaceDraft: next => { changed(next); },
    confirmDiscard: () => true});
  const editReason = () => host.reason() || (!host.draft() && !host.map() ? '먼저 도면을 맞추거나 조사 초안을 만드세요' : '');
  const editor = createMapEditor({svg: host.svg, map: host.map, view: host.view, changed, reason: editReason});
  const extraction = createExtractionPanel({request: host.request, changed,
    context: () => ({draft: host.draft(), epoch: host.epoch(), projection, reason: editReason()}), render: host.render});
  const act = async operation => {
    if (host.reason()) { message(host.reason()); return; }
    try { await operation(); } catch (error) { if (error.name !== 'AbortError') message(siteMapErrorText(error)); }
    sync();
  };
  $('drawing-file').addEventListener('change', () => act(async () => {
    message('도면 업로드 중');
    const result = await importer.load($('drawing-file').files[0]);
    if (result) {
      const raster = ['png', 'jpeg'].includes(result.format);
      for (const id of ['drawing-plane', 'drawing-unit']) {
        $(id).disabled = raster;
        if (raster) $(id).setAttribute('reason', '이미지 도면은 정규화 픽셀 좌표를 사용합니다');
        else $(id).removeAttribute('reason');
      }
      message(raster ? `원본 확인 · ${result.width_px} × ${result.height_px} px · 기준점은 정규화 이미지 픽셀입니다`
        : `원본 확인 · ${result.triangle_count}개 삼각형 · 좌표 범위 ${JSON.stringify(result.bounds_3d)}`);
    }
  }));
  $('drawing-register').addEventListener('click', () => act(async () => {
    const number = id => {
      if (!$(id).value.trim()) throw new Error('좌표와 실측 거리를 입력하세요');
      const value = Number($(id).value);
      if (!Number.isFinite(value)) throw new Error('좌표와 실측 거리는 유한한 수여야 합니다');
      return value;
    };
    const origin = [number('drawing-source-x'), number('drawing-source-y')];
    const distance = number('drawing-distance');
    const sourceDistance = Math.hypot(number('drawing-axis-x') - origin[0], number('drawing-axis-y') - origin[1]);
    const unit = $('drawing-unit').value;
    if (!(sourceDistance > 0 && distance > 0)) throw new Error('서로 다른 기준 두 점과 양수 실측 거리가 필요합니다');
    const raster = ['png', 'jpeg'].includes(importer.source()?.format);
    const transform = {map_origin_m: [number('drawing-map-x'), number('drawing-map-y')],
      heading_rad: number('drawing-rotation') * Math.PI / 180,
      ...(raster ? {source_origin_px: origin, meters_per_pixel: distance / sourceDistance}
        : {plane: $('drawing-plane').value, unit, source_origin: origin,
          scale: distance / (sourceDistance * {m: 1, cm: .01, mm: .001}[unit])})};
    const result = await importer.register(transform,
      {measured_distance_m: distance, description: $('drawing-description').value});
    if (result) message('맞춤 완료 · 도면은 배경이며 그린 요소는 초안에 보존했습니다. 현장 기준을 다시 검토하세요');
  }));
  $('drawing-cancel').addEventListener('click', () => { importer.cancel(); message('도면 요청을 취소했습니다. 초안은 그대로입니다'); });
  if ($('drawing-from-camera')) {
    $('drawing-from-camera').addEventListener('click', () => act(async () => {
      host.begin();
      const sourceId = $('plane-source')?.value || $('camera-draft-source')?.value || 'ceiling_north';
      $('extract-status').textContent = `카메라(${sourceId}) 평면 영상을 도면으로 등록하고 선·윤곽을 추출하는 중…`;
      let imgBlob = null, minX = -1.22, maxY = 0.61, ppm = 400, widthPx = 976, heightPx = 488;
      try {
        const got = await fetchMapPlane(host.request, sourceId, null, AbortSignal.timeout(8000));
        if (got.state === 'live' && got.blob) {
          imgBlob = got.blob;
          const url = URL.createObjectURL(got.blob);
          try {
            const img = new Image(); img.src = url; await img.decode();
            widthPx = img.naturalWidth || 976; heightPx = img.naturalHeight || 488;
            if (got.plane) {
              minX = Number.isFinite(got.plane.min_x) ? got.plane.min_x : -1.22;
              maxY = Number.isFinite(got.plane.max_y) ? got.plane.max_y : 0.61;
              ppm = Number.isFinite(got.plane.ppm) && got.plane.ppm > 0 ? got.plane.ppm : widthPx / 2.44;
            }
          } finally { URL.revokeObjectURL(url); }
        }
      } catch {}
      if (!imgBlob) {
        message('보정된 카메라 평면 영상을 가져올 수 없습니다. 먼저 카메라 설치·보정을 확인하세요');
        return;
      }
      const ext = imgBlob.type === 'image/png' ? 'png' : 'jpg';
      const file = new File([imgBlob], `${sourceId}_plane.${ext}`, {type: imgBlob.type || 'image/jpeg'});
      const uploaded = await importer.load(file);
      if (!uploaded) return;
      const reg = await importer.register({
        source_origin_px: [0, 0],
        meters_per_pixel: 1 / ppm,
        map_origin_m: [minX, maxY],
        heading_rad: 0,
      }, {
        measured_distance_m: Number((widthPx / ppm).toFixed(3)),
        description: `보정 카메라(${sourceId}) 평면 자동 맞춤 (${widthPx}×${heightPx} px, ${Math.round(ppm)} px/m)`,
      });
      if (reg) {
        if (rasterUrl) URL.revokeObjectURL(rasterUrl);
        rasterUrl = URL.createObjectURL(imgBlob);
        loadingHash = reg.projection_sha256;
        projection = reg;
        $('extract-x0').value = 0; $('extract-y0').value = 0;
        $('extract-x1').value = reg.width_px || widthPx; $('extract-y1').value = reg.height_px || heightPx;
        sync();
        host.render();
        $('extract-run').click();
      }
    }));
  }
  for (const field of $('drawing-tools').querySelectorAll('input:not([type=file]), select'))
    field.addEventListener('input', importer.cancelRegistration);
  $('editor-enabled').addEventListener('change', () => { host.begin(); editor.cancel(); host.render(); });
  $('editor-kind').addEventListener('change', () => {
    if ($('editor-kind').value !== 'select' && !$('editor-enabled').checked) {
      $('editor-enabled').checked = true;
    }
    if ($('editor-enabled').checked) host.begin();
    editor.cancel(); host.render();
  });
  const step = operation => {
    if (editReason()) { host.notice(editReason()); return; }
    editor.cancel(); host.changed(history[operation]());
  };
  $('editor-undo').addEventListener('click', () => step('undo'));
  $('editor-redo').addEventListener('click', () => step('redo'));
  $('editor-zoom').addEventListener('change', () => {
    const zoom = Number($('editor-zoom').value), width = 800 / zoom, height = 480 / zoom;
    host.svg.setAttribute('viewBox', `${(800 - width) / 2} ${(480 - height) / 2} ${width} ${height}`);
  });
  for (const [direction, dx, dy] of [['left', -1, 0], ['right', 1, 0], ['up', 0, -1], ['down', 0, 1]]) {
    $(`editor-pan-${direction}`).addEventListener('click', () => {
      const {x, y, width, height} = host.svg.viewBox.baseVal;
      host.svg.setAttribute('viewBox', `${x + dx * width / 4} ${y + dy * height / 4} ${width} ${height}`);
    });
  }
  const shortcut = event => {
    if (!editReason() && !editor.drawing() && (event.ctrlKey || event.metaKey)
        && ['z', 'y'].includes(event.key.toLowerCase())
        && !event.target.closest('input, textarea, select, [contenteditable="true"]')) {
      event.preventDefault();
      step(event.shiftKey || event.key.toLowerCase() === 'y' ? 'redo' : 'undo');
    }
  };
  document.addEventListener('keydown', shortcut);
  const leaving = event => {
    if (host.dirty() || editor.drawing()) { event.preventDefault(); event.returnValue = ''; }
  };
  window.addEventListener('beforeunload', leaving);
  function sync() {
    extraction.sync();
    const working = host.draft();
    if (!host.dirty()) history.reset(working);
    else if (JSON.stringify(history.current()) !== JSON.stringify(working)) history.apply(working);
    for (const [id, reason] of [
      ['editor-undo', editReason() || (!history.canUndo() ? '실행 취소할 변경이 없습니다' : '')],
      ['editor-redo', editReason() || (!history.canRedo() ? '다시 실행할 변경이 없습니다' : '')],
      ['drawing-file', host.reason()],
      ...($('drawing-from-camera') ? [['drawing-from-camera', host.reason()]] : []),
    ]) {
      $(id).disabled = Boolean(reason);
      if (reason) $(id).setAttribute('reason', reason); else $(id).removeAttribute('reason');
      $(id).title = reason;
    }
    const registrationReason = host.reason() || (!importer.ready() ? '도면 원본을 먼저 확인하세요' : '');
    $('drawing-register').disabled = Boolean(registrationReason);
    if (registrationReason) $('drawing-register').setAttribute('reason', registrationReason);
    else $('drawing-register').removeAttribute('reason');
    const hash = host.map()?.drawing?.projection_sha256;
    if (hash !== loadingHash) {
      cacheController?.abort(); projection = null; loadingHash = hash;
      if (rasterUrl) URL.revokeObjectURL(rasterUrl);
      rasterUrl = null;
      if (hash) {
        const controller = cacheController = new AbortController();
        host.request(`/api/fleet/site-map/drawing-projections/${hash}`, {signal: controller.signal})
          .then(async result => {
            if (controller.signal.aborted || loadingHash !== hash) return;
            if (result.kind === 'raster') {
              const {blob} = await host.request(`/api/fleet/site-map/drawing-projections/${hash}/render`,
                {blob: true, signal: controller.signal, timeoutMs: 10000});
              if (controller.signal.aborted || loadingHash !== hash) return;
              if (blob.type !== 'image/png' || blob.size > 16 * 1024 * 1024) throw new Error('도면 이미지 형식을 확인하세요');
              rasterUrl = URL.createObjectURL(blob);
            }
            projection = result; host.render();
          })
          .catch(error => { if (error.name !== 'AbortError') message(`도면 배경 확인 실패 · ${error.message}`); });
      }
    }
  }
  return {
    sync,
    discs: () => projection?.bounds_m.map(([x, y]) => ({x, y, r: 0})) || [],
    paint() {
      const view = host.view();
      if (projection && view) {
        if (projection.kind === 'raster' && rasterUrl) {
          const at = (u, v) => view.toPx(...rasterMapPoint([u, v], projection.transform));
          const [x, y] = at(0, 0), [xx, xy] = at(1, 0), [yx, yy] = at(0, 1);
          const image = svgElement('image', {'data-drawing': projection.projection_sha256, href: rasterUrl,
            width: projection.width_px, height: projection.height_px, preserveAspectRatio: 'none',
            transform: `matrix(${xx - x} ${xy - y} ${yx - x} ${yy - y} ${x} ${y})`}, host.svg);
          host.svg.prepend(image);
          extraction.paint(host.svg, view); editor.sync(); return;
        }
        const [x, y] = view.toPx(0, 0), [xx, xy] = view.toPx(1, 0), [yx, yy] = view.toPx(0, 1);
        const path = svgElement('path', {'data-drawing': projection.projection_sha256, class: 'drawing-background',
          d: projection.segments.map(([a, b]) => `M${a.join(',')}L${b.join(',')}`).join(''),
          transform: `matrix(${xx - x} ${xy - y} ${yx - x} ${yy - y} ${x} ${y})`}, host.svg);
        host.svg.prepend(path);
      }
      editor.sync();
    },
    destroy() {
      importer.cancel(); cacheController?.abort(); editor.destroy();
      extraction.destroy();
      if (rasterUrl) URL.revokeObjectURL(rasterUrl);
      document.removeEventListener('keydown', shortcut); window.removeEventListener('beforeunload', leaving);
    },
  };
}
