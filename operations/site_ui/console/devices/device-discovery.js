// Fleet device discovery, approved app directory and address guidance; no registration writes.
import { addressMap, movableRobots, renumberBanner } from "/console/assets/address-drift.js";

// Navigation uses the authenticated peer directory, never a discovered URL or a guessed port.
export function robotAppLinks(robotId, peers = []) {
  if (!Array.isArray(peers) || peers.some(peer => !peer || typeof peer !== "object")) return [];
  const candidates = peers.filter(peer => peer.role === "robot" && peer.peer_id === robotId);
  if (!candidates.length || candidates.some(peer => peer.approval !== "approved"
      || !["fresh", "unavailable"].includes(peer.freshness))) return [];
  const origins = new Set();
  for (const peer of candidates) {
    // mDNS approval binds the identity, not the advertised transport/port.
    if (peer.provenance !== "approved-directory") return [];
    if (!["http", "https"].includes(peer.transport) || !Number.isInteger(peer.port)
        || peer.port < 1 || peer.port > 65535) return [];
    const host = peer.hostname || peer.address;
    if (typeof host !== "string" || !/^[a-zA-Z0-9.:-]+$/.test(host)) return [];
    try {
      const authority = host.includes(":") ? `[${host}]` : host;
      const target = new URL(`${peer.transport}://${authority}:${peer.port}`);
      origins.add(target.origin);
    } catch { return []; }
  }
  if (origins.size !== 1) return [];
  const [origin] = origins;
  return [
    {app: "robot", href: `${origin}/console`, label: "Rosy Robot · 한 대 관리"},
    {app: "pilot", href: `${origin}/pilot`, label: "Rosy Pilot · 직접 운전"},
  ];
}

export function createRobotAppActions(robotId, peers, nodeWithText) {
  const context = nodeWithText('div', 'robot-actions');
  const appLinks = robotAppLinks(robotId, peers);
  for (const app of appLinks) {
    const link = nodeWithText('a', '', app.label);
    link.href = app.href;
    link.dataset.robotApp = app.app;
    link.rel = "noreferrer";
    context.append(link);
  }
  if (!appLinks.length) {
    const guidance = nodeWithText('span', 'hint', '앱을 열려면 설치에서 승인된 로봇 주소를 확인하세요.');
    guidance.dataset.robotAppGuidance = '';
    context.append(guidance);
  }
  const recording = nodeWithText('a', '', '지도 기록');
  recording.href = `/console/site-map?robot=${encodeURIComponent(robotId)}#teach-heading`;
  recording.dataset.mapRecording = '';
  context.append(recording);
  return context;
}

export function createDeviceDiscovery({pageScope, auth, discoveryGate, view, call, render, incidents, el, log}) {
  let scannerLost = false;

  let robotAppsRevision = 0;
  function resetRobotApps() {
    robotAppsRevision += 1;
    view.robotPeers = [];
    document.querySelectorAll("[data-robot-app]").forEach(link => link.remove());
  }

  async function refreshRobotApps() {
    if (auth.locked) return;
    const revision = ++robotAppsRevision;
    try {
      const snapshot = await call("/api/fleet/peers");
      if (auth.locked || revision !== robotAppsRevision) return;
      view.robotPeers = Array.isArray(snapshot.peers) ? snapshot.peers : [];
    } catch (error) {
      if (error.name === "AbortError" || revision !== robotAppsRevision) return;
      view.robotPeers = [];
    }
    render();
  }

  async function refreshDiscovery() {
    const life = pageScope.capture();
    life.check();
    // D-410 — 발견 목록·등록은 설치 화면에 있다. 운용 화면은 검색기 건강과
    // 고정 주소 판정(로스터 안내)만 이 요청에서 얻는다.
    if (auth.locked) return;
    if (!discoveryGate.due()) return;
    try {
      const snapshot = await call("/api/fleet/discovery");
      life.check();
      discoveryGate.ok();
      let names = { ...view.robotNames };
      try {
        const listing = await call("/api/fleet/enrollment/robots");
        life.check();
        names = Object.fromEntries((listing.robots || [])
          .filter((row) => row.robot_id && row.hostname)
          .map((row) => [row.robot_id, row.hostname]));
      } catch (err) {
        if (err.name === "AbortError") return;
      }
      for (const device of snapshot.devices || []) {
        if (device.status === "enrolled" && device.robot_id && device.name) names[device.robot_id] = device.name;
      }
      if (JSON.stringify(names) !== JSON.stringify(view.robotNames)) {
        view.robotNames = names;
        render();
        await incidents.refresh();
      }
      const pending = snapshot.scanner_online
        ? (snapshot.devices || []).filter((device) => device.status === "registration_pending") : [];
      const pendingNote = el("discovery-pending");
      const summary = pending.length
        ? `발견됐지만 미등록 ${pending.length}대: ${pending.map((device) => device.name).join(", ")}` : "";
      if (pendingNote.firstElementChild.textContent !== summary) pendingNote.firstElementChild.textContent = summary;
      pendingNote.hidden = !summary;
      await refreshAddresses();
      life.check();
      // 검색기 임대(45 s)가 끊기면 새 주소 안내가 멈춘다 — 대기와 구별해 알린다.
      if (snapshot.scanner_state === "expired") {
        if (!scannerLost) log("발견 검색기 끊김 — 로봇 발견·주소 이동 안내 불가", "bad");
        scannerLost = true;
        return;
      }
      if (scannerLost && snapshot.scanner_online) log("발견 검색기 다시 연결됨", "good");
      scannerLost = false;
    } catch (err) {
      if (err.name === "AbortError") return;
      if (auth.locked) return;
      if (discoveryGate.fail(err.status, err.code) === "absent") return;
    }
  }

  // 고정 주소 판정은 발견과 같은 주기로 읽는다. 못 읽으면 까닭 줄을 지운다(짐작하지 않는다).
  let addressText = "";

  // D-410 — 주소 이동 대화상자(로봇 화면 코드)는 설치 화면에 있다. 운용 화면의
  // 이동 안내는 그 화면으로 가는 링크로만 말한다.
  function moveLink() {
    const node = document.createElement("a");
    node.href = "/console/install";
    node.textContent = "설치 화면에서 이동";
    return node;
  }

  async function refreshAddresses() {
    const life = pageScope.capture();
    life.check();
    let payload = null;
    try {
      payload = await call("/api/fleet/discovery/addresses");
      life.check();
    } catch (_err) {
      if (_err.name === "AbortError") return;
      payload = null;
    }
    const banner = el("address-banner");
    const text = renumberBanner(payload, view.robots);
    banner.hidden = !text;
    if (text && banner.textContent !== text) banner.textContent = text;
    // 옮길 수 있는 로봇마다 한 줄과 그 로봇의 지름길. 옮기기마다 그 로봇의 화면 코드를 묻는다.
    const movable = movableRobots(payload);
    const next = JSON.stringify([payload?.robots || [], auth.role, auth.principal]);
    if (next !== addressText) {
      addressText = next;
      el("address-movable").replaceChildren(...movable.map((entry) => {
        const item = document.createElement("li");
        const label = document.createElement("span");
        label.textContent = `${entry.robot_id} → ${entry.seen_addresses[0]}`;
        item.append(label, moveLink());
        return item;
      }));
      view.addresses = addressMap(payload);
      render();
    }
    el("address-drift").hidden = !text && movable.length === 0;
  }
  return {refreshDiscovery, refreshRobotApps, resetRobotApps, get scannerLost() { return scannerLost; }};
}
