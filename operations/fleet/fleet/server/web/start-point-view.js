// The operator saves a map reference. Captured map clicks never enter goal dispatch.
import {pointerPose} from './start-point-layer.js';
import {createPollGate} from './poll-gate.js';

export function createStartPointView({scope, el, view, call, auth, onChanged}) {
  const source=el('start-point-source'), message=el('start-point-state'), canvas=el('map-canvas');
  const fields=['x','y','yaw'].map(name=>el(`start-point-${name}`));
  const pick=el('start-point-pick'), save=el('start-point-save'), remove=el('start-point-delete');
  const gate=createPollGate();
  let records=[], points=[], ready=false, picking=false, busy=false, loading=false, serial=0, pendingSource=null;
  const operator=()=>auth.role==='operator' && !auth.locked;
  const record=()=>records.find(row=>row.source_id===source.value);
  const point=()=>points.find(row=>row.source_id===source.value);
  function stopPicking() {
    picking=false; pick.textContent='지도에서 시작 위치 선택';
    if (!view.selected) {canvas.tabIndex=-1; canvas.classList.add('idle');}
  }
  function controls() {
    const editable=operator() && ready && !!record() && !busy;
    const reason=!operator() ? '운영자 권한이 필요합니다' : busy ? '시작점 저장 처리 중' : '승인된 무마커 보정과 서버 연결이 필요합니다';
    setEnabled(pick,editable,reason); setEnabled(save,editable,reason);
    setEnabled(remove,editable && !!point(),point() ? reason : '저장한 시작점이 없습니다');
    setEnabled(source,operator() && !busy && !!records.length,reason);
    fields.forEach(field=>setEnabled(field,editable,reason));
    if (!editable) stopPicking();
  }
  function setEnabled(control,enabled,reason) {
    control.disabled=!enabled;
    if (enabled) control.removeAttribute('reason'); else control.setAttribute('reason',reason);
    control.setAttribute('aria-describedby','start-point-state');
  }
  function populate() {
    stopPicking();
    const saved=point();
    fields[0].value=saved ? saved.x : '';
    fields[1].value=saved ? saved.y : '';
    fields[2].value=saved ? (saved.yaw*180/Math.PI).toFixed(1) : '0';
    message.textContent=saved ? (saved.valid ? `시작점 · X ${saved.x.toFixed(2)} / Y ${saved.y.toFixed(2)} m · 방향 ${(saved.yaw*180/Math.PI).toFixed(1)}°` : '보정이 바뀌었습니다. 시작 위치와 방향을 다시 확인하고 저장하세요.')
      : records.length ? '지도에서 위치를 선택하거나 좌표를 입력한 뒤 저장하세요.' : '카메라 설치 화면에서 무마커 추적 보정을 먼저 적용하세요.';
    controls();
  }
  async function refresh() {
    if (auth.locked || !auth.token || loading || busy || !gate.due()) {controls(); return;}
    const life=scope.capture(), epoch=serial;
    loading=true;
    try {
      const [calibrations, saved]=await Promise.all([call('/api/fleet/calibrations'),call('/api/fleet/start-points')]);
      if (!life.current() || epoch!==serial) return;
      gate.ok();
      const wasReady=ready, prior=JSON.stringify(points), sourcesBefore=records.map(row=>`${row.source_id}:${row.calibration_revision}`).join('|');
      records=calibrations.calibrations; points=saved.start_points;
      ready=true; view.startPoints=points;
      const sourcesAfter=records.map(row=>`${row.source_id}:${row.calibration_revision}`).join('|');
      if (sourcesBefore!==sourcesAfter) {
        const selected=source.value;
        source.replaceChildren(...records.map(row=>{const option=document.createElement('option'); option.value=row.source_id; option.textContent=`${row.source_id} · ${row.map_id}`; return option;}));
        if (records.some(row=>row.source_id===selected)) source.value=selected;
      }
      if (!wasReady || prior!==JSON.stringify(points) || sourcesBefore!==sourcesAfter) {
        populate();
        if (!saved.persistent) message.textContent+=' · 임시 저장: 서버 재시작 시 사라집니다.';
      }
      controls(); onChanged();
    } catch (error) {
      if (life.current() && epoch===serial) {
        gate.fail(error.status,error.code);
        ready=false; view.startPoints=[]; controls(); onChanged();
        message.textContent=error.status===404 ? '이 서버는 시작점 저장 기능을 아직 지원하지 않습니다.' : '시작점 상태를 확인할 수 없습니다. 연결과 인증을 확인하세요.';
      }
    } finally {if (life.current()) loading=false;}
  }
  scope.listen(source,'change',()=>{if (busy) {source.value=pendingSource;return;}serial++;populate();});
  scope.listen(pick,'click',()=>{
    if (!operator() || !ready || !record() || busy) return;
    if (view.map && view.map.map_id!==record().map_id) {message.textContent='현재 지도와 보정 지도가 다릅니다. 같은 지도를 확인한 뒤 선택하세요.';return;}
    if (picking) {stopPicking(); return;}
    picking=true; view.selected=null; view.cursor=null; canvas.classList.remove('idle'); canvas.tabIndex=0;
    el("map-stage").dataset.view = "map"; el("birdseye-toggle").setAttribute("aria-pressed", "false"); // D-493: a start pick needs the map
    pick.textContent='위치 선택 취소'; message.textContent='시작 위치를 지도에서 선택하세요. 방향은 아래에서 입력하세요.'; canvas.focus();
  });
  scope.listen(canvas,'click',event=>{
    if (!picking) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (!operator() || !ready || busy) {stopPicking(); return;}
    if (view.map && view.map.map_id!==record()?.map_id) {
      stopPicking(); message.textContent='지도 선택 중 지도가 바뀌었습니다. 보정 지도와 같은 지도를 확인하세요.'; return;
    }
    const pos=pointerPose(view,canvas.getBoundingClientRect(),canvas,event.clientX,event.clientY);
    if (!pos) {message.textContent='지도 영역 안에서 시작 위치를 선택하세요.'; return;}
    fields[0].value=pos.x.toFixed(3); fields[1].value=pos.y.toFixed(3);
    message.textContent='시작 위치를 선택했습니다. 방향을 확인하고 저장하세요.'; stopPicking();
  },{capture:true});
  scope.listen(canvas,'keydown',event=>{
    if (!picking) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (event.key==='Escape') stopPicking();
    else message.textContent='키보드로는 아래 X/Y·방향 입력란에서 시작점을 지정할 수 있습니다.';
  },{capture:true});
  async function mutate(method) {
    if (!operator() || !ready || busy || !record()) return;
    if (method==='PUT' && fields.some(field=>!field.value.trim() || !field.checkValidity())) {message.textContent='X/Y와 방향(-180°~180°)을 확인하세요.'; return;}
    const cal=record(), previous=point(), life=scope.capture(), epoch=serial;
    const pose={x:Number(fields[0].value),y:Number(fields[1].value),yaw:Number(fields[2].value)*Math.PI/180};
    const path=`/api/fleet/start-points/${encodeURIComponent(cal.source_id)}`;
    if (method==='DELETE' && !previous) return;
    busy=true; pendingSource=cal.source_id; stopPicking(); controls();
    try {
      await call(method==='DELETE' ? `${path}?expected_revision=${encodeURIComponent(previous.revision)}` : path,
        {method, ...(method==='PUT' ? {headers:{'Content-Type':'application/json'},body:JSON.stringify({...pose,map_id:cal.map_id,calibration_revision:cal.calibration_revision,expected_revision:previous?.revision || null})} : {})});
      if (!life.current() || epoch!==serial) return;
      message.textContent=method==='PUT' ? '시작점을 저장했습니다.' : '시작점을 지웠습니다.';
    } catch (error) {
      if (life.current() && epoch===serial) message.textContent=`저장하지 못했습니다: ${error.message}`;
    } finally {if (life.current() && epoch===serial) {busy=false;controls();await refresh();}}
  }
  scope.listen(save,'click',()=>mutate('PUT')); scope.listen(remove,'click',()=>mutate('DELETE'));
  function reset() {serial++; busy=false; loading=false; ready=false; records=[]; points=[];gate.reset();view.startPoints=[];source.replaceChildren();fields.forEach(field=>field.value='');message.textContent='관제에 접속하면 시작점 상태를 확인할 수 있습니다.';stopPicking();controls();onChanged();}
  scope.onDispose(reset); scope.onResume(refresh); scope.interval(refresh,3000);
  controls(); refresh();
  return {refresh,reset,updateAuthorization:controls};
}
