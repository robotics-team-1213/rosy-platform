// D-792 S2: one photo against one camera setup reference. Dashed = reference, solid = this photo.
import {accountFetch} from '/account-session.js';
import {cssColor, clearPalette} from '/common/ui.js';
import '/commands.js';
const $=id=>document.getElementById(id);
const MOUNT=[['height_cm','높이','cm'],['distance_cm','거리','cm'],['tilt_deg','tilt','°'],['pan_deg','pan','°'],['roll_deg','roll','°']];
const VERDICT={ok:['ready','맞음 — 이 위치로 녹화할 수 있습니다.'],adjust:['warning','조정 필요 — 점선에 실선이 겹치도록 카메라를 옮기세요.'],
  unmeasurable:['error','측정 불가 — 마커가 3개 이상 보이는지, 교정 지문과 해상도가 기준과 같은지 확인하세요.']};
let token, references=[], still=null, photo=null, result=null;

$('theme').value=document.documentElement.dataset.theme||'dark';
$('theme').onchange=()=>{document.documentElement.dataset.theme=$('theme').value;try{localStorage.setItem('rosy.theme',$('theme').value);}catch{} clearPalette();document.dispatchEvent(new CustomEvent('rosy:theme'));draw();};
$('intrinsics').value=JSON.stringify({camera_info_sha256:'',revision:'',k:[600,600,320,240],dist:[0,0,0,0,0]});
$('layout').value=JSON.stringify([[-20,0],[20,0],[-20,30],[20,30]].map((c,id)=>({id,size_cm:6,center_cm:c})));

function fail(error){$('camera-error').hidden=false;$('camera-error').textContent=error.message||String(error);}
async function request(path,body){
  const response=await accountFetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':token},body:JSON.stringify(body)}:{});
  const value=await response.json();
  if(!response.ok)throw new Error(response.status===403?'이 작업대의 권한이 거부되었습니다.':value.error||'요청 실패');
  return value;
}
async function jpeg(file){
  const bitmap=await createImageBitmap(file);
  const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;
  canvas.getContext('2d').drawImage(bitmap,0,0);
  return {bitmap,base64:canvas.toDataURL('image/jpeg',0.92).split(',')[1]};
}
function selected(){return references.find(r=>r.revision===$('reference').value);}
async function loadReferences(keep){
  references=(await request('/api/learning/camera/references')).references;
  $('reference').replaceChildren(...references.map(r=>{const o=document.createElement('option');o.value=r.revision;
    o.textContent=`${r.camera_role} · ${r.camera_identity} · ${r.created_at} · ${r.revision.slice(0,8)}`;return o;}));
  if(keep)$('reference').value=keep;
  await pick();
}
async function pick(){
  const ref=selected();result=null;still=null;
  $('fingerprint').value=ref?.intrinsics.camera_info_sha256||'';
  $('verdict').setAttribute('state',ref?'pending':'empty');
  $('verdict').textContent=ref?'지금 사진을 고르고 판정을 누르세요.':'촬영 기준이 없습니다. 아래에서 먼저 만드세요.';
  if(ref){still=new Image();still.onload=draw;still.src='/api/learning/camera/stills/'+ref.revision;}
  draw();
}
function poly(ctx,points,closed){ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));if(closed)ctx.closePath();ctx.stroke();}
function centre(points){return points.reduce(([a,b],[x,y])=>[a+x/points.length,b+y/points.length],[0,0]);}
function draw(){
  const ref=selected(),canvas=$('view'),ctx=canvas.getContext('2d');
  const base=photo||still;
  canvas.width=base?.width||ref?.width||640;canvas.height=base?.height||ref?.height||480;
  ctx.clearRect(0,0,canvas.width,canvas.height);
  if(photo)ctx.drawImage(photo,0,0);
  if(still?.complete&&still.naturalWidth){ctx.globalAlpha=photo?$('onion').value/100:1;ctx.drawImage(still,0,0);ctx.globalAlpha=1;}
  if(!ref)return;
  const width=Math.max(2,canvas.width/320);
  ctx.lineWidth=width;ctx.strokeStyle=cssColor('--status-warn');ctx.setLineDash([4*width,3*width]);
  ref.markers.forEach(m=>poly(ctx,m.corners_px,true));
  ref.guides.forEach(g=>poly(ctx,g.points,g.closed));
  ctx.setLineDash([]);
  if(!result)return;
  ctx.strokeStyle=cssColor('--status-good');
  for(const m of ref.markers){
    const now=result.detected[String(m.id)];if(!now)continue;
    poly(ctx,now,true);
    const [x0,y0]=centre(m.corners_px),[x1,y1]=centre(now);
    ctx.beginPath();ctx.moveTo(x0,y0);ctx.lineTo(x1,y1);ctx.stroke();
    const a=Math.atan2(y1-y0,x1-x0),h=4*width;
    if(Math.hypot(x1-x0,y1-y0)>h){ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x1-h*Math.cos(a-0.5),y1-h*Math.sin(a-0.5));
      ctx.moveTo(x1,y1);ctx.lineTo(x1-h*Math.cos(a+0.5),y1-h*Math.sin(a+0.5));ctx.stroke();}
  }
}
function signed(v,unit){return v==null?'—':`${v>0?'+':''}${v.toFixed(1)} ${unit}`;}
function show(check){
  const [state,text]=VERDICT[check.verdict];
  $('verdict').setAttribute('state',state);$('verdict').textContent=text;
  const rows=[['보인 마커',String(check.markers_seen)],['마커 오차 평균',signed(check.marker_px_mean,'px')],['마커 오차 최대',signed(check.marker_px_max,'px')],
    ...MOUNT.map(([key,label,unit])=>[label+' 차이',signed(check['d_'+key],unit)])];
  $('numbers').replaceChildren(...rows.flatMap(([k,v])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;return [dt,dd];}));
}

