// Native training uses an explicit saved human review, never current editor drafts.
import {accountFetch} from '/account-session.js';
const $=id=>document.getElementById(id);
let sets=[],busy=false,pending=null;
function uuid(){
  const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
function selection(){
  const row=sets.find(row=>row.id===$('prepared-set').value),mode=$('native-train-review').value;
  const review=mode==='episodes'?row?.latest_review_id:mode==='segments'?row?.segment_review?.version:null;
  const valid=!!row&&!row.error&&!row.fixture_only&&!!review;
  $('native-train-start').disabled=busy||!valid;
  $('native-train-selection').textContent=valid?
    `${row.name} · ${mode==='episodes'?'전체 시연 검수 '+review:'저장 파지 구간 v'+review} · 분할과 원본은 서버가 다시 검증합니다.`:
    '등록 시연과 저장 검수를 선택하세요. 아직 저장하지 않은 검수나 시험 fixture는 학습할 수 없습니다.';
  return valid?{prepared_id:row.id,...(mode==='episodes'?{review_id:review}:{segment_version:review})}:null;
}
document.addEventListener('omx-prepared-loaded',event=>{sets=event.detail?.sets||[];pending=null;selection();});
document.addEventListener('omx-segments-saved',event=>{
  const row=sets.find(row=>row.id===event.detail.id);
  if(row)row.segment_review=event.detail.saved;
  pending=null;selection();
});
for(const id of ['prepared-set','native-train-review','native-train-steps','native-train-batch']){
  $(id).addEventListener('change',()=>{pending=null;selection();});
}
$('native-train-form').addEventListener('input',()=>{pending=null;});
$('native-train-form').onsubmit=async event=>{
  event.preventDefault();if(busy)return;
  const selected=selection();if(!selected)return;
  pending??={...selected,steps:Number($('native-train-steps').value),
    batch_size:Number($('native-train-batch').value),request_id:uuid()};
  const submitted=pending;busy=true;selection();
  $('native-train-status').textContent='원본과 저장 검수를 확인하고 작업을 접수하는 중입니다.';
  try{
    const workspace=await accountFetch('/api/workspace'),credentials=await workspace.json();
    if(!workspace.ok||!credentials.token)throw new Error('작업대 로그인과 연결을 확인하세요.');
    const response=await accountFetch('/api/learning/omx/center/native-run',{method:'POST',
      headers:{'Content-Type':'application/json','X-Pinky-Token':credentials.token},body:JSON.stringify(submitted)});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||`학습 접수 실패 (${response.status})`);
    if(pending===submitted)pending=null;
    $('native-train-status').textContent=`작업 ${result.id} 접수됨. 학습 단계의 작업 기록에서 중단·진행·평가와 모델 다운로드를 확인하세요.`;
    location.hash='train-section';
  }catch(exc){$('native-train-status').textContent=`접수 결과를 확인하세요: ${exc.message}. 입력을 바꾸지 않고 다시 누르면 같은 요청으로 확인합니다.`;}
  finally{busy=false;selection();}
};
