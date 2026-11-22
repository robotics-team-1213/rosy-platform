// Arm-aware canonical workbench map (shared/web/cell-site-map.json + YAML cards), route overlay, and goal provenance.
// Ship address ship-h<hold>r<row>-l<layer>: counts from 0 for rows and layers (tools/sim/omx_two_arm_sites.py r08_sites; r0 is nearest arm_a, r2 arm_b).
// The names below count layers from 1 (tier numbers of shared/web/cell-site-map.json). Hold h1 is columns 4~6 and h2 columns 1~3 there (Harbor's hold 1 is h2).
const ROW_LABELS=['A쪽 줄','가운데 줄','B쪽 줄'];
const LAYER_LABELS=['1층(바닥)','2층(중간)','3층(맨 위)'];
const HOLD_COLUMNS={1:'4~6열',2:'1~3열'};

window.cellMapData=null;
let lastMapNote='', lastStandTask='';
window.clearMapNote=()=>{lastMapNote='';lastStandTask='';};
window.mapZone=null;
window.standDir='to-ship';
window.shipHold=null;
window.mapFullView=false;

function escHtml(s){
  return String(s??'').replace(/[&<>"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
}

async function loadCellMap(){
  try{
    window.cellMapData=await api('/api/cell_map');
    if(typeof window.populateCustomSpotSelects==='function')window.populateCustomSpotSelects();
    renderCamGuide();
  }catch(_){}
}
window.loadCellMap=loadCellMap;

function canonicalSpotInfo(code){
  const raw=String(code||'').trim();
  if(!raw)return null;
  const cat=window.cellMapData&&Array.isArray(window.cellMapData.spot_catalog)?window.cellMapData.spot_catalog:[];
  const mapped=(window.cellMapData?.aliases?.legacy_sim||{})[raw]||raw;
  const hit=cat.find(s=>s.code===raw||s.site_id===raw||s.site_id===mapped);
  if(hit)return hit;
  return null;
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
    return '화물칸 h'+m[1]+' · '+(ROW_LABELS[r]||((r+1)+'번째 줄'))+' · '+(LAYER_LABELS[l]||((l+1)+'층'))+' ['+s+']';
  }
  m=s.match(/^tmp-([ab])-(\d+)(?:-l(\d+))?$/);
  if(m){
    const side=m[1]==='a'?'왼쪽':'오른쪽';
    const lTxt=m[3]?(LAYER_LABELS[Number(m[3])]||((Number(m[3])+1)+'층')):'1층(바닥)';
    return '임시대 '+m[1].toUpperCase()+'('+side+') · '+m[2]+'번 칸 · '+lTxt+' ['+s+']';
  }
  const canon=canonicalSpotInfo(s);
  return canon?canon.label:s;
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
  const isPinky=taskLow.includes('pinky'), isSupply=taskLow.includes('supply');
  const isBeltIn=taskLow.includes('conveyor')||isSupply, isStraw=taskLow.includes('strawberry');
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
    if(s.startsWith('tmp-a')||s.startsWith('temp_a'))return 'tmp-a';
    if(s.startsWith('tmp-b')||s.startsWith('temp_b'))return 'tmp-b';
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
  if(window.goalMode==='custom'&&typeof window.applyCustomMapSpot==='function'){
    window.applyCustomMapSpot(spot);
    return;
  }
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
    if(spot==='supply')return tasks.filter(v=>(v+' '+(cards[v].origin||'')+' '+(cards[v].single_task||'')).toLowerCase().includes('supply'));
    if(spot==='bowl')return tasks.filter(v=>(v+' '+(cards[v].origin||'')+' '+(cards[v].single_task||'')).toLowerCase().includes('strawberry'));
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
  }else if(spot==='pinky'||spot==='belt-in'||spot==='supply'||spot==='bowl'){
    if(arm==='arm_s'){window.mapZone='arm-s';window.shipHold=null;}
  }else if(spot==='belt'){
    window.mapZone=null;window.shipHold=null;
  }
  const pool=poolFor(validArm);
  if(!pool.length){
    const otherPool=poolFor(validAll);
    const owner=otherPool.length?taskArmOwnerHint(otherPool[0],cards[otherPool[0]]):'';
    lastMapNote=owner
      ?(spot+': '+owner+' 전용 구역/칸입니다 (우측 패널에서 '+owner+' 선택)')
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

function spotSvgCenter(spot){
  const s=String(spot||'').trim();
  const c=canonicalSpotInfo(s);
  const code=c?c.code:s;
  if(!code)return null;
  if(code==='pinky'||code.startsWith('pinky'))return [56,144];
  if(code==='supply')return [56,144];
  if(code==='belt-in'||code==='belt-s')return [156,144];
  if(code==='belt')return [266,144];
  if(code==='stand'||code.startsWith('stand:'))return [364,144];
  let m=code.match(/^tmp-([ab])-(\d+)/);
  if(m){
    const cx=m[1]==='a'?56:364;
    const lane=Math.max(1,Math.min(3,Number(m[2]))) - 1;
    return [cx,32+lane*19];
  }
  if(code==='tmp-a')return [56,50];
  if(code==='tmp-b')return [364,50];
  m=code.match(/^ship-h(\d)r(\d)/);
  if(m){
    const h=Number(m[1]), r=Number(m[2]);
    return [145+r*65,h===2?29:67];
  }
  if(code==='ship-h2')return [210,25];
  if(code==='ship-h1')return [210,63];
  return null;
}

function renderShipGridHtml(k,n,tStr,isStandTask,arm,tasks,cards){
  const sm=!isStandTask?tStr.match(/^ship-h(\d)r(\d)-l(\d)$/):null;
  const th=sm?Number(sm[1]):0, tr=sm?Number(sm[2]):-1, tl=sm?Number(sm[3]):-1;
  let html='<div><b>화물칸 h'+k+'</b> · '+HOLD_COLUMNS[k]+' · 3줄 × 3층 · '+(n?'과제 카드 '+n+'개':'과제 카드 없음 (칸을 눌러도 연결되지 않음)')+'</div>';
  html+='<div class="ship-grid'+(n?'':' empty')+'" aria-label="화물칸 h'+k+' 층·줄 선택" style="display:grid;grid-template-columns:68px repeat(3,minmax(0,1fr));gap:4px;align-items:center"><div></div>';
  for(const row of [0,1,2])html+='<div class="quiet" style="text-align:center;font-size:.75rem;font-weight:700">'+ROW_LABELS[row]+'</div>';
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
      const doneCell=Boolean(q&&q.goal>0&&q.rem===0);
      const cls='slot-btn'+(hit?' active':'')+(doneCell?' done-cell':'')+(!armMatch&&anyMatch?' other-arm':(!anyMatch?' empty-cell':''));
      const lbl=(lv+1)+'층'+(hit?' ★':(ownerShort?' ('+ownerShort+')':(doneCell?' ✓':(q&&q.done>0?' · '+q.done+'/'+q.goal:''))));
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
  html+='</div></div><div class="stand-grid" aria-label="'+sideLabel+' 칸·층 선택" style="grid-template-columns:68px repeat('+slots.length+',minmax(0,1fr))"><div></div>';
  for(const slot of slots)html+='<div class="quiet" style="text-align:center;font-size:.75rem;font-weight:700">'+slot+'번 칸</div>';
  for(const lv of [2,1,0]){
    html+='<div class="quiet" style="font-size:.75rem;font-weight:700;text-align:right;padding-right:4px">'+LAYER_LABELS[lv]+'</div>';
    for(const slot of slots){
      const match=allParsed.find(p=>p.slot===slot&&p.layer===lv&&p.dir===dir);
      const hit=Boolean(match&&curTask===match.key);
      const q=(match&&typeof epQuota==='function')?epQuota(match.card):null;
      const tip=match?(sideLabel+' · '+slot+'번 칸 · '+(lv+1)+'층 · '+(dir==='to-ship'?'선박 적재':'선박에서 내림')+' ['+match.key+']'):'해당 칸·층 과제 카드 없음';
      const lbl=match?((lv+1)+'층'+(hit?' ★':(q&&q.done>0?' · '+q.done+'/'+q.goal:''))):'—';
      if(match)html+='<button type="button" class="slot-btn'+(hit?' active':'')+'" aria-pressed="'+(hit?'true':'false')+'" data-task-pick="'+escHtml(match.key)+'" title="'+escHtml(tip)+'" aria-label="'+escHtml(tip)+'">'+escHtml(lbl)+'</button>';
      else html+='<button type="button" class="slot-btn empty-cell" disabled title="'+escHtml(tip)+'" aria-label="'+escHtml(tip)+'">—</button>';
    }
  }
  return html+'</div>';
}

function renderArmSTableHtml(tasks,cards,curTask){
  let html='<div class="stand-head-row"><b>Arm S 위치 · 동선 빠른 선택</b><span class="quiet mono">'+tasks.length+'개 과제</span></div>';
  if(!tasks.length)return html+'<div class="quiet">사용 가능한 Arm S 과제 카드가 없습니다.</div>';
  html+='<div class="arm-s-table" role="list" aria-label="Arm S 위치별 과제 선택">';
  for(const v of tasks){
    const c=cards[v], meta=armSRowMeta(v,c), hit=(curTask===v);
    const q=typeof epQuota==='function'?epQuota(c):null;
    const badge=hit?'선택됨 ★':(q?(q.done+'/'+q.goal+'회'):'');
    html+='<button type="button" class="arm-s-row'+(hit?' active':'')+'" role="listitem" aria-pressed="'+(hit?'true':'false')+'" data-task-pick="'+escHtml(v)+'" title="'+escHtml(c?.single_task||v)+'">';
    html+='<div class="arm-s-row-top"><strong>'+escHtml(meta.pick)+' &rarr; '+escHtml(meta.place)+'</strong>'+(badge?'<span class="mono" style="font-size:.74rem;color:'+(hit?'var(--good)':'var(--ink-q)')+'">'+escHtml(badge)+'</span>':'')+'</div>';
    html+='<div class="arm-s-row-sub mono">'+escHtml(c?.task_id||v)+'</div></button>';
  }
  return html+'</div>';
}

function renderGoalPanelState(arm,c,okCard,isCustom,oStr,tStr){
  const goalEmpty=$('goal-empty'), goalActive=$('goal-active'), swBtn=$('swap-zones-btn'), provEl=$('goal-provenance'), armBadge=$('goal-arm-badge');
  const activeGoal=okCard||isCustom;
  if(armBadge){
    armBadge.textContent=arm==='arm_ab'?'Arm A+B':(arm?arm.replace('arm_','Arm ').toUpperCase():'');
    armBadge.hidden=!arm;
  }
  if(goalEmpty&&goalActive){
    goalEmpty.hidden=activeGoal;
    goalActive.hidden=!activeGoal;
    if(swBtn){
      swBtn.hidden=!okCard||isCustom;
      swBtn.setAttribute('aria-pressed',window.zoneSwapped?'true':'false');
      swBtn.textContent='⇄ 집기↔놓기 스왑'+(window.zoneSwapped?' (적용됨)':'');
    }
    if(activeGoal){
      const oCanon=canonicalSpotInfo(oStr), tCanon=canonicalSpotInfo(tStr);
      const oDisp=splitSpotDisplay(describeSpot(oStr));
      const tDisp=splitSpotDisplay(describeSpot([tStr,(!isCustom&&c?.target_layer)||''].filter(Boolean).join('-')));
      if($('goal-origin-name'))$('goal-origin-name').textContent=oDisp.main;
      if($('goal-origin-sub')){
        const oMeta=[oDisp.sub,oCanon?.site_id].filter(Boolean).join(' · ');
        $('goal-origin-sub').textContent=oMeta;$('goal-origin-sub').hidden=!oMeta;
      }
      if($('goal-target-name'))$('goal-target-name').textContent=tDisp.main;
      if($('goal-target-sub')){
        const hTxt=(tCanon&&tCanon.height_mm!=null)?('+'+tCanon.height_mm+'mm'):'';
        const tMeta=[tDisp.sub,tCanon?.site_id,hTxt].filter(Boolean).join(' · ');
        $('goal-target-sub').textContent=tMeta;$('goal-target-sub').hidden=!tMeta;
      }
      const instrEl=$('goal-instruction');
      if(instrEl){
        if(isCustom){
          instrEl.textContent=(window.customGoal?.single_task)||('직접 지정: '+oStr+' → '+tStr);
        }else{
          const rawInstr=c.single_task?String(c.single_task):'';
          instrEl.textContent=(window.zoneSwapped&&rawInstr&&typeof window.flipTaskLabel==='function')?(window.flipTaskLabel(rawInstr)+' [스왑]'):rawInstr;
        }
      }
      const q=(!isCustom&&typeof epQuota==='function')?epQuota(c):null;
      const epCustom=$('lp-episodes')?.value?.trim()||'5';
      if($('goal-rep-count'))$('goal-rep-count').textContent=isCustom?('직접 수집 목표 '+epCustom+' 회'):(q?(q.done+' / '+q.goal+' 회'):(c.num_episodes!=null?('0 / '+c.num_episodes+' 회'):'— / — 회'));
      if($('goal-prog-fill')){
        const pct=isCustom?0:(q?q.pct:0);
        $('goal-prog-fill').style.width=pct+'%';
        $('goal-prog-fill').style.background=(!isCustom&&q&&q.rem===0&&q.goal>0)?'var(--good)':'var(--pri)';
      }
    }
  }
  if(provEl){
    const rev=window.cellMapData?.revision?('v'+window.cellMapData.revision):'';
    const lim=(!isCustom&&Array.isArray(c?.known_limits)&&c.known_limits[0])?String(c.known_limits[0]):'';
    const lines=[];
    if(isCustom)lines.push('출처: 직접(기타) → effective-task-card.yaml · 맵: shared/web/cell-site-map.json '+rev);
    else if(okCard)lines.push('카드: '+(c.source_file||c.task_id||'yaml')+(c.root_prefix?' · 저장: '+c.root_prefix:''));
    else lines.push('표준 맵: shared/web/cell-site-map.json '+rev+' (층고 '+(window.cellMapData?.tier_height_mm||32.4)+'mm)');
    if(lim)lines.push('제약: '+lim);
    provEl.textContent=lines.join('\n');
    provEl.hidden=false;
  }
}

function renderSpatialSvg(zoneBg,zoneCol,arm,activeZone,hold,oStr,tStr,na,nb,ns){
  let svg='<svg class="cam-guide-svg" viewBox="0 0 420 220" preserveAspectRatio="xMidYMid meet" aria-label="작업대 구역 및 경로 배치도">';
  svg+='<defs><marker id="map-route-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 1 L 10 5 L 0 9 z" fill="#3dd68c"/></marker></defs>';
  svg+='<path d="M 28 84 A 118 118 0 0 1 168 122" fill="none" stroke="rgba(88,166,255,.22)" stroke-width="1.2" stroke-dasharray="3 3"/>';
  svg+='<path d="M 392 84 A 118 118 0 0 0 252 122" fill="none" stroke="rgba(231,150,243,.22)" stroke-width="1.2" stroke-dasharray="3 3"/>';
  const dimAttr=(ok)=>ok?'':' data-arm-dim="1"';
  for(const [k,y] of [[2,8],[1,46]]){
    const hz='ship-h'+k;
    svg+='<g class="map-spot" data-spot="ship-h'+k+'" role="button" tabindex="0"'+dimAttr(arm!=='arm_s')+'>';
    svg+='<rect x="112" y="'+y+'" width="196" height="34" rx="6" fill="'+zoneBg(hz)+'" stroke="'+zoneCol(hz)+'" stroke-width="'+(k===hold?'2.4':'1.6')+'"/>';
    svg+='<text x="210" y="'+(y+11)+'" fill="#eeeeef" font-size="9.5" font-weight="700" text-anchor="middle">'+(k===hold?'▶ ':'')+'화물칸 h'+k+' ('+HOLD_COLUMNS[k]+')</text>';
    for(const r of [0,1,2]){
      const spotPre='ship-h'+k+'r'+r;
      const isT=tStr.startsWith(spotPre), isO=oStr.startsWith(spotPre);
      const sx=116+r*64, col=isT?'#3dd68c':(isO?'#58a6ff':'rgba(238,238,239,.25)');
      const bg=isT?'#163325':(isO?'#132238':'#111317');
      svg+='<g class="map-spot" data-spot="'+spotPre+'-l0" role="button" tabindex="0"><rect x="'+sx+'" y="'+(y+14)+'" width="60" height="17" rx="3" fill="'+bg+'" stroke="'+col+'" stroke-width="'+(isT||isO?'1.8':'1')+'"/><text x="'+(sx+30)+'" y="'+(y+25.5)+'" fill="#d9dce1" font-size="8.2" text-anchor="middle">r'+r+' '+(isT?'②':(isO?'①':ROW_LABELS[r].slice(0,2)))+'</text></g>';
    }
    svg+='</g>';
  }
  for(const [zid,x,sideOk,n,lbl,role] of [['tmp-a',12,arm!=='arm_b'&&arm!=='arm_s'&&na>0,na,'임시대 A','arm_a'],['tmp-b',316,arm!=='arm_a'&&arm!=='arm_s'&&nb>0,nb,'임시대 B','arm_b']]){
    svg+='<g class="map-spot" data-spot="'+zid+'" role="button" tabindex="0"'+dimAttr(sideOk)+'>';
    svg+='<rect x="'+x+'" y="8" width="92" height="82" rx="6" fill="'+zoneBg(zid)+'" stroke="'+zoneCol(zid)+'" stroke-width="1.8"/>';
    svg+='<text x="'+(x+46)+'" y="20" fill="#eeeeef" font-size="9.5" font-weight="700" text-anchor="middle">'+(activeZone===zid?'▶ ':'')+lbl+' ('+(n||role)+')</text>';
    for(const lane of [1,2,3]){
      const sp=zid+'-'+lane, ly=24+(lane-1)*20;
      const isT=tStr.startsWith(sp), isO=oStr.startsWith(sp);
      const col=isT?'#3dd68c':(isO?'#58a6ff':'rgba(238,238,239,.22)');
      svg+='<g class="map-spot" data-spot="'+sp+'" role="button" tabindex="0"><rect x="'+(x+6)+'" y="'+ly+'" width="80" height="16" rx="3" fill="'+(isT?'#163325':(isO?'#132238':'#111317'))+'" stroke="'+col+'" stroke-width="'+(isT||isO?'1.8':'1')+'"/><text x="'+(x+46)+'" y="'+(ly+11)+'" fill="#d9dce1" font-size="8.2" text-anchor="middle">'+lane+'번'+(isT?' ②':(isO?' ①':''))+'</text></g>';
    }
    svg+='</g>';
  }
  svg+='<g class="map-spot" data-spot="pinky" role="button" tabindex="0"'+dimAttr(!arm||arm==='arm_s')+'><rect x="12" y="120" width="88" height="44" rx="6" fill="'+zoneBg('pinky')+'" stroke="'+zoneCol('pinky')+'" stroke-width="2"/><text x="56" y="138" fill="#eeeeef" font-size="10.5" font-weight="700" text-anchor="middle">핑키 로봇</text><text x="56" y="153" fill="#b0b4ba" font-size="8.8" text-anchor="middle">'+(arm==='arm_s'?'Arm S ('+ns+'개)':'arm_s 전용')+'</text></g>';
  svg+='<g class="map-spot" data-spot="belt-in" role="button" tabindex="0"'+dimAttr(!arm||arm==='arm_s')+'><rect x="108" y="120" width="96" height="44" rx="6" fill="'+zoneBg('belt-in')+'" stroke="'+zoneCol('belt-in')+'" stroke-width="2"/><text x="156" y="138" fill="#eeeeef" font-size="10.5" font-weight="700" text-anchor="middle">벨트 공급단</text><text x="156" y="153" fill="#b0b4ba" font-size="8.8" text-anchor="middle">belt-in (Arm S)</text></g>';
  svg+='<text x="212" y="146" fill="#8ab4f8" font-size="12" font-weight="700" text-anchor="middle">&raquo;</text>';
  svg+='<g class="map-spot" data-spot="belt" role="button" tabindex="0"'+dimAttr(arm!=='arm_s')+'><rect x="220" y="120" width="92" height="44" rx="6" fill="'+zoneBg('belt')+'" stroke="'+zoneCol('belt')+'" stroke-width="2"/><text x="266" y="138" fill="#eeeeef" font-size="10.5" font-weight="700" text-anchor="middle">벨트 인출단</text><text x="266" y="153" fill="#b0b4ba" font-size="8.8" text-anchor="middle">belt (Arm A/B)</text></g>';
  svg+='<g class="map-spot" data-spot="stand" role="button" tabindex="0"'+dimAttr(!arm||arm==='arm_a'||arm==='arm_ab')+'><rect x="320" y="120" width="88" height="44" rx="6" fill="'+zoneBg('stand')+'" stroke="'+zoneCol('stand')+'" stroke-width="2"/><text x="364" y="138" fill="#eeeeef" font-size="10.5" font-weight="700" text-anchor="middle">반출대</text><text x="364" y="153" fill="#b0b4ba" font-size="8.8" text-anchor="middle">stand (Arm A)</text></g>';
  svg+='<circle cx="28" cy="103" r="8" fill="#132238" stroke="#58a6ff" stroke-width="1.8"/><text x="28" y="106" fill="#58a6ff" font-size="8.5" font-weight="700" text-anchor="middle">A</text>';
  svg+='<circle cx="392" cy="103" r="8" fill="#23172b" stroke="#e796f3" stroke-width="1.8"/><text x="392" y="106" fill="#e796f3" font-size="8.5" font-weight="700" text-anchor="middle">B</text>';
  const p0=spotSvgCenter(oStr), p1=spotSvgCenter(tStr);
  if(p0&&p1&&(p0[0]!==p1[0]||p0[1]!==p1[1])){
    const mx=(p0[0]+p1[0])/2, my=Math.min(p0[1],p1[1])-14;
    svg+='<path d="M '+p0[0]+' '+p0[1]+' Q '+mx+' '+my+' '+p1[0]+' '+p1[1]+'" fill="none" stroke="#3dd68c" stroke-width="2.4" stroke-dasharray="5 3" marker-end="url(#map-route-arrow)"/>';
    svg+='<circle cx="'+p0[0]+'" cy="'+p0[1]+'" r="5.5" fill="#58a6ff" stroke="#0c0d0f" stroke-width="1.5"/><text x="'+p0[0]+'" y="'+(p0[1]+2.8)+'" fill="#0c0d0f" font-size="7.5" font-weight="800" text-anchor="middle">1</text>';
    svg+='<circle cx="'+p1[0]+'" cy="'+p1[1]+'" r="5.5" fill="#3dd68c" stroke="#0c0d0f" stroke-width="1.5"/><text x="'+p1[0]+'" y="'+(p1[1]+2.8)+'" fill="#0c0d0f" font-size="7.5" font-weight="800" text-anchor="middle">2</text>';
  }
  const rev=window.cellMapData?.revision?('v'+window.cellMapData.revision):'';
  svg+='<rect x="12" y="174" width="396" height="38" rx="6" fill="#0c0d0f" stroke="rgba(238,238,239,.12)"/>';
  svg+='<text x="22" y="190" fill="#58a6ff" font-size="9" font-weight="700">① 집기</text><text x="72" y="190" fill="#3dd68c" font-size="9" font-weight="700">② 놓기</text><text x="128" y="190" fill="#b0b4ba" font-size="8.8">점선: A/B 작업 반경 · 화살표: 목표 이동 경로</text>';
  svg+='<text x="22" y="204" fill="#b0b4ba" font-size="8.4">기준: shared/web/cell-site-map.json '+escHtml(rev)+' (단 높이 '+(window.cellMapData?.tier_height_mm||32.4)+'mm) · 클릭 시 '+(window.goalMode==='custom'?'직접 목표 지정':'과제 역선택')+'</text>';
  return svg+'</svg>';
}

function renderCamGuide(){
  const box=$('cam-guide');
  if(!box)return;
  const arm=f.arm?f.arm.value:'';
  const t=f.task.value;
  const cards=(choices&&choices.task_cards)||{};
  const validAll=(choices&&Array.isArray(choices.tasks)?choices.tasks:[]).filter(v=>cards[v]&&cards[v].valid!==false);
  const validArm=validAll.filter(v=>taskFitsArm(v,cards[v],arm));
  const c=t?cards[t]:null;
  const isCustom=window.goalMode==='custom';
  const okCard=Boolean(!isCustom&&c&&c.valid!==false);
  const {rawO,rawT}=inferCardSpots(t,c);
  const swapped=Boolean(!isCustom&&window.zoneSwapped&&okCard&&(rawO||rawT));
  const oStr=isCustom?String(window.customGoal?.origin||''):(swapped?rawT:rawO);
  const tStr=isCustom?String(window.customGoal?.target_slot||''):(swapped?rawO:rawT);
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
  renderGoalPanelState(arm,c,okCard,isCustom,oStr,tStr);
  if($('sb-guide-sum')){
    $('sb-guide-sum').textContent=(arm==='arm_ab'?'arm_a+b':(arm||'팔 미선택'))+' · '+(isCustom?(oStr+'→'+tStr):(okCard?(c.task_id||t):zoneTitleLabel(activeZone)));
  }

  let html='<div class="cam-guide-inner"><div class="map-toolbar">';
  html+=arm==='arm_s'
    ?'<button type="button" class="pill-btn" data-map-view="toggle">'+(window.mapFullView?'Arm S 확대 보기':'전체 셀 보기')+'</button>'
    :'<span class="quiet mono" style="font-size:.74rem">표준 셀 배치도 ('+(isCustom?'직접 찍기':'카드 선택')+')</span>';
  html+='<button type="button" id="map-expand-btn" class="btn-tool btn-xs">배치도 크게 보기</button></div>';
  html+='<div id="cam-map-note" class="cam-map-note quiet" hidden></div>';
  const na=armZoneCount('tmp-a'), nb=armZoneCount('tmp-b'), ns=validAll.filter(v=>taskFitsArm(v,cards[v],'arm_s')).length;
  html+=(arm==='arm_s'&&!window.mapFullView)?renderArmSMapSvg(zoneBg,zoneCol,validArm,cards):renderSpatialSvg(zoneBg,zoneCol,arm,activeZone,hold,oStr,tStr,na,nb,ns);

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
  if(hold)html+=renderShipGridHtml(hold,armZoneCount('ship-h'+hold),tStr,isStandTask,arm,validAll,cards);
  else if(activeZone==='tmp-a'||activeZone==='tmp-b')html+=renderStandGridHtml(activeZone.slice(-1),validArm,cards,t);
  else html+=renderArmSTableHtml(validArm,cards,t);

  box.innerHTML=html+'</div>';
  const nEl=$('cam-map-note');
  if(nEl){nEl.textContent=lastMapNote;nEl.hidden=!lastMapNote;}
  box.hidden=(currentBenchPhase()==='result');
  const bindSpots=(root)=>{
    for(const el of root.querySelectorAll('[data-spot]')){
      el.addEventListener('click',(e)=>{e.stopPropagation();pickTaskBySpot(el.dataset.spot);});
      el.addEventListener('keydown',(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();pickTaskBySpot(el.dataset.spot);}});
    }
  };
  bindSpots(box);
  const viewBtn=box.querySelector('[data-map-view]');
  if(viewBtn)viewBtn.addEventListener('click',()=>{window.mapFullView=!window.mapFullView;renderCamGuide();});
  const expBtn=$('map-expand-btn');
  if(expBtn)expBtn.addEventListener('click',()=>openMapModal(bindSpots));
  for(const el of box.querySelectorAll('[data-zone-tab]')){
    el.addEventListener('click',()=>{const z=el.dataset.zoneTab;window.mapZone=z;window.shipHold=z.startsWith('ship-h')?Number(z.slice(-1)):null;lastMapNote='';renderCamGuide();});
  }
  for(const el of box.querySelectorAll('[data-stand-dir]')){
    el.addEventListener('click',()=>{window.standDir=el.dataset.standDir;lastMapNote='';renderCamGuide();});
  }
  for(const el of box.querySelectorAll('[data-task-pick]')){
    el.addEventListener('click',()=>{
      if(benchSessionActive())return;
      const v=el.dataset.taskPick;if(!v)return;
      if($('task-search'))$('task-search').value='';
      selectTask(v,{keepMapZone:true});
      lastMapNote='위치 선택 · '+v;
      const noteEl=$('cam-map-note');if(noteEl){noteEl.textContent=lastMapNote;noteEl.hidden=false;}
    });
  }
  const swBtn=$('swap-zones-btn');
  if(swBtn&&!swBtn.dataset.bound){
    swBtn.dataset.bound='1';
    swBtn.addEventListener('click',()=>{window.zoneSwapped=!window.zoneSwapped;renderCamGuide();updateTaskSummary();});
  }
  for(const tag of $('cam-grid').querySelectorAll('.cam-tag')){
    const lblTgt=isCustom?tStr:(okCard&&c.target_slot?c.target_slot:'');
    tag.textContent=lblTgt?('목표 '+lblTgt):'';
    tag.hidden=!lblTgt;
  }
  updateGoalSummaryRows();
}

const ARM_S_SPOTS={pinky:{title:'핑키 로봇 (pinky)',sub:'도착/상차'},supply:{title:'공급대 (supply)',sub:'집는 곳'},bowl:{title:'흰 그릇 (bowl)',sub:'딸기 왕복'}};
function renderArmSMapSvg(zoneBg,zoneCol,validArm,cards){
  const counts=new Map();
  for(const v of (validArm||[])){const {rawO}=inferCardSpots(v,cards&&cards[v]);const spot=ARM_S_SPOTS[rawO]?rawO:(rawO||'pinky');counts.set(spot,(counts.get(spot)||0)+1);}
  const active=[...counts.entries()].filter(([,n])=>n>0);
  const spots=active.length?active:[['pinky',0],['supply',0]];
  const total=active.reduce((acc,[,n])=>acc+n,0), pad=8, avail=146, gap=spots.length>1?7:0, h=Math.floor((avail-gap*(spots.length-1))/spots.length);
  let s='<svg class="cam-guide-svg" viewBox="0 0 360 162" preserveAspectRatio="xMidYMid meet" aria-label="Arm S 작업 구역 확대 배치도">';
  spots.forEach(([spot,n],idx)=>{
    const y=pad+idx*(h+gap), meta=ARM_S_SPOTS[spot]||{title:describeSpot(spot),sub:'출발 구역'}, ty1=Math.round(y+h/2-4), ty2=ty1+16, sub=meta.sub+(n?' ('+n+'개 과제)':'');
    s+='<g class="map-spot" data-spot="'+escHtml(spot)+'" role="button" tabindex="0"><rect x="8" y="'+y+'" width="154" height="'+h+'" rx="8" fill="'+zoneBg(spot)+'" stroke="'+zoneCol(spot)+'" stroke-width="2"/><text x="85" y="'+ty1+'" fill="#eeeeef" font-size="13" font-weight="700" text-anchor="middle">'+escHtml(meta.title)+'</text><text x="85" y="'+ty2+'" fill="#b0b4ba" font-size="10.5" text-anchor="middle">'+escHtml(sub)+'</text></g>';
  });
  s+='<text x="180" y="86" fill="#eeeeef" font-size="18" font-weight="700" text-anchor="middle">&rarr;</text>';
  s+='<g class="map-spot" data-spot="belt-in" role="button" tabindex="0"><rect x="198" y="20" width="154" height="122" rx="10" fill="'+zoneBg('belt-in')+'" stroke="'+zoneCol('belt-in')+'" stroke-width="2.5"/><text x="275" y="64" fill="#eeeeef" font-size="14" font-weight="700" text-anchor="middle">벨트 공급단</text><text x="275" y="84" fill="#b0b4ba" font-size="11.5" text-anchor="middle">belt-in (놓는 곳)'+(total?' · '+total+'개':'')+'</text><text x="275" y="108" fill="#8ab4f8" font-size="10.5" text-anchor="middle">Arm A/B 구역으로 이송</text></g>';
  return s+'</svg>';
}

function closeMapModal(){const host=$('map-modal-host');if(host)host.hidden=true;}
function openMapModal(bindSpots){
  const host=$('map-modal-host'), body=$('map-modal-body'), srcBox=$('map-modal-sources'), svg=document.querySelector('#cam-guide .cam-guide-svg');
  if(!host||!body||!svg)return;
  body.innerHTML='';body.append(svg.cloneNode(true));
  if(typeof bindSpots==='function')bindSpots(body);
  if(srcBox){
    const srcs=(window.cellMapData&&Array.isArray(window.cellMapData.sources))?window.cellMapData.sources:[];
    srcBox.innerHTML=srcs.length
      ?('<strong>데이터 출처 및 실측 설정</strong>'+srcs.map(r=>'<div>'+(r.exists?'✓':'✗')+' <b>'+escHtml(r.label)+'</b>: <span>'+escHtml(r.path)+'</span> ('+escHtml(r.schema||'')+(r.status?' · '+escHtml(r.status):'')+')</div>').join(''))
      :'출처 정보를 불러오지 못했습니다.';
  }
  host.hidden=false;$('map-modal-close-btn')?.focus();
}
if($('map-modal-close-btn'))$('map-modal-close-btn').addEventListener('click',closeMapModal);
if($('map-modal-backdrop'))$('map-modal-backdrop').addEventListener('click',closeMapModal);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('map-modal-host')&&!$('map-modal-host').hidden){e.preventDefault();e.stopImmediatePropagation();closeMapModal();}});
