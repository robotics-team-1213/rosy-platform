// STL is one input adapter; registration retains edited geometry and resets site review.
const clone = value => JSON.parse(JSON.stringify(value));

export function rasterMapPoint([u, v], t) {
  const x = (u - t.source_origin_px[0]) * t.meters_per_pixel;
  const y = (t.source_origin_px[1] - v) * t.meters_per_pixel;
  const c = Math.cos(t.heading_rad), s = Math.sin(t.heading_rad);
  const point = [t.map_origin_m[0] + c * x - s * y, t.map_origin_m[1] + s * x + c * y];
  if (!point.every(Number.isFinite)) throw new Error('유한한 도면 좌표가 필요합니다');
  return point;
}

export function copyMapTemplate(map, mapId = crypto.randomUUID()) {
  if (!map) throw new Error('복사할 지도를 먼저 고르세요');
  const next = {...clone(map), map_id: mapId};
  if (next.survey) next.survey = {...next.survey, reviewed: false, review_note: ''};
  for (const edge of [...next.edges, ...(next.facilities || [])]) if (edge.evidence) edge.evidence.status = 'observed';
  return next;
}

export function createDrawingImport({request, map, replaceDraft, confirmDiscard}) {
  let asset = null, generation = 0, registrationGeneration = 0, upload = null, registration = null;
  const cancelRegistration = () => { registrationGeneration++; registration?.abort(); };
  const cancel = () => { generation++; upload?.abort(); cancelRegistration(); };
  return {
    cancel, cancelRegistration, ready: () => asset !== null, source: () => asset,
    async load(file) {
      cancel(); asset = null;
      if (!file) return null;
      if (!file.size || file.size > 16 * 1024 * 1024) throw new Error('도면 파일은 0보다 크고 16 MiB 이하여야 합니다');
      const current = generation;
      upload = new AbortController();
      const result = await request('/api/fleet/site-map/drawings', {method: 'POST', body: file,
        headers: {'Content-Type': ['image/png', 'image/jpeg'].includes(file.type) ? file.type : 'application/octet-stream'},
        signal: upload.signal, timeoutMs: 65000});
      if (current !== generation) return null;
      asset = result;
      return result;
    },
    async register(transform, reference) {
      if (!asset) throw new Error('도면 원본을 먼저 확인하세요');
      if (!(Number.isFinite(reference.measured_distance_m) && reference.measured_distance_m > 0
          && reference.measured_distance_m <= 2000) || !reference.description?.trim()
          || reference.description.length > 1000) throw new Error('실측 거리와 좌표 기준 설명을 확인하세요');
      const scale = transform.meters_per_pixel ?? transform.scale;
      if (![...(transform.source_origin_px ?? transform.source_origin), ...transform.map_origin_m,
        transform.heading_rad, scale].every(Number.isFinite) || scale <= 0) throw new Error('원점·방향·축척을 확인하세요');
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
      for (const facility of next.facilities || []) if (facility.evidence)
        facility.evidence = {...facility.evidence, status: 'observed', reference_revision: result.projection_sha256};
      replaceDraft(next, result);
      return result;
    },
  };
}
