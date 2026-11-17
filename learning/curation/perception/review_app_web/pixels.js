import {workspacePage,pageControls,frameOrdinal,reviewLink,reasonLines,pinDecisionBar,showPhotos,revealOpen} from '/review-pages.js';
import {reviewContext} from '/review-context.js';
import {accountFetch,commonDown,panelError,setText} from '/review-alerts.js';
import {showVersions,resetVersions} from '/versions.js';
import {showAI,resetAI,updateAI,candidateOrigin} from '/ai-jobs.js';
import {cssColor, clearPalette, actionIcon, confirmIrreversible} from '/common/ui.js';
import {setGeometry} from '/common/geometry.js';
import {createBusyScope} from '/common/busy-scope.js';
import {statusTag} from '/common/status-tag.js';
import {showHistory,resetHistory,feedbackPresentation} from '/history.js';
import {reviewViewport} from '/viewport.js';
import {createChoiceList} from '/common/choice-list.js';
import {createChoiceGroup} from '/common/choice-group.js';
import '/commands.js';
const $=id=>document.getElementById(id);
const modeBadge=document.createElement('ui-status');
modeBadge.id='pixel-workspace-mode';
modeBadge.setAttribute('role','status');
$('pixel-workspace-meta').append(modeBadge);
const inputPurpose=()=>workspace?.workspace_kind==='evaluation'?'고정 평가 · 학습 제외':'학습 후보 · 승인 후 수용 확인';
const pixelStage=document.querySelector('.pixel-stage');
const resizePixelViewport=reviewViewport(pixelStage,$('pixel-canvas'),$('pixel-viewport-controls'),()=>!stroke,
 ()=>Math.max(160,innerHeight-pixelStage.getBoundingClientRect().top-document.querySelector('.pixel-canvas-footer').offsetHeight-32));
const pixelContent=$('pixel-content');pinDecisionBar(document.querySelector('.pixel-decision-panel'));
const photoNavigation=document.querySelector('.pixel-frame-controls');
photoNavigation.id='pixel-photo-navigation';photoNavigation.setAttribute('role','group');photoNavigation.setAttribute('aria-label','현재 사진 이동');
const updateContext=reviewContext(photoNavigation);
// K3: the one photo picker (thumbnail + state per photo). The 이전·다음·다음 대기 row above is the K15 command row.
let frameLocked=()=>false,candidateLocked=false,classOff=false,candidateKept='';
const classGroup=createChoiceGroup({id:'pixel-class',label:'픽셀 클래스',mode:'single',value:'',items:[{value:'',label:'선택 안 함'}],onChange:()=>{classChanged();canvas.focus({preventScroll:true});}});
$('pixel-class').replaceWith(classGroup.element);
classGroup.element.addEventListener('click',event=>{if(!classOff&&event.target.tagName==='INPUT'&&!event.target.disabled)canvas.focus({preventScroll:true});});
const pixelClass={get value(){return classGroup.value??'';},set value(v){classGroup.set(String(v));},get disabled(){return classOff;},set disabled(on){classOff=on;for(const input of classGroup.element.querySelectorAll('input')){input.disabled=on;input.closest('label').toggleAttribute('data-disabled',on);}},has:v=>[...classGroup.element.querySelectorAll('input')].some(input=>input.value===v)};
// K1: the three exclusive editing modes are one radio group (the old role=toolbar of aria-pressed buttons is gone). The inputs keep the
// old ids so the T and P keys and the tests reach them; the group itself is never rebuilt.
const toolGroup=createChoiceGroup({id:'pixel-tool',label:'편집 도구',mode:'single',value:'sample',items:[{value:'sample',label:'점'},{value:'brush',label:'브러시'},{value:'polygon',label:'영역'}],onChange:mode=>{tool=mode;brush.hidden=true;enable();canvas.focus({preventScroll:true});}});
toolGroup.element.querySelector('legend').classList.add('sr-only');
$('pixel-tool-group').replaceWith(toolGroup.element);
for(const [id,mode,tip,icon] of [['pixel-flood','sample','색상 점 선택 · T','pixels'],['pixel-brush-tool','brush','브러시 · T','pencil'],['pixel-polygon-tool','polygon','다각형 영역 · P','area']]){const input=toolGroup.element.querySelector(`input[value="${mode}"]`);input.id=id;input.setAttribute('aria-describedby','pixel-tool-hint');input.closest('label').dataset.uiTooltip=tip;const holder=document.createElement('span');actionIcon(holder,icon);holder.firstElementChild.classList.add('choice-tool-icon');input.closest('label').querySelector('.choice-check').after(holder.firstElementChild);}
// K3: AI drafts of the open photo. `candidates` keeps the value / disabled shape the editor code reads.
const candidateList=createChoiceList({id:'pixel-candidates',label:'미리볼 초안',emptyText:'새 자동 초안이 없습니다',onChange:id=>{if(candidateLocked){candidateList.select(candidateKept);return;}candidateKept=id;resetCandidatePreview();previewCandidate();}});
$('pixel-candidates').replaceWith(candidateList.element);
const candidates={get value(){return candidateList.value||'';},set value(id){candidateKept=id;candidateList.select(id);},get disabled(){return candidateLocked;},set disabled(on){candidateLocked=on;candidateList.element.querySelector('[role=listbox]').setAttribute('aria-disabled',String(on));}};
const frameList=createChoiceList({id:'pixel-frames',label:'사진 선택',labelHidden:true,emptyText:'이 상태의 사진이 없습니다',onChange:async id=>{if(frameLocked()){frameList.select(String(frame?.index));return;}await select(id);if(ready)canvas.focus({preventScroll:true});}});
$('pixel-frames').replaceWith(frameList.element);
const updatePages=pageControls($('pixel-frames'),offset=>load({offset}).catch(loadError));
const pageBar=$('pixel-frames').nextElementSibling;pageBar.id='pixel-page-controls';pageBar.setAttribute('role','group');pageBar.setAttribute('aria-label','사진 목록 페이지 이동');
const pixelFillClass=$('pixel-fill-unknown-class'),pixelResolve=$('pixel-resolve-unknown'),pixelResolveBackground=$('pixel-resolve-background'),pixelResolveClass=$('pixel-resolve-class');
pixelResolveBackground.onclick=()=>$('pixel-fill-unknown').click();pixelResolveClass.onclick=()=>pixelFillClass.click();
$('pixel-reload').textContent='새로고침';
actionIcon($('pixel-reload'),'refresh');
$('pixel-reload').setAttribute('aria-label','최신 픽셀 검수 내용 불러오기');
const pixelResult=$('pixel-result'),pixelResultNote=$('pixel-result-note'),pixelResultTag=statusTag('caution','완료 대기');
pixelResultNote.before(pixelResultTag);
const pixelResultDetails=document.createElement('p');pixelResultDetails.id='pixel-result-details';pixelResultDetails.className='quiet';$('pixel-legend').before(pixelResultDetails);
const aiPanel=document.querySelector('.pixel-vlm-feedback');
const aiActions=document.createElement('div');aiActions.className='review-ai-actions';
const refreshAi=document.createElement('ui-button');refreshAi.id='pixel-vlm-refresh';refreshAi.setAttribute('kind','quiet');refreshAi.setAttribute('data-action-icon','reload');refreshAi.textContent='저장 의견 새로고침';
refreshAi.onclick=()=>{if(ready&&!loading)void loadVlm(frame.index,serial);};
aiActions.append(refreshAi);aiPanel.append(aiActions);
const candidateEmpty=document.createElement('p');candidateEmpty.id='pixel-candidate-empty';candidateEmpty.className='quiet';
$('pixel-candidate-tools').before(candidateEmpty);

const compactTools=matchMedia('(width < 64rem)');
let lastToolLayout='';
function keepPixelFocusVisible(){
 const active=document.activeElement;
 if(active?.isConnected&&!active.disabled&&$('pixel-content').contains(active))requestAnimationFrame(()=>active.scrollIntoView({block:'nearest',inline:'nearest'}));
}
compactTools.addEventListener('change',keepPixelFocusVisible);
for(const [id,key] of [['pixel-prev','ArrowLeft'],['pixel-next','ArrowRight'],['pixel-next-pending','N'],['pixel-undo','Control+Z Meta+Z']])$(id).setAttribute('aria-keyshortcuts',key);
$('pixel-undo').setAttribute('data-ui-tooltip','마지막 픽셀 수정 되돌리기 · Ctrl+Z');
const undoCaption=document.createElement('span');undoCaption.textContent='되돌리기 · Ctrl+Z';$('pixel-undo').replaceChildren(undoCaption);
actionIcon($('pixel-undo'),'undo');
$('pixel-approve').textContent='완료';$('pixel-approve').setAttribute('aria-label','픽셀 검수 완료');
for(const [id,label] of [['pixel-prev','이전 사진'],['pixel-next','다음 사진'],['pixel-undo','마지막 픽셀 수정 되돌리기']]){$(id).setAttribute('aria-label',label);$(id).setAttribute('data-ui-tooltip',label);}
for(const button of document.querySelectorAll('.pixel-quick-actions ui-button'))button.setAttribute('aria-label',button.getAttribute('data-ui-tooltip'));

