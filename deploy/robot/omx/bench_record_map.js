// Arm-aware interactive workbench map, hold 3x3 grid, stand slot/layer table, and arm_s route table.
// Ship address ship-h<hold>r<row>-l<layer>: counts from 0 for rows and layers (tools/sim/omx_two_arm_sites.py r08_sites; r0 is nearest arm_a, r2 arm_b).
// The names below count layers from 1 (tier numbers of shared/web/cell-site-map.json). Hold h1 is columns 4~6 and h2 columns 1~3 there (Harbor's hold 1 is h2).
const ROW_LABELS=['A쪽 줄','가운데 줄','B쪽 줄'];
const LAYER_LABELS=['1층(바닥)','2층(중간)','3층(맨 위)'];
const HOLD_COLUMNS={1:'4~6열',2:'1~3열'};

function escHtml(s){
  return String(s??'').replace(/[&<>"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
}

function taskFitsArm(v,c,arm){
  if(!arm)return true;
  const explicit=String(c?.shot_arm||'').trim().toLowerCase();
  if(explicit){
    if(arm==='arm_ab')return explicit==='arm_a'||explicit==='arm_b'||explicit==='arm_ab';
    return explicit===arm;
  }
  const hay=(String(v||'')+' '+(c?.origin||'')+' '+(c?.target_slot||'')+' '+(c?.single_task||'')).toLowerCase();
  if(arm==='arm_s')return /arm[_ -]?s\b|belt-in|conveyor|supply|pinky|strawberry|teach-cycle/.test(hay);
  if(arm==='arm_a')return !/arm[_ -]?[bs]\b|tmp-b|belt-in|conveyor|supply|pinky|strawberry|teach-cycle/.test(hay);
  if(arm==='arm_b')return !/arm[_ -]?[as]\b|tmp-a|belt-in|conveyor|supply|pinky|strawberry|teach-cycle|\bstand\b/.test(hay);
  if(arm==='arm_ab')return !/arm[_ -]?s\b|belt-in|conveyor|supply|pinky|strawberry|teach-cycle/.test(hay);
  return true;
}
window.taskFitsArm=taskFitsArm;

function taskArmOwnerHint(v,c){
  const explicit=String(c?.shot_arm||'').trim().toLowerCase();
  if(explicit==='arm_a'||explicit==='arm_b'||explicit==='arm_s')return explicit;
  const hay=(String(v||'')+' '+(c?.origin||'')+' '+(c?.target_slot||'')+' '+(c?.single_task||'')).toLowerCase();
  if(/\barm[_ -]?a\b|tmp-a/.test(hay))return 'arm_a';
  if(/\barm[_ -]?b\b|tmp-b/.test(hay))return 'arm_b';
  if(/\barm[_ -]?s\b|pinky|conveyor|supply|strawberry/.test(hay))return 'arm_s';
  return '';
}

function describeSpot(code){
  if(!code)return '미확인';
  const s=String(code);
  if(s==='belt')return '벨트 인출단 (Arm A/B 집는 곳 · belt)';
  if(s==='belt-in'||s==='belt-s')return '벨트 공급단 (Arm S 놓는 곳 · belt-in)';
  if(s==='stand'||s==='stand:r1-s1'||s==='stand:r1-s1-t1')return '반출대 (Arm A 전용 · 컨베이어 우측 · stand)';
  if(s==='pinky'||s.startsWith('pinky-'))return '핑키 로봇 ('+s+')';
  if(s==='supply')return '공급대 (supply)';
  if(s==='bowl')return '흰 그릇 (bowl)';
  let m=s.match(/^ship-h(\d)r(\d)-l(\d)$/);
  if(m){
    const r=Number(m[2]), l=Number(m[3]);
    const rTxt=ROW_LABELS[r]||((r+1)+'번째 줄');
    const lTxt=LAYER_LABELS[l]||((l+1)+'층');
    return '화물칸 h'+m[1]+' · '+rTxt+' · '+lTxt+' ['+s+']';
  }
  m=s.match(/^tmp-([ab])-(\d+)(?:-l(\d+))?$/);
  if(m){
    const side=m[1]==='a'?'왼쪽':'오른쪽';
    const lTxt=m[3]?(LAYER_LABELS[Number(m[3])]||((Number(m[3])+1)+'층')):'1층(바닥)';
    return '임시대 '+m[1].toUpperCase()+'('+side+') · '+m[2]+'번 칸 · '+lTxt+' ['+s+']';
  }
  return s;
}

function splitSpotDisplay(text){
  const s=String(text||'');
  const m=s.match(/^(.+?)\s*(?:\(([^)]+)\)|\[([^\]]+)\])\s*$/);
  if(!m)return {main:s,sub:''};
  return {main:m[1].trim(),sub:(m[2]||m[3]||'').trim()};
}

