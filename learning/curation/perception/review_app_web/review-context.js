// Scope comes from the bound server; selectors never accept filesystem paths or URLs.
export function reviewContext(anchor) {
  const bar=document.createElement('div');bar.hidden=true;bar.className='ui-workspace-bar';bar.setAttribute('aria-label','검수 작업 범위');
  const workspace=document.createElement('select'),folder=document.createElement('select'),scope=document.createElement('span');
  workspace.id='review-workspace';folder.id='review-folder';
  workspace.className=folder.className='ui-field';scope.setAttribute('role','status');
  for(const [text,select] of [['작업공간',workspace],['자료 폴더',folder]]) {
    const label=document.createElement('label');label.textContent=text+' ';label.append(select);bar.append(label);
  }
  const manage=document.createElement('a');manage.textContent='클래스 관리';
  const pixel=location.pathname==='/pixels';let container=bar,summary=null,total=null;
  if(pixel){
    container=document.createElement('details');container.className='pixel-review-context';container.setAttribute('aria-label','검수 작업 범위');container.hidden=true;
    summary=document.createElement('summary');const text=document.createElement('span');text.className='pixel-context-summary';total=document.createElement('span');
    text.append(scope,total);summary.append(text);bar.removeAttribute('aria-label');bar.hidden=false;bar.append(manage);container.append(summary,bar);
    document.querySelector('.ui-pathbar').append(container);
  }else{bar.append(scope,manage);anchor.after(bar);}
  let context,signature;
  const option=(select,value,label)=>{const item=document.createElement('option');item.value=value;item.textContent=label;select.append(item);};
  workspace.onchange=()=>{
    const target=context.workspaces.find(item=>item.id===workspace.value);
    if(target){
      const url=new URL(target.url);
      if(['/','/learning','/pixels'].includes(url.pathname)&&['/','/pixels'].includes(location.pathname)) {
        url.pathname=location.pathname;
        for(const key of ['frame','filter','offset','around','after','source_session','folder_id'])url.searchParams.delete(key);
      }
      location.assign(url);
    }
  };
  folder.onchange=()=>{
    const url=new URL(location.href);url.searchParams.set('folder_id',folder.value);
    for(const key of ['frame','offset','around','after','source_session','filter'])url.searchParams.delete(key);
    location.assign(url);
  };
  return (value,locked=false)=>{
    context=value;container.hidden=!context;
    if(!context)return;
    const next=JSON.stringify(context);
    if(signature!==next) {
      signature=next;workspace.replaceChildren();folder.replaceChildren();
      const current=`${context.workspace.label}${context.workspace.id?' · '+context.workspace.id.slice(0,8):''}`;
      option(workspace,'',current);
      for(const item of context.workspaces)if(new URL(item.url).origin!==location.origin)option(workspace,item.id,item.label);
      workspace.value='';workspace.title=`프로젝트 ${context.workspace.id || '현재 서버'}`;
      for(const item of context.folders)option(folder,item.id,item.label);
      option(folder,'all','전체 자료');
      if(context.folder_id)folder.value=context.folder_id;
      else if(context.default_scope||context.source_session){option(folder,'','현재 지정 범위');folder.value='';}
      else folder.value='all';
      const selected=folder.selectedOptions[0]?.textContent || '현재 지정 범위';
      scope.textContent=`${context.workspace.label} · ${selected}${pixel?'':` · ${context.total}장`}${context.source_session?' · 세션 한정':''}`;
      scope.title=`프로젝트 ${context.workspace.id || '현재 서버'}`;
      if(pixel){total.textContent=` · ${context.total}장`;summary.title=scope.textContent+total.textContent;}
      const target=new URL('/classes',location.origin);target.searchParams.set('kind',location.pathname==='/pixels'?'pixel':'object');
      if(context.folder_id)target.searchParams.set('folder_id',context.folder_id);
      manage.href=target.pathname+target.search;
    }
    workspace.disabled=locked||workspace.options.length<2;
    folder.disabled=locked;
    manage.setAttribute('aria-disabled',String(locked));manage.onclick=event=>{if(locked)event.preventDefault();};
  };
}