const states={pending:'픽셀 검수 대기',approved:'픽셀 승인',excluded:'픽셀 제외'};
const serverReasons={'known mask index required':'등록된 픽셀 클래스만 사용할 수 있습니다.','flood seed outside original image':'누른 점이 원본 사진 범위를 벗어났습니다.','bounded flood tolerance required':'비슷한 색 허용치는 0~100 사이 정수입니다.','bounded brush radius required':'브러시 반지름은 0~128 사이 정수입니다.','bounded brush points required':'브러시 획이 너무 깁니다. 나누어 그리세요.','brush point outside original image':'브러시 획이 원본 사진 범위를 벗어났습니다.','3..128 polygon points required':'영역은 꼭짓점 3~128개가 필요합니다.','polygon point outside original image':'영역 꼭짓점이 사진 밖에 있습니다.','mask encoding failed':'마스크를 저장하지 못했습니다.','no unknown pixels remain':'남은 미검수 픽셀이 없습니다.','exactly one background class required':'배경 클래스가 정확히 하나여야 합니다.','drivable outside visible lane boundary':'보이는 왼쪽 차선 바깥 또는 오른쪽 차선 바깥에 주행 가능 영역이 있습니다. 해당 픽셀을 배경이나 미검수로 수정하세요.','unknown pixel review action':'지원하지 않는 동작입니다.'};
function readableError(message){return serverReasons[message]||message;}
serverReasons['draft has no labels for remaining unknown pixels']='이 초안은 남은 255 영역에 제안한 라벨이 없습니다. 다른 초안을 선택하거나 직접 검수하세요.';
let workspace,frame,review,original,displayPhoto,maskImage,ready=false,loading=true,conflicted=false,forbidden=false,serial=0,stroke=null,draft=[],tool='sample',polygon=[],keyCursor=null;
const reasons=reasonLines([['.pixel-decision-panel',null,'#pixel-approval-hint'],['.pixel-save-actions'],['#pixel-whole-frame-tools']]);
const scope=createBusyScope(document.querySelector('.ui-app-main'),{readonly:'input, textarea'});
let vlmRequest=0;
const keyboardPosition=document.createElement('p');keyboardPosition.id='pixel-keyboard-position';keyboardPosition.className='quiet';keyboardPosition.setAttribute('role','status');keyboardPosition.hidden=true;document.querySelector('.pixel-stage').after(keyboardPosition);
let savedPixelSummary='';
let candidatePreviewDigest='';
let candidateData=null,candidateVisible=false,candidateLoading=false,candidatePixels=0,candidateRequest=0;
function resetCandidatePreview(){candidateRequest++;candidatePreviewDigest='';candidateData=null;candidateVisible=false;candidateLoading=false;candidatePixels=0;$('pixel-candidate-preview').hidden=true;}
function candidateReference(){return review?.draft_candidates?.some(row=>row.sha256===candidates.value&&row.origin==='v12_pixel_mask_candidate');}
function candidateDraftReady(){return workspace?.workspace_kind!=='evaluation'&&frame?.status!=='excluded'&&review?.status!=='excluded'&&candidateVisible&&candidateData&&candidatePixels>0&&candidatePreviewDigest===candidates.value&&!candidateReference();}
const mergeCandidate=document.createElement('ui-button');mergeCandidate.id='pixel-merge-candidate';mergeCandidate.setAttribute('data-action-icon','pixels');mergeCandidate.setAttribute('kind','quiet');mergeCandidate.textContent='사람 라벨 유지 · 255만 초안 보완';$('pixel-apply-candidate').before(mergeCandidate);
$('pixel-candidate-tools').classList.add('review-draft-bar');
$('pixel-preview-candidate').textContent='초안 미리보기';
$('pixel-candidate-image').alt='선택한 자동 초안을 원본 사진 위에 표시';
let detailView=false;
try {detailView=sessionStorage.getItem('rosy.review.detailView')==='true';} catch {}
let seeds=[],sampleImage=null,samplePixels=0,sampleTolerance=null,previewing=false,previewSerial=0;
let samCapability=null,samJob=null,samTimer=null,samGeneration=0,selectionDigest=null;
const samMode=()=>$('pixel-selection-method').value==='sam';
const preserveExisting=()=>$('pixel-preserve').checked&&Number(pixelClass.value)!==255;
const activeSam=()=>samJob&&['queued','running'].includes(samJob.state);
function samMessage(text){$('pixel-sam-state').hidden=false;$('pixel-sam-state').textContent=text;}
function focusSamResult(){const button=selectionDigest&&!$('pixel-sample-apply').disabled?$('pixel-sample-apply'):!$('pixel-sam-run').disabled?$('pixel-sam-run'):$('pixel-selection-method');button.focus({preventScroll:true});}
function updateSamControls(labelReady,locked,dirty){
 const selected=tool==='sample',sam=selected&&samMode(),eraser=Number(pixelClass.value)===255;
 $('pixel-selection-method').closest('label').hidden=!selected;
 $('pixel-selection-method').disabled=!labelReady||locked||dirty;
 const option=$('pixel-selection-method').querySelector('[value=sam]');option.disabled=!samCapability?.available||eraser;
 option.textContent=samCapability?.available?'SAM':'SAM · 연결 필요';
 $('pixel-tolerance-mode').closest('label').hidden=!selected||sam;
 $('pixel-tolerance').closest('label').hidden=!selected||sam||$('pixel-tolerance-mode').value!=='manual';
 $('pixel-preserve').closest('label').hidden=tool==='brush';$('pixel-preserve').disabled=!labelReady||locked||dirty||eraser;
 $('pixel-sam-run').hidden=!sam;$('pixel-sam-run').disabled=!labelReady||locked||dirty||!seeds.length||!!activeSam()||!samCapability?.available||eraser;
 $('pixel-sam-cancel').hidden=!activeSam();$('pixel-sam-cancel').disabled=scope.busy;
}
function resetSam(cancel=false){
 clearTimeout(samTimer);const job=activeSam()?samJob:null,ticket=++samGeneration;
 samJob=null;selectionDigest=null;
 if(cancel&&job?.id)void request(`/api/review-ai-cancel/${job.id}`,{}).catch(()=>{if(ticket===samGeneration)samMessage('SAM 취소 요청 실패 · AI 실행 상태를 확인하세요.');});
}
async function loadSamCapability(index,ticket){
 samCapability=null;const generation=samGeneration;samMessage('SAM 설정 확인 중…');
 try{const value=await request(`/api/review-ai/${index}`);if(ticket!==serial||frame?.index!==index)return;
  samCapability=value.can_request===false?{available:false,reason:'AI 실행 권한이 없는 읽기 전용 계정입니다.'}:value.actions?.sam_points||{available:false,reason:'이 서버는 SAM 점 선택을 지원하지 않습니다.'};
  if(generation===samGeneration&&!samJob)samMessage(samCapability.available?'SAM 설정됨 · 점 선택 후 영역 찾기를 누르세요.':`SAM · ${samCapability.reason||'실행 설정이 필요합니다.'}`);
 }catch{if(ticket===serial){samCapability={available:false,reason:commonDown()?'불러오지 못함':'SAM 설정을 조회하지 못했습니다.'};samMessage(samCapability.reason);}}
 finally{if(ticket===serial)enable();}
}
async function runSam(){
 if($('pixel-sam-run').disabled)return;
 const keepFocus=document.activeElement===$('pixel-sam-run');
 resetSam(true);const ticket=samGeneration,index=frame.index,version=review.version,label=Number(pixelClass.value),points=seeds.map(point=>[...point]);
 sampleImage=null;samplePixels=0;previewing=true;samJob={state:'queued'};samMessage('SAM 영역 요청 중…');paint();enable();
 if(keepFocus)$('pixel-sam-cancel').focus({preventScroll:true});
 const current=()=>ticket===samGeneration&&frame?.index===index&&review?.version===version;
 const poll=async()=>{try{
  const status=await request(`/api/review-ai/${index}`);if(!current())return;
  samCapability=status.actions?.sam_points||samCapability;const job=status.jobs.find(row=>row.id===samJob.id);
  if(!job)throw new Error('SAM 작업 상태를 찾지 못했습니다. 다시 요청하세요.');samJob=job;
  if(activeSam()){samMessage(job.state==='queued'?'SAM 영역 계산 대기 중…':'SAM 영역 찾기 실행 중…');samTimer=setTimeout(poll,1500);enable();return;}
  const returnFocus=document.activeElement===$('pixel-sam-cancel');
  previewing=false;
  if(job.state!=='succeeded')throw new Error(job.error||({cancelled:'SAM 영역 찾기를 취소했습니다.',stale:'사진이나 라벨이 바뀌었습니다. 다시 선택하세요.'})[job.state]||'SAM 영역 찾기에 실패했습니다.');
  if(job.result?.selected_pixels===0){samMessage('SAM 선택 영역이 없습니다. 점을 바꾸고 다시 찾으세요.');paint();enable();if(returnFocus)focusSamResult();return;}
  if(!/^[a-f0-9]{64}$/.test(job.result?.selection_sha256||''))throw new Error('SAM 선택 결과를 확인할 수 없습니다.');
  selectionDigest=job.result.selection_sha256;samMessage('SAM 영역 준비됨 · 미리보기를 확인한 뒤 적용하세요.');await refreshSample();
  if(current()&&returnFocus&&document.activeElement===document.body)focusSamResult();
 }catch(value){if(current()){const returnFocus=document.activeElement===$('pixel-sam-cancel');previewing=false;sampleImage=null;samplePixels=0;samJob=null;samMessage(value.message);paint();enable();if(returnFocus)focusSamResult();}}};
 try{const job=await request(`/api/review-ai/${index}`,{action:'sam_points',version,label,points});
  if(!current()){if(job.id)void request(`/api/review-ai-cancel/${job.id}`,{}).catch(()=>{});return;}
  samJob=job;await poll();
 }catch(value){if(current()){const returnFocus=document.activeElement===$('pixel-sam-cancel');samJob=null;previewing=false;samMessage(value.message);enable();if(returnFocus)focusSamResult();}}
}
$('pixel-sam-run').onclick=runSam;
$('pixel-sam-cancel').onclick=()=>{const returnFocus=document.activeElement===$('pixel-sam-cancel');resetSam(true);previewing=false;sampleImage=null;samplePixels=0;samMessage('SAM 취소 요청됨 · 점을 바꾸거나 다시 요청할 수 있습니다.');paint();enable();if(returnFocus)focusSamResult();};
$('pixel-selection-method').onchange=()=>{
 if(samMode()&&seeds.length>16){$('pixel-selection-method').value='color';error('SAM은 최대 16점입니다. 점을 줄인 뒤 선택하세요.');return;}
 resetSam(true);void refreshSample();enable();
};
let unknownPixels=null,totalPixels=0;
// focusReload=false: the caller keeps the photo editable and returns focus to the canvas itself.
function error(value='',focusReload=true){
 setText($('pixel-error'),value);$('pixel-error').hidden=!value;
 if(value){const reload=$('pixel-reload');reload.classList.add('pixel-recovery-reload');$('pixel-error').after(reload);
  requestAnimationFrame(()=>requestAnimationFrame(()=>{if(!$('pixel-error').hidden){reload.scrollIntoView({block:'center'});if(focusReload&&!reload.disabled)reload.focus({preventScroll:true});}}));
 }
}
async function setView(detail){
 detailView=detail;
 try{sessionStorage.setItem('rosy.review.detailView',String(detail));}catch{}
 $('pixel-view-original').setAttribute('aria-pressed',String(!detail));
 $('pixel-view-detail').setAttribute('aria-pressed',String(detail));
 if(!ready)return;
 if(!detail){displayPhoto=original;$('pixel-view-status').textContent=`원본 사진 · ${inputPurpose()}`;paint();return;}
 const ticket=serial,index=frame.index;
 $('pixel-view-status').textContent='명암 보정 화면을 불러오는 중…';
 try{const photo=await image(`/api/view-images/${index}`);if(ticket!==serial||!detailView)return;
  if(photo.naturalWidth!==original.naturalWidth||photo.naturalHeight!==original.naturalHeight)throw new Error('보기 보정 크기가 원본과 다릅니다.');
  displayPhoto=photo;$('pixel-view-status').textContent='명암 보정 보기 · 흰 포화 영역은 복원되지 않음';paint();
 }catch(value){if(ticket!==serial)return;detailView=false;displayPhoto=original;
  $('pixel-view-original').setAttribute('aria-pressed','true');$('pixel-view-detail').setAttribute('aria-pressed','false');
  $('pixel-view-status').textContent=`명암 보정을 표시하지 못했습니다. 원본 보기로 돌아왔습니다. ${value.message}`;paint();}
}
function evaluationControls(){if(workspace.workspace_kind!=='evaluation')return;const label=document.createElement('label');label.className='ui-check';label.innerHTML='<input class="ui-field" id="pixel-unknown" type="checkbox">가려져 경계를 판단할 수 없는 투명 영역을 모두 확인했습니다 (평가 전용)';$('pixel-approval-hint').before(label);$('pixel-unknown').onchange=enable;$('pixel-unknown-help').textContent='평가 전용: 가림 때문에 판단할 수 없는 영역만 255로 남기고 확인하세요. 학습 자료에는 포함되지 않습니다.';$('pixel-preparation').hidden=true;}
let candidateKey='';
function v13Review(){return !!review?.classes?.classes.some(row=>row.name==='lane_left')&&!!review?.classes?.classes.some(row=>row.name==='lane_right'&&row.role==='lane_marking')&&!!review?.classes?.classes.some(row=>row.name==='drivable');}
function legacyCandidate(){return v13Review()&&review?.draft_candidates?.find(row=>row.sha256===candidates.value)?.origin==='v12_pixel_mask_candidate';}
function candidateOptions(){const rows=ready?review?.draft_candidates||[]:[],key=`${frame?.index}:${rows.map(row=>`${row.sha256}:${row.origin}`).join(',')}`,select=candidates;
 if(key!==candidateKey){const chosen=select.value;candidateKey=key;candidateList.set(rows.map(row=>({id:row.sha256,label:`${row.origin==='v12_pixel_mask_candidate'&&v13Review()?'v12 이관 참고 · v13 주행영역 없음':({'v12_pixel_mask_candidate':'v12 기존 마스크','sam3_road_v1_v12_base':'SAM3 주행영역 + v12 마스크','sam3_road_visible_lane_clip':'SAM3 차선 밖 미검수 보정','sam3_obstacle_unknown_v12_base':'SAM3 장애물 보류 · 사람 확인 필요'})[row.origin]||candidateOrigin(row.origin)} · ${row.sha256.slice(0,8)}`,secondary:`출처: ${row.origin||'미기록'} · 목록 ${String(row.catalog_sha256).slice(0,8)}`})));select.value=rows.some(row=>row.sha256===chosen)?chosen:rows[0]?.sha256;}
 if(candidatePreviewDigest&&candidatePreviewDigest!==select.value){resetCandidatePreview();paint();$('pixel-candidate-status').textContent='초안 목록이 바뀌었습니다. 미리보기를 다시 누르세요.';}
  const evaluation=workspace?.workspace_kind==='evaluation',excluded=frame?.status==='excluded'||review?.status==='excluded',unavailable=evaluation||excluded;
  candidateEmpty.hidden=!unavailable&&(rows.length>0||!ready);candidateEmpty.textContent=evaluation?'고정 평가는 자동 초안을 표시·저장하지 않습니다. 직접 검수하세요.':excluded?'제외된 사진입니다. 재검수를 시작한 뒤 초안을 확인하세요.':ready?'새 자동 초안이 없습니다.':'초안 목록을 불러오는 중…';$('pixel-candidate-tools').hidden=unavailable||!rows.length;select.disabled=unavailable||scope.busy||!ready||loading||conflicted||forbidden||draft.length>0||seeds.length>0||polygon.length>0;
  $('pixel-apply-candidate').disabled=select.disabled||!rows.length||frame?.status==='excluded'||review?.status==='excluded';
  mergeCandidate.disabled=select.disabled||!rows.length||!unknownPixels||frame?.status==='excluded'||review?.status==='excluded';
 $('pixel-apply-candidate').textContent=legacyCandidate()?'v12 참고 마스크로 전체 교체':'선택 초안으로 전체 교체';
 $('pixel-preview-candidate').disabled=select.disabled||!rows.length;
 $('pixel-preview-candidate').setAttribute('aria-pressed',String(candidateVisible));}
