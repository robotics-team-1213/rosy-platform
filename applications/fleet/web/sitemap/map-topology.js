// Explicit Fleet graph edits; generic geometry never infers road connectivity.
import {splitPolyline, joinPolylines} from '/console/assets/geometry-edit.js';
import {appendSurveyElement} from '/console/assets/site-map-edit.js';

const copy = value => JSON.parse(JSON.stringify(value));
function road(map, id) {
  const edge = map?.edges.find(e => e.id === id);
  if (!map?.survey || !edge) throw new Error('조사 초안의 도로를 고르세요');
  const referenced = (map.turn_bans || []).some(b => b.from_edge === id || b.to_edge === id)
    || (map.facilities || []).some(f => (f.approaches || []).some(a => a.edge_id === id))
    || (map.crosswalks || []).some(c => c.lanes?.includes(id));
  if (referenced) throw new Error('다른 요소가 참조하는 도로입니다. 연결 관계를 먼저 검토하세요');
  return edge;
}
const observed = (edge, revision) => ({...edge.evidence, source: edge.evidence?.source || 'operator',
  status: 'observed', reference_revision: revision, note: edge.evidence?.note || ''});

export function splitRoad(map, edgeId, index, placeId, secondId) {
  const edge = road(map, edgeId);
  if (!Number.isInteger(index) || index <= 0 || index >= edge.polyline.length - 1)
    throw new Error('도로 내부의 꼭짓점을 고르세요');
  const at = edge.polyline[index], [first, second] = splitPolyline(edge.polyline, index - 1, at);
  let next = appendSurveyElement(map, {id: placeId, name: '분할점', kind: 'junction', geometry: [at]});
  next.edges = next.edges.map(e => e.id === edgeId ? {...e, to: placeId, polyline: first,
    evidence: observed(e, next.survey.revision)} : e);
  next = appendSurveyElement(next, {id: secondId, name: edge.name || '', kind: 'road', geometry: second,
    from: placeId, to: edge.to, width_m: edge.width_m, direction: edge.direction});
  next.edges[next.edges.length - 1] = {...copy(edge), id: secondId, from: placeId, polyline: second,
    evidence: observed(edge, next.survey.revision)};
  return next;
}

export function joinRoads(map, firstId, secondId) {
  const a = road(map, firstId), b = road(map, secondId);
  if (a.id === b.id || a.to !== b.from || a.from === b.to
      || map.edges.some(e => e.id !== a.id && e.id !== b.id && (e.from === a.to || e.to === a.to)))
    throw new Error('다른 갈림길이 없는 순서대로 연결된 도로 둘을 고르세요');
  for (const key of ['width_m', 'direction', 'speed_cap_mps', 'drive_mode', 'robot_kinds', 'name'])
    if (JSON.stringify(a[key]) !== JSON.stringify(b[key])) throw new Error('도로 속성을 먼저 같게 맞추세요');
  const polyline = joinPolylines(a.polyline, b.polyline);
  if (polyline.length > 32) throw new Error('연결한 도로는 꼭짓점 32개 이하여야 합니다');
  const next = copy(map);
  const note = [...new Set([a.evidence?.note, b.evidence?.note].filter(Boolean))].join('\n');
  const sources = a.evidence?.source === b.evidence?.source ? ''
    : `도로 연결: ${a.id} (${a.evidence?.source || 'operator'}), ${b.id} (${b.evidence?.source || 'operator'})`;
  const combined = [sources, note].filter(Boolean).join('\n');
  if (combined.length > 1000) throw new Error('연결할 도로의 근거를 1000자 이내로 검토하세요');
  next.edges = next.edges.filter(e => e.id !== b.id).map(e => e.id === a.id
    ? {...e, to: b.to, polyline, evidence: {...observed(e, next.survey.revision),
      ...(sources ? {source: 'operator'} : {}), note: combined}} : e);
  next.survey = {...next.survey, reviewed: false, review_note: ''};
  return next;
}
