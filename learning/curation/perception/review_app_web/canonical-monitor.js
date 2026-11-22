import {setOff} from '/common/cause-line.js';
import {EVIDENCE_LABEL, evidenceAgeText} from '/common/core_ui_logic.js';
import {actionIcon} from '/common/ui.js';

const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (cls) node.className = cls;
  return node;
};

const TAG_TONE = {
  fresh: 'neutral', progress: 'active', delayed: 'warn',
  disconnected: 'warn', caution: 'warn', danger: 'crit', unknown: 'neutral',
};

export function statusTag(state, text) {
  const tag = document.createElement('ui-tag');
  tag.setAttribute('status', TAG_TONE[state] || 'neutral');
  tag.textContent = text;
  return tag;
}

function summarizeReceipts(receipts) {
  if (!receipts?.length) return '없음';
  return receipts.map((r) => {
    const c = r.counts || {};
    const rej = r.dataset_reject?.length ? ` reject=${r.dataset_reject.join(',')}` : '';
    return `${r.name}: pass ${c.pass ?? 0}/rev ${c.review ?? 0}/rej ${c.reject ?? 0}${rej}`;
  }).join(' · ');
}

function fmtEta(sec) {
  if (typeof sec !== 'number' || !Number.isFinite(sec) || sec < 0) return '—';
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}시간 ${m}분`;
  if (m > 0) return `${m}분 ${s % 60}초`;
  return `${s}초`;
}

function fmtSci(val, digits = 3) {
  if (typeof val !== 'number' || !Number.isFinite(val)) return '—';
  if (Math.abs(val) > 0 && Math.abs(val) < 1e-2) return val.toExponential(1);
  return val.toFixed(digits);
}

function clampPct(val) {
  if (typeof val !== 'number' || !Number.isFinite(val)) return null;
  return Math.max(0, Math.min(100, val));
}

function peerFreshnessTag(peerStatus, fetchedAt) {
  if (peerStatus === 'ok') return statusTag('fresh', '실시간');
  if (peerStatus === 'stale') {
    const ageS = typeof fetchedAt === 'number' && Number.isFinite(fetchedAt)
      ? Math.max(0, Math.round(Date.now() / 1000 - fetchedAt)) : null;
    return statusTag('delayed', `${EVIDENCE_LABEL.delayed}${evidenceAgeText(ageS)}`);
  }
  if (peerStatus === 'unavailable') return statusTag('disconnected', EVIDENCE_LABEL.disconnected);
  return statusTag('unknown', EVIDENCE_LABEL.unavailable);
}

function phaseTagFor(entry) {
  const activeTrain = (entry?.training || []).find((t) => t.active);
  if (activeTrain) return statusTag('progress', `학습 중 · ${activeTrain.arm || activeTrain.file}`);
  const activeEval = (entry?.eval_progress || []).find((e) => e.active);
  if (activeEval) return statusTag('progress', `평가 중 · ${activeEval.checkpoint || activeEval.file}`);
  if (entry?.markers?.['stage2-done']?.present) return statusTag('fresh', 'stage2-done');
  if (entry?.markers?.['stage1-done']?.present) return statusTag('fresh', 'stage1-done');
  if (entry?.markers?.['collect.done']?.present) return statusTag('fresh', 'collect.done');
  return statusTag('unknown', '유휴');
}

function renderMeterCell(label, valueText, subText, valPct, level = 'nominal') {
  const cell = el('div', undefined, 'canon-meter-cell');
  const head = el('div', undefined, 'canon-meter-head');
  head.append(el('span', label, 'canon-kpi-label'), el('strong', valueText, 'canon-mono'));
  cell.append(head);
  const clamped = clampPct(valPct);
  if (clamped !== null) {
    const meter = document.createElement('meter');
    meter.className = 'canon-meter';
    meter.min = 0;
    meter.max = 100;
    meter.value = clamped;
    meter.dataset.level = level;
    meter.setAttribute('aria-label', label);
    cell.append(meter);
  }
  if (subText) cell.append(el('span', subText, 'canon-kpi-label'));
  return cell;
}

function renderTelemetryGrid(tel) {
  if (!tel) return el('p', '자원 사용량 정보 없음', 'quiet');
  const grid = el('div', undefined, 'canon-meters');
  const g = tel.gpu || {}, c = tel.cpu || {}, m = tel.memory || {}, d = tel.disk || {};

  const gpuAvail = Boolean(g.available);
  grid.append(renderMeterCell(
    'GPU 사용률',
    gpuAvail && g.util_pct != null ? `${g.util_pct}%` : EVIDENCE_LABEL.unavailable,
    gpuAvail ? `${g.name || 'CUDA GPU'}${g.power_w != null ? ` · ${g.power_w}W` : ''}` : 'GPU 정보 없음',
    gpuAvail ? g.util_pct : null,
    'nominal',
  ));

  const hasVram = gpuAvail && g.vram_used_mib != null && g.vram_total_mib > 0;
  const vPct = hasVram ? (100 * g.vram_used_mib) / g.vram_total_mib : null;
  grid.append(renderMeterCell(
    'VRAM',
    hasVram ? `${(g.vram_used_mib / 1024).toFixed(1)} / ${(g.vram_total_mib / 1024).toFixed(1)} GiB` : EVIDENCE_LABEL.unavailable,
    hasVram ? `${vPct.toFixed(0)}% 사용` : '메모리 정보 없음',
    vPct,
    vPct == null ? 'nominal' : vPct >= 97 ? 'crit' : vPct >= 92 ? 'warn' : 'nominal',
  ));

  const hasTemp = gpuAvail && g.temp_c != null;
  const ramText = m.used_gib != null && m.total_gib != null ? `RAM ${m.used_gib}/${m.total_gib} GiB` : 'RAM 미확인';
  const cpuText = `CPU ${c.load_1m != null ? c.load_1m : '—'}${c.cores ? ` (${c.cores}c)` : ''}`;
  grid.append(renderMeterCell(
    hasTemp ? 'GPU 온도 · CPU/RAM' : 'CPU · RAM',
    hasTemp ? `${g.temp_c}°C` : (m.pct != null ? `RAM ${m.pct}%` : EVIDENCE_LABEL.unavailable),
    `${cpuText} · ${ramText}`,
    hasTemp ? g.temp_c : m.pct,
    hasTemp ? (g.temp_c >= 85 ? 'crit' : g.temp_c >= 80 ? 'warn' : 'nominal') : 'nominal',
  ));

  const hasDisk = d.free_gib != null && d.use_pct != null;
  const diskStateWord = d.state === 'crit' ? '위험' : d.state === 'warn' ? '주의' : '정상';
  grid.append(renderMeterCell(
    '디스크',
    hasDisk ? `${d.free_gib} GiB 여유` : EVIDENCE_LABEL.unavailable,
    hasDisk ? `${d.use_pct}% 사용 (${d.total_gib ?? '—'} GiB 중) · ${diskStateWord}` : '디스크 정보 없음',
    hasDisk ? d.use_pct : null,
    d.state === 'crit' ? 'crit' : d.state === 'warn' ? 'warn' : 'nominal',
  ));
  return grid;
}

function renderTrainBlock(entry, hostTitle) {
  const wrap = el('div', undefined, 'canon-train-block');
  const runs = entry?.training || [];
  if (runs.length) {
    for (const tr of runs.slice(0, 2)) {
      const box = el('div', undefined, 'canon-train-item');
      const head = el('div', undefined, 'canon-train-head');
      const stepStr = tr.step != null && tr.total_steps ? `${tr.step.toLocaleString('ko-KR')} / ${tr.total_steps.toLocaleString('ko-KR')}`
        : tr.step != null ? `${tr.step.toLocaleString('ko-KR')} step` : tr.file;
      const pctStr = tr.pct != null ? ` (${tr.pct}%)` : '';
      const label = tr.arm ? `${tr.arm} · ${stepStr}${pctStr}` : `${stepStr}${pctStr}`;
      const rateStr = `${tr.rate_step_s != null ? `${tr.rate_step_s} step/s` : '—'} · ETA ${tr.ended ? '완료' : fmtEta(tr.eta_s)}`;
      head.append(el('strong', label, 'canon-mono'), el('span', rateStr, 'canon-mono quiet'));
      box.append(head);

      const prog = document.createElement('progress');
      prog.className = 'canon-progress';
      prog.max = tr.total_steps && tr.total_steps > 0 ? tr.total_steps : 100;
      prog.value = tr.step != null && tr.total_steps > 0 ? Math.min(tr.step, prog.max) : (tr.ended ? prog.max : 0);
      prog.dataset.state = tr.ended ? 'done' : tr.active ? 'running' : 'idle';
      prog.setAttribute('aria-label', `${hostTitle} ${tr.arm || ''} 학습 진행률`);
      box.append(prog);

      const stats = el('div', undefined, 'canon-train-stats');
      for (const [k, v] of [['loss', fmtSci(tr.loss, 4)], ['grdn', fmtSci(tr.grdn, 2)], ['lr', fmtSci(tr.lr, 1)]]) {
        const cell = el('div', undefined, 'canon-stat');
        cell.append(el('span', k, 'canon-kpi-label'), el('strong', v, 'canon-mono'));
        stats.append(cell);
      }
      box.append(stats);
      wrap.append(box);
    }
  } else {
    wrap.append(el('p', '진행 중인 학습 로그가 없습니다.', 'quiet'));
  }

  for (const ev of (entry?.eval_progress || []).slice(0, 2)) {
    const doneTxt = ev.done != null && ev.total ? `${ev.done}/${ev.total}` : ev.done != null ? `${ev.done}` : '진행 중';
    const okTxt = ev.successes != null ? ` · 성공 ${ev.successes}` : '';
    wrap.append(el('p', `평가 ${ev.checkpoint || ev.file}: ${doneTxt}${okTxt}${ev.last_line ? ` — ${ev.last_line}` : ''}`, 'canon-mono quiet'));
  }
  return wrap;
}

function renderCheckpoints(ckMap) {
  const chips = [];
  for (const [arm, stages] of Object.entries(ckMap || {})) {
    for (const [stage, names] of Object.entries(stages || {})) {
      if (!Array.isArray(names) || !names.length) continue;
      const tail = names.slice(-4);
      const hidden = names.length - tail.length;
      if (hidden > 0) chips.push(el('span', `+${hidden}`, 'canon-chip'));
      tail.forEach((n, idx) => {
        const chip = el('span', `${arm}/${stage === 'train' ? 'S1' : stage}:${n}`, 'canon-chip');
        if (idx === tail.length - 1) chip.dataset.latest = 'true';
        chips.push(chip);
      });
    }
  }
  if (!chips.length) return null;
  const row = el('div', undefined, 'canon-ckpts');
  row.append(el('span', '체크포인트', 'canon-kpi-label'), ...chips);
  return row;
}

function renderHostCard({title, hostId, entry, telemetry, peerId, peerStatus, fetchedAt, snap, busy, manager, onRefreshPeer}) {
  const card = el('article', undefined, 'canon-card canon-host-card');
  const available = entry ? entry.available !== false : Boolean(telemetry);
  card.dataset.availability = peerStatus === 'unavailable' || !available ? 'unavailable' : 'available';
  if (peerStatus === 'stale' || telemetry?.stale) card.dataset.freshness = 'delayed';

  const head = el('div', undefined, 'canon-host-head');
  const left = el('div', undefined, 'canon-host-title');
  left.append(el('h3', title));
  if (hostId) left.append(el('span', hostId === 'ai' ? 'AI PC' : hostId === 'model' ? 'Model PC' : hostId, 'canon-chip'));
  const tags = el('div', undefined, 'canon-head-tags');
  if (peerId) tags.append(peerFreshnessTag(peerStatus, fetchedAt));
  else tags.append(statusTag(telemetry?.stale ? 'delayed' : 'fresh', telemetry?.stale ? '로컬(지연)' : '실시간'));
  if (entry && available) tags.append(phaseTagFor(entry));
  head.append(left, tags);
  card.append(head);

  if (entry && available) {
    card.append(renderTrainBlock(entry, title));
    const ckRow = renderCheckpoints(entry.checkpoints);
    if (ckRow) card.append(ckRow);
    const gates = el('div', undefined, 'canon-gates');
    const receipts = entry.gate_receipts || [];
    const rejCount = receipts.reduce((s, r) => s + (r.counts?.reject ?? 0) + (r.dataset_reject?.length ?? 0), 0);
    const revCount = receipts.reduce((s, r) => s + (r.counts?.review ?? 0), 0);
    const gateTone = !receipts.length ? 'delayed' : (rejCount > 0 || revCount > 0) ? 'caution' : 'fresh';
    const gateText = !receipts.length ? 'data_gate 대기' : rejCount > 0 ? `data_gate 거부 ${rejCount}` : revCount > 0 ? `data_gate 검토 ${revCount}` : 'data_gate 통과';
    gates.append(
      statusTag(entry.align_done === 'RC=0' ? 'fresh' : 'delayed', `align.done: ${entry.align_done ?? '대기'}`),
      statusTag(gateTone, gateText),
    );
    const seeds = entry.collect_seeds || {};
    gates.append(el('span', `DART 시드: arm_a ${seeds.arm_a ?? 0} · arm_b ${seeds.arm_b ?? 0}`, 'canon-mono quiet'));
    card.append(gates);
    if (entry.gate_receipts?.length) {
      card.append(el('p', summarizeReceipts(entry.gate_receipts), 'canon-mono quiet'));
    }
  } else if (entry && entry.available === false) {
    card.append(el('p', '관찰 폴더를 읽을 수 없습니다.', 'quiet'));
  }

  card.append(renderTelemetryGrid(telemetry));

  if (peerId) {
    const btn = document.createElement('ui-button');
    btn.setAttribute('kind', 'quiet');
    btn.textContent = '피어 새로고침';
    actionIcon(btn, 'refresh');
    btn.addEventListener('click', () => onRefreshPeer(peerId));
    const pReason = !snap?.configured ? '미설정' : !manager ? '관리 권한 필요' : busy ? '요청 처리 중입니다.' : '';
    setOff(btn, busy || !manager || !snap?.configured, pReason);
    card.append(btn);
  }
  return card;
}

export function renderMonitorHosts(container, emptyEl, snap, opts) {
  const cards = [];
  for (const w of Object.values(snap?.watched || {})) {
    cards.push(renderHostCard({
      title: `${w.label || w.id}`, hostId: w.host_id || snap.host_id,
      entry: w, telemetry: snap.host_telemetry, snap, ...opts,
    }));
  }
  for (const [pid, p] of Object.entries(snap?.peers || {})) {
    const watched = Object.values(p.summary?.watched || {});
    if (watched.length) {
      for (const w of watched) {
        cards.push(renderHostCard({
          title: `${p.label || pid} · ${w.label || w.id}`, hostId: w.host_id || p.summary?.host_id,
          entry: w, telemetry: p.summary?.host_telemetry, peerId: pid,
          peerStatus: p.status, fetchedAt: p.fetched_at, snap, ...opts,
        }));
      }
    } else {
      cards.push(renderHostCard({
        title: `${p.label || pid}`, hostId: p.summary?.host_id,
        entry: null, telemetry: p.summary?.host_telemetry, peerId: pid,
        peerStatus: p.status, fetchedAt: p.fetched_at, snap, ...opts,
      }));
    }
  }
  container.replaceChildren(...cards);
  emptyEl.hidden = cards.length > 0;
}

export function hasActiveMonitorWork(snap) {
  if ((snap?.runs || []).some((r) => ['launching', 'running', 'stopping'].includes(r.status))) return true;
  const watchActive = (w) => Boolean((w?.training || []).some((t) => t.active) || (w?.eval_progress || []).some((e) => e.active));
  if (Object.values(snap?.watched || {}).some(watchActive)) return true;
  return Object.values(snap?.peers || {}).some((p) => (
    p.status === 'stale'
    || (p.summary?.runs || []).some((r) => ['launching', 'running', 'stopping'].includes(r.status))
    || Object.values(p.summary?.watched || {}).some(watchActive)
  ));
}
