// Each editor keeps only one bounded page of labels and thumbnails in memory.
export function frameOrdinal(workspace,index) {
  const position=workspace.frames.findIndex(row=>row.index===index);
  return position<0?'—':workspace.page.offset+position+1;
}
export function reviewLink(path,frame) {
  const query=new URLSearchParams({frame});
  const current=new URLSearchParams(location.search);
  for(const key of ['folder_id','source_session'])if(current.has(key))query.set(key,current.get(key));
  return `${path}?${query}`;
}
export function workspacePage(lane, status='all', options={}) {
  const query=new URLSearchParams({limit:'60',lane,status});
  const session=new URLSearchParams(location.search).get('source_session');
  if(session!==null)query.set('source_session',session);
  const folder=new URLSearchParams(location.search).get('folder_id');
  if(folder!==null)query.set('folder_id',folder);
  for(const [key,value] of Object.entries(options))if(value!==undefined&&value!==null)query.set(key,value);
  return `/api/workspace?${query}`;
}
export function pageControls(anchor, move) {
  const bar=document.createElement('div');bar.className='ui-workspace-bar';
  const previous=document.createElement('ui-button'),next=document.createElement('ui-button'),label=document.createElement('span');
  previous.setAttribute('kind','quiet');next.setAttribute('kind','quiet');
  previous.textContent='이전 60장';next.textContent='다음 60장';label.setAttribute('role','status');
  bar.append(previous,label,next);anchor.after(bar);
  let page;
  previous.onclick=()=>move(Math.max(0,page.offset-page.limit));
  next.onclick=()=>move(page.offset+page.limit);
  return (value,locked=false)=>{
    page=value;bar.hidden=!page||page.total<=page.limit;
    previous.disabled=locked||!page||page.offset===0;
    next.disabled=locked||!page||page.offset+page.limit>=page.total;
    label.textContent=page?`${page.total? page.offset+1:0}–${Math.min(page.offset+page.limit,page.total)} / ${page.total}장`:'';
  };
}
