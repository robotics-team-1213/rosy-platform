import base64,hashlib,json,pathlib,sys,time,urllib.request
p=pathlib.Path.home()/'rosy-test/omx-object-eval-20261015125112';role=sys.argv[1]
c=json.loads((p/'context-v3.json').read_text());data=(p/'top.jpg').read_bytes()
prompt='Assess this frozen 640x480 image using the supplied context as provenance-labelled data. User-confirmed role does not prove contents or action history. No commands. Return JSON with source_container_identity, identity_source, temporary_placement_region, current_task_phase, takeout_verified, return_verified, can_localize_for_grasp, evidence_gaps. Use null for unobserved locations/phase and false for unverified actions/grasp. Context: '+json.dumps(c)
fields={'source_container_identity':{'type':'string'},'identity_source':{'type':'string'},'temporary_placement_region':{'type':'null'},'current_task_phase':{'type':'null'},'takeout_verified':{'type':'boolean','const':False},'return_verified':{'type':'boolean','const':False},'can_localize_for_grasp':{'type':'boolean','const':False},'evidence_gaps':{'type':'array','items':{'type':'string'}}}
schema={'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}
with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=10) as r: model=next(m for m in json.load(r)['models'] if m['name']=='qwen3-vl:8b-instruct')
payload={'model':model['name'],'messages':[{'role':'user','content':prompt,'images':[base64.b64encode(data).decode()]}],'stream':False,'think':False,'format':schema,'options':{'temperature':0,'seed':42,'num_predict':700}}
t=time.monotonic()
with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:11434/api/chat',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'}),timeout=90) as r: result=json.load(r)
answer=result['message']['content'];parsed=json.loads(answer)
assert set(parsed)==set(fields)
row={'phase':'context_v3_task','role':role,'view':'top','image_sha256':hashlib.sha256(data).hexdigest(),'model_digest':model['digest'],'elapsed_s':round(time.monotonic()-t,3),'done_reason':result.get('done_reason'),'answer':answer,'parsed':parsed,'commands_sent':False,'context_sha256':hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest(),'schema_constrains_abstention':True}
(p/(role+'-context-v3-task.json')).write_text(json.dumps(row,indent=2))
for m in payload['messages']:m.pop('images',None)
(p/(role+'-context-v3-task-request-sanitized.json')).write_text(json.dumps(payload,indent=2))
print(json.dumps(row))