function inferCardSpots(t,c){
  if(!c||c.valid===false)return {rawO:'',rawT:''};
  const taskLow=(String(t||'')+' '+String(c.single_task||'')).toLowerCase();
  const isPinky=taskLow.includes('pinky');
  const isSupply=taskLow.includes('supply');
  const isBeltIn=taskLow.includes('conveyor')||isSupply;
  const isStraw=taskLow.includes('strawberry');
  const rawO=c.origin?String(c.origin):(isPinky?'pinky':(isSupply?'supply':(isStraw?'bowl':'')));
  const rawT=c.target_slot?String(c.target_slot):(isPinky&&taskLow.includes('teach')?'벨트 왕복 (teach-cycle)':(isBeltIn?'belt-in':(isStraw?'표시 지점':'')));
  return {rawO,rawT};
}

function armZones(arm){
  if(arm==='arm_s')return ['arm-s'];
  if(arm==='arm_a')return ['ship-h1','ship-h2','tmp-a'];
  if(arm==='arm_b')return ['ship-h1','ship-h2','tmp-b'];
  return ['ship-h1','ship-h2','tmp-a','tmp-b'];
}

function zoneForTask(oStr,tStr,arm){
  if(arm==='arm_s')return 'arm-s';
  for(const s of [oStr,tStr]){
    if(s.startsWith('tmp-a'))return 'tmp-a';
    if(s.startsWith('tmp-b'))return 'tmp-b';
  }
  for(const s of [tStr,oStr]){
    const m=s.match(/^ship-h(\d)/);
    if(m)return 'ship-h'+m[1];
  }
  return null;
}

function resolveActiveZone(arm,oStr,tStr){
  if(window.shipHold)return 'ship-h'+window.shipHold;
  const zones=armZones(arm);
  if(window.mapZone&&zones.includes(window.mapZone))return window.mapZone;
  const inferred=zoneForTask(oStr,tStr,arm);
  if(inferred&&zones.includes(inferred))return inferred;
  return zones[0];
}

function parseStandCard(v,c){
  for(const [field,dir] of [[c?.origin,'to-ship'],[c?.target_slot,'to-temp']]){
    const m=String(field||'').match(/^tmp-([ab])-(\d+)(?:-l(\d+))?$/);
    if(m)return {key:v,card:c,side:m[1],slot:Number(m[2]),layer:m[3]?Number(m[3]):0,dir};
  }
  return null;
}

function armSRowMeta(v,c){
  const low=(String(v||'')+' '+String(c?.single_task||'')).toLowerCase();
  if(low.includes('teach'))return {pick:'핑키 로봇',place:'벨트 공급단 왕복 (교시)'};
  if(low.includes('pinky'))return {pick:'핑키 로봇 (pinky)',place:'벨트 공급단 (belt-in)'};
  if(low.includes('supply'))return {pick:'공급대 (supply)',place:'벨트 공급단 (belt-in)'};
  if(low.includes('strawberry'))return {pick:'흰 그릇 (딸기)',place:'표시 지점 왕복'};
  const {rawO,rawT}=inferCardSpots(v,c);
  if(rawO||rawT)return {pick:describeSpot(rawO),place:describeSpot(rawT)};
  return {pick:c?.task_id||v,place:String(c?.single_task||'')};
}

let lastMapNote='', lastStandTask='';
window.clearMapNote=()=>{lastMapNote='';lastStandTask='';};
window.mapZone=null;
window.standDir='to-ship';
window.shipHold=null;

function applyPickedTask(spot,pool){
  const curIdx=pool.indexOf(f.task.value);
  const nextTask=pool[(curIdx+1)%pool.length];
  if($('task-search'))$('task-search').value='';
  selectTask(nextTask,{keepMapZone:true});
  lastMapNote=spot+' 선택 · 일치 과제 카드 '+pool.length+'개 ('+(pool.indexOf(nextTask)+1)+'/'+pool.length+' · '+nextTask+')';
  const noteEl=$('cam-map-note');
  if(noteEl){noteEl.textContent=lastMapNote;noteEl.hidden=false;}
  const selOpt=$('task-listbox')?.querySelector('[aria-selected="true"]');
  if(selOpt)selOpt.scrollIntoView({block:'nearest'});
}