async function previewCandidate(allow=()=>true){
 const digest=candidates.value,index=frame?.index,ticket=serial;
 if(workspace?.workspace_kind==='evaluation'||frame?.status==='excluded'||review?.status==='excluded'){resetCandidatePreview();return;}
 if(!ready||!digest)return;
 resetCandidatePreview();candidatePreviewDigest=digest;candidateLoading=true;const generation=candidateRequest;
 $('pixel-candidate-status').textContent='초안 미리보기를 불러오는 중…';
 paint();enable();
 try{
  const proposal=await image(`/api/draft-images/${index}/${digest}`);
  if(ticket!==serial||generation!==candidateRequest||frame?.index!==index||candidates.value!==digest)return;
  if(!allow()){resetCandidatePreview();paint();enable();return false;}
  if(proposal.naturalWidth!==original.naturalWidth||proposal.naturalHeight!==original.naturalHeight)throw new Error('초안 크기가 원본 사진과 다릅니다.');
  const off=document.createElement('canvas');off.width=proposal.naturalWidth;off.height=proposal.naturalHeight;
  const ctx=off.getContext('2d');ctx.drawImage(proposal,0,0);candidateData=ctx.getImageData(0,0,off.width,off.height).data;candidateVisible=true;candidateLoading=false;
  paint();$('pixel-candidate-status').textContent=candidateReference()?'v12 참고 · 자동 저장 대상이 아닙니다.':candidatePixels?`AI 초안 ${candidatePixels.toLocaleString()}픽셀 · 미저장 · 사람 라벨 보존`:'보완할 새 픽셀이 없습니다. 사람 라벨은 유지됩니다.';enable();
 }catch(value){
  if(ticket!==serial||generation!==candidateRequest)return;
  candidateLoading=false;candidateVisible=false;candidateData=null;candidatePixels=0;paint();$('pixel-candidate-status').textContent='초안을 불러오지 못했습니다. 미리보기를 다시 누르거나 직접 수정하세요.';enable();
 }
}
function visible(){return workspace?.frames.filter(row=>$('pixel-filter').value==='all'||row.status!=='excluded'&&row.pixel_status===$('pixel-filter').value)||[];}
function url(){const link=new URL(location.href);if(frame)link.searchParams.set('frame',frame.index);else link.searchParams.delete('frame');if($('pixel-filter').value==='all')link.searchParams.delete('filter');else link.searchParams.set('filter',$('pixel-filter').value);history.replaceState(null,'',link);}
function enable(){updatePages(workspace?.page,scope.busy||loading||!!stroke||draft.length>0||seeds.length>0||polygon.length>0);updateAI();const dirty=draft.length>0,hasSamples=seeds.length>0,hasPolygon=polygon.length>0,selection=hasSamples||hasPolygon,locked=scope.busy||!ready||loading||conflicted||forbidden||!!stroke,excluded=frame?.status==='excluded'||review?.status==='excluded',editable=!locked&&!excluded&&!!review?.classes,labelReady=editable&&pixelClass.value!=='';
 updateContext(workspace?.context,scope.busy||loading||!!stroke||dirty||selection);
  const step=!ready?0:review?.status!=='pending'?3:dirty||selection||unknownPixels>0?2:3;
  [...$('pixel-flow').children].forEach((item,index)=>{
    item.dataset.state=index===step?'now':'todo'; // The work guide never turns a draft or a selected option into human approval.
    if(index===step)item.setAttribute('aria-current','step');else item.removeAttribute('aria-current');
  });
  const selectedRole=review?.classes?.classes.find(row=>String(row.index)===pixelClass.value)?.role;
  const toolHint=!ready?'':excluded?'제외 사진은 재검수를 시작한 뒤 편집하세요.':!review?.classes?'자료 등록에서 픽셀 클래스를 연결하세요.':dirty?'먼저 초안을 저장하거나 버리세요.':selection?'선택 영역을 적용하거나 취소하세요.':!pixelClass.value?'픽셀 클래스를 선택하세요.':selectedRole==='background'?'경계선 바깥 바닥을 칠하세요.':selectedRole==='drivable'?'경계선 안쪽 바닥을 칠하세요.':'';
  $('pixel-tool-hint').textContent=toolHint;$('pixel-tool-hint').hidden=!toolHint;
  document.querySelector('.pixel-save-panel').hidden=!(dirty||selection||candidateDraftReady());
  $('pixel-radius').closest('label').hidden=tool!=='brush';
 $('pixel-sample-apply').hidden=$('pixel-sample-clear').hidden=tool==='brush';
  $('pixel-tolerance-mode').closest('label').hidden=tool!=='sample';
 $('pixel-tolerance').closest('label').hidden=tool!=='sample'||$('pixel-tolerance-mode').value!=='manual';
 const toolLayout=tool+':'+$('pixel-selection-method').value+':'+$('pixel-tolerance-mode').value;
 if(lastToolLayout!==toolLayout){lastToolLayout=toolLayout;requestAnimationFrame(resizePixelViewport);}
 frameLocked=()=>scope.busy||loading||!!stroke||dirty||selection;frameList.element.querySelector('[role=listbox]').setAttribute('aria-disabled',String(frameLocked()));
 $('pixel-fill-unknown').disabled=!editable||dirty||selection||!unknownPixels;
 pixelFillClass.disabled=$('pixel-fill-unknown').disabled||!pixelClass.value||pixelClass.value==='255';
 reasons.why(pixelFillClass,!pixelClass.value||pixelClass.value==='255'?'채울 픽셀 클래스를 먼저 선택하세요.':!unknownPixels?'남은 미검수가 없습니다.':'');
 pixelResolve.hidden=!ready||!unknownPixels||unknownPixels===totalPixels;
 pixelResolveBackground.textContent=`남은 ${(unknownPixels||0).toLocaleString()}픽셀 배경으로 채우기`;
 pixelResolveBackground.disabled=$('pixel-fill-unknown').disabled;
 pixelResolveClass.disabled=pixelFillClass.disabled;
 pixelResolveClass.hidden=!pixelClass.value||pixelClass.value==='255';
 $('pixel-fill-unknown').textContent='나머지 배경으로 채우기';
 $('pixel-fill-unknown').setAttribute('aria-label',ready&&unknownPixels?`나머지 배경으로 채우기 · 미검수 ${unknownPixels.toLocaleString()}픽셀`:'나머지 배경으로 채우기');
 for(const id of ['pixel-view-original','pixel-view-detail'])$(id).disabled=!ready||loading;
 $('pixel-mode').textContent='선택한 도구: '+{sample:'점',brush:'브러시',polygon:'영역'}[tool];
 toolGroup.set(tool);for(const id of ['pixel-flood','pixel-brush-tool','pixel-polygon-tool']){$(id).disabled=!labelReady||dirty||selection;$(id).closest('label').toggleAttribute('data-disabled',$(id).disabled);}
 $('pixel-preserve').disabled=!editable||dirty;
 pixelClass.disabled=!editable;for(const id of ['pixel-radius','pixel-tolerance-mode','pixel-tolerance'])$(id).disabled=!editable;
 if($('pixel-unknown'))$('pixel-unknown').disabled=!editable;
 for(const id of ['pixel-fill','pixel-undo','pixel-exclude','pixel-reopen','pixel-approve']){$(id).disabled=id==='pixel-reopen'?locked||frame?.status==='excluded':!editable;reasons.why($(id),forbidden?'검수 권한이 없습니다. 최신 내용을 다시 불러오세요.':locked?'사진 불러오기와 저장을 마친 뒤 다시 시도하세요.':excluded?'제외 사진은 먼저 재검수로 돌리세요.':!review?.classes?'자료 등록에서 검증된 class 파일을 연결하세요.':'');
  if((dirty||selection||id==='pixel-approve'&&candidateDraftReady())&&id!=='pixel-undo'){$(id).disabled=true;reasons.why($(id),id==='pixel-approve'&&candidateDraftReady()?'미저장 AI 초안을 저장하거나 버린 뒤 완료하세요.':'현재 초안을 적용하거나 버린 뒤 진행하세요.');}}
 $('pixel-fill').disabled=!labelReady||dirty||selection;
 if(!labelReady)reasons.why($('pixel-fill'),'먼저 픽셀 클래스를 선택하세요.');
 $('pixel-sample-apply').disabled=!labelReady||locked||dirty||(tool==='polygon'?polygon.length<3:!hasSamples||previewing||samplePixels===0);
 $('pixel-sample-apply').setAttribute('aria-label',tool==='polygon'?'다각형 영역 적용':'점 선택 영역 적용');
 $('pixel-sample-clear').disabled=!selection||scope.busy;
 $('pixel-sample-clear').setAttribute('aria-label',tool==='polygon'?'다각형 영역 취소':'선택 점 지우기');
 $('pixel-radius').disabled=!labelReady||tool!=='brush';
 $('pixel-tolerance-mode').disabled=!labelReady||tool!=='sample';
 $('pixel-tolerance').disabled=!labelReady||tool!=='sample';
 updateSamControls(labelReady,locked,dirty);
 $('pixel-save').disabled=!(dirty||candidateDraftReady())||locked||selection;$('pixel-discard').disabled=!(dirty||candidateDraftReady())||scope.busy||!!stroke;
 for(const id of ['pixel-save','pixel-discard'])reasons.why($(id),!(dirty||candidateDraftReady())?'저장하지 않은 초안이 없습니다.':scope.busy||stroke?'현재 저장·편집을 마친 뒤 다시 시도하세요.':conflicted?'다른 탭에서 바뀌었습니다. 초안을 버리고 다시 불러오세요.':selection?'선택 영역을 먼저 적용하거나 취소하세요.':'');
 const sampleState=previewing?(samMode()?'SAM 영역 찾기 실행 중':'색 영역 계산 중'):sampleImage?`${samplePixels.toLocaleString()}픽셀 미리보기 · ${samMode()?'SAM':`Lab 허용치 ${sampleTolerance}`}`:samMode()?'SAM 영역 찾기를 누르세요':'미리보기 실패';
 $('pixel-draft').textContent=hasPolygon?`영역 꼭짓점 ${polygon.length}개 · ${polygon.length<3?'3개 이상 찍으세요':'Enter로 적용하세요'}`:hasSamples?`${seeds.length}점 선택 · ${sampleState}`:dirty?`저장하지 않은 브러시 ${draft.length}획`:!pixelClass.value?'먼저 픽셀 클래스를 선택하세요.':tool==='sample'?'수정할 영역 안에 점을 찍으세요.':'';
 const protectionHint=tool==='polygon'?(preserveExisting()?'기존 라벨은 두고 미검수 영역만 수정합니다.':'둘러싼 영역을 선택 클래스로 바꿉니다.'):preserveExisting()?'찍은 라벨 영역은 수정하고 다른 저장 라벨은 보호합니다.':'선택 영역의 기존 라벨도 바꿉니다.';
 $('pixel-preserve').setAttribute('data-ui-tooltip',protectionHint);
 $('pixel-tool-hint').textContent=toolHint;
 $('pixel-tool-hint').hidden=!$('pixel-tool-hint').textContent;
 if(ready&&unknownPixels>0&&(workspace.workspace_kind==='evaluation'||unknownPixels===totalPixels)){
  const evaluation=workspace.workspace_kind==='evaluation';
  const canReviewUnknown=evaluation&&frame.source.source_kind==='mcap'&&unknownPixels<totalPixels&&$('pixel-unknown')?.checked;
  if(!canReviewUnknown){
   $('pixel-approve').disabled=true;
   reasons.why($('pixel-approve'),evaluation?(unknownPixels===totalPixels?'사진 전체가 가림 후보여서 승인할 수 없습니다.':frame.source.source_kind!=='mcap'?'MCAP 평가 사진에서만 가림 후보를 승인할 수 있습니다.':'가림 후보를 확인하고 평가 전용 확인란을 선택하세요.'):`미검수 ${unknownPixels.toLocaleString()}픽셀이 남았습니다. ${unknownPixels<totalPixels?'아래 버튼으로 남은 영역을 채우거나 경계를 직접 수정하세요.':'중요한 영역을 먼저 칠한 뒤 남은 영역을 채우세요.'} 판단할 수 없는 영역은 대기로 두세요.`);
  }
 }
 pixelResultNote.textContent=ready&&$('pixel-approve').disabled?'':ready&&unknownPixels>0?'완료를 누르면 남은 미검수를 배경으로 채우고 사진 전체 검수를 기록한 뒤 다음 사진을 엽니다. 아래 버튼은 배경 채우기만 합니다.':ready?'원본과 경계를 확인한 뒤 완료를 누르면 검수를 기록하고 다음 사진을 엽니다.':'';
 pixelResultNote.hidden=!pixelResultNote.textContent;pixelResultTag.hidden=!(ready&&$('pixel-approve').disabled);
 if(savedPixelSummary)pixelResult.textContent=`${savedPixelSummary} · ${dirty?`${draft.length}개 미저장 획`:'미저장 획 없음'}`;
 const rows=visible(),pos=rows.findIndex(row=>row.index===frame?.index);
 for(const [id,available] of [['pixel-prev',pos>0||workspace?.page?.offset>0],['pixel-next',pos>=0&&(pos<rows.length-1||workspace?.page?.offset+workspace?.page?.limit<workspace?.page?.total)],['pixel-next-pending',(workspace?.pixel_counts?.pending??0)>(frame?.pixel_status==='pending'&&frame?.status!=='excluded'?1:0)]]){$(id).disabled=scope.busy||!!stroke||dirty||selection||!ready||!available;reasons.why($(id),!available?id==='pixel-next-pending'?'다른 검수 대기 사진이 없습니다.':'현재 필터에서 더 이동할 사진이 없습니다.':scope.busy||stroke||dirty||selection?'현재 초안을 적용하거나 버린 뒤 이동하세요.':'');}
 for(const id of ['pixel-filter'])$(id).disabled=scope.busy||loading||!!stroke||dirty||selection;
 $('pixel-reload').disabled=scope.busy||loading||!!stroke||dirty||selection;reasons.why($('pixel-reload'),loading?'검수 내용을 불러오는 중입니다.':scope.busy||stroke||dirty||selection?'현재 초안을 적용하거나 버린 뒤 다시 불러오세요.':'');
 $('pixel-export').disabled=scope.busy||loading||!!stroke||dirty||selection||conflicted||forbidden||!workspace;reasons.why($('pixel-export'),loading?'검수 내용을 불러오는 중입니다.':forbidden?'검수 권한이 없습니다. 최신 내용을 다시 불러오세요.':scope.busy||stroke||dirty||selection||conflicted?'저장을 마치고 최신 내용을 확인하세요.':'');reasons.sync();
 candidateOptions();
}
async function request(path,body){const response=await accountFetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Pinky-Token':workspace.token},body:JSON.stringify(body)}:{});if(response.status>=500){const error=new Error('검수 서비스를 사용할 수 없습니다. 잠시 후 다시 시도하세요.');error.status=response.status;throw error;}const value=await response.json();if(!response.ok){if(response.status===409)conflicted=true;if(response.status===403){forbidden=true;throw new Error('검수 권한이 없습니다. 최신 내용을 다시 불러오고 접근 권한을 확인하세요.');}throw new Error(readableError(value.error));}return value;}
function showPixelCounts(counts){
  const checkedAt=`검수 원장 · ${new Date().toTimeString().slice(0,8)}`;
  $('pixel-counts').replaceChildren(...(counts?[['승인',counts.approved],['제외',counts.excluded],['대기',counts.pending]]:[]).map(([name,value])=>{
    const cell=document.createElement('div'),term=document.createElement('dt'),count=document.createElement('dd'),note=document.createElement('dd');
    term.textContent=name;count.textContent=value??0;note.setAttribute('data-note','');note.textContent=checkedAt;cell.append(term,' ',count,note);return cell;}));
}
function options(){showPixelCounts(workspace?.pixel_counts);const rows=visible(),firstUse=!Object.values(workspace.counts).some(Boolean);if(rows.length&&!conflicted&&!forbidden){$('pixel-reload').classList.remove('pixel-recovery-reload');photoNavigation.append($('pixel-reload'));}$('pixel-filter').parentElement.hidden=firstUse;for(const id of ['pixel-prev','pixel-next','pixel-next-pending'])$(id).hidden=!rows.length;$('pixel-empty').hidden=!!rows.length;$('pixel-empty').querySelector('h3').textContent=firstUse?'등록된 사진이 없습니다':'이 상태의 픽셀 검수가 없습니다';$('pixel-all').hidden=false;$('pixel-all').textContent=firstUse?'자료 등록 열기':'전체 보기';$('pixel-content').hidden=!rows.length;thumbnails(rows);}
function image(path){return new Promise((resolve,reject)=>{const value=new Image();value.onload=()=>resolve(value);value.onerror=()=>reject(new Error('원본 또는 마스크를 불러오지 못했습니다. 승인할 수 없습니다.'));value.src=path;});}
function thumbnails(rows){frameList.element.hidden=!rows.length;showPhotos(frameList,rows.map(row=>({id:String(row.index),label:`사진 ${frameOrdinal(workspace,row.index)}`,secondary:row.status==='excluded'?'객체 제외':states[row.pixel_status],thumb:`/api/images/${row.index}`})));if(frame){frameList.select(String(frame.index));revealOpen(frameList);}}
// classes.yaml requires a colour per class; names come from its optional display (D-485).
function classColor(index){const cls=review?.classes?.classes.find(row=>row.index===index);return cls?`#${cls.color.map(v=>v.toString(16).padStart(2,'0')).join('')}`:cssColor('--ink');}
function className(cls){return cls.display||cls.name;}
function paintSwatch(swatch,index){const color=classColor(index);setGeometry(swatch,{color:color.startsWith('#')?color:'var(--ink)'});}
function legend(){ const classes=review.classes?.classes||[],ignored=classes.filter(c=>c.role==='ignore');$('pixel-legend').replaceChildren();for(const cls of classes){const item=document.createElement('span'),swatch=document.createElement('i');swatch.className='review-swatch';paintSwatch(swatch,cls.index);swatch.setAttribute('aria-hidden','true');item.append(swatch,document.createTextNode(className(cls)));$('pixel-legend').append(item);}$('pixel-class-help').textContent=`${classes.some(c=>c.role==='drivable')?'먼저 흰 경계선 바깥의 주행 불가 바닥을 배경으로 확인하세요. 장애물 가림은 255로 보류하고, 그다음 경계선 안의 주행 가능 바닥을 확인하세요. ':''}픽셀 면 · ${classes.map(className).join(' · ')}. 255는 클래스가 아닙니다.${workspace.workspace_kind==='evaluation'?' 가림으로 판단할 수 없는 픽셀만 따로 확인할 수 있습니다.':''}${ignored.length?' '+ignored.map(className).join('·')+': 픽셀로 표시하지만 로봇 주행 해석에는 쓰지 않습니다.':''}`;}
// K1 class chips (S2: the old select is gone). '' = no class chosen (tools wait), 255 = erase back to unchecked; swatch and digit key are drawn
// on the chips after each build because the shared group only knows a label.
function setClassItems(classes,wanted){classGroup.setItems([{value:'',label:'선택 안 함'},...classes.map(cls=>({value:String(cls.index),label:className(cls)})),{value:'255',label:'미검수로 지우기'}]);classGroup.set(wanted);}
function decorateClasses(){const chips=[...classGroup.element.querySelectorAll('label.choice-chip')],classes=review.classes?.classes||[];classes.forEach((cls,index)=>{const chip=chips[index+1],swatch=document.createElement('i'),key=document.createElement('kbd');swatch.className='review-swatch';paintSwatch(swatch,cls.index);swatch.setAttribute('aria-hidden','true');key.textContent=index<9?String(index+1):'·';chip.querySelector('.choice-check').after(swatch);chip.append(key);});}
let paletteCache=null,paletteTheme='';
function palette(){const theme=document.documentElement.dataset.theme;if(paletteCache&&paletteTheme===theme)return paletteCache;const scratch=document.createElement('canvas');scratch.width=scratch.height=1;const ctx=scratch.getContext('2d'),values={};for(const cls of review.classes?.classes||[]){ctx.fillStyle=classColor(cls.index);ctx.fillRect(0,0,1,1);values[cls.index]=[...ctx.getImageData(0,0,1,1).data];}ctx.fillStyle=cssColor('--status-warn');ctx.fillRect(0,0,1,1);values[255]=[...ctx.getImageData(0,0,1,1).data];paletteCache=values;paletteTheme=theme;return values;}
function trace(ctx,line,style){ctx.strokeStyle=ctx.fillStyle=style;ctx.lineWidth=Math.max(1,line.radius*2);ctx.lineCap=ctx.lineJoin='round';ctx.beginPath();line.points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();for(const [x,y] of line.points){if(line.radius===0){ctx.fillRect(x,y,1,1);continue;}ctx.beginPath();ctx.arc(x,y,line.radius,0,Math.PI*2);ctx.fill();}}
// Draft strokes are previews only; the eraser (255) shows the bare photo inside the stroke.
let overlayCanvas=null,overlayKey='',scratch=null;
function overlay(){ // Recoloured mask layer (D-469): rebuild when frame, version or display setting changes.
  const key=[frame.index,review.version,$('pixel-opacity').value,$('pixel-show-unknown').checked,document.documentElement.dataset.theme,candidatePreviewDigest,candidateVisible,candidateRequest].join('|');
  if(overlayCanvas&&overlayKey===key)return overlayCanvas;
  const off=document.createElement('canvas');off.width=original.naturalWidth;off.height=original.naturalHeight;
  const other=off.getContext('2d');other.drawImage(maskImage,0,0);
  const data=other.getImageData(0,0,off.width,off.height),colors=palette();const opacity=Number($('pixel-opacity').value)/100,counts=new Map();let unknown=0;
  for(let i=0;i<data.data.length;i+=4){const value=data.data[i];counts.set(value,(counts.get(value)||0)+1);if(value===255)unknown++;}
  const rare=unknown>0&&unknown*100<off.width*off.height;
  candidatePixels=0;
  for(let i=0;i<data.data.length;i+=4){let value=data.data[i];if(value===255&&candidateVisible&&candidateData&&workspace.workspace_kind!=='evaluation'&&candidateData[i]!==255&&colors[candidateData[i]]){value=candidateData[i];candidatePixels++;}const color=colors[value];if(!color||(value===255&&!$('pixel-show-unknown').checked)){data.data[i+3]=0;continue;}data.data[i]=color[0];data.data[i+1]=color[1];data.data[i+2]=color[2];data.data[i+3]=value===255&&rare?255:Math.round(opacity*(value===255?180:255));}
  unknownPixels=unknown;totalPixels=off.width*off.height;
  $('pixel-coverage').textContent=`${workspace.workspace_kind==='evaluation'?'가림 후보':'미검수'} ${unknown.toLocaleString()}픽셀 (${rare?'<1':Math.round(unknown/(off.width*off.height)*100)}%)`;
  pixelResultDetails.textContent=`전체 ${(off.width*off.height).toLocaleString()}픽셀 · 후보 ${review.draft_candidates?.length||0}개 · ${review.classes?.classes.map(cls=>`${className(cls)} ${Number(counts.get(cls.index)||0).toLocaleString()}`).join(' · ')||'클래스 미연결'}`;
  savedPixelSummary=`저장 v${review.version}`;
  pixelResult.textContent=`${savedPixelSummary} · ${draft.length?`${draft.length}개 미저장 획`:'미저장 획 없음'}`;
  other.putImageData(data,0,0);overlayCanvas=off;overlayKey=key;return off;
}
function sampleOverlay(){if(!sampleImage)return null;const off=document.createElement('canvas');off.width=original.naturalWidth;off.height=original.naturalHeight;const ctx=off.getContext('2d');ctx.drawImage(sampleImage,0,0);const data=ctx.getImageData(0,0,off.width,off.height),colors=palette(),opacity=Number($('pixel-opacity').value)/100;for(let i=0;i<data.data.length;i+=4){const value=data.data[i],color=colors[value];if(value===255||!color){data.data[i+3]=0;continue;}data.data[i]=color[0];data.data[i+1]=color[1];data.data[i+2]=color[2];data.data[i+3]=Math.round(opacity*255);}ctx.putImageData(data,0,0);return off;}
function eraserLines(ctx,lines){ // One scratch pass for every eraser stroke: trace all, then clip to the photo.
  if(!scratch||scratch.width!==ctx.canvas.width||scratch.height!==ctx.canvas.height){scratch=document.createElement('canvas');scratch.width=ctx.canvas.width;scratch.height=ctx.canvas.height;}
  const other=scratch.getContext('2d');other.clearRect(0,0,scratch.width,scratch.height);
  for(const line of lines)trace(other,line,cssColor('--ink'));
  other.globalCompositeOperation='source-in';other.drawImage(displayPhoto||original,0,0);other.globalCompositeOperation='source-over';
  ctx.drawImage(scratch,0,0);
}
function paint(){if(!ready)return;const canvas=$('pixel-canvas'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(displayPhoto||original,0,0);const mask=overlay();if($('pixel-mask-visible').checked)ctx.drawImage(mask,0,0);if(sampleImage)ctx.drawImage(sampleOverlay(),0,0);
  const opacity=Number($('pixel-opacity').value)/100,lines=stroke?[...draft,stroke]:draft;
  for(const line of lines)if(line.label!==255){ctx.globalAlpha=opacity;trace(ctx,line,classColor(line.label));ctx.globalAlpha=1;}
  const erasers=lines.filter(line=>line.label===255);if(erasers.length)eraserLines(ctx,erasers);
  if(polygon.length){ctx.beginPath();polygon.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));if(polygon.length>2){ctx.closePath();
    const off=document.createElement('canvas');off.width=canvas.width;off.height=canvas.height;const fill=off.getContext('2d');
    fill.beginPath();polygon.forEach(([x,y],i)=>i?fill.lineTo(x,y):fill.moveTo(x,y));fill.closePath();fill.fillStyle=classColor(Number(pixelClass.value))||cssColor('--status-warn');fill.fill();
    if(preserveExisting()){const saved=document.createElement('canvas');saved.width=canvas.width;saved.height=canvas.height;const mask=saved.getContext('2d');mask.drawImage(maskImage,0,0);const labels=mask.getImageData(0,0,canvas.width,canvas.height).data,data=fill.getImageData(0,0,canvas.width,canvas.height);for(let i=0;i<data.data.length;i+=4)if(labels[i]!==255)data.data[i+3]=0;fill.putImageData(data,0,0);}
    ctx.globalAlpha=.25;ctx.drawImage(off,0,0);ctx.globalAlpha=1;
  }ctx.setLineDash([4,3]);ctx.lineWidth=2;ctx.strokeStyle=cssColor('--ink');ctx.stroke();ctx.setLineDash([]);for(const [x,y] of polygon){ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fillStyle=cssColor('--ink');ctx.fill();}}
  const radius=Math.max(3,5*canvas.width/Math.max(1,canvas.getBoundingClientRect().width));ctx.lineWidth=Math.max(2,radius/2);for(const [x,y] of seeds){ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.fillStyle=cssColor('--ink');ctx.fill();ctx.strokeStyle=cssColor('--ground');ctx.stroke();}
  if(keyCursor){const [x,y]=keyCursor,scale=canvas.width/Math.max(1,canvas.getBoundingClientRect().width);ctx.save();ctx.strokeStyle=cssColor('--series-primary');ctx.lineWidth=2*scale;ctx.beginPath();ctx.moveTo(x-5*scale,y);ctx.lineTo(x+5*scale,y);ctx.moveTo(x,y-5*scale);ctx.lineTo(x,y+5*scale);ctx.stroke();ctx.restore();}
}
async function loadVlm(index,ticket){
 if(ticket!==serial)return;
 const requestId=++vlmRequest;
 const state=$('pixel-vlm-state'),note=$('pixel-vlm-note');
 state.setAttribute('state','pending');state.textContent='AI 의견을 불러오는 중…';note.textContent='';$('pixel-vlm-details').textContent='';
 try{const value=await request(`/api/vlm-feedback/${index}`);if(ticket!==serial||requestId!==vlmRequest)return;
  const result=feedbackPresentation(value);state.setAttribute('state',result.state);state.textContent=result.title;note.textContent=result.note;
  $('pixel-vlm-details').textContent=result.details||'';
 }catch(value){if(ticket!==serial||requestId!==vlmRequest)return;state.setAttribute('state','warning');state.textContent='AI 의견 조회 실패';note.textContent=commonDown()?'':'서버 연결을 확인한 뒤 저장 의견을 새로고침하세요.';$('pixel-vlm-details').textContent=panelError(value,'');}
}

