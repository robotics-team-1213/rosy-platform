import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {test} from 'node:test';

const source=await readFile(new URL('../../../learning/curation/perception/review_app_web/history.js',import.meta.url),'utf8');
const {reviewerSummary,feedbackPresentation}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('current approval and latest editor remain distinct; missing identity is not guessed',()=>{
  const value={pixel_status:'pending',events:{pixel:[{action:'paint',actor:'editor-a'},{action:'approve',actor:'reviewer-b'}]}};
  assert.match(reviewerSummary(value,'pixel'),/editor-a/);
  assert.match(reviewerSummary(value,'pixel'),/승인 전/);
  value.pixel_status='approved';value.events.pixel.unshift({action:'approve',actor:'reviewer-c'});
  assert.match(reviewerSummary(value,'pixel'),/현재 승인자: reviewer-c/);
  delete value.events.pixel[0].actor;
  assert.match(reviewerSummary(value,'pixel'),/현재 승인자: 미기록/);
});

test('only a current non-blocked no-concern opinion may use ready styling',()=>{
  const value={available:true,current:true,model:'test-model',model_digest:'revision-a',unknown_pixels:0,review_blocked:false,feedback:{verdict:'no_obvious_concern',issue:'none',note:'test note'}};
  assert.equal(feedbackPresentation(value).state,'ready');
  for(const verdict of ['concern','uncertain','abstain']){
    value.feedback.verdict=verdict;assert.equal(feedbackPresentation(value).state,'warning');
  }
  value.feedback.verdict='no_obvious_concern';value.current=false;
  assert.equal(feedbackPresentation(value).state,'warning');
  assert.match(feedbackPresentation(value).note,/revision-a/);
  assert.equal(feedbackPresentation({available:false}).state,'pending');
});

test('opinion status distinguishes requests, failures and stale jobs without hiding previous advice',()=>{
  for(const [state,title] of [['not_requested','요청 전'],['queued','대기'],['running','실행 중'],['failed','실패'],['cancelled','취소됨'],['stale','재확인 필요']]){
    const view=feedbackPresentation({available:false,check:{state,version:4,error:state==='failed'?'runtime unavailable':null}});
    assert.match(view.title,new RegExp(title));assert.match(view.note,/저장된 픽셀 v4 기준/);
    if(state==='failed'){assert.equal(view.state,'warning');assert.match(view.note,/runtime unavailable/);}
  }
  const old=feedbackPresentation({available:true,current:false,check:{state:'failed',version:5,error:'runtime unavailable'},
    model:'qwen',mask_version:4,feedback:{note:'previous visible advice'}});
  assert.match(old.note,/previous visible advice/);assert.match(old.note,/runtime unavailable/);assert.match(old.note,/픽셀 v4 기준/);
});
