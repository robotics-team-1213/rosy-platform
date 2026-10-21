// D-792: one photo against one camera setup reference. Dashed = reference, solid = this photo.
// features (default, no markers): reference outlines mapped by the measured homography.
// markers (optional): reference marker squares against the detected ones.
import {accountFetch} from '/account-session.js';
import {cssColor} from '/common/ui.js';
import '/commands.js';
const $=id=>document.getElementById(id);
const MOUNT=[['height_cm','높이','cm'],['distance_cm','거리','cm'],['tilt_deg','tilt','°'],['pan_deg','pan','°'],['roll_deg','roll','°']];
const VERDICT={ok:['ready','맞음 — 이 위치로 녹화할 수 있습니다.'],adjust:['warning','조정 필요 — 점선에 실선이 겹치도록 카메라를 옮기세요.'],
  unmeasurable:['error','측정 불가 — 너무 어둡거나 장면이 많이 바뀌어 기준과 맞출 수 없습니다(마커 방식은 마커 3개 이상). 손목 카메라는 팔을 확인 자세로 보냈는지, 교정 지문과 해상도도 확인하세요.']};
let token, references=[], still=null, photo=null, result=null;

document.addEventListener('rosy:theme',draw);
$('intrinsics').value=JSON.stringify({camera_info_sha256:'',revision:'',k:[600,600,320,240],dist:[0,0,0,0,0]});
$('layout').value=JSON.stringify([[-20,0],[20,0],[-20,30],[20,30]].map((c,id)=>({id,size_cm:6,center_cm:c})));
$('method').onchange=()=>{$('layout-field').hidden=$('method').value!=='markers';};
$('method').onchange();
$('check-pose').value=JSON.stringify({joint_names:['joint1','joint2','joint3','joint4','joint5'],positions_rad:[0,0,0,0,0],tolerance_rad:0.01});
$('camera-role').onchange=()=>{$('check-pose-field').hidden=$('camera-role').value!=='front';};
$('camera-role').onchange();

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
    o.textContent=`${r.camera_role} · ${r.camera_identity} · ${r.method==='markers'?'마커':'마커 없음'} · ${r.created_at} · ${r.revision.slice(0,8)}`;return o;}));
  if(keep)$('reference').value=keep;
  await pick();
}
async function pick(){
  const ref=selected();result=null;still=null;
  $('fingerprint').value=ref?.intrinsics.camera_info_sha256||'';
  $('verdict').setAttribute('state',ref?'pending':'empty');
  $('verdict').textContent=ref?'지금 사진을 고르고 판정을 누르세요.':'촬영 기준이 없습니다. 아래에서 먼저 만드세요.';
  $('numbers').replaceChildren();
  $('joints-field').hidden=!ref?.check_pose;
  if(ref?.check_pose)$('joints').value=JSON.stringify(Object.fromEntries(ref.check_pose.joint_names.map((n,i)=>[n,ref.check_pose.positions_rad[i]])));
  if(ref){still=new Image();still.onload=draw;still.src='/api/learning/camera/stills/'+ref.revision;}
  draw();
}
function poly(ctx,points,closed){ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));if(closed)ctx.closePath();ctx.stroke();}
function centre(points){return points.reduce(([a,b],[x,y])=>[a+x/points.length,b+y/points.length],[0,0]);}
function project(h,[x,y]){const w=h[2][0]*x+h[2][1]*y+h[2][2];return [(h[0][0]*x+h[0][1]*y+h[0][2])/w,(h[1][0]*x+h[1][1]*y+h[1][2])/w];}
// Shapes every reference shows: its guides, its markers, and an inset frame so a reference without guides still has one.
function shapes(ref){
  const [w,h]=[ref.width,ref.height],frame=[[.1*w,.1*h],[.9*w,.1*h],[.9*w,.9*h],[.1*w,.9*h]];
  return [{points:frame,closed:true},...ref.guides,...ref.markers.map(m=>({points:m.corners_px,closed:true,id:m.id}))];
}
function arrow(ctx,[x0,y0],[x1,y1],head){
  ctx.beginPath();ctx.moveTo(x0,y0);ctx.lineTo(x1,y1);ctx.stroke();
  if(Math.hypot(x1-x0,y1-y0)<=head)return;
  const a=Math.atan2(y1-y0,x1-x0);
  ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x1-head*Math.cos(a-0.5),y1-head*Math.sin(a-0.5));
  ctx.moveTo(x1,y1);ctx.lineTo(x1-head*Math.cos(a+0.5),y1-head*Math.sin(a+0.5));ctx.stroke();
}
function draw(){
  const ref=selected(),canvas=$('view'),ctx=canvas.getContext('2d');
  const base=photo||still;
  canvas.hidden=!(ref||photo||still);  // no reference and no photo: nothing to compare, no empty board
  canvas.width=base?.width||ref?.width||640;canvas.height=base?.height||ref?.height||480;
  ctx.clearRect(0,0,canvas.width,canvas.height);
  if(photo)ctx.drawImage(photo,0,0);
  if(still?.complete&&still.naturalWidth){ctx.globalAlpha=photo?$('onion').value/100:1;ctx.drawImage(still,0,0);ctx.globalAlpha=1;}
  if(!ref)return;
  const width=Math.max(2,canvas.width/320),list=shapes(ref);
  ctx.lineWidth=width;ctx.strokeStyle=cssColor('--status-warn');ctx.setLineDash([4*width,3*width]);
  list.forEach(s=>poly(ctx,s.points,s.closed));
  ctx.setLineDash([]);
  if(!result)return;
  ctx.strokeStyle=cssColor('--status-good');
  if(result.homography){
    for(const s of list){
      const now=s.points.map(p=>project(result.homography,p));
      poly(ctx,now,s.closed);
      if(s===list[0])s.points.forEach((p,i)=>arrow(ctx,p,now[i],4*width));
    }
    const c=[ref.width/2,ref.height/2];arrow(ctx,c,project(result.homography,c),4*width);
  }
  for(const m of ref.markers){
    const now=result.detected?.[String(m.id)];if(!now)continue;
    poly(ctx,now,true);arrow(ctx,centre(m.corners_px),centre(now),4*width);
  }
}
function signed(v,unit){return v==null?'—':`${v>0?'+':''}${v.toFixed(1)} ${unit}`;}
function show(check){
  const [state,text]=VERDICT[check.verdict];
  $('verdict').setAttribute('state',state);$('verdict').textContent=text;
  const rows=[[check.method==='markers'?'보인 마커':'맞춘 특징점',String(check.matches)],['확인 자세 오차',check.pose_error_rad==null?'—':`${check.pose_error_rad.toFixed(3)} rad`],
    ['화면 이동 평균',signed(check.px_mean,'px')],['화면 이동 최대',signed(check.px_max,'px')],
    ['pan 차이',signed(check.d_pan_deg,'°')],['tilt 차이',signed(check.d_tilt_deg,'°')],['roll 차이',signed(check.d_roll_deg,'°')],
    ['크기 차이(멀어짐 −)',signed(check.d_scale_pct,'%')],['높이 차이',signed(check.d_height_cm,'cm')],['거리 차이',signed(check.d_distance_cm,'cm')]];
  $('numbers').replaceChildren(...rows.flatMap(([k,v])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;return [dt,dd];}));
}

