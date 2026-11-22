import {accountFetch} from '/account-session.js';
import {actionIcon} from '/common/ui.js';
import {statusTag} from '/canonical-monitor.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const $ = (id) => document.getElementById(id);

const PRIO_TAG = {
  p1: ['danger', '우선순위 1 · 0 ep'],
  p2: ['caution', '우선순위 2 · 부족'],
  p3: ['progress', '우선순위 3 · h2 별도'],
  done: ['fresh', '충족'],
};

const WARN_LABELS = {
  negative_wrist_branch: ['caution', '음수 손목롤(-48) 분기만'],
  near_fixed_layout: ['caution', '픽업 분산 낮음(고정 의심)'],
  h2_separate_scope: ['caution', 'h2 별도 범위 (h1 gate 제외)'],
  holdout_excluded: ['unknown', '평가 보류 세트(S06) 제외'],
};

let todoDoc = null;
let onNotice = () => {};

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (cls) node.className = cls;
  return node;
}

function svgEl(tag, attrs = {}, text = null) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  if (text !== null && text !== undefined) node.textContent = String(text);
  return node;
}

function slotVisualState(card, bay, row) {
  if (bay !== card.bay) return 'other';
  const found = (card.slots || []).find((s) => s.row === row);
  if (!found) return 'other';
  if ((found.episodes_pass ?? 0) === 0) return 'target-empty';
  if ((found.remaining_episodes ?? 0) > 0 || found.negative_branch_only || found.near_fixed_layout) return 'target-low';
  return 'target-done';
}

function buildTopDownSvg(card) {
  const svg = svgEl('svg', {
    viewBox: '0 0 280 132',
    preserveAspectRatio: 'xMidYMid meet',
    class: 'canon-svg canon-svg-topdown',
    role: 'img',
    'aria-label': `${card.arm_label} ${card.bay} 목표 배치 평면도`,
  });

  // Top & bottom arm anchors: arm_b (+y, r2/S01쪽) top, arm_a (-y, r0/S03쪽) bottom
  const bActive = card.arm === 'arm_b' ? 'true' : 'false';
  const aActive = card.arm === 'arm_a' ? 'true' : 'false';
  svg.append(
    svgEl('rect', {x: 84, y: 4, width: 108, height: 18, rx: 4, class: 'canon-svg-arm', 'data-arm-active': bActive}),
    svgEl('text', {x: 138, y: 16, 'text-anchor': 'middle', class: 'canon-svg-label'}, 'arm_b 왼팔 (+y)'),
    svgEl('rect', {x: 84, y: 110, width: 108, height: 18, rx: 4, class: 'canon-svg-arm', 'data-arm-active': aActive}),
    svgEl('text', {x: 138, y: 122, 'text-anchor': 'middle', class: 'canon-svg-label'}, 'arm_a 오른팔 (-y)'),
  );

  // Hull + belt end
  svg.append(
    svgEl('rect', {x: 24, y: 26, width: 190, height: 80, rx: 6, class: 'canon-svg-hull'}),
    svgEl('text', {x: 70, y: 37, 'text-anchor': 'middle', class: 'canon-svg-label'}, 'h2 선수'),
    svgEl('text', {x: 164, y: 37, 'text-anchor': 'middle', class: 'canon-svg-label'}, 'h1 선미'),
    svgEl('rect', {x: 222, y: 40, width: 52, height: 52, rx: 4, class: 'canon-svg-belt'}),
    svgEl('text', {x: 248, y: 63, 'text-anchor': 'middle', class: 'canon-svg-label'}, '벨트'),
    svgEl('text', {x: 248, y: 76, 'text-anchor': 'middle', class: 'canon-svg-label'}, '픽업'),
  );

  // 2 bays x 3 rows (r2 top, r1 mid, r0 bottom)
  const bayX = {'ship-h2': 32, 'ship-h1': 126};
  const rowY = {2: 42, 1: 62, 0: 82};
  const legMap = {'ship-h1': {2: 'S01', 1: 'S02', 0: 'S03'}, 'ship-h2': {2: 'S04', 1: 'S05', 0: 'S06'}};
  for (const bay of ['ship-h2', 'ship-h1']) {
    for (const row of [2, 1, 0]) {
      const state = slotVisualState(card, bay, row);
      const x = bayX[bay], y = rowY[row];
      svg.append(
        svgEl('rect', {
          x, y, width: 78, height: 17, rx: 3, class: 'canon-svg-cell',
          'data-slot-key': `${bay}r${row}`, 'data-slot-state': state,
        }),
        svgEl('text', {x: x + 39, y: y + 12, 'text-anchor': 'middle', class: 'canon-svg-label'}, `r${row} (${legMap[bay][row]})`),
      );
    }
  }

  // Carry direction arrow belt -> active bay
  const tgtX = card.bay === 'ship-h1' ? 204 : 114;
  svg.append(
    svgEl('path', {d: `M222,66 L${tgtX},66`, class: 'canon-svg-arrow'}),
    svgEl('polygon', {points: `${tgtX},62 ${tgtX},70 ${tgtX - 7},66`, class: 'canon-svg-arrow-head'}),
  );
  return svg;
}