async function select(index){
 resetAI();resetVersions();review=null;original=displayPhoto=maskImage=null;
 $('pixel-ai-summary').hidden=true;$('pixel-vlm-note').textContent='';$('pixel-vlm-details').textContent='';
 $('pixel-canvas').hidden=true;$('pixel-canvas').getContext('2d').clearRect(0,0,$('pixel-canvas').width,$('pixel-canvas').height);
 $('pixel-status').setAttribute('state','pending');$('pixel-status').textContent='선택한 사진을 불러오는 중…';
 $('pixel-source').textContent='';$('pixel-legend').replaceChildren();$('pixel-view-status').textContent='';aiPanel.hidden=false;const ticket=++serial,selectedClass=pixelClass.value;ready=false;keyCursor=null;keyboardPosition.hidden=true;savedPixelSummary='';pixelResult.textContent='사진을 불러오는 중';resetCandidatePreview();$('pixel-candidate-status').textContent='';stroke=null;draft=[];polygon=[];clearSamples();brush.hidden=true;frame=workspace.frames.find(row=>row.index===Number(index));error();$('pixel-coverage').textContent='';$('pixel-decision').hidden=true;options();url();enable();if(!frame)return;
 resetHistory();$('pixel-vlm-state').textContent='AI 의견을 불러오는 중…';$('pixel-vlm-state').setAttribute('state','pending');$('pixel-vlm-note').textContent='';
 request(`/api/history/${frame.index}`).then(value=>{if(ticket===serial)showHistory(value);})
   .catch(()=>{if(ticket===serial)resetHistory(commonDown()?'불러오지 못함':'검수 기록을 불러오지 못했습니다. 최신 내용을 다시 불러오세요.');});
 $('pixel-title').textContent=`사진 ${frameOrdinal(workspace,frame.index)} 픽셀 검수`;for(const link of document.querySelectorAll('#pixel-object,.review-kinds a[href^="/?frame="],.review-kinds a[href="/"]'))link.href=reviewLink('/',frame.index);if($('pixel-unknown'))$('pixel-unknown').checked=false;
 try{const next=await request(`/api/masks/${frame.index}`);const [photo,pixels]=await Promise.all([image(`/api/images/${frame.index}`),image(`/api/mask-images/${frame.index}?v=${next.version}`)]);if(ticket!==serial)return;if(photo.naturalWidth!==frame.source.width||photo.naturalHeight!==frame.source.height||pixels.naturalWidth!==photo.naturalWidth||pixels.naturalHeight!==photo.naturalHeight)throw new Error('원본과 마스크 크기가 다릅니다.');review=next;original=displayPhoto=photo;maskImage=pixels;const canvas=$('pixel-canvas');canvas.width=photo.naturalWidth;canvas.height=photo.naturalHeight;
 setClassItems(next.classes?.classes||[],selectedClass||String(next.classes?.classes.find(cls=>cls.name==='lane_line')?.index??''));$('pixel-status').setAttribute('state',next.status==='approved'?'ready':'warning');$('pixel-status').textContent=`${states[next.status]} · v${next.version} · ${photo.naturalWidth} × ${photo.naturalHeight} · 객체 ${frame.status==='excluded'?'제외':frame.status==='approved'?'승인':'대기'}`;$('pixel-source').textContent=JSON.stringify({source:frame.source,mask:next,map_reference:workspace.map_reference},null,2);legend();decorateClasses();$('pixel-canvas').hidden=false;ready=true;showVersions('pixel',frame.index);connectAI();paint();void loadVlm(frame.index,ticket);if(detailView)void setView(true);else $('pixel-view-status').textContent='원본 사진 · '+inputPurpose();}
 catch(value){if(ticket===serial){error(panelError(value,'불러오지 못함'));aiPanel.hidden=true;
 $('pixel-status').setAttribute('state','warning');$('pixel-status').textContent='선택한 사진 조회 실패 · 새로고침 후 다시 확인하세요.';
 pixelResult.textContent='검수 내용을 확인할 수 없습니다.';pixelResultNote.textContent='';
 }}finally{if(ticket===serial){enable();$('pixel-ai-summary').hidden=!ready;if(ready){void previewCandidate();void loadSamCapability(frame.index,ticket);}}}}
