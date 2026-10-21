import {openLiveDialog} from '/common/ui.js';

const trigger=document.createElement('ui-button');
trigger.id='review-command-open';trigger.setAttribute('kind','quiet');
trigger.setAttribute('aria-keyshortcuts','Control+K Meta+K');
trigger.textContent='기능 검색';trigger.title='기능 검색 · Ctrl+K';
(document.querySelector('.review-flow')||document.querySelector('main')).append(trigger);
const dialog=document.createElement('dialog');
dialog.id='review-commands';dialog.className='review-commands';dialog.setAttribute('aria-label','기능 검색');
dialog.innerHTML='<h2>기능 검색</h2><label class="ui-field-label">기능 이름 <input class="ui-field" id="review-command-query" aria-label="기능 검색어" type="text" autocomplete="off"></label><p class="quiet">이름 검색 · ↑/↓ 선택 · Enter 실행 · Esc 닫기. 입력은 선택 후 기존 필드에서 수정합니다.</p><p id="review-command-count" role="status"></p><ul id="review-command-results" aria-label="검색된 기능"></ul>';
const search=dialog.querySelector('input'),results=dialog.querySelector('ul'),count=dialog.querySelector('[role=status]');
const bindings=[
  ['KeyS','Control+S Meta+S',['pixel-save']],
  ['KeyR','R',['reload','pixel-reload','refresh','catalog-retry']],
  ['KeyU','U',['reopen','pixel-reopen']],
  ['KeyE','E',['prepare','pixel-export']],
  ['Insert','Insert',['add']],
];
for(const [,keys,ids] of bindings)for(const id of ids){const el=document.getElementById(id);if(el)el.setAttribute('aria-keyshortcuts',keys);}
for(const p of document.querySelectorAll('#object-keys p,#pixel-keys p'))p.append(' Ctrl+K 기능 검색 · R 최신 내용 · U 재검수 · E 승인 자료 준비 · 픽셀 Ctrl+S 초안 저장 · 객체 Insert 좌표 박스 추가.');

let closeCommands=null;
const disabled=el=>el.matches(':disabled,[disabled],[aria-disabled="true"]');
function reachable(el){
  if(!el.isConnected||dialog.contains(el)||el===trigger)return false;
  for(let node=el;node&&node!==document.body;node=node.parentElement){
    if(node.hidden||getComputedStyle(node).display==='none'||getComputedStyle(node).visibility==='hidden')return false;
  }
  return true;
}
function name(el){
  if(el.getAttribute('aria-label'))return el.getAttribute('aria-label');
  if(el.getAttribute('aria-labelledby'))return document.getElementById(el.getAttribute('aria-labelledby'))?.textContent.trim()||'';
  if(el.labels?.length){
    const label=el.labels[0].cloneNode(true);
    label.querySelectorAll('input,select,textarea').forEach(node=>node.remove());
    return label.textContent.trim();
  }
  return (el.querySelector('.ui-icon-label')?.textContent||el.textContent).trim();
}
function inventory(){
  return [...document.querySelectorAll('ui-button,button,a[href],input:not([type=hidden]),select,textarea,summary,canvas[tabindex],section[aria-labelledby]')]
    .filter(reachable).map(el=>({el,label:name(el)})).filter(row=>row.label)
    .sort((a,b)=>Number(!!a.el.closest('#frames,#pixel-frames'))-Number(!!b.el.closest('#frames,#pixel-frames')));
}
function execute({el}){
  if(!reachable(el)||disabled(el)){render();count.textContent='현재 실행할 수 없는 기능입니다. 상태와 비활성 이유를 확인하세요.';return;}
  closeCommands?.('selected');
  for(let parent=el.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS'&&parent.firstElementChild!==el)parent.open=true;
  if(el.matches('section'))el.tabIndex=-1;
  el.scrollIntoView({block:'nearest'});el.focus({preventScroll:true});
  if(!el.matches('textarea,select,canvas,section,input:not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit])'))el.click();
}
function render(){
  const query=search.value.trim().toLocaleLowerCase(),rows=inventory().filter(row=>row.label.toLocaleLowerCase().includes(query))
    .sort((a,b)=>Number(b.label.toLocaleLowerCase()===query)-Number(a.label.toLocaleLowerCase()===query));
  results.replaceChildren();count.textContent=`${rows.length}개 항목${rows.length>30?' · 처음 30개 표시, 검색어를 더 입력하세요.':''}`;
  for(const command of rows.slice(0,30)){
    const item=document.createElement('li'),button=document.createElement('ui-button');button.setAttribute('kind','quiet');
    const keys=command.el.getAttribute('aria-keyshortcuts');
    button.textContent=command.label+(keys?` · ${keys}`:'');
    button.disabled=disabled(command.el);
    if(button.disabled)button.setAttribute('reason',command.el.getAttribute('reason')||'현재 상태에서는 사용할 수 없습니다.');
    button.onclick=()=>execute(command);item.append(button);results.append(item);
  }
}
function open(){
  if(dialog.open||document.querySelector('dialog[open]'))return;
  search.value='';render();
  closeCommands=openLiveDialog(dialog,{initialFocus:search,onClose:()=>{closeCommands=null;}});
}
trigger.onclick=open;search.oninput=render;
dialog.addEventListener('keydown',event=>{
  event.stopPropagation();
  if(event.isComposing)return;
  if(event.key==='Enter'&&event.target===search){event.preventDefault();render();results.querySelector('ui-button:not([disabled])')?.click();return;}
  const buttons=[...results.querySelectorAll('ui-button:not([disabled])')];
  if(['ArrowDown','ArrowUp'].includes(event.key)&&buttons.length){
    event.preventDefault();const at=buttons.indexOf(document.activeElement),step=event.key==='ArrowDown'?1:-1;
    buttons[at<0?(step>0?0:buttons.length-1):(at+step+buttons.length)%buttons.length].focus();
  }
});
document.addEventListener('keydown',event=>{
  if(event.isComposing||event.repeat)return;
  if(event.code==='KeyK'&&(event.ctrlKey||event.metaKey)&&!event.altKey&&!event.shiftKey){event.preventDefault();event.stopImmediatePropagation();if(dialog.open)closeCommands?.('cancel');else open();return;}
  if(dialog.open||document.querySelector('dialog[open]')||event.target?.closest?.('input,textarea,select,[contenteditable]')||event.altKey||event.shiftKey)return;
  const binding=bindings.find(([code])=>event.code===code);
  if(!binding||(event.code==='KeyS')!==!!(event.ctrlKey||event.metaKey))return;
  const el=binding[2].map(id=>document.getElementById(id)).find(node=>node&&reachable(node));
  if(el){event.preventDefault();event.stopImmediatePropagation();if(!disabled(el))el.click();}
},true);