function buildSideElevationSvg(card) {
  const svg = svgEl('svg', {
    viewBox: '0 0 120 132',
    preserveAspectRatio: 'xMidYMid meet',
    class: 'canon-svg canon-svg-layers',
    role: 'img',
    'aria-label': `${card.layer_label} 3층 단면 높이`,
  });
  svg.append(
    svgEl('line', {x1: 12, y1: 112, x2: 108, y2: 112, class: 'canon-svg-deck'}),
    svgEl('text', {x: 60, y: 125, 'text-anchor': 'middle', class: 'canon-svg-label'}, '선체 바닥 (0mm)'),
  );
  const layers = [
    {layer: 2, y: 20, label: 'l2 · F03 (70.8)'},
    {layer: 1, y: 50, label: 'l1 · F02 (38.4)'},
    {layer: 0, y: 80, label: 'l0 · F01 (6.0)'},
  ];
  for (const item of layers) {
    const state = item.layer === card.layer ? 'target' : 'other';
    svg.append(
      svgEl('rect', {
        x: 16, y: item.y, width: 88, height: 24, rx: 3,
        class: 'canon-svg-layer', 'data-layer-state': state,
      }),
      svgEl('text', {x: 60, y: item.y + 15, 'text-anchor': 'middle', class: 'canon-svg-label'}, item.label),
    );
  }
  return svg;
}

function copyTemplateText(card) {
  const txt = `${card.hf_path_hint}\n${card.bench_card_ids.join(', ')}\n${(card.goal_text_examples || [])[0] || ''}`;
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(txt).then(
      () => onNotice('ready', `촬영 정보 복사됨: ${card.hf_path_hint}`),
      () => onNotice('ready', `선택된 촬영 템플릿: ${card.hf_path_hint}`),
    );
  } else {
    onNotice('ready', `촬영 템플릿: ${card.hf_path_hint}`);
  }
}

