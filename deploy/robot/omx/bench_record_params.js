// Connected-first Arm cards + always-visible Speed Stage & 6-joint Caps parameter controls.
const JOINT_LABELS={'11':'11 · 어깨 회전(pan)','12':'12 · 어깨 들기(lift)','13':'13 · 팔꿈치(elbow)','14':'14 · 손목 굽힘(flex)','15':'15 · 손목 회전(roll)','16':'16 · 그리퍼(gripper)'};
const JOINT_SHORT={'11':'M11 회전','12':'M12 들기','13':'M13 팔꿈치','14':'M14 굽힘','15':'M15 회전','16':'M16 집게'};
const PARAM_LABELS={'pwm':'최대 토크(PWM)','current':'최대 전류(mA)','p':'추적 강성(P)','i':'오차 보정(I)','acc':'가속도(acc)','vel':'속도(vel)'};
const PARAM_SHORT={'pwm':'PWM','current':'전류','p':'P','i':'I','acc':'ACC','vel':'VEL'};
const ARM_META={arm_s:{title:'Arm S',role:'공급·컨베이어'},arm_a:{title:'Arm A',role:'선박 좌'},arm_b:{title:'Arm B',role:'선박 우'},arm_ab:{title:'Arm A+B',role:'양팔 동시'}};
const TELEOP_STAGES=[null,30,45,60,90,120];
let showOfflineArms=false, speedInFlight=false, capsSaveInFlight=false;

function armConnectivity(arm){
  const info=(lastArmsStatus&&lastArmsStatus[arm])||(choices&&choices.arm_connectivity&&choices.arm_connectivity[arm])||null;
  if(info&&typeof info.connected==='boolean')return info;
  return {connected:null,follower_connected:null,leader_connected:null};
}

function renderArmCards(){
  const bar=$('arm-card-bar');
  if(!bar||!armContractValid())return;
  const arms=choices.arms||[];
  const curArm=f&&f.arm?f.arm.value:'';
  const busy=benchSessionActive()||poseInFlight||startInFlight;
  const connArms=arms.filter(a=>armConnectivity(a).connected===true);
  const offArms=arms.filter(a=>armConnectivity(a).connected===false);
  const visible=(connArms.length>0&&!showOfflineArms)?arms.filter(a=>armConnectivity(a).connected===true||a===curArm):arms;
  for(const btn of document.querySelectorAll('#rail-arm-pills button[data-arm]')){
    const a=btn.dataset.arm;
    btn.hidden=(connArms.length>0&&!showOfflineArms&&armConnectivity(a).connected!==true&&a!==curArm);
  }
  const sig=JSON.stringify([visible,curArm,showOfflineArms,busy,arms.map(a=>armConnectivity(a)),lastStatus?.teleop_speed_declared]);
  if(bar.dataset.sig===sig)return;
  bar.dataset.sig=sig;
  bar.innerHTML='';
  const grid=document.createElement('div');
  grid.className='arm-card-grid';
  for(const a of visible){
    const c=armConnectivity(a), meta=ARM_META[a]||{title:a,role:''};
    const spd=lastStatus?.teleop_speed_declared?.[a];
    const spdTxt=spd&&Number.isFinite(spd.track_deg_s)?(spd.track_deg_s+'°/s'):'';
    const card=document.createElement('button');
    card.type='button';
    card.className='arm-card'+(a===curArm?' active':'')+(c.connected===false?' is-offline':'');
    card.dataset.armCard=a;
    card.setAttribute('aria-pressed',a===curArm?'true':'false');
    card.disabled=busy;
    const head=document.createElement('div');head.className='arm-card-head';
    const title=document.createElement('strong');title.textContent=meta.title;
    const dot=document.createElement('span');dot.className='arm-dot';
    dot.dataset.conn=c.connected===true?'on':(c.connected===false?'off':'unk');
    dot.textContent=c.connected===true?'● 연결됨':(c.connected===false?'미연결':'확인 중');
    head.append(title,dot);
    const sub=document.createElement('div');sub.className='arm-card-meta mono';
    const fMark=c.follower_connected===true?'F✓':(c.follower_connected===false?'F✗':'F?');
    const lMark=c.leader_connected===true?'L✓':(c.leader_connected===false?'L✗':'L?');
    sub.textContent=[meta.role,fMark+' '+lMark,spdTxt].filter(Boolean).join(' · ');
    card.append(head,sub);
    card.addEventListener('click',()=>{if(!benchSessionActive())selectArm(a);});
    grid.append(card);
  }
  bar.append(grid);
  if(connArms.length>0&&offArms.length>0){
    const toggle=document.createElement('button');
    toggle.type='button';
    toggle.className='btn-tool btn-xs arm-offline-toggle';
    toggle.textContent=showOfflineArms?'미연결 암 숨기기':('미연결 암 '+offArms.length+'개 보기');
    toggle.addEventListener('click',()=>{showOfflineArms=!showOfflineArms;renderArmCards();});
    bar.append(toggle);
  }
}

