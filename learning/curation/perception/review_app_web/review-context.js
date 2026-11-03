// Scope comes from the bound server; selectors never accept filesystem paths or URLs.
export function reviewContext(anchor) {
  const bar=document.createElement('div');bar.hidden=true;bar.className='ui-workspace-bar';bar.setAttribute('aria-label','검수 작업 범위');
  const workspace=document.createElement('select'),folder=document.createElement('select'),scope=document.createElement('span');
  workspace.id='review-workspace';folder.id='review-folder';
  workspace.className=folder.className='ui-field';scope.setAttribute('role','status');
  for(const [text,select] of [['작업공간',workspace],['자료 폴더',folder]]) {
    const label=document.createElement('label');label.textContent=text+' ';label.append(select);bar.append(label);
  }
  bar.append(scope);anchor.after(bar);
  let context,signature;
  const option=(select,value,label)=>{const item=document.createElement('option');item.value=value;item.textContent=label;select.append(item);};
  workspace.onchange=()=>{
    const target=context.workspaces.find(item=>item.id===workspace.value);
    if(target)location.assign(target.url);
  };
  folder.onchange=()=>{
    const url=new URL(location.href);url.searchParams.set('folder_id',folder.value);
    for(const key of ['frame','offset','around','after','source_session','filter'])url.searchParams.delete(key);
    location.assign(url);
  };
  return (value,locked=false)=>{
    context=value;bar.hidden=!context;
    if(!context)return;
    const next=JSON.stringify(context);
    if(signature!==next) {
      signature=next;workspace.replaceChildren();folder.replaceChildren();
      const current=`${context.workspace.label}${context.workspace.id?' · '+context.workspace.id.slice(0,8):''}`;
      option(workspace,'',current);
      for(const item of context.workspaces)option(workspace,item.id,item.label);
      workspace.value='';workspace.title=`프로젝트 ${context.workspace.id || '현재 서버'}`;
      for(const item of context.folders)option(folder,item.id,item.label);
      option(folder,'all','전체 자료');
      if(context.folder_id)folder.value=context.folder_id;
      else if(context.default_scope||context.source_session){option(folder,'','현재 지정 범위');folder.value='';}
      else folder.value='all';
      const selected=folder.selectedOptions[0]?.textContent || '현재 지정 범위';
      scope.textContent=`${context.workspace.label} · ${selected} · ${context.total}장${context.source_session?' · 세션 한정':''}`;
      scope.title=`프로젝트 ${context.workspace.id || '현재 서버'}`;
    }
    workspace.disabled=locked||!context.workspaces.length;
    folder.disabled=locked;
  };
}