function pickTaskBySpot(spot){
  if(benchSessionActive()||!choices||!Array.isArray(choices.tasks))return;
  const arm=f.arm?f.arm.value:'';
  const cards=choices.task_cards||{};
  const validAll=choices.tasks.filter(v=>cards[v]&&cards[v].valid!==false);
  const validArm=validAll.filter(v=>taskFitsArm(v,cards[v],arm));
  const cellSel=spot.match(/^ship-h(\d)r(\d)-l(\d)$/);
  const holdSel=spot.match(/^ship-h(\d)$/);
  const pickStand=(tasks,side)=>{
    const parsed=tasks.map(v=>parseStandCard(v,cards[v])).filter(p=>p&&p.side===side);
    const sameDir=parsed.filter(p=>p.dir===(window.standDir||'to-ship')).map(p=>p.key);
    return sameDir.length?sameDir:parsed.map(p=>p.key);
  };
  const poolFor=(tasks)=>{
    if(spot==='belt-in')return tasks.filter(v=>/conveyor|supply|arm[_ -]?s/.test((v+' '+(cards[v].single_task||'')+' '+(cards[v].raw||'')).toLowerCase()));
    if(spot==='pinky')return tasks.filter(v=>(v+' '+(cards[v].origin||'')+' '+(cards[v].target_slot||'')+' '+(cards[v].single_task||'')).toLowerCase().includes('pinky'));
    if(spot==='tmp-a'||spot==='tmp-b')return pickStand(tasks,spot.slice(-1));
    if(spot==='belt')return tasks.filter(v=>String(cards[v].origin||'')==='belt');
    const nonTmpExact=tasks.filter(v=>String(cards[v].target_slot||'')===spot&&!String(cards[v].origin||'').startsWith('tmp-'));
    const exactTgt=tasks.filter(v=>String(cards[v].target_slot||'')===spot);
    const prefNonTmp=tasks.filter(v=>String(cards[v].target_slot||'').startsWith(spot)&&!String(cards[v].origin||'').startsWith('tmp-'));
    const prefTgt=tasks.filter(v=>String(cards[v].target_slot||'').startsWith(spot));
    const anySpot=tasks.filter(v=>{
      const c=cards[v];
      return String(c.origin||'').startsWith(spot)||String(c.target_slot||'').startsWith(spot)||String(v).toLowerCase().includes(spot.toLowerCase());
    });
    return nonTmpExact.length?nonTmpExact:(exactTgt.length?exactTgt:(prefNonTmp.length?prefNonTmp:(prefTgt.length?prefTgt:anySpot)));
  };
  if(holdSel){window.mapZone=spot;window.shipHold=Number(holdSel[1]);}
  else if(cellSel){window.mapZone='ship-h'+cellSel[1];window.shipHold=Number(cellSel[1]);}
  else if(spot==='tmp-a'||spot==='tmp-b'){
    const armStand=poolFor(validArm);
    if(armStand.length){window.mapZone=spot;window.shipHold=null;}
  }else if(spot==='pinky'||spot==='belt-in'){
    if(arm==='arm_s'){window.mapZone='arm-s';window.shipHold=null;}
  }else if(spot==='belt'){
    window.mapZone=null;window.shipHold=null;
  }
  const pool=poolFor(validArm);
  if(!pool.length){
    const otherPool=poolFor(validAll);
    const owner=otherPool.length?taskArmOwnerHint(otherPool[0],cards[otherPool[0]]):'';
    lastMapNote=owner
      ?(spot+': '+owner+' 전용 구역/칸입니다 (상단에서 '+owner+' 선택)')
      :(spot+' 구역: 이 조합의 과제 카드 없음'+(holdSel?' (화물칸 h'+holdSel[1]+')':''));
    renderCamGuide();
    return;
  }
  applyPickedTask(spot,pool);
}