// After a decision, open the next pending photo whose pixels are editable (object exclusion locks them).
async function nextPending(index){const ticket=serial,page=await request(workspacePage('pixel','pending',{after:index}));if(ticket!==serial||frame?.index!==index)return;if(!page.frames.length){workspace.counts=page.counts;workspace.pixel_counts=page.pixel_counts;return;}const next=page.frames.find(row=>row.index===page.page.target)||page.frames[0];const current=await request(workspacePage('pixel',$('pixel-filter').value,{around:next.index}));if(ticket!==serial||frame?.index!==index)return;workspace={...workspace,...current};return next;}
function mutate(action,extra={}){return commit([{action,...extra}]);}
// Each saved draft stroke leaves the draft, so a failed save keeps only the unsaved rest.
async function commit(bodies){if(scope.busy||!ready||conflicted||forbidden)return false;error();const decidedOrdinal=frameOrdinal(workspace,frame.index);let saved=0,ok=false;try{ok=await scope.run(async()=>{try{for(const body of bodies){review=await request(`/api/masks/${frame.index}`,{version:review.version,...body});saved++;if(body.action==='paint')draft.shift();}workspace.pixel_counts[frame.pixel_status]--;workspace.pixel_counts[review.status]++;frame.pixel_status=review.status;const selectedClass=pixelClass.value,decided=bodies.length===1&&['approve','exclude'].includes(bodies[0].action),decision=decided?`사진 ${decidedOrdinal} ${states[review.status]}`:'',pending=decided&&['all','pending'].includes($('pixel-filter').value)&&await nextPending(frame.index),next=['all','pending'].includes($('pixel-filter').value)&&pending;if(next){await select(next.index);canvas.scrollIntoView({block:'center'});canvas.focus({preventScroll:true});if(pixelClass.has(selectedClass))pixelClass.value=selectedClass;$('pixel-decision').textContent=`${decision} · 다음 검수 대기 사진 ${frameOrdinal(workspace,next.index)}을 열었습니다.`;$('pixel-decision').hidden=false;return true;}if($('pixel-filter').value!=='all'&&review.status!==$('pixel-filter').value){$('pixel-filter').value='all';url();workspace={...workspace,...await request(workspacePage('pixel','all',{around:frame.index}))};}await select(frame.index);pixelClass.value=selectedClass;if(decided){$('pixel-decision').textContent=pending?decision:`${decision} · 편집 가능한 검수 대기 사진을 모두 처리했습니다.`;$('pixel-decision').hidden=false;}return true;}
 catch(value){const message=panelError(value,'서버 연결 문제로 저장하지 못했습니다.'),rest=draft;if(saved){await select(frame.index);draft=rest;paint();}error(message);return false;}});}finally{enable();if(saved&&bodies.some(body=>body.action==='fill_unknown')&&ready&&unknownPixels===0&&!$('pixel-approve').disabled){$('pixel-approve').scrollIntoView({block:'center'});$('pixel-approve').focus({preventScroll:true});}}return ok;}
