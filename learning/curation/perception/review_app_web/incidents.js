import {accountFetch} from '/account-session.js';
import '/common/ui.js';
const $=id=>document.getElementById(id);
const LIMIT=256*1024;  // each uploaded object stays under the server's 256 KiB bound
const STATES={unreviewed:'미검수',review_candidate:'검수 후보',disputed:'이견'};
const FIELDS=[['incident_id','사건'],['robot_id','로봇'],['review_state','검수 상태'],
  ['core_cause','CORE 원인'],['ai_cause_draft','AI 초안 원인'],['reviewed_root_cause','확정 원인']];
let token='';
function fail(message){$('incident-error').hidden=!message;$('incident-error').textContent=message||'';}
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
async function read(input,name){
  const file=input.files[0];
  if(!file)throw new Error(`${name} 파일을 선택하세요.`);
  if(file.size>LIMIT)throw new Error(`${name} 파일이 256 KiB를 넘습니다.`);
  try{return JSON.parse(await file.text());}
  catch{throw new Error(`${name} 파일을 JSON으로 읽을 수 없습니다.`);}
}
async function request(body){
  if(!token)token=(await (await accountFetch('/api/learning')).json()).token;
  const response=await accountFetch('/api/learning/recording/incident-feedback',
    {method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':token},body:JSON.stringify(body)});
  const value=await response.json();
  if(!response.ok)throw new Error(response.status===401?'로그인·계정에서 접속한 뒤 다시 시도하세요.'
    :response.status===403?'이 작업의 자료 가져오기(import) 권한이 없습니다.':value.error||`요청 실패 (${response.status})`);
  return value;
}
function render(result){
  const list=$('incident-results');list.replaceChildren();
  if(!result.matches.length)list.append(node('p','묶은 사건이 없습니다.','quiet'));
  for(const match of result.matches){
    const row=node('div','','incident-match');
    const grid=node('dl','','incident-match-fields');
    for(const [key,label] of FIELDS){
      grid.append(node('dt',label));
      grid.append(node('dd',key==='review_state'?STATES[match[key]]||match[key]:match[key]??'—'));
    }
    row.append(grid);list.append(row);
  }
  const missing=result.missing_incidents||[];
  list.append(node('p',missing.length
    ?`대응 사건 없는 마커 ${missing.length}개: ${missing.join(', ')}`
    :'대응 사건 없는 마커가 없습니다.','quiet'));
  const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)+'\n'],{type:'application/json'}));
  $('incident-download').href=url;$('incident-download').hidden=false;
}
$('incident-form').onsubmit=async event=>{
  event.preventDefault();
  $('incident-submit').disabled=true;fail('');$('incident-status').textContent='두 파일을 읽는 중입니다.';
  try{
    const [incidents,markers]=await Promise.all([
      read($('incident-incidents'),'사건 내보내기'),read($('incident-markers'),'stuck 마커')]);
    $('incident-status').textContent='서버에서 근거를 묶는 중입니다.';
    const result=await request({incidents,markers});
    render(result);
    $('incident-status').textContent=`사건 ${result.matches.length}건을 묶었습니다. 결과는 저장되지 않습니다.`;
  }catch(error){fail(error.message||String(error));$('incident-status').textContent='';}
  finally{$('incident-submit').disabled=false;}
};