function zoneTitleLabel(z){
  if(z==='ship-h1')return '화물칸 h1 · '+HOLD_COLUMNS[1];
  if(z==='ship-h2')return '화물칸 h2 · '+HOLD_COLUMNS[2];
  if(z==='tmp-a')return '임시대 A (좌)';
  if(z==='tmp-b')return '임시대 B (우)';
  return 'Arm S 위치 · 동선';
}

function renderShipGridHtml(k,n,tStr,isStandTask,arm,tasks,cards){
  const sm=!isStandTask?tStr.match(/^ship-h(\d)r(\d)-l(\d)$/):null;
  const th=sm?Number(sm[1]):0, tr=sm?Number(sm[2]):-1, tl=sm?Number(sm[3]):-1;
  // one grid: the selected hold (hold boxes above sit in site-map column order, h2 = columns 1~3 on top, h1 = columns 4~6 below)
  let html='<div><b>화물칸 h'+k+'</b> · '+HOLD_COLUMNS[k]+' · 3줄 × 3층 · '+(n?'과제 카드 '+n+'개':'과제 카드 없음 (칸을 눌러도 연결되지 않음)')+'</div>';
  html+='<div class="ship-grid'+(n?'':' empty')+'" aria-label="화물칸 h'+k+' 층·줄 선택" style="display:grid;grid-template-columns:68px repeat(3,minmax(0,1fr));gap:4px;align-items:center"><div></div>';
  for(const row of [0,1,2]){
    html+='<div class="quiet" style="text-align:center;font-size:.75rem;font-weight:700">'+ROW_LABELS[row]+'</div>';
  }
  for(const lv of [2,1,0]){
    html+='<div class="quiet" style="font-size:.75rem;font-weight:700;text-align:right;padding-right:4px">'+LAYER_LABELS[lv]+'</div>';
    for(const row of [0,1,2]){
      const spot='ship-h'+k+'r'+row+'-l'+lv;
      const hit=(k===th&&row===tr&&lv===tl);
      const allMatches=tasks.filter(v=>String(cards[v].target_slot||'')===spot&&!String(cards[v].origin||'').startsWith('tmp-'));
      const armMatch=allMatches.find(v=>taskFitsArm(v,cards[v],arm));
      const anyMatch=armMatch||allMatches[0];
      const owner=anyMatch&&!armMatch?taskArmOwnerHint(anyMatch,cards[anyMatch]):'';
      const ownerShort=owner==='arm_a'?'A전용':(owner==='arm_b'?'B전용':'');
      const q=(armMatch&&typeof epQuota==='function')?epQuota(cards[armMatch]):null;
      const cls='slot-btn'+(hit?' active':'')+(!armMatch&&anyMatch?' other-arm':(!anyMatch?' empty-cell':''));
      const lbl=(lv+1)+'층'+(hit?' ★':(ownerShort?' ('+ownerShort+')':(q&&q.done>0?' · '+q.done+'/'+q.goal:'')));
      const tip=describeSpot(spot)+(owner?' · '+owner+' 전용':(armMatch?' · '+armMatch:' · 카드 없음'));
      html+='<button type="button" class="'+cls+'" aria-pressed="'+(hit?'true':'false')+'" data-spot="'+spot+'" title="'+escHtml(tip)+'" aria-label="'+escHtml(tip)+'">'+escHtml(lbl)+'</button>';
    }
  }
  return html+'</div>';
}

