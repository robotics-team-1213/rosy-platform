const $=id=>document.getElementById(id);
const bytes=value=>value==null?'미확인':`${(value/1024**3).toLocaleString('ko-KR',{maximumFractionDigits:3})} GiB`;
const roles={raw:'수집 원본',derived:'파생 자료',cache:'작업 캐시',pending:'전송 대기'};
let send, busy=false, epoch=0;
function line(parent,value){const p=document.createElement('p');p.textContent=value;parent.append(p);}
function fail(error){$('storage-error').textContent=error.message||'저장 현황을 확인할 수 없습니다.';$('storage-error').hidden=false;}
export function clearStorage(){
  epoch+=1;
  $('storage-status').textContent='저장 현황 미확인';
  $('storage-roots').replaceChildren();$('storage-destination').replaceChildren();
  $('storage-preflight').hidden=true;$('storage-result').textContent='';
}
export async function loadStorage(request){
  if(busy)return;
  send=request;busy=true;$('storage-refresh').disabled=true;$('storage-error').hidden=true;
  clearStorage();
  const current=epoch;
  $('storage-status').textContent='저장 현황을 확인하는 중입니다.';
  try{
    const data=await send('/api/learning/storage');
    if(current!==epoch)return;
    if(data.status==='not_configured'){
      $('storage-status').textContent='저장 경로 미설정 · 관리자가 프로젝트의 수집·저장 폴더를 등록해야 합니다.';return;
    }
    $('storage-status').textContent=`${new Date(data.measured_at*1000).toLocaleString('ko-KR')} 측정 · 전송 대기 ${bytes(data.pending_bytes)} · 최대 60초 캐시`;
    for(const row of data.roots){
      const article=document.createElement('article');$('storage-roots').append(article);
      const heading=document.createElement('h3');heading.textContent=`${row.label} · ${roles[row.role]}`;article.append(heading);
      line(article,row.status==='ready'?`파일 ${row.files}개 · 논리 크기 ${bytes(row.logical_bytes)} · 하드링크 중복 제외 ${bytes(row.file_bytes)} · 할당 ${bytes(row.allocated_bytes)}`:
        row.status==='partial'?'일부 항목을 집계하지 못했습니다. 합계 미확인.':'등록 폴더를 읽을 수 없습니다. 합계 미확인.');
      line(article,`미완료 이름의 파일 ${bytes(row.incomplete_bytes)} · 볼륨 잔여 ${bytes(row.free_bytes)}`);
      line(article,`하루 증가량 ${bytes(row.growth_bytes_per_day)} · 예상 잔여 ${row.estimated_days==null?'미확인':row.estimated_days.toFixed(1)+'일'} (최근 30일의 이 폴더 증가율 기준)`);
      const option=document.createElement('option');option.value=row.id;option.textContent=row.label;$('storage-destination').append(option);
    }
    $('storage-preflight').hidden=false;
  }catch(error){if(current!==epoch)return;clearStorage();$('storage-status').textContent='저장 현황 확인 실패 · 다시 확인으로 재시도하세요.';fail(error);}
  finally{busy=false;$('storage-refresh').disabled=false;}
}
$('storage-refresh').onclick=()=>{if(send)loadStorage(send);};
$('storage-preflight').onsubmit=async event=>{
  event.preventDefault();if(busy||!send)return;
  busy=true;const button=event.target.querySelector('button');button.disabled=true;
  $('storage-error').hidden=true;$('storage-result').textContent='공간을 점검하는 중입니다.';
  const current=epoch;
  try{
    const body={destination_id:$('storage-destination').value};
    for(const key of ['download','staging','transform','upload']) body[`${key}_bytes`]=Math.ceil(Number($(`storage-${key}`).value)*1024**3);
    const result=await send('/api/learning/storage/preflight',body);
    if(current!==epoch)return;
    const states={ready:'공간 추정 충족',hold:'공간 확인 보류',blocked:'공간 부족'};
    const remote={not_required:'업로드 없음',unknown:'미확인 또는 유효기간 만료',sufficient:'추정 충족',insufficient:'부족'};
    $('storage-result').textContent=`${states[result.status]} · 로컬 필요 ${bytes(result.local_required_bytes)} (여유분 ${bytes(result.reserve_bytes)} 포함) / 잔여 ${bytes(result.local_available_bytes)} · 원격 ${remote[result.remote_status]} · 공간 예약·전송은 하지 않았습니다.`;
    if(result.remote_quota) $('storage-result').textContent+=` 원격 근거: ${result.remote_quota.source}, ${new Date(result.remote_quota.measured_at*1000).toLocaleString('ko-KR')} 측정.`;
  }catch(error){if(current!==epoch)return;$('storage-result').textContent='공간 점검 실패';if(error.status===401||error.status===403)clearStorage();fail(error);}
  finally{busy=false;button.disabled=false;}
};
