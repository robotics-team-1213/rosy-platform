// Page composition: input adapter, local history and Fleet geometry adapter.
import {confirmIrreversible} from '/common/ui.js';
import {createEditHistory} from '/console/assets/edit-history.js';
import {createDrawingImport} from '/console/assets/drawing-import.js';
import {createMapEditor, svgElement} from '/console/assets/map-editor.js';

const $ = id => document.getElementById(id);
export function createMapAuthoring(host) {
  const history = createEditHistory(null);
  let projection = null, loadingHash = null, cacheController = null;
  const message = text => { $('drawing-status').textContent = text; };
  const changed = next => { history.apply(next); host.changed(history.current()); };
  const importer = createDrawingImport({request: host.request, map: host.draft,
    replaceDraft: (next, result) => { projection = result; loadingHash = result.projection_sha256; changed(next); },
    confirmDiscard: () => !host.dirty() || confirmIrreversible({
      message: '도면 기준을 바꾸고 검토 상태를 초기화할까요? 그린 요소는 보존합니다.',
      action: '도면 기준 바꾸기', opener: $('drawing-register')})});
  const editReason = () => host.reason() || (host.source() !== 'draft' ? '직접 편집은 초안에서 하세요'
    : !host.map()?.survey ? '먼저 도면을 맞추거나 조사 초안을 만드세요' : '');
  const editor = createMapEditor({svg: host.svg, map: host.map, view: host.view, changed, reason: editReason});
  const act = async operation => {
    if (host.reason()) { message(host.reason()); return; }
    try { await operation(); } catch (error) { if (error.name !== 'AbortError') message(error.message); }
    sync();
  };
  $('drawing-file').addEventListener('change', () => act(async () => {
    message('도면 업로드 중');
    const result = await importer.load($('drawing-file').files[0]);
    if (result) message(`원본 확인 · ${result.triangle_count}개 삼각형 · 좌표 범위 ${JSON.stringify(result.bounds_3d)}`);
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
    const result = await importer.register({plane: $('drawing-plane').value, unit, source_origin: origin,
      map_origin_m: [number('drawing-map-x'), number('drawing-map-y')],
      heading_rad: number('drawing-rotation') * Math.PI / 180,
      scale: distance / (sourceDistance * {m: 1, cm: .01, mm: .001}[unit])},
      {measured_distance_m: distance, description: $('drawing-description').value});
    if (result) message('맞춤 완료 · 도면은 배경이며 그린 요소는 초안에 보존했습니다. 현장 기준을 다시 검토하세요');
  }));
  $('drawing-cancel').addEventListener('click', () => { importer.cancel(); message('도면 요청을 취소했습니다. 초안은 그대로입니다'); });
  for (const field of $('drawing-tools').querySelectorAll('input:not([type=file]), select'))
    field.addEventListener('input', importer.cancelRegistration);
  $('editor-enabled').addEventListener('change', () => { host.begin(); editor.cancel(); host.render(); });
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
    const working = host.draft();
    if (!host.dirty()) history.reset(working);
    else if (JSON.stringify(history.current()) !== JSON.stringify(working)) history.apply(working);
    for (const [id, reason] of [
      ['editor-undo', editReason() || (!history.canUndo() ? '실행 취소할 변경이 없습니다' : '')],
      ['editor-redo', editReason() || (!history.canRedo() ? '다시 실행할 변경이 없습니다' : '')],
      ['drawing-file', host.reason()],
    ]) {
      $(id).disabled = Boolean(reason);
      if (reason) $(id).setAttribute('reason', reason); else $(id).removeAttribute('reason');
      $(id).title = reason;
    }
    const registrationReason = host.reason() || (!importer.ready() ? 'STL 원본을 먼저 확인하세요' : '');
    $('drawing-register').disabled = Boolean(registrationReason);
    if (registrationReason) $('drawing-register').setAttribute('reason', registrationReason);
    else $('drawing-register').removeAttribute('reason');
    const hash = host.map()?.drawing?.projection_sha256;
    if (hash !== loadingHash) {
      cacheController?.abort(); projection = null; loadingHash = hash;
      if (hash) {
        const controller = cacheController = new AbortController();
        host.request(`/api/fleet/site-map/drawing-projections/${hash}`, {signal: controller.signal})
          .then(result => { if (!controller.signal.aborted && loadingHash === hash) { projection = result; host.render(); } })
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
      document.removeEventListener('keydown', shortcut); window.removeEventListener('beforeunload', leaving);
    },
  };
}