function renderStandGridHtml(side,tasks,cards,curTask){
  const allParsed=tasks.map(v=>parseStandCard(v,cards[v])).filter(p=>p&&p.side===side);
  const curParsed=curTask?parseStandCard(curTask,cards[curTask]):null;
  if(curParsed&&curParsed.side===side&&curTask!==lastStandTask)window.standDir=curParsed.dir;
  lastStandTask=curTask||'';
  const dir=window.standDir==='to-temp'?'to-temp':'to-ship';
  const defaultSlots=side==='a'?[1,2,3]:[2,3];
  const slots=[...new Set([...defaultSlots,...allParsed.map(p=>p.slot)])].sort((a,b)=>a-b);
  const sideLabel=side==='a'?'임시대 A (좌)':'임시대 B (우)';
  let html='<div class="stand-head-row"><b>'+sideLabel+' · 칸 × 층 선택</b><div class="dir-toggle" role="group" aria-label="임시대 이동 방향">';
  html+='<button type="button" class="pill-btn'+(dir==='to-ship'?' active':'')+'" data-stand-dir="to-ship" aria-pressed="'+(dir==='to-ship'?'true':'false')+'">임시대 → 선박</button>';
  html+='<button type="button" class="pill-btn'+(dir==='to-temp'?' active':'')+'" data-stand-dir="to-temp" aria-pressed="'+(dir==='to-temp'?'true':'false')+'">선박 → 임시대</button>';
  html+='</div></div>';
  html+='<div class="stand-grid" aria-label="'+sideLabel+' 칸·층 선택" style="grid-template-columns:68px repeat('+slots.length+',minmax(0,1fr))"><div></div>';
  for(const slot of slots){
    html+='<div class="quiet" style="text-align:center;font-size:.75rem;font-weight:700">'+slot+'번 칸</div>';
  }
  for(const lv of [2,1,0]){
    html+='<div class="quiet" style="font-size:.75rem;font-weight:700;text-align:right;padding-right:4px">'+LAYER_LABELS[lv]+'</div>';
    for(const slot of slots){
      const match=allParsed.find(p=>p.slot===slot&&p.layer===lv&&p.dir===dir);
      const hit=Boolean(match&&curTask===match.key);
      const q=(match&&typeof epQuota==='function')?epQuota(match.card):null;
      const tip=match?(sideLabel+' · '+slot+'번 칸 · '+(lv+1)+'층 · '+(dir==='to-ship'?'선박 적재':'선박에서 내림')+' ['+match.key+']'):'해당 칸·층 과제 카드 없음';
      const lbl=match?((lv+1)+'층'+(hit?' ★':(q&&q.done>0?' · '+q.done+'/'+q.goal:''))):'—';
      if(match){
        html+='<button type="button" class="slot-btn'+(hit?' active':'')+'" aria-pressed="'+(hit?'true':'false')+'" data-task-pick="'+escHtml(match.key)+'" title="'+escHtml(tip)+'" aria-label="'+escHtml(tip)+'">'+escHtml(lbl)+'</button>';
      }else{
        html+='<button type="button" class="slot-btn empty-cell" disabled title="'+escHtml(tip)+'" aria-label="'+escHtml(tip)+'">—</button>';
      }
    }
  }
  return html+'</div>';
}

function renderArmSTableHtml(tasks,cards,curTask){
  let html='<div class="stand-head-row"><b>Arm S 위치 · 동선 빠른 선택</b><span class="quiet mono">'+tasks.length+'개 과제</span></div>';
  if(!tasks.length)return html+'<div class="quiet">사용 가능한 Arm S 과제 카드가 없습니다.</div>';
  html+='<div class="arm-s-table" role="list" aria-label="Arm S 위치별 과제 선택">';
  for(const v of tasks){
    const c=cards[v];
    const meta=armSRowMeta(v,c);
    const hit=(curTask===v);
    const q=typeof epQuota==='function'?epQuota(c):null;
    const badge=hit?'선택됨 ★':(q?(q.done+'/'+q.goal+'회'):'');
    html+='<button type="button" class="arm-s-row'+(hit?' active':'')+'" role="listitem" aria-pressed="'+(hit?'true':'false')+'" data-task-pick="'+escHtml(v)+'" title="'+escHtml(c?.single_task||v)+'">';
    html+='<div class="arm-s-row-top"><strong>'+escHtml(meta.pick)+' &rarr; '+escHtml(meta.place)+'</strong>'+(badge?'<span class="mono" style="font-size:.74rem;color:'+(hit?'var(--good)':'var(--ink-q)')+'">'+escHtml(badge)+'</span>':'')+'</div>';
    html+='<div class="arm-s-row-sub mono">'+escHtml(c?.task_id||v)+'</div></button>';
  }
  return html+'</div>';
}

