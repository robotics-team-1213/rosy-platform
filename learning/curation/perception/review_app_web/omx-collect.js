// Draft real-arm collection plans in Learning Center (8768); execution & approval remain in Fleet/Cell (D-1024, D-911).
const $=id=>document.getElementById(id);
const KIND={policy:'학습 정책',sim_optimized:'시뮬 최적화 IK',scripted_teacher:'교시 IK'};
let request,busy=false;
function el(tag,text){const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;}
function togglePolicyFields(){
  const policy=$('collect-executor').value!=='ik_chunk';
  $('collect-policy-fields').hidden=!policy;
  $('collect-library').required=policy;$('collect-cal').required=policy;
  $('collect-policy-root').required=policy;$('collect-policy-revision').required=policy;
}
function buildPlan(){
  const executor=$('collect-executor').value;
  const item={item_id:'carry_1',from:$('collect-from').value.trim(),to:$('collect-to').value.trim(),executor};
  const cell={config:$('collect-config').value.trim(),catalog:$('collect-catalog').value.trim()};
  if(executor!=='ik_chunk'){
    cell.library=$('collect-library').value.trim();
    cell.cell_calibration=$('collect-cal').value.trim();
    item.policy={root:$('collect-policy-root').value.trim(),revision:$('collect-policy-revision').value.trim()};
  }
  return {schema:'rosy.omx-collect-plan.v1',plan_id:$('collect-plan-id').value.trim(),arm:$('collect-arm').value,
    proposer:$('collect-proposer').value.trim(),values_from:$('collect-values-from').value,
    policy_real_approved:false,cell,items:[item]};
}
function renderPlan(record){
  const box=el('section');box.className='learning-section';
  const kinds=record.items.map(item=>KIND[item.source_kind]||item.source_kind).join(', ');
  box.append(el('h4',`${record.plan_id} · ${record.arm} · ${kinds}`),
    el('p',`제안자 ${record.proposer} · 실물 정책 승인: 미승인(Fleet·셀 Gate 관할) · ${record.created_at}`));
  const dl=el('ui-button','계획 JSON 내려받기');dl.type='button';dl.setAttribute('kind','quiet');
  dl.onclick=()=>{
    const blob=new Blob([JSON.stringify(record.plan,null,2)+'\n'],{type:'application/json'});
    const link=el('a');link.href=URL.createObjectURL(blob);link.download=`${record.plan_id}.json`;link.click();
    setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  };
  box.append(dl);return box;
}
export async function refreshCollectPlans(){
  if(!$('collect-plans-list'))return;
  try{
    const data=await request('/api/learning/omx/center/collect-plans');
    const list=data.plans||[];
    $('collect-plans-list').replaceChildren(...(list.length?list.map(renderPlan):[el('p','저장된 수집 계획 초안이 없습니다.')]));
  }catch(exc){$('collect-plans-list').replaceChildren(el('p',`수집 계획을 읽지 못했습니다: ${exc.message}`));}
}
export function updateCollectRuns(runs){
  const sel=$('collect-run');if(!sel)return;
  const done=(runs||[]).filter(run=>run.status==='succeeded'&&run.execution_mode!=='native_export');
  const prev=sel.value;
  sel.replaceChildren(...[new Option('직접 입력 (학습 결과 선택 안 함)',''),...done.map(run=>{
    const o=el('option',`${run.method==='act'?'ACT':'SAC'} · ${run.id.slice(0,8)}`);o.value=run.id;return o;})]);
  if(done.some(run=>run.id===prev))sel.value=prev;
}
export function initCollect(options){
  ({request}=options);
  if(!$('collect-plan-form'))return;
  togglePolicyFields();
  $('collect-executor').onchange=togglePolicyFields;
  $('collect-run').onchange=()=>{
    const rid=$('collect-run').value;
    if(rid&&!$('collect-policy-root').value)$('collect-policy-root').value=`~/rosy-models/${rid}`;
  };
  $('collect-plan-form').onsubmit=async event=>{
    event.preventDefault();if(busy)return;busy=true;$('collect-plan-submit').disabled=true;
    $('collect-plan-status').textContent='수집 계획 초안을 검증·저장하는 중입니다.';
    try{
      const saved=await request('/api/learning/omx/center/collect-plan',buildPlan());
      $('collect-plan-status').textContent=`초안 ${saved.plan_id} 저장됨. cell_collect_plan.py는 dry-run 요청만 검증·출력하며 제출이나 Fleet 승인을 대신하지 않습니다.`;
      await refreshCollectPlans();
    }catch(exc){$('collect-plan-status').textContent=`수집 계획 거절: ${exc.message}`;}
    finally{busy=false;$('collect-plan-submit').disabled=false;}
  };
  refreshCollectPlans();
}
