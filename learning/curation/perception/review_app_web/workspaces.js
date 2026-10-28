// D-857 §2: the center lists its other review workspaces (separate states, D-485) as same-tab links only.
import {accountFetch} from '/account-session.js';
import '/common/ui.js';
import '/commands.js';
const $=id=>document.getElementById(id);
const KINDS={training:'학습',evaluation:'평가',review:'검수'};
let loading=false;

function entry(label,tag,note,url){
  const item=document.createElement('li');item.className='workspace-entry';
  const title=document.createElement('h3');title.textContent=label;
  const badge=document.createElement('ui-tag');badge.textContent=tag;
  item.append(title,badge);
  if(url){const link=document.createElement('a');link.className='workspace-link';link.href=url;link.textContent='열기';link.setAttribute('aria-label',`${label} 열기`);item.append(link);}
  if(note){const text=document.createElement('p');text.className='quiet';text.textContent=note;item.append(text);}
  return item;
}

async function load(){
  if(loading)return;
  loading=true;$('workspaces-retry').disabled=true;
  const status=$('workspaces-status');
  status.setAttribute('state','pending');status.setAttribute('role','status');status.textContent='작업 공간 목록을 읽는 중입니다.';
  $('workspaces').replaceChildren();
  try{
    const response=await accountFetch('/api/learning/workspaces');
    const value=await response.json();
    if(!response.ok)throw new Error(value.error||'작업 공간 목록을 읽지 못했습니다.');
    const current=entry('Rosy Learning 센터','이 센터','지금 보고 있는 센터입니다.');current.dataset.current='';
    $('workspaces').replaceChildren(current,...value.workspaces.map(row=>entry(row.label,KINDS[row.kind]||row.kind,row.note,row.url)));
    status.setAttribute('state',value.workspaces.length?'ready':'empty');
    status.textContent=value.workspaces.length?`연결된 작업 공간 ${value.workspaces.length}개`:value.configured?'연결된 작업 공간이 없습니다.':'이 센터에는 연결된 작업 공간 설정이 없습니다.';
  }catch(error){status.setAttribute('state','error');status.setAttribute('role','alert');status.textContent=error.message+' · 다시 확인을 눌러 목록을 읽으세요.';}
  finally{loading=false;$('workspaces-retry').disabled=false;}
}
$('workspaces-retry').onclick=load;
load();