function capsBounds(mid,key){
  if(key==='pwm')return [1,('11'===mid||'12'===mid||'13'===mid)?600:400];
  if(key==='current')return [1,400];
  if(key==='p')return [1,1600];
  if(key==='i')return [0,1600];
  return [0,2000];
}

async function submitCaps(rootEl){
  if(!rootEl||capsSaveInFlight)return;
  const values={};
  for(const inp of rootEl.querySelectorAll('input[data-mid]')){
    const m=inp.dataset.mid, k=inp.dataset.key, v=Number(inp.value);
    const [lo,hi]=capsBounds(m,k);
    if(!Number.isInteger(v)||v<lo||v>hi){setReqError('모터 '+m+'.'+k+' 값은 '+lo+'~'+hi+' 정수여야 합니다');return;}
    (values[m]=values[m]||{})[k]=v;
  }
  capsSaveInFlight=true;
  if(typeof setActivity==='function')setActivity('관절 한계(caps) 저장 중...','live',f.arm.value);
  try{
    setReqError('');
    const res=await api('/save_caps',{arm:f.arm.value,values});
    choices=res.choices;
    f.caps.innerHTML='';f.caps.append(new Option('선택하세요',''));
    for(const v of (choices.caps||[]))f.caps.append(new Option(v,v));
    applyArmRules(false);
    f.caps.value=res.saved;
    renderCapsEditor();
    renderParamsPanel();
    validateStart();
    if(typeof setActivity==='function')setActivity('관절 한계(caps) 저장 완료','good',res.saved);
  }catch(err){
    setReqError(err.message);
    if(typeof setActivity==='function')setActivity('관절 한계(caps) 저장 실패','crit',err.message);
  }finally{
    capsSaveInFlight=false;
    renderParamsPanel();
  }
}