function renderCard(card) {
  const art = el('article', undefined, 'canon-card canon-todo-card');
  art.dataset.cardId = card.card_id;
  art.dataset.priority = card.priority;

  const head = el('div', undefined, 'canon-card-head');
  const title = el('h3', `${card.arm_label} · ${card.bay} · ${card.layer_label}`);
  const tags = el('div', undefined, 'canon-head-tags');
  const [tone, pText] = PRIO_TAG[card.priority] || ['unknown', card.priority];
  tags.append(statusTag(tone, pText));
  for (const w of card.warnings || []) {
    const [wt, wl] = WARN_LABELS[w] || ['caution', w];
    tags.append(statusTag(wt, wl));
  }
  head.append(title, tags);
  art.append(head);

  const progRow = el('div', undefined, 'canon-train-item');
  const progHead = el('div', undefined, 'canon-train-head');
  const epLine = `data_gate 통과 ${card.episodes_pass} / 목표 ${card.episodes_target} ep · 부족 ${card.remaining_episodes} ep`;
  const subParts = [];
  if (card.episodes_raw > card.episodes_pass) subParts.push(`원본 ${card.episodes_raw}`);
  if (card.holdout_episodes > 0) subParts.push(`보류 ${card.holdout_episodes} 제외`);
  progHead.append(el('strong', epLine, 'canon-mono'), el('span', subParts.join(' · ') || card.slot_range_label, 'canon-mono quiet'));
  const prog = document.createElement('progress');
  prog.className = 'canon-progress';
  prog.max = Math.max(1, card.episodes_target || 1);
  prog.value = Math.min(prog.max, card.episodes_pass || 0);
  prog.dataset.state = card.priority === 'done' ? 'done' : 'running';
  prog.setAttribute('aria-label', `${card.card_id} 수집 진행률`);
  progRow.append(progHead, prog);
  art.append(progRow);

  const mapPair = el('div', undefined, 'canon-minimap-pair');
  mapPair.append(buildTopDownSvg(card), buildSideElevationSvg(card));
  art.append(mapPair);

  const tblWrap = el('div', undefined, 'ui-table-scroll');
  const tbl = el('table', undefined, 'ui-data-table canon-slot-mini-table');
  const thead = el('thead');
  const htr = el('tr');
  for (const h of ['슬롯(구 번호)', 'gate통과/원본', '부족', '손목롤·카드 ID']) htr.append(el('th', h));
  thead.append(htr);
  const tbody = el('tbody');
  for (const s of card.slots || []) {
    const tr = el('tr');
    const br = s.negative_branch_only ? '-48분기' : s.episodes_canonical_branch > 0 ? '+40분기' : '미수집';
    const loc = s.local_gate_passed != null ? ` (로컬 ${s.local_gate_passed})` : '';
    tr.append(
      el('td', `${s.slot_id} (${s.legacy_slot})`, 'canon-mono'),
      el('td', `${s.episodes_pass}/${s.episodes_raw}${loc}`, 'canon-mono'),
      el('td', String(s.remaining_episodes), 'canon-mono'),
      el('td', `${br} · ${s.task_card_id || '이 팔의 촬영 카드 없음'}`, 'canon-mono'),
    );
    tbody.append(tr);
  }
  tbl.append(thead, tbody);
  tblWrap.append(tbl);
  art.append(tblWrap);

  const foot = el('div', undefined, 'canon-card-head');
  foot.append(el('code', card.hf_path_hint, 'canon-mono quiet'));
  const copyBtn = document.createElement('ui-button');
  copyBtn.setAttribute('kind', 'quiet');
  copyBtn.setAttribute('type', 'button');
  copyBtn.textContent = card.bench_card_ids.length ? '촬영 경로·카드 ID 복사' : '저장 경로 복사';
  actionIcon(copyBtn, 'list');
  copyBtn.addEventListener('click', () => copyTemplateText(card));
  foot.append(copyBtn);
  art.append(foot);

  return art;
}

function renderChecklist() {
  const body = $('canon-filming-body');
  if (!body || !todoDoc) return;
  const proto = todoDoc.filming_protocol || {};
  const dg = proto.data_gate || {};
  const items = [
    el('p', proto.authority_note || '', 'quiet'),
    el('p', `HF 업로드 대상: ${proto.hf_repo || 'robotteam/rosy-omx-data'} (${proto.curated_prefix || 'curated/omx-real-v1'}) · ${proto.naming_template || ''}`, 'canon-mono'),
    el('p', `data_gate 필수 조건: min_frames=${dg.min_frames ?? 60}, black<${dg.black_reject_s ?? 1.0}s, frozen<${dg.frozen_review_s ?? 3.0}s, home<=${dg.home_review_rad ?? 0.35}rad, layout=${dg.layout ?? 'random'}`, 'canon-mono'),
    el('p', dg.layout_warning || '', 'quiet'),
  ];
  const ul = el('ul', undefined, 'canon-list');
  for (const cam of proto.cameras || []) ul.append(el('li', `${cam.role}: ${cam.meaning}`));
  items.push(ul);
  body.replaceChildren(...items);
}