function renderCamGuide(){
  const box=$('cam-guide');
  const arm=f.arm?f.arm.value:'';
  const t=f.task.value;
  const cards=(choices&&choices.task_cards)||{};
  const validAll=(choices&&Array.isArray(choices.tasks)?choices.tasks:[]).filter(v=>cards[v]&&cards[v].valid!==false);
  const validArm=validAll.filter(v=>taskFitsArm(v,cards[v],arm));
  const c=t?cards[t]:null;
  const okCard=Boolean(c&&c.valid!==false);
  const {rawO,rawT}=inferCardSpots(t,c);
  const swapped=Boolean(window.zoneSwapped&&okCard&&(rawO||rawT));
  const oStr=swapped?rawT:rawO;
  const tStr=swapped?rawO:rawT;
  const org=okCard?describeSpot(oStr):'미선택';
  const tgt=okCard?describeSpot([tStr,c?.target_layer].filter(Boolean).join('-')):'미선택';
  const activeZone=resolveActiveZone(arm,oStr,tStr);
  const isStandTask=oStr.startsWith('tmp-')||tStr.startsWith('tmp-');
  const hold=activeZone.startsWith('ship-h')?Number(activeZone.slice(-1)):0;
  const zoneCol=(z)=>(z==='belt'?tStr==='belt':tStr.startsWith(z))?'#3dd68c':((z==='belt'?oStr==='belt':oStr.startsWith(z))?'#58a6ff':(z===activeZone?'#8ab4f8':'#363a3f'));
  const zoneBg=(z)=>(z==='belt'?tStr==='belt':tStr.startsWith(z))?'#14261e':((z==='belt'?oStr==='belt':oStr.startsWith(z))?'#132238':'#18191b');
  const armZoneCount=(z)=>{
    if(z.startsWith('ship-h'))return validArm.filter(v=>!String(cards[v].origin||'').startsWith('tmp-')&&!String(cards[v].target_slot||'').startsWith('tmp-')&&(String(cards[v].target_slot||'').startsWith(z)||String(cards[v].origin||'').startsWith(z))).length;
    if(z==='tmp-a'||z==='tmp-b')return validArm.filter(v=>{const p=parseStandCard(v,cards[v]);return p&&p.side===z.slice(-1);}).length;
    if(z==='pinky'||z==='belt-in')return validArm.filter(v=>/pinky|conveyor|supply|arm[_ -]?s/.test((v+' '+(cards[v].single_task||'')).toLowerCase())).length;
    return validArm.filter(v=>String(cards[v].origin||'')==='belt').length;
  };
  const dimAttr=(ok)=>ok?'':' data-arm-dim="1"';

  const goalEmpty=$('goal-empty'), goalActive=$('goal-active'), swBtn=$('swap-zones-btn');
  if(goalEmpty&&goalActive){
    goalEmpty.hidden=okCard;
    goalActive.hidden=!okCard;
    if(swBtn){
      swBtn.hidden=!okCard;
      swBtn.setAttribute('aria-pressed',swapped?'true':'false');
      swBtn.textContent='⇄ 집기↔놓기 스왑'+(swapped?' (적용됨)':'');
    }
    if(okCard){
      const oDisp=splitSpotDisplay(org);
      const tDisp=splitSpotDisplay(tgt);
      if($('goal-origin-name'))$('goal-origin-name').textContent=oDisp.main;
      if($('goal-origin-sub')){$('goal-origin-sub').textContent=oDisp.sub;$('goal-origin-sub').hidden=!oDisp.sub;}
      if($('goal-target-name'))$('goal-target-name').textContent=tDisp.main;
      if($('goal-target-sub')){$('goal-target-sub').textContent=tDisp.sub;$('goal-target-sub').hidden=!tDisp.sub;}
      const instrEl=$('goal-instruction');
      if(instrEl){
        const rawInstr=c.single_task?String(c.single_task):'';
        instrEl.textContent=(swapped&&rawInstr&&typeof window.flipTaskLabel==='function')?(window.flipTaskLabel(rawInstr)+' [스왑]'):rawInstr;
      }
      const q=typeof epQuota==='function'?epQuota(c):null;
      if($('goal-rep-count'))$('goal-rep-count').textContent=q?(q.done+' / '+q.goal+' 회'):(c.num_episodes!=null?('0 / '+c.num_episodes+' 회'):'— / — 회');
      if($('goal-prog-fill')){
        const pct=q?q.pct:0;
        $('goal-prog-fill').style.width=pct+'%';
        $('goal-prog-fill').style.background=(q&&q.rem===0&&q.goal>0)?'var(--good)':'var(--pri)';
      }
    }
  }
  if($('sb-guide-sum')){
    $('sb-guide-sum').textContent=(arm==='arm_ab'?'arm_a+b':(arm||'팔 미선택'))+' · '+(okCard?(c.task_id||t):zoneTitleLabel(activeZone));
  }

  let html='<div class="cam-guide-inner">';
  html+='<div id="cam-map-note" class="cam-map-note quiet" hidden></div>';
  html+='<svg class="cam-guide-svg" viewBox="0 0 360 178" preserveAspectRatio="xMidYMid meet" aria-label="작업대 구역 배치도">';
  const na=armZoneCount('tmp-a'), nb=armZoneCount('tmp-b'), ns=validAll.filter(v=>taskFitsArm(v,cards[v],'arm_s')).length;
  html+='<g class="map-spot" data-spot="tmp-a" role="button" tabindex="0"'+dimAttr(arm!=='arm_b'&&arm!=='arm_s'&&na>0)+'><rect x="8" y="8" width="84" height="70" rx="6" fill="'+zoneBg('tmp-a')+'" stroke="'+zoneCol('tmp-a')+'" stroke-width="2"/><text x="50" y="38" fill="#eeeeef" font-size="11.5" text-anchor="middle">'+(activeZone==='tmp-a'?'▶ ':'')+'임시대 A (좌)</text><text x="50" y="54" fill="#b0b4ba" font-size="9" text-anchor="middle">'+(na?'카드 '+na+'개':'arm_a 전용')+'</text></g>';
  html+='<g class="map-spot" data-spot="tmp-b" role="button" tabindex="0"'+dimAttr(arm!=='arm_a'&&arm!=='arm_s'&&nb>0)+'><rect x="268" y="8" width="84" height="70" rx="6" fill="'+zoneBg('tmp-b')+'" stroke="'+zoneCol('tmp-b')+'" stroke-width="2"/><text x="310" y="38" fill="#eeeeef" font-size="11.5" text-anchor="middle">'+(activeZone==='tmp-b'?'▶ ':'')+'임시대 B (우)</text><text x="310" y="54" fill="#b0b4ba" font-size="9" text-anchor="middle">'+(nb?'카드 '+nb+'개':'arm_b 전용')+'</text></g>';
  for(const [k,y] of [[2,8],[1,46]]){
    const n=armZoneCount('ship-h'+k);
    html+='<g class="map-spot" data-spot="ship-h'+k+'" role="button" tabindex="0"'+dimAttr(arm!=='arm_s')+'><rect x="100" y="'+y+'" width="160" height="32" rx="6" fill="'+zoneBg('ship-h'+k)+'" stroke="'+zoneCol('ship-h'+k)+'" stroke-width="2"/><text x="180" y="'+(y+14)+'" fill="#eeeeef" font-size="11" text-anchor="middle">'+(k===hold?'▶ ':'')+'화물칸 h'+k+' · '+HOLD_COLUMNS[k]+'</text><text x="180" y="'+(y+26)+'" fill="#b0b4ba" font-size="9" text-anchor="middle">'+(n?'과제 카드 '+n+'개':(arm==='arm_s'?'arm_a/b 전용':'과제 카드 없음'))+'</text></g>';
  }
  html+='<g transform="translate(0,16)">';
  html+='<g class="map-spot" data-spot="pinky" role="button" tabindex="0"'+dimAttr(!arm||arm==='arm_s')+'><rect x="8" y="72" width="96" height="40" rx="6" fill="'+zoneBg('pinky')+'" stroke="'+zoneCol('pinky')+'" stroke-width="2"/><text x="56" y="89" fill="#eeeeef" font-size="11" text-anchor="middle">핑키 로봇</text><text x="56" y="103" fill="#b0b4ba" font-size="9" text-anchor="middle">'+(arm==='arm_s'?'Arm S ('+ns+'개)':'arm_s 전용')+'</text></g>';
  html+='<g class="map-spot" data-spot="belt-in" role="button" tabindex="0"'+dimAttr(!arm||arm==='arm_s')+'><rect x="114" y="72" width="110" height="40" rx="6" fill="'+zoneBg('belt-in')+'" stroke="'+zoneCol('belt-in')+'" stroke-width="2"/><text x="169" y="89" fill="#eeeeef" font-size="11" text-anchor="middle">벨트 공급단 (S)</text><text x="169" y="103" fill="#b0b4ba" font-size="9" text-anchor="middle">belt-in (놓는 곳)</text></g>';
  html+='<text x="232" y="96" fill="#b0b4ba" font-size="12" text-anchor="middle">&rarr;</text>';
  html+='<g class="map-spot" data-spot="belt" role="button" tabindex="0"'+dimAttr(arm!=='arm_s')+'><rect x="240" y="72" width="112" height="40" rx="6" fill="'+zoneBg('belt')+'" stroke="'+zoneCol('belt')+'" stroke-width="2"/><text x="296" y="89" fill="#eeeeef" font-size="11" text-anchor="middle">벨트 인출단 (A/B)</text><text x="296" y="103" fill="#b0b4ba" font-size="9" text-anchor="middle">belt (집는 곳)</text></g>';
  html+='</g>';
  html+='<g class="map-spot" data-spot="stand" role="button" tabindex="0"'+dimAttr(!arm||arm==='arm_a'||arm==='arm_ab')+'><rect x="8" y="134" width="344" height="36" rx="6" fill="'+zoneBg('stand')+'" stroke="'+zoneCol('stand')+'" stroke-width="2"/><text x="180" y="149" fill="#eeeeef" font-size="11" text-anchor="middle">반출대 (Arm A · 컨베이어 우측 상단)</text><text x="180" y="163" fill="#b0b4ba" font-size="9" text-anchor="middle">stand:r1-s1 (top.jpg ROI 410..570 × 30..125)</text></g>';
  html+='</svg>';

  const tabs=armZones(arm);
  if(tabs.length>1){
    html+='<div class="map-zone-tabs" role="tablist" aria-label="선택 팔의 작업 구역">';
    for(const z of tabs){
      const on=(z===activeZone);
      const zName=z==='ship-h1'?'화물칸 h1':(z==='ship-h2'?'화물칸 h2':(z==='tmp-a'?'임시대 A':'임시대 B'));
      html+='<button type="button" class="pill-btn'+(on?' active':'')+'" role="tab" aria-selected="'+(on?'true':'false')+'" data-zone-tab="'+z+'">'+zName+' ('+armZoneCount(z)+')</button>';
    }
    html+='</div>';
  }
  if(hold){
    html+=renderShipGridHtml(hold,armZoneCount('ship-h'+hold),tStr,isStandTask,arm,validAll,cards);
  }else if(activeZone==='tmp-a'||activeZone==='tmp-b'){
    html+=renderStandGridHtml(activeZone.slice(-1),validArm,cards,t);
  }else{
    html+=renderArmSTableHtml(validArm,cards,t);
  }

  box.innerHTML=html+'</div>';
  const nEl=$('cam-map-note');
  if(nEl){nEl.textContent=lastMapNote;nEl.hidden=!lastMapNote;}
  box.hidden=(currentBenchPhase()==='result');
  for(const el of box.querySelectorAll('[data-spot]')){
    el.addEventListener('click',()=>pickTaskBySpot(el.dataset.spot));
    el.addEventListener('keydown',(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pickTaskBySpot(el.dataset.spot);}});
  }
  for(const el of box.querySelectorAll('[data-zone-tab]')){
    el.addEventListener('click',()=>{
      const z=el.dataset.zoneTab;
      window.mapZone=z;
      window.shipHold=z.startsWith('ship-h')?Number(z.slice(-1)):null;
      lastMapNote='';
      renderCamGuide();
    });
  }
  for(const el of box.querySelectorAll('[data-stand-dir]')){
    el.addEventListener('click',()=>{
      window.standDir=el.dataset.standDir;
      lastMapNote='';
      renderCamGuide();
    });
  }
  for(const el of box.querySelectorAll('[data-task-pick]')){
    el.addEventListener('click',()=>{
      if(benchSessionActive())return;
      const v=el.dataset.taskPick;
      if(!v)return;
      if($('task-search'))$('task-search').value='';
      selectTask(v,{keepMapZone:true});
      lastMapNote='위치 선택 · '+v;
      const noteEl=$('cam-map-note');
      if(noteEl){noteEl.textContent=lastMapNote;noteEl.hidden=false;}
    });
  }
  if(swBtn&&!swBtn.dataset.bound){
    swBtn.dataset.bound='1';
    swBtn.addEventListener('click',()=>{
      window.zoneSwapped=!window.zoneSwapped;
      renderCamGuide();
      updateTaskSummary();
    });
  }
  for(const tag of $('cam-grid').querySelectorAll('.cam-tag')){
    tag.textContent=(okCard&&c.target_slot)?('목표 '+c.target_slot):'';
    tag.hidden=!(okCard&&c.target_slot);
  }
  updateGoalSummaryRows();
}
