"""Per run: did the bend hand its sighting on ('waiting' straight after B_SW), did the SW turn run
(turning) and finish (SW instruction left reacquiring for idle), where and why the trip ended."""
import glob, json, sys, os
out = []
for d in sorted(glob.glob(os.path.join(sys.argv[1], 'lap_*')) + glob.glob(os.path.join(sys.argv[1], 'arc_*'))):
    rows = [json.loads(l) for l in open(os.path.join(d, 'log.jsonl'))]
    seq, last = [], None
    for r in rows:
        j = r.get('junction') or {}
        k = (j.get('state'), j.get('place_id'))
        if k != last:
            seq.append((k, r.get('reason'), r.get('gt'))); last = k
    handoff = any(a[0] == ('waiting', None) and b[0][1] == 'SW' and i > 0 and seq[i-1][0][1] == 'B_SW'
                  for i, (a, b) in enumerate(zip(seq, seq[1:])))
    started = any(k == ('turning', 'SW') for k, _, _ in seq)
    done = any(a[0] == ('reacquiring', 'SW') and b[0][0] in ('idle', 'armed') and b[0][1] != 'SW'
               for a, b in zip(seq, seq[1:]))
    wrong = any(k == ('armed', 'SW') and (g or [0, 0, 0])[1] > -0.30 and (g or [0, 0, 0])[0] < -0.56
                for k, _, g in seq)
    trip = [json.loads(l) for l in open(os.path.join(d, 'trip.jsonl'))][-1]
    out.append(dict(run=os.path.basename(d).strip(), handoff=handoff, sw_started=started, sw_done=done,
                    state=trip.get('state'), reason=trip.get('reason'), segment=trip.get('segment_index'),
                    edge=trip.get('current_edge'), gt=[round(v, 3) for v in (trip.get('gt') or [])][:2]))
for o in out:
    print(json.dumps(o))
n = len(out)
print(json.dumps(dict(n=n, handoff=sum(o['handoff'] for o in out), sw_started=sum(o['sw_started'] for o in out),
                      sw_done=sum(o['sw_done'] for o in out), arrived=sum(o['state'] == 'arrived' for o in out))))
