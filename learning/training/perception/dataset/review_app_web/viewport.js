import {actionIcon} from '/common/ui.js';

// The canvas bitmap stays at source resolution. Only its displayed size changes.
export function reviewViewport(stage, canvas, viewBar, canChange=()=>true) {
  const controls=document.createElement('div');
  controls.className='review-viewport-controls';
  controls.setAttribute('role','group');
  controls.setAttribute('aria-label','사진 확대와 이동');
  const buttons=[['minus','축소 · -'],['fit','화면 맞춤 · 0'],['plus','확대 · +'],['hand','이동 · H']].map(([icon,label])=>{
    const button=document.createElement('ui-button');
    button.setAttribute('kind','quiet');
    if(icon==='hand')button.setAttribute('kind','toggle');
    button.setAttribute('aria-label',label);
    button.title=label;
    button.textContent=label.split(' · ')[0];
    actionIcon(button,icon);
    controls.append(button);
    return button;
  });
  const [out,fit,zoomIn,hand]=buttons;
  const level=document.createElement('output');
  level.className='review-zoom-level';
  level.setAttribute('aria-label','사진 확대율');
  controls.insertBefore(level,hand);
  viewBar.append(controls);
  const steps=[1,1.5,2,3,4];
  let index=0,pan=null;
  function size(){
    const style=getComputedStyle(stage);
    const padding=parseFloat(style.paddingLeft)+parseFloat(style.paddingRight);
    const base=Math.min(768,Math.max(1,stage.clientWidth-padding));
    const oldWidth=canvas.getBoundingClientRect().width||base;
    const centerX=(stage.scrollLeft+stage.clientWidth/2)/oldWidth;
    const centerY=(stage.scrollTop+stage.clientHeight/2)/(canvas.getBoundingClientRect().height||1);
    canvas.style.width=`${base*steps[index]}px`;
    canvas.style.maxWidth='none';
    stage.scrollLeft=centerX*canvas.getBoundingClientRect().width-stage.clientWidth/2;
    stage.scrollTop=centerY*canvas.getBoundingClientRect().height-stage.clientHeight/2;
    level.value=`${Math.round(steps[index]*100)}%`;
    out.disabled=index===0;
    zoomIn.disabled=index===steps.length-1;
  }
  out.onclick=()=>{if(canChange()&&index>0){index--;size();}};
  fit.onclick=()=>{if(canChange()){index=0;size();stage.scrollTo(0,0);}};
  zoomIn.onclick=()=>{if(canChange()&&index<steps.length-1){index++;size();}};
  hand.onclick=()=>{if(!canChange())return;const active=hand.getAttribute('aria-pressed')!=='true';hand.setAttribute('aria-pressed',String(active));stage.classList.toggle('review-pan',active);};
  function capture(event){
    if(!stage.classList.contains('review-pan')||(event.type==='pointerdown'&&event.button!==0))return;
    if(event.type==='pointerdown'&&event.button===0&&pan===null){pan={id:event.pointerId,x:event.clientX,y:event.clientY};canvas.setPointerCapture(event.pointerId);}
    else if(event.type==='pointermove'&&pan?.id===event.pointerId){stage.scrollLeft+=pan.x-event.clientX;stage.scrollTop+=pan.y-event.clientY;pan.x=event.clientX;pan.y=event.clientY;}
    else if(['pointerup','pointercancel','lostpointercapture'].includes(event.type)&&pan?.id===event.pointerId){pan=null;if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);}
    event.preventDefault();
    event.stopImmediatePropagation();
  }
  for(const type of ['pointerdown','pointermove','pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(type,capture,true);
  document.addEventListener('keydown',event=>{
    if(event.isComposing||event.ctrlKey||event.metaKey||event.altKey||event.repeat||event.target?.matches?.('input, select, textarea, [contenteditable]'))return;
    const key=event.code==='KeyH'?'h':event.key;
    const button=key==='h'?hand:key==='0'?fit:key==='+'||key==='='?zoomIn:key==='-'?out:null;
    if(button&&!button.disabled){event.preventDefault();button.click();}
  });
  new ResizeObserver(size).observe(stage);
  size();
}
