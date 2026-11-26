// Put the top camera back where a calibration saw it: the reference image over the live frame, with arrows.
import { $, fetchJson } from "./app.js";

const PERIOD_MS = 1500;
let profileId = null, running = false, timer = null, refImage = null, refKey = "", gen = 0;

export function setAlignProfile(id) {
  if (id === profileId) return;
  profileId = id;
  stop();
  loadReferences();
}

async function loadReferences() {
  const select = $("alignRef"), id = profileId;
  select.replaceChildren();
  $("alignReadout").textContent = "";
  if (!id) return;
  try {
    const data = await fetchJson(`/api/calibration/v1/profiles/${encodeURIComponent(id)}/align`);
    if (id !== profileId) return;  // a later profile's listing owns the select
    for (const ref of data.references || []) select.append(new Option(ref.label, ref.id));
    $("alignReadout").textContent = select.options.length ? "기준 영상을 고르고 맞춤 보기를 시작하세요." : "이 팔에는 기준 영상이 없습니다.";
  } catch (err) {
    $("alignReadout").textContent = `기준 영상 목록을 읽지 못했습니다: ${err.message}`;
  }
  $("alignStart").disabled = !select.options.length;
}

function stop() {
  running = false;
  gen += 1;  // a tick still awaiting a reply sees a newer generation and does not reschedule
  clearTimeout(timer);
  $("alignStart").textContent = "맞춤 보기 시작";
  $("alignTag").setAttribute("status", "neutral");
  $("alignTag").textContent = "-";
  const canvas = $("alignCanvas");
  canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
}

// Bitmaps from blobs: the page's CSP (img-src 'self') refuses data: URLs for <img>.
async function bitmap(blob) {
  try { return await createImageBitmap(blob); } catch { throw new Error("이미지를 읽지 못했습니다."); }
}

async function fetchBitmap(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`기준 영상 HTTP ${res.status}`);
  return bitmap(await res.blob());
}

function decodeBase64(text) {
  const raw = atob(text);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

// Each arrow runs from where a reference point was to where it is now; red past the limit.
export function draw(canvas, live, ref, report, opacity) {
  const ctx = canvas.getContext("2d");
  canvas.width = live.width;
  canvas.height = live.height;
  ctx.globalAlpha = 1;
  ctx.drawImage(live, 0, 0);
  ctx.globalAlpha = opacity;
  ctx.drawImage(ref, 0, 0, canvas.width, canvas.height);
  ctx.globalAlpha = 1;
  ctx.lineWidth = 3;
  for (const [x0, y0, x1, y1] of report.arrows || []) {
    const over = Math.hypot(x1 - x0, y1 - y0) > report.limit_px;
    ctx.strokeStyle = ctx.fillStyle = over ? "#ff4d4f" : "#3ddc84";
    ctx.beginPath(); ctx.arc(x0, y0, 4, 0, 2 * Math.PI); ctx.fill();
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
    const a = Math.atan2(y1 - y0, x1 - x0);
    ctx.beginPath(); ctx.moveTo(x1, y1);
    ctx.lineTo(x1 - 10 * Math.cos(a - 0.4), y1 - 10 * Math.sin(a - 0.4));
    ctx.lineTo(x1 - 10 * Math.cos(a + 0.4), y1 - 10 * Math.sin(a + 0.4));
    ctx.closePath(); ctx.fill();
  }
}

export function readout(report) {
  if (!report.ok) return `비교할 수 없습니다: ${report.why}`;
  const [dx, dy] = report.shift_px;
  const where = [dx >= 0 ? `오른쪽 ${dx.toFixed(1)}` : `왼쪽 ${(-dx).toFixed(1)}`, dy >= 0 ? `아래 ${dy.toFixed(1)}` : `위 ${(-dy).toFixed(1)}`].join(", ");
  const turn = report.rotation_deg >= 0 ? `시계 방향 ${report.rotation_deg}°` : `반시계 방향 ${-report.rotation_deg}°`;  // image y points down
  const size = report.scale < 1 ? "작게" : "크게";
  const body = `최대 ${report.max_px} px · 화면 내용이 ${where} px 밀림 · ${turn} 회전 · 기준보다 ${size} 보임(배율 ${report.scale})`;
  return report.aligned ? `기준 안입니다(${report.limit_px} px 이내). ${body}` : `${report.limit_px} px 이내로 맞추세요. ${body}`;
}

async function tick(mine) {
  if (!running || mine !== gen) return;
  const id = profileId, ref = $("alignRef").value;
  const base = `/api/calibration/v1/profiles/${encodeURIComponent(id)}/align`;
  try {
    if (refKey !== id + "|" + ref) {
      refImage = await fetchBitmap(`${base}/reference?ref=${encodeURIComponent(ref)}`);
      refKey = id + "|" + ref;
    }
    const report = await fetchJson(`${base}?ref=${encodeURIComponent(ref)}`);
    if (mine !== gen || id !== profileId) return;
    if (!report.live_image) throw new Error(report.error || report.why || "실시간 영상이 없습니다.");
    const live = await bitmap(new Blob([decodeBase64(report.live_image)]));
    draw($("alignCanvas"), live, refImage, report, Number($("alignOpacity").value) / 100);
    const text = readout(report);
    if ($("alignReadout").textContent !== text) $("alignReadout").textContent = text;  // a screen reader hears changes only
    $("alignTag").setAttribute("status", report.ok && report.aligned ? "ok" : "warn");
    $("alignTag").textContent = report.ok ? (report.aligned ? "기준 안" : `어긋남 ${report.max_px} px`) : "비교 불가";
  } catch (err) {
    $("alignReadout").textContent = `실시간 비교 실패: ${err.message}`;
  }
  if (mine === gen) timer = setTimeout(() => tick(mine), PERIOD_MS);
}

function init() {
  // The profile bar's pressed button names the profile ("<id> · LOO · badge"); app.js is at its size limit, so watch it.
  const bar = $("profileBar");
  const follow = () => setAlignProfile(bar.querySelector('[aria-pressed="true"]')?.textContent.split(" · ")[0] || null);
  new MutationObserver(follow).observe(bar, { subtree: true, childList: true, attributes: true, attributeFilter: ["aria-pressed"] });
  follow();
  $("alignStart").addEventListener("click", () => {
    if (running) return stop();
    running = true;
    gen += 1;
    $("alignStart").textContent = "맞춤 보기 멈춤";
    tick(gen);
  });
  $("alignRef").addEventListener("change", () => { refKey = ""; });
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
}

init();
