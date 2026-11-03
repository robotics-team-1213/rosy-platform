import {accountFetch} from '/account-session.js';
const $=id=>document.getElementById(id),query=new URLSearchParams(location.search);
$('kind').value=query.get('kind')==='pixel'?'pixel':'object';
let current,rows=[],busy=false;
const rgb=color=>'#'+(color||[128,128,128]).map(v=>v.toString(16).padStart(2,'0')).join('');
async function request(path,body) {
  const response=await accountFetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':current.token},body:JSON.stringify(body)}:{});
  const value=await response.json();if(!response.ok)throw Error(value.error||'요청을 처리하지 못했습니다.');return value;
}
function impact() {
  const old=current?.binding?.classes||[];
  const changed=$('kind').value==='object'?rows.length!==old.length:
    JSON.stringify(rows.map(({display,...row})=>row))!==JSON.stringify(old.map(({display,...row})=>row));
  return changed?(current?.approved_count||0):0;
}
function update() {
  $('impact').textContent=`작업공간 전체 · 승인 ${current?.approved_count||0}건 중 ${impact()}건을 검수 대기로 돌립니다. 원본 라벨과 승인 기록은 보존됩니다.`;
  $('apply').disabled=busy||!current||!$('confirm').checked;
  $('kind').disabled=busy;$('add').disabled=busy||!current||rows.length>=255;$('reload').disabled=busy;
  for(const fieldset of $('rows').children)fieldset.disabled=busy;
}
function render() {
  $('rows').replaceChildren();
  for(const [position,row] of rows.entries()) {
    const section=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent=`클래스 ${row.index}`;section.append(legend);
    const input=(text,key,type='text',immutable=false)=>{
      const label=document.createElement('label'),field=document.createElement('input');label.textContent=text+' ';field.className='ui-field';field.type=type;
      field.value=type==='color'?rgb(row[key]):row[key]||'';field.disabled=immutable;field.required=type!=='color';field.maxLength=key==='display'?80:64;
      field.oninput=()=>{row[key]=type==='color'?field.value.slice(1).match(/../g).map(v=>parseInt(v,16)):field.value;$('confirm').checked=false;update();};label.append(field);section.append(label);
    };
    const existing=position<(current.binding?.classes.length||0);
    input('정본 이름','name','text',existing);input('표시 이름','display');input('색상','color','color');
    if($('kind').value==='pixel') {
      const label=document.createElement('label'),select=document.createElement('select');label.textContent='역할 ';select.className='ui-field';
      for(const role of current.roles){const option=document.createElement('option');option.value=option.textContent=role;select.append(option);}select.value=row.role;select.disabled=existing;
      select.onchange=()=>{row.role=select.value;$('confirm').checked=false;update();};label.append(select);section.append(label);
      if(row.semantic){const semantic=document.createElement('p');semantic.textContent='의미: '+JSON.stringify(row.semantic);section.append(semantic);}
    }
    $('rows').append(section);
  }
  update();
}
async function load() {
  busy=true;update();$('error').textContent='';$('confirm').checked=false;
  try {
    current=await request('/api/classes?kind='+$('kind').value);rows=structuredClone(current.binding?.classes||[]);
    $('workspace').textContent=`${current.workspace_label} · 프로젝트 ${current.workspace_id}`;
    const back=new URL($('kind').value==='pixel'?'/pixels':'/',location.origin);if(query.has('folder_id'))back.searchParams.set('folder_id',query.get('folder_id'));$('back').href=back.pathname+back.search;
    render();
  }catch(error){current=undefined;$('error').textContent=error.message;}
  finally{busy=false;update();}
}
$('add').onclick=()=>{
  const used=new Set(rows.map(row=>row.index));let index=0;while(used.has(index))index++;
  rows.push({index,name:'',display:'',color:[128,128,128],...($('kind').value==='pixel'?{role:rows.length?'ignore':'background'}:{})});$('confirm').checked=false;render();
};
$('confirm').onchange=update;$('kind').onchange=load;$('reload').onclick=load;
$('form').onsubmit=async event=>{
  event.preventDefault();if(busy||!current||!$('confirm').checked)return;
  busy=true;update();$('error').textContent='';
  try{await request('/api/classes/revisions',{kind:$('kind').value,classes:rows,expected_sha:current.expected_sha,expected_impact:impact(),confirm:true});$('result').textContent='클래스 개정을 저장했습니다. 검수 화면을 새로 열어 사용하세요.';await load();}
  catch(error){$('error').textContent=error.message;$('confirm').checked=false;}
  finally{busy=false;update();}
};
load();