$('reference').onchange=()=>pick().catch(fail);
$('onion').oninput=()=>{$('onion-value').textContent=$('onion').value+'%';draw();};
$('check-photo').onchange=async()=>{photo=null;result=null;draw();};
$('check-form').onsubmit=async event=>{
  event.preventDefault();$('camera-error').hidden=true;
  try{
    const image=await jpeg($('check-photo').files[0]);photo=image.bitmap;
    result=await request('/api/learning/camera/check',{reference_revision:$('reference').value,image_jpeg:image.base64,camera_info_sha256:$('fingerprint').value});
    show(result.check);draw();
  }catch(error){fail(error);}
};
$('reference-form').onsubmit=async event=>{
  event.preventDefault();$('camera-error').hidden=true;
  try{
    const image=await jpeg($('reference-photo').files[0]);
    const measured=Object.fromEntries(MOUNT.map(([key])=>[key,$('m-'+key).value]).filter(([,v])=>v!=='').map(([k,v])=>[k,Number(v)]));
    const doc=await request('/api/learning/camera/reference',{image_jpeg:image.base64,camera_role:$('camera-role').value,
      camera_identity:$('camera-identity').value,fps:Number($('fps').value),intrinsics:JSON.parse($('intrinsics').value),
      layout:JSON.parse($('layout').value),measured,guides:JSON.parse($('guides').value)});
    const e=doc.mount.estimated;
    $('reference-result').textContent=`기준 ${doc.revision.slice(0,8)} 저장 — 추정 높이 ${e.height_cm.toFixed(1)} cm, 거리 ${e.distance_cm.toFixed(1)} cm, tilt ${e.tilt_deg.toFixed(1)}°`;
    await loadReferences(doc.revision);
  }catch(error){fail(error);}
};

(async()=>{token=(await request('/api/workspace')).token;await loadReferences();})().catch(fail);