export function renderRecordingTodo() {
  const metaEl = $('canon-todo-meta');
  const cardsEl = $('canon-todo-cards');
  const emptyEl = $('canon-todo-empty');
  if (!metaEl || !cardsEl || !emptyEl) return;

  renderChecklist();
  if (!todoDoc || todoDoc.inventory_status !== 'ready') {
    const state = todoDoc?.inventory_status || 'unconfigured';
    metaEl.replaceChildren(
      statusTag('unknown', `인벤토리 상태: ${state}`),
      el('span', todoDoc?.filming_protocol?.authority_note || '', 'quiet'),
    );
    cardsEl.replaceChildren();
    emptyEl.hidden = false;
    return;
  }

  emptyEl.hidden = true;
  const prov = todoDoc.provenance || {};
  const sum = todoDoc.summary || {};
  const rev = prov.hf_revision ? prov.hf_revision.slice(0, 8) : (prov.manifest_sha256 ? prov.manifest_sha256.slice(0, 8) : 'local');
  metaEl.replaceChildren(
    statusTag('fresh', `${prov.hf_repo || 'robotteam/rosy-omx-data'} · ${prov.curated_version || ''}`),
    el('span', `rev ${rev} · h1 통과 ${sum.ship_h1_pass ?? 0}/${sum.ship_h1_target ?? 540} ep · 부족 ${sum.ship_h1_remaining ?? 0} ep · 출처 ${prov.source_state || ''}`, 'canon-mono quiet'),
  );

  const armFilter = $('canon-todo-arm')?.value || 'all';
  const holdFilter = $('canon-todo-hold')?.value || 'all';
  const gapOnly = ($('canon-todo-gap')?.value || 'all') === 'gap';

  const visible = (todoDoc.cards || []).filter((c) => (
    (armFilter === 'all' || c.arm === armFilter)
    && (holdFilter === 'all' || c.bay === holdFilter)
    && (!gapOnly || c.priority !== 'done')
  ));
  cardsEl.replaceChildren(...visible.map(renderCard));
}

function applyView(view) {
  const mode = ['all', 'todo', 'monitor', 'spec'].includes(view) ? view : 'all';
  for (const btn of document.querySelectorAll('.canon-view-bar [data-canon-view]')) {
    btn.setAttribute('aria-pressed', btn.dataset.canonView === mode ? 'true' : 'false');
  }
  for (const sec of document.querySelectorAll('[data-canon-section]')) {
    sec.hidden = mode !== 'all' && sec.dataset.canonSection !== mode;
  }
}

export async function loadRecordingTodo() {
  try {
    const res = await accountFetch('/api/learning/canonical/recording-todo', {cache: 'no-store'});
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    todoDoc = await res.json();
  } catch {
    todoDoc = {...todoDoc, inventory_status: 'unavailable'};
  }
  renderRecordingTodo();
}

export function initRecordingTodo({notice} = {}) {
  if (typeof notice === 'function') onNotice = notice;
  const qs = new URLSearchParams(window.location.search);
  applyView(qs.get('view') || 'all');
  for (const btn of document.querySelectorAll('.canon-view-bar [data-canon-view]')) {
    btn.addEventListener('click', () => applyView(btn.dataset.canonView));
  }
  for (const fid of ['canon-todo-arm', 'canon-todo-hold', 'canon-todo-gap']) {
    $(fid)?.addEventListener('change', renderRecordingTodo);
  }
}
