// D-573 1/7: waiting bands are drawn on the draft; the polygon itself is lane_graph's.
import {addApproach, removeApproach, mergeCrosswalks} from '/console/assets/site-map-model.js';

const $ = id => document.getElementById(id);

// Moved out of site-map.js (D-766): the four crosswalk-band buttons, behavior unchanged.
export function installBandEditing({request, guarded, state, select, render, syncButtons, notice}) {
  $('band-draw').addEventListener('click', () => {
    state.band = [];
    $('map-source').value = 'draft';
    render(); syncButtons();
    notice('지도에서 대기 띠의 꼭짓점을 차례로 찍고 띠 닫기를 누르세요.');
  });
  $('band-finish').addEventListener('click', () => guarded(async () => {
    const sel = state.selected;
    state.working = addApproach(state.working, sel.crosswalk, state.band);
    state.band = null;
    state.dirty = true;
    select(sel);
    notice('대기 띠를 초안에 넣었습니다. 저장할 때 차로에 닿는지, 바닥 안인지 확인합니다.');
  }));
  $('band-delete').addEventListener('click', () => guarded(async () => {
    const sel = state.selected;
    state.working = removeApproach(state.working, sel.crosswalk, Number($('crosswalk-band').value || 0));
    state.dirty = true;
    $('map-source').value = 'draft';
    select(sel);
    notice('대기 띠를 초안에서 지웠습니다. 저장해야 남습니다.');
  }));
  $('import-crosswalks').addEventListener('click', () => guarded(async () => {
    const got = await request('/api/fleet/site-map/lane-graph-crosswalks');
    state.working = mergeCrosswalks(state.working, got.crosswalks || []);
    state.dirty = true;
    $('map-source').value = 'draft';
    select(null);
    notice(`${got.source}에서 횡단보도 ${(got.crosswalks || []).length}개를 초안에 넣었습니다. 그린 대기 띠는 그대로 둡니다. 저장해야 남습니다.`);
  }));
}
