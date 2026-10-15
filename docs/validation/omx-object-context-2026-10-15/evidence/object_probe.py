import argparse,base64,hashlib,json,pathlib,time,urllib.request
p=argparse.ArgumentParser();p.add_argument('--phase',choices=['baseline','structured','critique'],required=True);p.add_argument('--role',required=True);p.add_argument('--view',choices=['top','front'],required=True);a=p.parse_args()
root=pathlib.Path.home()/'rosy-test/omx-object-eval-20261015125112';data=(root/(a.view+'.jpg')).read_bytes();digest=hashlib.sha256(data).hexdigest()
assert data.startswith(b'\xff\xd8')
meta=json.loads((root/'frames.json').read_text());assert any(x['file']==a.view+'.jpg' and x['sha256']==digest for x in meta)
with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=10) as r: tags=json.load(r)
model=next(x for x in tags['models'] if x['name']=='qwen3-vl:8b-instruct')
base='This is one frozen OMX workbench '+a.view+' camera image, exactly 640 by 480 pixels. No robot commands are requested. '
baseline=base+'List the visible workbench objects, their counts, and whether this view is usable for identifying small parts. Do not infer physical coordinates or grasp readiness. Answer briefly in Korean.'
structured=base+'''Return JSON only, with keys targets,equipment,limitations,can_localize_for_grasp. targets is a list of {id,label,bbox_xyxy,visibility,uncertainties}. label must be one of brown_cylinder_like,white_round_region,red_strawberry_like,other_small_object. bbox_xyxy is four integer IMAGE PIXEL coordinates x1,y1,x2,y2 bounded by 0<=x1<x2<=640 and 0<=y1<y2<=480. List each visible loose target instance separately, including partially visible ones at image borders. visibility is fully_visible,border_clipped,or occluded. Exclude robot components and fixtures from targets; list them in equipment instead. Use appearance labels only: a white circle does not establish a sphere, and red fruit shape does not establish real fruit or material. Do not invent hidden objects or metric/depth/joint coordinates. If a view has no identifiable loose targets return targets=[]. uncertainties and limitations must explain unobservable attributes and visibility. can_localize_for_grasp must be false because calibration and depth are unverified. Korean text for descriptions.'''
messages=[{'role':'user','content':baseline if a.phase=='baseline' else structured,'images':[base64.b64encode(data).decode()]}]
if a.phase=='critique':
 own=json.loads((root/(a.role+'-structured-'+a.view+'.json')).read_text());other='ai_pc' if a.role=='model_pc' else 'model_pc';peer=json.loads((root/(other+'-structured-'+a.view+'.json')).read_text())
 messages += [{'role':'assistant','content':own['answer']},{'role':'user','content':'Review the same attached image again. A peer model produced the following candidate, not ground truth: '+peer['answer']+' An external visual reviewer also asks you to check separately complete and border-clipped cylinder-like regions; do not assume the white circular region is a ball, do not confuse robot hardware with loose objects, and do not infer objects through occlusion. Correct your own unsupported claims and boxes. Return JSON with keys targets,equipment,limitations,can_localize_for_grasp,corrections using the same pixel-coordinate schema; corrections explains what changed. Do not merely agree with the peer. No commands or control proposals.'}]
started=time.monotonic();payload={'model':model['name'],'stream':False,'think':False,'messages':messages,'options':{'temperature':0,'seed':42,'num_predict':1800 if a.phase!='baseline' else 600}}
req=urllib.request.Request('http://127.0.0.1:11434/api/chat',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=120) as r:answer=json.load(r)
row={'phase':a.phase,'role':a.role,'view':a.view,'image_sha256':digest,'model':model['name'],'model_digest':model['digest'],'prompt_sha256':hashlib.sha256(json.dumps(messages,sort_keys=True).encode()).hexdigest(),'elapsed_s':round(time.monotonic()-started,3),'answer':answer['message']['content'],'independent_of_peer':a.phase!='critique','commands_sent':False,'parsed':None,'parse_error':None}
if a.phase!='baseline':
 try:
  text=row['answer'].strip()
  if text.startswith('```'):text='\n'.join(text.splitlines()[1:-1])
  parsed=json.loads(text);assert isinstance(parsed,dict) and isinstance(parsed['targets'],list)
  assert parsed['can_localize_for_grasp'] is False
  ids=set()
  for obj in parsed['targets']:
   assert obj['id'] not in ids;ids.add(obj['id']);assert obj['label'] in ['brown_cylinder_like','white_round_region','red_strawberry_like','other_small_object']
   box=obj['bbox_xyxy'];assert len(box)==4 and all(type(v) is int for v in box)
   x1,y1,x2,y2=box;assert 0<=x1<x2<=640 and 0<=y1<y2<=480
   assert obj['visibility'] in ['fully_visible','border_clipped','occluded']
  row['parsed']=parsed
 except Exception as error:row['parse_error']=type(error).__name__+':'+str(error)
file=root/(a.role+'-'+a.phase+'-'+a.view+'.json');file.write_text(json.dumps(row,ensure_ascii=False,indent=2))
(root/(a.role+'-'+a.phase+'-'+a.view+'-request.json')).write_text(json.dumps(payload,ensure_ascii=False))
print(json.dumps(row,ensure_ascii=False),flush=True)