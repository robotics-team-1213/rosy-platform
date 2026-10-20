// STL is one input adapter; registration retains edited geometry and resets site review.
const clone = value => JSON.parse(JSON.stringify(value));

export function copyMapTemplate(map, mapId = crypto.randomUUID()) {
  if (!map) throw new Error('복사할 지도를 먼저 고르세요');
  const next = {...clone(map), map_id: mapId};
  if (next.survey) next.survey = {...next.survey, reviewed: false, review_note: ''};
  for (const edge of next.edges) if (edge.evidence) edge.evidence.status = 'observed';
  return next;
}

export function createDrawingImport({request, map, replaceDraft, confirmDiscard}) {
  let asset = null, generation = 0, registrationGeneration = 0, upload = null, registration = null;
  const cancelRegistration = () => { registrationGeneration++; registration?.abort(); };
  const cancel = () => { generation++; upload?.abort(); cancelRegistration(); };
  return {
    cancel, cancelRegistration, ready: () => asset !== null,
    async load(file) {
      cancel(); asset = null;
      if (!file) return null;
      if (!file.size || file.size > 16 * 1024 * 1024) throw new Error('STL 파일은 0보다 크고 16 MiB 이하여야 합니다');
      const current = generation;
      upload = new AbortController();
      const result = await request('/api/fleet/site-map/drawings', {method: 'POST', body: file,
        headers: {'Content-Type': 'application/octet-stream'}, signal: upload.signal, timeoutMs: 65000});
      if (current !== generation) return null;
      asset = result;
      return result;
    },
    async register(transform, reference) {
      if (!asset) throw new Error('STL 원본을 먼저 확인하세요');
      if (!(Number.isFinite(reference.measured_distance_m) && reference.measured_distance_m > 0
          && reference.measured_distance_m <= 2000) || !reference.description?.trim()
          || reference.description.length > 1000) throw new Error('실측 거리와 좌표 기준 설명을 확인하세요');
      if (![...transform.source_origin, ...transform.map_origin_m, transform.heading_rad, transform.scale]
          .every(Number.isFinite) || transform.scale <= 0) throw new Error('원점·방향·축척을 확인하세요');
      cancelRegistration();
      const current = generation, attempt = registrationGeneration, before = map(), source = asset;
      if (!await confirmDiscard()) return null;
      if (current !== generation || attempt !== registrationGeneration || map() !== before)
        throw new Error('초안이 바뀌었습니다. 도면 맞춤을 다시 확인하세요');
      registration = new AbortController();
      const result = await request(`/api/fleet/site-map/drawings/${source.asset_sha256}/projections`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(transform),
        signal: registration.signal, timeoutMs: 10000});
      if (current !== generation || attempt !== registrationGeneration || map() !== before)
        throw new Error('초안이 바뀌었습니다. 도면 맞춤을 다시 확인하세요');
      const next = before ? clone(before) : {schema: 'rosy.site_map/1', places: [], edges: []};
      if (next.drawing?.projection_sha256 !== result.projection_sha256) next.map_id = crypto.randomUUID();
      next.drawing = {asset_sha256: result.asset_sha256, projection_sha256: result.projection_sha256};
      next.survey = {revision: result.projection_sha256, origin: [...transform.map_origin_m],
        heading_rad: transform.heading_rad, scale_source: 'measured',
        measured_distance_m: reference.measured_distance_m, description: reference.description.trim(),
        reviewed: false, review_note: ''};
      for (const edge of next.edges) edge.evidence = {...edge.evidence, source: edge.evidence?.source || 'operator',
        status: 'observed', reference_revision: result.projection_sha256, note: edge.evidence?.note || ''};
      replaceDraft(next, result);
      return result;
    },
  };
}