function renderParamsPanel(){
  const arm=f&&f.arm?f.arm.value:'';
  const busy=benchSessionActive()||poseInFlight||startInFlight;
  const pillsEl=$('sb-speed-pills'), detailEl=$('sb-speed-detail');
  if(pillsEl){
    const single=arm==='arm_a'||arm==='arm_b'||arm==='arm_s';
    const decl=single?lastStatus?.teleop_speed_declared?.[arm]:null;
    const curStage=decl?decl.stage:null;
    if(detailEl){
      detailEl.textContent=decl?('추종 '+decl.track_deg_s+'°/s · 가속 '+decl.accel_deg_s2+' · 제동 '+decl.brake_deg_s2):(single?'속도 정보 확인 중':'단일 팔 전용');
    }
    const sSig=JSON.stringify([arm,single,curStage,busy,speedInFlight]);
    if(pillsEl.dataset.sig!==sSig){
      pillsEl.dataset.sig=sSig;
      pillsEl.innerHTML='';
      for(const s of TELEOP_STAGES){
        const btn=document.createElement('button');
        btn.type='button';
        btn.className='pill-btn mono'+((single&&curStage===s)?' active':'');
        btn.dataset.speedStage=s===null?'default':String(s);
        btn.textContent=s===null?'기본 25':(s+'°/s');
        btn.setAttribute('aria-pressed',(single&&curStage===s)?'true':'false');
        btn.disabled=!single||busy||speedInFlight;
        btn.addEventListener('click',async()=>{
          if(!single||benchSessionActive()||speedInFlight)return;
          speedInFlight=true;renderParamsPanel();
          if(typeof setActivity==='function')setActivity('추종 속도 변경 중...','live',arm+' → '+(s?s+'°/s':'기본 25°/s'));
          try{
            setReqError('');
            const st=await api('/api/teleop_speed',{arm,stage:s});
            renderStatus(st);
            if(typeof setActivity==='function')setActivity('추종 속도 변경 완료','good',arm+' → '+(s?s+'°/s':'기본 25°/s'));
          }catch(err){
            setReqError('속도 변경: '+err.message);
            if(typeof setActivity==='function')setActivity('추종 속도 변경 실패','crit',err.message);
          }finally{speedInFlight=false;renderParamsPanel();}
        });
        pillsEl.append(btn);
      }
    }
  }
  const table=$('sb-joint-caps-table'), saveBtn=$('sb-caps-save-btn');
  if(!table)return;
  const cname=f&&f.caps?f.caps.value:'';
  const data=choices&&choices.caps_data?choices.caps_data[cname]:null;
  const cSig=(cname||'')+':'+JSON.stringify(data||{});
  if(saveBtn)saveBtn.disabled=busy||capsSaveInFlight||!cname||!data;
  if(table.dataset.capsSig!==cSig&&!table.contains(document.activeElement)){
    table.dataset.capsSig=cSig;
    table.innerHTML='';
    if(!cname||!data||typeof data!=='object'){
      const p=document.createElement('div');p.className='quiet';p.textContent='caps 파일을 선택하면 6관절 한계·P/I 게인을 바로 조정할 수 있습니다.';
      table.append(p);
    }else{
      for(const [mid,obj] of Object.entries(data)){
        if(!obj||typeof obj!=='object')continue;
        const row=document.createElement('div');row.className='jc-row';
        const lbl=document.createElement('span');lbl.className='jc-lbl';lbl.textContent=JOINT_SHORT[mid]||('M'+mid);
        const flds=document.createElement('div');flds.className='jc-fields';
        for(const [k,val] of Object.entries(obj)){
          const [lo,hi]=capsBounds(mid,k);
          const wrap=document.createElement('label');wrap.className='jc-field';
          const sp=document.createElement('span');sp.textContent=PARAM_SHORT[k]||k;
          const inp=document.createElement('input');
          inp.type='number';inp.className='jc-inp';inp.min=String(lo);inp.max=String(hi);inp.value=String(val);
          inp.dataset.mid=mid;inp.dataset.key=k;
          inp.ariaLabel=(JOINT_SHORT[mid]||('M'+mid))+' '+(PARAM_LABELS[k]||k);
          wrap.append(sp,inp);flds.append(wrap);
        }
        row.append(lbl,flds);table.append(row);
      }
    }
  }
  for(const inp of table.querySelectorAll('input[data-mid]'))inp.disabled=busy||capsSaveInFlight;
}

function renderCapsSummary(){
  const wrap=$('caps-summary-chart');
  const inputs=[...$('caps-fields').querySelectorAll('input[data-mid][data-key="pwm"]')];
  if(!inputs.length){wrap.innerHTML='';return;}
  let html='<div style="display:grid;grid-template-columns:repeat('+inputs.length+',minmax(0,1fr));gap:6px;align-items:end;height:68px;padding:8px;background:var(--ground-deep);border:1px solid var(--bd);border-radius:6px">';
  for(const inp of inputs){
    const v=Math.max(0,Math.min(2000,Number(inp.value)||0));
    const h=Math.max(6,Math.round((v/2000)*46));
    const col=v>=1000?'#ffc53d':'#58a6ff';
    html+='<div style="display:flex;flex-direction:column;align-items:center;gap:2px"><div style="width:100%;max-width:34px;height:'+h+'px;background:'+col+';border-radius:4px 4px 0 0"></div><span class="mono" style="font-size:.7rem;color:var(--ink-q)">M'+inp.dataset.mid+'</span></div>';
  }
  wrap.innerHTML=html+'</div>';
}

