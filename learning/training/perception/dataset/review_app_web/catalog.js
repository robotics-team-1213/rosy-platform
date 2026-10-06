import '/common/ui.js';
const $=id=>document.getElementById(id);
let token,busy=false,loading=true;
function show(id,value){$(id).textContent=value;$(id).hidden=!value;}
function controls(){for(const id of ['import','cad']){$(id).disabled=busy||loading||!token;$(id).reason=loading?'현재 연결과 권한을 확인하는 중입니다.':busy?'파일 검증을 마친 뒤 다시 사용할 수 있습니다.':!token?'자료 등록 권한을 다시 확인하세요.':'';}for(const id of ['catalog-path','cad-path'])$(id).disabled=busy||loading||!token;}
async function request(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':token},body:JSON.stringify(body)}:{});const value=await response.json();if(!response.ok){if(response.status===403)token=undefined;throw new Error(response.status===403?'이 작업대의 자료 등록 권한이 거부되었습니다.':value.error||'요청 실패');}return value;}
function map(value){if(!value)return;$('map-status').setAttribute('state','warning');$('map-status').textContent=`${value.map_id} · CAD/그래프 파일 출처 확인됨 · 영상 투영 미검증`;$('map-details').textContent=JSON.stringify(value,null,2);}
async function perform(id,path,body,done){if(busy||loading||!token)return;busy=true;show('catalog-error','');controls();try{done(await request(path,body));}catch(error){show('catalog-error',error.message+(token?' · 원본 자료와 검증 경로를 확인하세요.':' · 다시 확인으로 권한을 새로 읽으세요.'));$('catalog-error').scrollIntoView({block:'center'});if(!token){$('catalog-load').setAttribute('state','error');$('catalog-load').textContent='자료 등록 권한을 확인할 수 없습니다.';$('catalog-retry').hidden=false;}}finally{busy=false;controls();}}
function register(event){event.preventDefault();if(loading||!token||!$('import-form').reportValidity())return;perform('import','/api/import',{path:$('catalog-path').value},value=>{$('result').setAttribute('state','ready');show('result',`새 사진 ${value.added}장 · 중복 표현 ${value.duplicate_representations}개 · 새 픽셀 검수 대기 ${value.pixel_reviews_pending}장. 기존 승인·제외는 유지됩니다.`);});}
function registerMap(event){event.preventDefault();if(loading||!token||!$('cad-form').reportValidity())return;perform('cad','/api/cad',{path:$('cad-path').value},map);}
$('import-form').onsubmit=register;$('import').onclick=register;$('cad-form').onsubmit=registerMap;$('cad').onclick=registerMap;
$('theme').value=document.documentElement.dataset.theme||'dark';
$('theme').onchange=()=> {document.documentElement.dataset.theme=$('theme').value;try{localStorage.setItem('rosy.theme',$('theme').value);}catch{} document.dispatchEvent(new CustomEvent('rosy:theme'));};
async function load(){loading=true;token=undefined;controls();show('catalog-error','');$('catalog-load').hidden=false;$('catalog-load').setAttribute('state','pending');$('catalog-load').textContent='자료 등록 권한과 현재 연결을 확인하는 중입니다.';$('catalog-retry').hidden=true;$('map-status').setAttribute('state','pending');$('map-status').textContent='지도 참조 확인 중입니다.';
  try{const value=await request('/api/catalog');token=value.token;$('catalog-path').value=value.catalog||'';$('cad-path').value=value.cad_catalog||'';$('map-status').setAttribute('state','empty');$('map-status').textContent='아직 연결한 지도 참조가 없습니다.';map(value.map_reference);$('catalog-load').hidden=true;}
  catch(error){$('catalog-load').setAttribute('state','error');$('catalog-load').textContent=error.message+' 접근 권한과 연결을 확인한 뒤 다시 확인하세요.';$('map-status').setAttribute('state','error');$('map-status').textContent='지도 참조를 확인할 수 없습니다.';$('catalog-retry').hidden=false;}
  finally{loading=false;controls();}}
$('catalog-retry').onclick=load;
controls();load();
