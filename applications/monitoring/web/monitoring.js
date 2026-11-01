import { EVIDENCE_LABEL, evidenceAgeText } from './common/core_ui_logic.js';

const $ = (id) => document.getElementById(id);
const HEALTH = { OK: '정상', WARNING: '주의', ERROR: '오류', UNKNOWN: '판정 정보 없음' };
const KIND = { collector: '수집기', robot: '로봇', host: '호스트', fleet: 'Fleet', service: '서비스' };
const STAGE = { none: '응답 확인', dns: '이름 해석', connect: '연결', tls: '인증서·TLS', auth: '인증 거절',
  http: 'HTTP 응답', protocol: '응답 형식·시각', timeout: '응답 시간 초과', source: '상태 파일', unknown: '단계 미확인' };
const TRANSPORT = { http: 'HTTP', https: 'HTTPS', file: '상태 파일', unknown: '프로토콜 미확인' };
const state = { key: null, epoch: 0, packet: null, scopes: null, site: '', job: null, requests: new Set(),
  received: 0, wall: 0, roundTrip: 0, stale: false, page: 0, history: [], cursor: 0, historyJob: null };
const finite = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const el = (tag, text, className) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; };
const stamp = (value) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('ko-KR') : '시각 정보 없음';
const seconds = () => Math.max(0, (performance.now() - state.received) / 1000, (Date.now() - state.wall) / 1000) + state.roundTrip;

