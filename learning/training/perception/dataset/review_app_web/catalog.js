import '/common/ui.js';
const $=id=>document.getElementById(id);
let token,busy=false;
function show(id,value){$(id).textContent=value;$(id).hidden=!value;}
async function request(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':token},body:JSON.stringify(body)}:{});const value=await response.json();if(!response.ok)throw new Error(value.error);return value;}
function map(value){if(!value)return;$('map-status').setAttribute('state','warning');$('map-status').textContent=`${value.map_id} · CAD/그래프 파일 출처 확인됨 · 영상 투영 미검증`;$('map-details').textContent=JSON.stringify(value,null,2);}
async function perform(id,path,body,done){if(busy)return;busy=true;show('catalog-error','');for(const name of ['import','cad']){$(name).disabled=true;$(name).reason='파일 검증을 마친 뒤 다시 사용할 수 있습니다.';}try{done(await request(path,body));}catch(error){show('catalog-error',`${error.message} · 원본 자료와 검증 경로를 확인하세요.`);}finally{busy=false;for(const name of ['import','cad']){$(name).disabled=false;$(name).reason='';}}}
function register(event){event.preventDefault();if(!$('import-form').reportValidity())return;perform('import','/api/import',{path:$('catalog-path').value},value=>{$('result').setAttribute('state','ready');show('result',`새 사진 ${value.added}장 · 중복 표현 ${value.duplicate_representations}개 · 새 픽셀 검수 대기 ${value.pixel_reviews_pending}장. 기존 승인·제외는 유지됩니다.`);});}
function registerMap(event){event.preventDefault();if(!$('cad-form').reportValidity())return;perform('cad','/api/cad',{path:$('cad-path').value},map);}
$('import-form').onsubmit=register;$('import').onclick=register;$('cad-form').onsubmit=registerMap;$('cad').onclick=registerMap;
request('/api/catalog').then(value=>{token=value.token;$('catalog-path').value=value.catalog||'';$('cad-path').value=value.cad_catalog||'';map(value.map_reference);}).catch(error=>show('catalog-error',error.message));