function connectAI(){
 const index=frame.index,ticket=serial;
 showAI('pixel',index,request,()=>frame?.index===index?{version:review.version,blocked:!ready||scope.busy||loading||conflicted||forbidden||!!stroke||draft.length>0||seeds.length>0||polygon.length>0,
  autoDraft:workspace?.workspace_kind!=='evaluation'&&frame.status!=='excluded'&&review.status==='pending'&&unknownPixels===totalPixels&&totalPixels>0&&!review.draft_candidates?.some(row=>row.origin!=='v12_pixel_mask_candidate'),
  autoKey:`${workspace?.workspace_id||''}:${index}:${frame.source.image_sha256}:${review.classes?.sha256||''}`,
  image_sha256:frame.source.image_sha256,classes_sha256:review.classes?.sha256}:null,async(changes=null)=>{
  const matching=()=>ticket===serial&&frame?.index===index;
  if(!matching())return false;
  const checks=changes?.some(job=>job.action==='mask_check');
  if(checks)await loadVlm(index,ticket);
  if(changes?.every(job=>job.action==='mask_check'))return matching();
  const version=review?.version;
  const clean=()=>matching()&&review?.version===version&&ready&&!scope.busy&&!loading&&!conflicted&&!forbidden&&!stroke&&!draft.length&&!seeds.length&&!polygon.length;
  if(!clean())return false;
  const latest=await request(`/api/masks/${index}`);if(!clean())return false;
  if(latest.version!==version)throw new Error('검수 버전이 바뀌었습니다. 새로고침 후 확인하세요.');
  if(!checks)await loadVlm(index,ticket);
  if(!clean())return false;
  review.draft_candidates=latest.draft_candidates;candidateOptions();
  const generated=changes?.find(job=>job.action==='pixel_draft'&&job.state==='succeeded'&&job.result?.added_pixels!==0&&latest.draft_candidates.some(row=>row.sha256===job.result?.candidate_sha256));
  if(generated)candidates.value=generated.result.candidate_sha256;
  if(generated||changes===null)await previewCandidate(clean);
  return clean();
 });
}
function clearReviewContext(){resetVersions();resetAI();resetHistory('현재 사진의 검수 정보를 확인할 수 없습니다.');aiPanel.hidden=true;$('pixel-ai-summary').hidden=true;$('pixel-vlm-state').textContent='';$('pixel-vlm-note').textContent='';$('pixel-vlm-details').textContent='';}
function filter(){url();return load({offset:0}).catch(loadError);}
function showEmptyFilter(){const rows=visible();if(rows.length)select(rows.some(row=>row.index===frame?.index)?frame.index:rows[0].index);else{++serial;clearReviewContext();ready=false;frame=null;review=null;error();$('pixel-title').textContent='픽셀 검수';$('pixel-status').setAttribute('state','empty');$('pixel-status').textContent=Object.values(workspace.counts).some(Boolean)?`${$('pixel-filter').selectedOptions[0].textContent} 0장 · 필터 결과가 없습니다.`:'등록된 사진 0장 · 자료 등록에서 원본을 추가하세요.';options();url();enable();}}
$('pixel-filter').onchange=filter;$('pixel-all').onclick=()=>{if(!Object.values(workspace.counts).some(Boolean)){location.assign('/catalog');return;}$('pixel-filter').value='all';filter();};
for(const [id,step] of [['pixel-prev',-1],['pixel-next',1]])$(id).onclick=()=>{const rows=visible(),pos=rows.findIndex(row=>row.index===frame.index);if(rows[pos+step])select(rows[pos+step].index);else load({offset:workspace.page.offset+step*workspace.page.limit,last:step<0}).catch(loadError);};
$('pixel-next-pending').onclick=async()=>{if($('pixel-next-pending').disabled)return;const previous=$('pixel-filter').value,ticket=serial;error();await scope.run(async()=>{try{$('pixel-filter').value='pending';const next=await nextPending(frame.index);if(next)await select(next.index);else if(ticket===serial)$('pixel-filter').value=previous;}catch(e){if(ticket===serial){$('pixel-filter').value=previous;error(e.message,false);}}});enable();if(ready)canvas.focus({preventScroll:true});};
$('pixel-fill').onclick=async()=>{if(await confirmIrreversible({message:'현재 마스크 전체를 선택 클래스로 바꾸고 재검수하시겠습니까?',action:'전체 채우기',opener:$('pixel-fill')}))mutate('fill',{label:Number(pixelClass.value)});};
$('pixel-fill-unknown').onclick=async()=>{if(await confirmIrreversible({message:'남은 미검수 영역만 배경으로 채웁니다. 기존 라벨은 유지됩니다. 놓친 선과 물체가 없는지 사진 전체를 확인한 뒤 별도로 승인하세요. 계속할까요?',action:'배경으로 채우기',opener:$('pixel-fill-unknown')}))mutate('fill_unknown');};
pixelFillClass.onclick=async()=>{const label=Number(pixelClass.value),name=review.classes?.classes.find(row=>String(row.index)===pixelClass.value)?.display||review.classes?.classes.find(row=>String(row.index)===pixelClass.value)?.name;if(!pixelFillClass.disabled&&await confirmIrreversible({message:`남은 미검수 영역만 ${name} 클래스로 채웁니다. 기존 라벨은 유지되고 승인은 별도입니다. 계속할까요?`,action:'클래스로 채우기',opener:pixelFillClass}))mutate('fill_unknown',{label});};