function renderCapsEditor(){
  renderConfigMeta();
  const name=f.caps.value;
  const data=choices&&choices.caps_data?choices.caps_data[name]:null;
  const box=$('caps-editor'), fields=$('caps-fields');
  if(!name||!data||typeof data!=='object'){box.hidden=true;fields.innerHTML='';$('caps-summary-chart').innerHTML='';return;}
  box.hidden=false;fields.innerHTML='';
  for(const [mid,obj] of Object.entries(data)){
    if(!obj||typeof obj!=='object')continue;
    const card=document.createElement('div');card.style.cssText='background:var(--ground-deep);border:1px solid var(--bd);border-radius:6px;padding:10px';
    const h=document.createElement('div');h.className='mono';h.style.cssText='font-weight:700;margin-bottom:6px;font-size:.9rem';h.textContent=JOINT_LABELS[mid]||('모터 ID '+mid);card.append(h);
    for(const [k,val] of Object.entries(obj)){
      const row=document.createElement('div');row.style.cssText='display:flex;align-items:center;gap:8px;margin-top:6px';
      const lbl=document.createElement('span');lbl.style.cssText='flex:0 0 118px;font-size:.82rem;color:var(--ink-q)';lbl.textContent=PARAM_LABELS[k]||k;
      const track=document.createElement('div');track.className='bar-track';
      const fill=document.createElement('div');fill.className='bar-fill';
      const vtxt=document.createElement('span');vtxt.className='bar-val';
      track.append(fill,vtxt);
      const inp=document.createElement('input');inp.type='number';inp.min='0';inp.max='2000';inp.value=String(val);
      inp.dataset.mid=mid;inp.dataset.key=k;
      inp.style.cssText='width:68px;min-height:30px;padding:2px 6px;background:var(--ground-soft);color:var(--ink);border:1px solid var(--bd);border-radius:4px;font-family:ui-monospace,monospace';
      const sync=(n)=>{
        const c=Math.max(0,Math.min(2000,Math.round(n)));
        inp.value=String(c);
        fill.style.width=(c/2000*100)+'%';
        fill.className='bar-fill'+(c>=1000?' high':'');
        vtxt.textContent=String(c);
        renderCapsSummary();
      };
      const onPtr=(e)=>{
        const r=track.getBoundingClientRect();
        const ratio=Math.max(0,Math.min(1,(e.clientX-r.left)/Math.max(1,r.width)));
        sync(Math.round((ratio*2000)/10)*10);
      };
      let dragging=false;
      track.addEventListener('pointerdown',e=>{dragging=true;track.setPointerCapture(e.pointerId);onPtr(e);});
      track.addEventListener('pointermove',e=>{if(dragging)onPtr(e);});
      track.addEventListener('pointerup',()=>{dragging=false;});
      track.addEventListener('pointercancel',()=>{dragging=false;});
      inp.addEventListener('input',()=>sync(Number(inp.value)||0));
      row.append(lbl,track,inp);card.append(row);
      sync(Number(val)||0);
    }
    fields.append(card);
  }
  renderCapsSummary();
}

if($('save-caps-btn'))$('save-caps-btn').addEventListener('click',()=>submitCaps($('caps-fields')));
if($('sb-caps-save-btn'))$('sb-caps-save-btn').addEventListener('click',()=>submitCaps($('sb-joint-caps-table')));
if($('sb-caps-drawer-btn'))$('sb-caps-drawer-btn').addEventListener('click',()=>{
  if(typeof window.openDrawer==='function')window.openDrawer('bindings',$('sb-caps-drawer-btn'),$('caps'));
  $('caps-editor')?.scrollIntoView({block:'nearest'});
});

window.renderArmCards=renderArmCards;
window.renderParamsPanel=renderParamsPanel;
window.renderCapsEditor=renderCapsEditor;
window.renderCapsSummary=renderCapsSummary;