$('reference').onchange=()=>pick().catch(fail);
$('onion').oninput=()=>{$('onion-value').textContent=$('onion').value+'%';draw();};
$('check-photo').onchange=async()=>{photo=null;result=null;draw();};
$('check-form').onsubmit=async event=>{
  event.preventDefault();$('camera-error').hidden=true;
  try{
    const image=await jpeg($('check-photo').files[0]);photo=image.bitmap;
    result=await request('/api/learning/camera/check',{reference_revision:$('reference').value,image_jpeg:image.base64,camera_info_sha256:$('fingerprint').value,
      joints:selected()?.check_pose?JSON.parse($('joints').value):null});
    show(result.check);draw();
  }catch(error){fail(error);}
};
$('reference-form').onsubmit=async event=>{
  event.preventDefault();$('camera-error').hidden=true;
  try{
    const image=await jpeg($('reference-photo').files[0]),method=$('method').value;
    const measured=Object.fromEntries(MOUNT.map(([key])=>[key,$('m-'+key).value]).filter(([,v])=>v!=='').map(([k,v])=>[k,Number(v)]));
    const doc=await request('/api/learning/camera/reference',{image_jpeg:image.base64,camera_role:$('camera-role').value,
      camera_identity:$('camera-identity').value,fps:Number($('fps').value),intrinsics:JSON.parse($('intrinsics').value),method,
      layout:method==='markers'?JSON.parse($('layout').value):[],measured,guides:JSON.parse($('guides').value),
      check_pose:$('camera-role').value==='front'?JSON.parse($('check-pose').value):null});
    const e=doc.mount.estimated;
    $('reference-result').textContent=`기준 ${doc.revision.slice(0,8)} 저장`+(e?` — 추정 높이 ${e.height_cm.toFixed(1)} cm, 거리 ${e.distance_cm.toFixed(1)} cm, tilt ${e.tilt_deg.toFixed(1)}°`:' — 마커 없이 배경 특징점으로 맞춥니다.');
    await loadReferences(doc.revision);
  }catch(error){fail(error);}
};

(async()=>{token=(await request('/api/workspace')).token;await loadReferences();})().catch(fail);