$('pixel-undo').onclick=()=>{if(polygon.length){polygon.pop();paint();enable();}else if(seeds.length){seeds.pop();resetSam(true);refreshSample();}else if(draft.length){draft.pop();paint();enable();}else mutate('undo');};
$('pixel-save').onclick=()=>{if($('pixel-save').disabled)return;const bodies=[];if(candidateDraftReady())bodies.push({action:'merge_draft',draft_sha256:candidatePreviewDigest});bodies.push(...draft.map(({label,radius,points})=>({action:'paint',label,radius,points})));return commit(bodies);};
$('pixel-discard').onclick=()=>{draft=[];resetCandidatePreview();$('pixel-candidate-status').textContent='저장된 마스크 표시 · AI 초안 미적용';paint();enable();};
addEventListener('beforeunload',event=>{if(draft.length||stroke||seeds.length||polygon.length)event.preventDefault();});
$('pixel-approve').onclick=async()=>{if($('pixel-approve').disabled||scope.busy||!ready||conflicted||forbidden)return;if(unknownPixels>0&&workspace.workspace_kind!=='evaluation'&&!await mutate('fill_unknown'))return;await mutate('approve',{complete_frame_review:true,background_reviewed:true,unknown_pixels_reviewed:$('pixel-unknown')?.checked===true});};$('pixel-exclude').onclick=()=>mutate('exclude');$('pixel-reopen').onclick=()=>mutate('reopen');
$('pixel-apply-candidate').onclick=async()=>{if(workspace?.workspace_kind==='evaluation')return;if(await confirmIrreversible({message:'새 초안을 적용하면 현재 마스크가 대체되고 픽셀 승인이 해제됩니다. 계속할까요?',action:'초안 적용',opener:$('pixel-apply-candidate')})&&workspace?.workspace_kind!=='evaluation')mutate('apply_draft',{draft_sha256:candidates.value});};
mergeCandidate.onclick=async()=>{if(workspace?.workspace_kind==='evaluation')return;if(await confirmIrreversible({message:'사람이 칠한 픽셀은 그대로 두고 255 영역 중 초안에 라벨이 있는 픽셀만 채웁니다. 적용 후 전체 사진을 다시 확인하세요.',action:'초안 병합',opener:mergeCandidate})&&workspace?.workspace_kind!=='evaluation')mutate('merge_draft',{draft_sha256:candidates.value});};

$('pixel-preview-candidate').onclick=()=>{if(candidateVisible||candidateLoading){resetCandidatePreview();$('pixel-candidate-status').textContent='저장된 마스크 표시 · AI 초안 미적용';paint();enable();}else previewCandidate();};
$('pixel-opacity').oninput=paint;$('pixel-show-unknown').onchange=paint;$('pixel-mask-visible').onchange=paint;
$('pixel-view-original').onclick=()=>setView(false);$('pixel-view-detail').onclick=()=>setView(true);
function clearSamples(){++previewSerial;resetSam(true);seeds=[];sampleImage=null;samplePixels=0;sampleTolerance=null;previewing=false;if(ready){paint();enable();}}
async function refreshSample(){
 const ticket=++previewSerial;sampleImage=null;samplePixels=0;sampleTolerance=null;
 if(!seeds.length||samMode()&&!selectionDigest){previewing=false;paint();enable();return;}
 previewing=true;paint();enable();
 try{const result=await request(`/api/mask-preview/${frame.index}`,{version:review.version,label:Number(pixelClass.value),seeds,preserve_existing:preserveExisting(),tolerance:samMode()?0:$('pixel-tolerance-mode').value==='auto'?'auto':Number($('pixel-tolerance').value),...(samMode()?{selection_sha256:selectionDigest}:{})});
  const preview=await image(`data:image/png;base64,${result.mask_png}`);if(ticket!==previewSerial)return;
  sampleImage=preview;samplePixels=result.selected_pixels;sampleTolerance=result.tolerance;error();
 }catch(value){if(ticket===previewSerial)error(panelError(value,''));}
 finally{if(ticket===previewSerial){previewing=false;paint();enable();}}
}
$('pixel-sample-apply').onclick=()=>{if(tool==='polygon'){if(polygon.length>=3)mutate('polygon',{label:Number(pixelClass.value),preserve_existing:preserveExisting(),points:polygon.map(point=>[...point])});return;}if(!sampleImage||previewing||!seeds.length)return;mutate('sample',{label:Number(pixelClass.value),preserve_existing:preserveExisting(),seeds:seeds.map(point=>[...point]),tolerance:sampleTolerance,...(samMode()?{selection_sha256:selectionDigest}:{})});};
$('pixel-sample-clear').onclick=()=>{if(tool==='polygon'){polygon=[];paint();enable();}else clearSamples();};
function classChanged(){resetSam(true);if(Number(pixelClass.value)===255)$('pixel-selection-method').value='color';if(seeds.length){if(pixelClass.value)refreshSample();else clearSamples();}if(polygon.length)paint();enable();}
for(const id of ['pixel-tolerance-mode','pixel-preserve'])$(id).addEventListener('change',()=>{
 if(seeds.length){if(pixelClass.value)refreshSample();else clearSamples();}if(polygon.length)paint();enable();
});
$('pixel-tolerance').addEventListener('input',()=>{if(seeds.length&&$('pixel-tolerance-mode').value==='manual')refreshSample();});
function point(event){const box=$('pixel-canvas').getBoundingClientRect();return [Math.max(0,Math.min(frame.source.width-1,Math.floor((event.clientX-box.left)*frame.source.width/box.width))),Math.max(0,Math.min(frame.source.height-1,Math.floor((event.clientY-box.top)*frame.source.height/box.height)))];}
// Brush size preview: a circle follows the pointer at the current radius in screen scale.
const brush=$('pixel-brush');
function brushAt(event){
  if(!ready||scope.busy||conflicted||forbidden||tool!=='brush'||!review?.classes||!pixelClass.value||frame?.status==='excluded'||review?.status==='excluded'){brush.hidden=true;return;}
  const box=canvas.getBoundingClientRect(),stage=brush.parentElement.getBoundingClientRect();
  const size=2*Number($('pixel-radius').value)*box.width/frame.source.width;
  if(!Number.isFinite(size)||size<3){brush.hidden=true;return;}
  setGeometry(brush,{size,left:event.clientX-stage.left+brush.parentElement.scrollLeft,top:event.clientY-stage.top+brush.parentElement.scrollTop});
  brush.hidden=false;
}
const canvas=$('pixel-canvas');
function canMark(){return ready&&!scope.busy&&!conflicted&&!forbidden&&review?.classes&&pixelClass.value&&frame.status!=='excluded'&&review.status!=='excluded';}
function selectPoint(position){
 if(tool==='sample'){const limit=samMode()?16:32;if(seeds.length>=limit){error(`선택 점은 최대 ${limit}개입니다.`);return;}resetSam(true);seeds.push(position);refreshSample();}
 else {if(polygon.length>=128){error('영역 꼭짓점은 최대 128개입니다.');return;}polygon.push(position);paint();enable();}
}
// A null id is a keyboard stroke and must never request pointer capture.
function beginStroke(id,position){
 const radius=Number($('pixel-radius').value);if(!Number.isInteger(radius)||radius<0||radius>128){error('브러시 반지름은 0~128 사이 정수입니다.');return;}
 stroke={id,points:[position],radius,label:Number(pixelClass.value)};if(id!==null)canvas.setPointerCapture(id);enable();paint();
}
function finishStroke(id){if(!stroke||stroke.id!==id)return;const finished=stroke;stroke=null;if(id!==null&&canvas.hasPointerCapture(id))canvas.releasePointerCapture(id);draft.push(finished);paint();enable();}
canvas.onpointerdown=event=>{if(!canMark()||stroke||event.button!==0)return;keyCursor=null;keyboardPosition.hidden=true;if(tool==='brush')beginStroke(event.pointerId,point(event));else selectPoint(point(event));event.preventDefault();};
canvas.onpointermove=event=>{if(!stroke){brushAt(event);return;}brush.hidden=true;if(stroke.id!==event.pointerId||stroke.points.length>=2048)return;stroke.points.push(point(event));paint();};
canvas.onpointerup=event=>finishStroke(event.pointerId);
function cancel(){if(!stroke)return;const id=stroke.id;stroke=null;if(id!==null&&canvas.hasPointerCapture(id))canvas.releasePointerCapture(id);paint();enable();}canvas.onpointercancel=cancel;canvas.onlostpointercapture=cancel;canvas.addEventListener('pointerleave',()=>{brush.hidden=true;});
canvas.addEventListener('keydown',event=>{
 if(event.isComposing||event.ctrlKey||event.metaKey||!ready||scope.busy||loading||conflicted||forbidden)return;
 const direction={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];
 if(!(event.altKey&&direction)&&event.code!=='Space')return;
 event.preventDefault();event.stopPropagation();
 const stage=canvas.parentElement;
 if(stage.classList.contains('review-pan')){if(direction)stage.scrollBy(direction[0]*16*(event.shiftKey?10:1),direction[1]*16*(event.shiftKey?10:1));return;}
 if(stroke&&stroke.id!==null)return;
 keyCursor??=[Math.floor(frame.source.width/2),Math.floor(frame.source.height/2)];
 if(direction){const step=event.shiftKey?10:1;keyCursor=[Math.max(0,Math.min(frame.source.width-1,keyCursor[0]+direction[0]*step)),Math.max(0,Math.min(frame.source.height-1,keyCursor[1]+direction[1]*step))];if(stroke?.id===null&&stroke.points.length<2048)stroke.points.push([...keyCursor]);}
 else if(!event.repeat&&canMark()){if(tool==='brush'){if(!stroke)beginStroke(null,[...keyCursor]);}else selectPoint([...keyCursor]);}
 keyboardPosition.hidden=false;keyboardPosition.textContent=`키보드 좌표 ${keyCursor.join(', ')} · 원본 ${frame.source.width} × ${frame.source.height} · Alt+방향키 이동 · Space 표시`;
 const box=canvas.getBoundingClientRect(),view=stage.getBoundingClientRect(),x=box.left+(keyCursor[0]+.5)*box.width/frame.source.width,y=box.top+(keyCursor[1]+.5)*box.height/frame.source.height;
 if(x<view.left||x>view.right)stage.scrollLeft+=x-(x<view.left?view.left:view.right);
 if(y<view.top||y>view.bottom)stage.scrollTop+=y-(y<view.top?view.top:view.bottom);
 paint();
});
canvas.addEventListener('keyup',event=>{if(event.code==='Space'&&stroke?.id===null){event.preventDefault();finishStroke(null);}});
canvas.addEventListener('blur',()=>{if(stroke?.id===null)cancel();});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&stroke){event.preventDefault();cancel();}else if(event.key==='Escape'&&polygon.length){event.preventDefault();polygon=[];paint();enable();}else if(event.key==='Escape'&&seeds.length){event.preventDefault();clearSamples();}
   if(event.code==='KeyZ'&&(event.ctrlKey||event.metaKey)&&!event.shiftKey&&!event.isComposing&&!event.target?.matches?.('input, textarea, select, [contenteditable]')&&!event.repeat&&!$('pixel-undo').disabled){event.preventDefault();$('pixel-undo').click();return;}
  // Arrow keys move between photos; number fields keep their native stepping.
  if((event.key==='ArrowLeft'||event.key==='ArrowRight')&&!['INPUT','SELECT','TEXTAREA'].includes(event.target?.tagName)){
    const button=$(event.key==='ArrowLeft'?'pixel-prev':'pixel-next');
    if(button&&!button.disabled){event.preventDefault();button.click();}
  }
  // Number keys pick the n-th class, A approves, X excludes (D-485); approval checks stay manual (D-461).
  // Physical keys (event.code) so a Korean IME layout still works; checkboxes keep working.
  if(event.target?.matches?.('input:not([type=checkbox]):not([type=radio]), textarea, select')||event.isComposing||event.ctrlKey||event.metaKey||event.altKey||event.repeat||scope.busy||stroke)return;
  if(event.key==='?'||event.code==='Slash'&&event.shiftKey){event.preventDefault();location.hash=location.hash==='#pixel-keys'?'#pixel-review':'#pixel-keys';return;}
  const digit=/^(?:Digit|Numpad)([1-9])$/.exec(event.code||''),key=digit?digit[1]:{KeyA:'a',KeyB:'b',KeyC:'c',KeyM:'m',KeyN:'n',KeyP:'p',KeyT:'t',KeyV:'v',KeyX:'x'}[event.code]||(/^[1-9abcmnptvx]$/i.test(event.key)?event.key.toLowerCase():null);
  if(key==='v'&&ready){event.preventDefault();setView(!detailView);return;}
  if(key==='m'&&ready){event.preventDefault();$('pixel-mask-visible').click();return;}
  if(key==='t'&&!polygon.length&&!$('pixel-flood').disabled){event.preventDefault();$(tool==='brush'?'pixel-flood':'pixel-brush-tool').click();return;}
  if(key==='p'&&!$('pixel-polygon-tool').disabled){event.preventDefault();$('pixel-polygon-tool').click();return;}
  if(event.key==='Backspace'&&tool==='polygon'&&polygon.length){event.preventDefault();polygon.pop();paint();enable();return;}
  if((event.code==='BracketLeft'||event.code==='BracketRight')&&tool==='brush'&&!$('pixel-radius').disabled){event.preventDefault();$('pixel-radius').value=String(Math.max(0,Math.min(128,Number($('pixel-radius').value)+(event.code==='BracketRight'?1:-1))));enable();return;}
  if(event.key==='Enter'&&event.target===canvas&&!$('pixel-sample-apply').disabled){event.preventDefault();$('pixel-sample-apply').click();return;}
  if(key==='n'&&!$('pixel-next-pending').disabled){event.preventDefault();$('pixel-next-pending').click();return;}
  const option=/^[1-9]$/.test(key)&&review?.classes?String(review.classes.classes[Number(key)-1]?.index??''):'';
  if(option&&!pixelClass.disabled){event.preventDefault();pixelClass.value=option;classChanged();}
  // X only excludes a pending mask; other decisions use the explicit reopen action.
  const decision=key==='a'?'pixel-approve':key==='x'&&review?.status==='pending'?'pixel-exclude':null;
  if(decision&&!$(decision).disabled){event.preventDefault();$(decision).click();}
  });