function evidence(item) {
  if (item.freshness === 'unknown' || !finite(item.age_s)) return 'unavailable';
  if (state.stale || Math.min(item.report_remaining_s, state.packet.remaining_s) - seconds() <= 0) return 'disconnected';
  return item.remaining_s - seconds() > 0 ? 'fresh' : 'delayed';
}
function evidenceNode(item) {
  const value = evidence(item);
  const node = el('small', EVIDENCE_LABEL[value] + evidenceAgeText(finite(item.age_s) ? item.age_s + seconds() : null));
  node.dataset.evidence = value;
  return node;
}
function abortReads() {
  for (const controller of state.requests) controller.abort();
  state.requests.clear(); state.job = null; state.historyJob = null;
}
function clearRows() {
  for (const id of ['observation-rows', 'link-rows', 'history-rows', 'graph']) $(id).replaceChildren();
  $('summary').textContent = ''; $('received').textContent = '';
  state.history = []; state.cursor = 0;
}
function logout() {
  state.epoch += 1; abortReads(); state.key = null; state.packet = null; state.scopes = null; state.site = '';
  clearRows(); $('reader-key').value = ''; $('login').hidden = false; $('logout').disabled = true;
  $('workspace').hidden = true; $('connection-status').textContent = '조회가 종료됐습니다.';
}
async function read(path, epoch) {
  const controller = new AbortController(); state.requests.add(controller);
  const timer = setTimeout(() => controller.abort(), 5000);
  const started = performance.now(), wall = Date.now(), key = state.key;
  try {
    const response = await fetch(path, {cache: 'no-store', credentials: 'omit', redirect: 'error', signal: controller.signal,
      headers: {Authorization: 'Bearer ' + key}});
    if (!response.ok) { const error = new Error('read unavailable'); error.status = response.status; throw error; }
    const body = await response.json();
    if (epoch !== state.epoch) throw new Error('obsolete response');
    return {body, elapsed: Math.max(0, (performance.now() - started) / 1000, (Date.now() - wall) / 1000)};
  } finally { clearTimeout(timer); state.requests.delete(controller); }
}
function validate(packet, site) {
  if (packet.schema_version !== 1 || !Array.isArray(packet.scope_sites) || !packet.scope_sites.length || packet.scope_sites.length > 64
      || !Array.isArray(packet.nodes) || packet.nodes.length > 2048 || !Array.isArray(packet.links) || packet.links.length > 4096
      || !finite(packet.remaining_s) || packet.remaining_s > 15 || (site && (packet.scope_sites.length !== 1 || packet.scope_sites[0] !== site))) throw new Error('invalid snapshot');
  const scopes = new Set(packet.scope_sites);
  for (const item of [...packet.nodes, ...packet.links]) {
    if (!scopes.has(item.site_id) || typeof item.id !== 'string' || typeof item.origin_source !== 'string'
        || !['fresh', 'stale', 'unknown'].includes(item.freshness) || !finite(item.remaining_s) || !finite(item.report_remaining_s)
        || item.report_remaining_s > 15 || (item.age_s !== null && !finite(item.age_s))) throw new Error('invalid observation');
  }
  return packet;
}
function setScopes(scopes) {
  state.scopes = scopes;
  $('scope-select').replaceChildren();
  if (scopes.length > 1) { const option = el('option', '전체 사이트'); option.value = ''; $('scope-select').append(option); }
  for (const site of scopes) { const option = el('option', site); option.value = site; $('scope-select').append(option); }
  state.site = scopes.length === 1 ? scopes[0] : ''; $('scope-select').value = state.site;
}
async function refresh() {
  if (!state.key || state.job) return;
  const epoch = state.epoch, job = {}; state.job = job;
  try {
    const result = await read('/api/monitoring/v1/snapshot' + (state.site ? '?site_id=' + encodeURIComponent(state.site) : ''), epoch);
    if (epoch !== state.epoch) return;
    state.packet = validate(result.body, state.site); state.roundTrip = result.elapsed;
    state.received = performance.now(); state.wall = Date.now(); state.stale = false;
    if (!state.scopes) setScopes(state.packet.scope_sites);
    $('workspace').hidden = false;
    $('connection-status').textContent = state.packet.nodes.some((n) => n.origin_collector === state.packet.collector_id && n.kind === 'collector' && n.reported_health === 'WARNING')
      ? '자료 수신 · 수집 보고 확인 필요' : '자료 수신 중';
    render(); loadHistory();
  } catch (error) {
    if (epoch !== state.epoch) return;
    if (error.status === 401) { logout(); $('connection-status').textContent = '조회 키를 확인하세요.'; }
    else { state.stale = true; $('connection-status').textContent = error.status === 403 ? '허용된 사이트를 확인하세요.' : '조회 연결 끊김 · 마지막 자료의 근거를 확인하세요.'; render(); }
  } finally { if (state.job === job) state.job = null; }
}
function cell(...children) { const node = el('td'); node.append(...children); return node; }
function healthNode(item) {
  const known = evidence(item) === 'fresh';
  return el('span', (HEALTH[item.reported_health] || HEALTH.UNKNOWN) + (known || !item.sampled_at ? '' : ' · 마지막 판정'),
    known && item.reported_health === 'ERROR' ? 'danger' : known && item.reported_health === 'WARNING' ? 'caution' : '');
}
function render() {
  if (!state.packet) return;
  const packet = state.packet, term = $('search').value.trim().toLocaleLowerCase();
  const own = (node) => node.kind === 'collector' && node.origin_collector === packet.collector_id && node.origin_source === 'collector';
  const all = packet.nodes.filter((node) => !own(node));
  const nodes = all.filter((node) => !term || [node.label, node.id, node.origin_source, node.origin_collector].join(' ').toLocaleLowerCase().includes(term));
  const priority = (node) => evidence(node) === 'fresh' ? ({ERROR: 0, WARNING: 1, UNKNOWN: 4, OK: 5}[node.reported_health] ?? 4) : 2;
  nodes.sort((a, b) => priority(a) - priority(b) || a.id.localeCompare(b.id));
  const pages = Math.max(1, Math.ceil(nodes.length / 50)); state.page = Math.min(state.page, pages - 1);
  const fragment = document.createDocumentFragment();
  for (const node of nodes.slice(state.page * 50, (state.page + 1) * 50)) {
    const row = el('tr');
    row.append(cell(el('p', node.label), el('small', KIND[node.kind] || '항목'), el('code', node.id)),
      cell(healthNode(node), evidenceNode(node)),
      cell(el('code', node.origin_collector + ' / ' + node.origin_source), el('small', '보고 관측 ' + stamp(node.sampled_at))));
    fragment.append(row);
  }
  $('observation-rows').replaceChildren(fragment); $('node-empty').hidden = nodes.length > 0; $('node-table').hidden = nodes.length === 0;
  $('page-number').textContent = `${state.page + 1} / ${pages}`; $('previous').disabled = state.page === 0; $('next').disabled = state.page + 1 >= pages;
  const count = all.filter((node) => evidence(node) !== 'fresh').length;
  $('summary').textContent = `관측 항목 ${all.length}개 · 최신 근거 없는 항목 ${count}개`;
  $('received').textContent = '조회 수집기 ' + packet.collector_id + ' · 마지막 자료 수신 ' + stamp(new Date(state.wall).toISOString());
  const map = new Map(packet.nodes.map((node) => [node.id, node]));
  const links = packet.links.filter((link) => !term || [link.id, map.get(link.source_id)?.label, map.get(link.target_id)?.label].join(' ').toLocaleLowerCase().includes(term));
  const rows = document.createDocumentFragment();
  for (const link of links.slice(0, 100)) {
    const row = el('tr'), fresh = evidence(link) === 'fresh';
    const outcome = link.reachable === true ? '응답 도달' : link.reachable === false ? '조회 불가 보고' : '도달 정보 없음';
    row.append(cell(el('p', (map.get(link.source_id)?.label || '원천 미확인') + ' → ' + (map.get(link.target_id)?.label || '대상 미확인')),
      el('small', (link.kind === 'probe' ? '직접 조회' : '원천 보고') + ' · ' + (TRANSPORT[link.transport] || TRANSPORT.unknown))),
      cell(el('p', outcome + ' · ' + (STAGE[link.failure_stage] || STAGE.unknown), fresh && link.failure_stage !== 'none' ? 'caution' : ''),
        el('small', finite(link.duration_ms) ? `응답 ${Math.round(link.duration_ms)}ms` : '응답 시간 미확인')),
      cell(evidenceNode(link), el('small', '성공 관측 ' + stamp(link.last_success_at)))); rows.append(row);
  }
  $('link-rows').replaceChildren(rows); $('link-empty').hidden = links.length > 0; $('link-table').hidden = links.length === 0;
  drawGraph(packet, links, map);
}
function svg(tag, attrs, text) { const node = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value)); if (text !== undefined) node.textContent = text; return node; }
function drawGraph(packet, links, map) {
  const chosen = links.slice(0, 8), ids = new Set(chosen.flatMap((link) => [link.source_id, link.target_id]));
  if (!ids.size) for (const node of packet.nodes.slice(0, 8)) ids.add(node.id);
  const levels = new Map();
  for (const id of ids) if (map.get(id)?.origin_collector === packet.collector_id && map.get(id)?.kind === 'collector') levels.set(id, 0);
  for (let pass = 0; pass < 8; pass++) for (const link of chosen) if (levels.has(link.source_id) && !levels.has(link.target_id)) levels.set(link.target_id, Math.min(4, levels.get(link.source_id) + 1));
  const counts = new Map(), points = new Map(); let width = 640, height = 180;
  for (const id of ids) { const level = levels.get(id) ?? 1, index = counts.get(level) || 0; counts.set(level, index + 1);
    const point = {x: 20 + level * 240, y: 24 + index * 84}; points.set(id, point); width = Math.max(width, point.x + 220); height = Math.max(height, point.y + 84); }
  const graph = $('graph'); graph.replaceChildren(); graph.setAttribute('viewBox', `0 0 ${width} ${height}`);
  for (const link of chosen) { const a = points.get(link.source_id), b = points.get(link.target_id); if (!a || !b) continue;
    graph.append(svg('path', {d: `M${a.x + 190},${a.y + 24} C${a.x + 220},${a.y + 24} ${b.x - 30},${b.y + 24} ${b.x},${b.y + 24}`,
      class: 'edge' + (evidence(link) !== 'fresh' ? ' old' : link.failure_stage !== 'none' ? ' problem' : '')})); }
  for (const [id, point] of points) { const node = map.get(id); if (!node) continue;
    const group = svg('g', {}); group.append(svg('title', {}, node.label + ' · ' + id), svg('rect', {x: point.x, y: point.y, width: 190, height: 52, rx: 4}),
      svg('text', {x: point.x + 10, y: point.y + 21}, Array.from(node.label).slice(0, 18).join('')),
      svg('text', {x: point.x + 10, y: point.y + 40, class: 'detail'}, (KIND[node.kind] || '항목') + ' · ' + node.origin_source.slice(0, 18))); graph.append(group); }
  $('graph-note').textContent = `그림 ${chosen.length}개 경로 · 연결 목록 ${Math.min(links.length, 100)} / ${links.length}개. 검색으로 범위를 좁히세요. 원천 판정의 신선도는 목록에서 확인할 수 있습니다.`;
}
async function loadHistory() {
  if (!state.key || !state.site || state.historyJob) return;
  const epoch = state.epoch, site = state.site, job = {}; state.historyJob = job;
  try {
    const result = await read(`/api/monitoring/v1/sites/${encodeURIComponent(site)}/events?after=${state.cursor}&limit=200`, epoch);
    if (epoch !== state.epoch) return;
    if (!Array.isArray(result.body.events) || result.body.events.length > 200) throw new Error('invalid history');
    state.history = [...state.history, ...result.body.events].slice(-200); state.cursor = result.body.next_after;
    $('history-rows').replaceChildren(...state.history.map((event) => el('li', stamp(event.time) + ' · ' + event.item_id + ' · 기록 당시 ' +
      (event.state?.reported_health ? HEALTH[event.state.reported_health] || HEALTH.UNKNOWN : STAGE[event.state?.failure_stage] || '관측 집합 변경'))));
    $('history-note').textContent = state.history.length ? '현재 창에 확인한 기록 최대 200건을 표시합니다.' : '아직 변경 기록이 없습니다.';
    $('history-next').hidden = result.body.events.length < 200;
  } catch { if (epoch === state.epoch) $('history-note').textContent = '변경 기록을 조회하지 못했습니다. 다시 조회하세요.'; }
  finally { if (state.historyJob === job) state.historyJob = null; }
}
$('login').addEventListener('submit', (event) => { event.preventDefault(); const key = $('reader-key').value.trim(); logout();
  state.key = key; $('reader-key').value = ''; $('login').hidden = true; $('logout').disabled = false; $('connection-status').textContent = '조회 키 확인 중…'; refresh(); });
$('logout').addEventListener('click', logout);
$('scope-select').addEventListener('change', () => { state.epoch += 1; abortReads(); state.site = $('scope-select').value; state.packet = null; state.page = 0; clearRows(); refresh(); });
$('search').addEventListener('input', () => { state.page = 0; render(); });
$('refresh').addEventListener('click', refresh); $('history-next').addEventListener('click', loadHistory);
$('previous').addEventListener('click', () => { state.page = Math.max(0, state.page - 1); render(); });
$('next').addEventListener('click', () => { state.page += 1; render(); });
const resume = () => { if (state.key) { state.stale = true; render(); refresh(); } };
document.addEventListener('visibilitychange', () => { if (document.hidden) { state.stale = true; render(); } else resume(); });
window.addEventListener('pageshow', resume); window.addEventListener('focus', resume);
setInterval(refresh, 5000); setInterval(() => { if (state.packet) render(); }, 1000);
for (const choice of window.RosyTheme.choices) { const option = el('option', choice.label); option.value = choice.value; $('theme').append(option); }
$('theme').value = window.RosyTheme.get(); $('theme').addEventListener('change', () => window.RosyTheme.set($('theme').value));