document.addEventListener('rosy:theme',()=>{if(review){legend();paint();}});
async function load(pageOptions={}){clearReviewContext();const index=frame?.index;loading=true;ready=false;++serial;workspace=undefined;error();$('pixel-title').textContent='사진 불러오는 중';$('pixel-status').setAttribute('state','pending');$('pixel-status').textContent='검수 내용을 확인하는 중 · 현재 사진과 결정 내용을 불러오고 있습니다.';$('pixel-filter').parentElement.hidden=true;for(const id of ['pixel-prev','pixel-next','pixel-next-pending'])$(id).hidden=true;$('pixel-content').hidden=true;$('pixel-empty').hidden=true;$('pixel-all').hidden=true;$('pixel-export-result').textContent='';enable();const started=performance.now();const timer=setInterval(()=>{const seconds=Math.floor((performance.now()-started)/1000);if(loading&&seconds>=3)$('pixel-status').textContent=`서버 응답 대기 ${seconds}초 · 현재 사진과 결정 내용을 확인하고 있습니다.`;},1000);try{workspace=await request(workspacePage('pixel',new URLSearchParams(location.search).get('filter')||'all',{around:pageOptions.offset===undefined?(index??new URLSearchParams(location.search).get('frame')):undefined,...Object.fromEntries(Object.entries(pageOptions).filter(([key])=>key!=='last'))}));}finally{clearInterval(timer);}modeBadge.textContent=workspace.workspace_kind==='evaluation'?'고정 평가 · 학습에서 제외':'학습 후보 · 승인 후 수용 확인';modeBadge.setAttribute('state',workspace.workspace_kind==='evaluation'?'warning':'pending');if(workspace.workspace_kind==='evaluation'&&!$('pixel-unknown'))evaluationControls();loading=false;conflicted=false;forbidden=false;const params=new URLSearchParams(location.search);$('pixel-filter').value=params.get('filter')||'all';if(!$('pixel-filter').value)$('pixel-filter').value='all';options();const rows=visible(),wanted=pageOptions.last?rows.at(-1)?.index:index??Number(params.get('frame'));if(rows.length)await select(rows.some(row=>row.index===wanted)?wanted:rows[0].index);else showEmptyFilter();}
function loadError(e){
 loading=false;workspace=undefined;frame=null;review=null;ready=false;$('pixel-title').textContent='픽셀 검수';
 const reason=forbidden?'검수 권한이 없습니다. 이 작업대의 접근 권한을 확인한 뒤 다시 불러오세요.':commonDown()?'불러오지 못함':e?.status>=500?'검수 서비스를 사용할 수 없습니다. 서비스가 복구되면 다시 불러오세요.':'검수 내용을 불러오지 못했습니다. 연결을 확인하고 다시 시도하세요.';
 error(reason);$('pixel-status').setAttribute('state','error');$('pixel-status').textContent=reason;
 $('pixel-filter').parentElement.hidden=true;for(const id of ['pixel-prev','pixel-next','pixel-next-pending'])$(id).hidden=true;
 $('pixel-content').hidden=true;$('pixel-empty').hidden=false;$('pixel-empty').querySelector('h3').textContent=commonDown()?'불러오지 못함':'작업 내용을 확인할 수 없습니다';$('pixel-all').hidden=true;enable();
}
$('pixel-reload').onclick=()=>load().catch(loadError);
$('pixel-export').onclick=async()=>{if(scope.busy||conflicted||forbidden)return;error();await scope.run(async()=>{try{const value=await request('/api/prepare',{});$('pixel-export-result').textContent=`준비 시점 결과 · 객체 승인 ${value.exported_frames}장 · 픽셀 승인 ${value.pixel_approved_frames}장 준비. 이후 결정이 바뀌면 다시 준비하세요. 최신 결정 대조와 학습 수용은 별도입니다.`;$('pixel-export-details').textContent=JSON.stringify(value,null,2);}catch(value){error(panelError(value,''));$('pixel-export-result').after($('pixel-reload'));$('pixel-export-result').textContent=`자료 준비 실패 · ${panelError(value,'서버 연결 문제')}`;$('pixel-export-result').scrollIntoView({block:'center'});}});enable();};
enable();load().catch(loadError);

for(const node of document.querySelectorAll('.pixel-review-column > :not(.review-tool-nav,[data-review-tool])')){
 const view=document.createElement('div');view.dataset.reviewTool='review';node.before(view);view.append(node);
}
function showReviewTool(focus=false){
  const requested=document.getElementById(location.hash.slice(1));
  const tool=requested?.closest('[data-review-tool]')?.dataset.reviewTool||'review';
  for(const section of document.querySelectorAll('[data-review-tool]'))section.hidden=section.dataset.reviewTool!==tool;
  document.querySelector('.pixel-decision-panel').hidden=tool==='preparation';// one primary action per screen: the export is the primary there
  const links=[...document.querySelectorAll('.review-tool-nav a')];
  const link=links.find(node=>node.hash===location.hash)||links.find(node=>document.getElementById(node.hash.slice(1))?.closest('[data-review-tool]')?.dataset.reviewTool===tool)||links[0];
  for(const node of links){if(node===link)node.setAttribute('aria-current','location');else node.removeAttribute('aria-current');}
  document.getElementById('learning-tool-path').textContent=' / '+link.textContent;
  if(focus){const target=requested||document.getElementById('pixel-canvas');if(target){if(target.tabIndex<0)target.tabIndex=-1;target.focus({preventScroll:true});target.scrollIntoView({block:'nearest'});}}
}
window.addEventListener('hashchange',()=>showReviewTool(true));
document.addEventListener('review-tool-open',event=>{const section=event.detail.closest('[data-review-tool]');if(section){history.pushState(null,'','#'+(section.id||section.querySelector('[id]')?.id));showReviewTool();}});
document.querySelector('.review-tool-nav').addEventListener('click',event=>{const link=event.target.closest('a');if(link?.hash===location.hash)showReviewTool(true);});
showReviewTool();
