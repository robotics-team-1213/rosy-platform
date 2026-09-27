import { createFieldMap } from "/assets/map.js";

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "지도 및 위치");
  const status = el("ui-status", "", "지도를 불러오는 중…"); status.setAttribute("state", "pending");
  const layers = el("ui-actions", "surface-actions map-layer-actions"); layers.setAttribute("aria-label", "지도 레이어");
  for (const [id, label] of [["occupancy", "점유 지도"], ["costmap", "비용 지도"], ["path", "경로"]]) {
    const button = el("ui-button", "", label); button.setAttribute("kind", "segment"); button.type = "button"; button.dataset.mapLayer = id; layers.append(button);
  }
  const clicks = el("ui-actions", "surface-actions"); clicks.setAttribute("aria-label", "지도 작업");
  for (const [id, label] of [["pose", "초기 위치 설정"], ["goal", "주행 목표 설정"]]) {
    const button = el("ui-button", "", label); button.setAttribute("kind", "segment"); button.type = "button"; button.dataset.mapClick = id; clicks.append(button);
  }
  const clickReason = el("p", "surface-message", "내비게이션 지원을 확인하는 중입니다.");
  clickReason.id = "map-action-reason";
  clickReason.setAttribute("role", "note");
  for (const button of clicks.querySelectorAll("[data-map-click]")) {
    button.setAttribute("aria-describedby", clickReason.id);
  }
  const empty = el("ui-empty", "", "지도 데이터를 불러오는 중입니다.");
  empty.hidden = true;
  const canvas = el("canvas", "surface-map-canvas"); canvas.setAttribute("aria-label", "점유 지도. 화살표 키로 십자선을 이동하고 Enter 키로 위치를 선택합니다.");
  const targetReadout = el("dl", "ui-readout surface-map-readout");
  const targetLabel = el("dt", "", "선택 좌표");
  const targetValue = el("dd", "", "지도를 키보드로 선택하세요.");
  targetValue.setAttribute("role", "status");
  targetValue.setAttribute("aria-live", "polite");
  targetValue.setAttribute("aria-atomic", "true");
  targetReadout.append(targetLabel, targetValue);
  const mapStatus = el("ui-status", "", ""); mapStatus.setAttribute("state", "pending");
  mapStatus.id = "map-status";
  const setupLink = el("a", "surface-link", "작업 준비에서 지도 확인");
  setupLink.href = "/setup";
  setupLink.hidden = true;
  const action = el("ui-status", "", ""); action.setAttribute("state", "ready");
  const mapFrame = el("div", "surface-map-frame"); mapFrame.append(empty, canvas, targetReadout);
  root.append(head, status, layers, clickReason, clicks, mapFrame, setupLink, mapStatus, action);

  let state = null;
  let capabilities = null;
  let commissioning = null;
  const syncMapActions = () => {
    const operator = ctx.role === "operator" || ctx.role === "administrator";
    const supported = capabilities?.navigation?.goal_navigation === true;
    const hardware = commissioning?.runtime_mode === "hardware";
    const enabled = operator && supported && hardware;
    clickReason.textContent = enabled
      ? "지도를 선택하면 확인 후 위치 또는 주행 목표를 전송합니다."
      : operator
        ? !hardware
          ? "바닥 주행과 지도 목표 조작은 승인된 hardware 모드에서만 가능합니다. 현재 지도를 볼 수는 있습니다."
          : "이 로봇 프로필은 위치·주행 목표 설정용 Navigation 기능을 제공하지 않습니다."
        : "위치·주행 목표 설정에는 운용자 권한이 필요합니다.";
    for (const button of clicks.querySelectorAll("[data-map-click]")) {
      button.disabled = !enabled;
    }
  };
  syncMapActions();
  const mayOpenSetup = ctx.role !== "viewer"
    && (ctx.surfaces || []).some((surface) => surface.id === "setup");
  const map = createFieldMap({
    canvas, empty, status: mapStatus, layerRoot: root, api: ctx.api,
    emptyRecoveryLink: setupLink,
    mayOpenSetup,
    apiMaybe: async (path) => {
      try { return await ctx.api(path); }
      catch (error) {
        if (error.status === 404 && error.code === "NOT_FOUND") return null;
        throw error;
      }
    },
    getPose: () => state?.pose,
    getNavigation: () => state?.navigation,
    canGoal: () => ctx.role !== "viewer" && capabilities?.navigation?.goal_navigation === true && commissioning?.runtime_mode === "hardware",
    setAction: (text) => { action.textContent = text; },
    onTargetReadout: (target) => {
      targetValue.textContent = target.unavailable
        ? "지도 데이터가 없습니다."
        : target.inside
          ? `X ${target.x.toFixed(2)} m · Y ${target.y.toFixed(2)} m`
          : "지도 영역 밖";
    },
  });
  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (payload) => { state = payload; map.setPose(); }, (error) => { state = null; mapStatus.setAttribute("state", "error"); mapStatus.textContent = `로봇 상태를 읽지 못했습니다: ${error.message}`; map.setPose(); });
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 10_000, (payload) => { capabilities = payload; syncMapActions(); map.setPose(); }, (error) => { capabilities = null; syncMapActions(); mapStatus.setAttribute("state", "error"); mapStatus.textContent = `Navigation 지원을 확인하지 못해 지도 조작을 막았습니다: ${error.message}`; map.setPose(); });
  const stopCommissioning = ctx.store.poll("/api/v1/host/commissioning", 2_000, (payload) => { commissioning = payload; syncMapActions(); }, () => { commissioning = null; syncMapActions(); });
  let loading = false;
  const refresh = async () => {
    if (loading) return;
    loading = true;
    try { await map.refresh(); }
    catch (error) { mapStatus.setAttribute("state", error.status === 403 ? "forbidden" : "error"); mapStatus.textContent = `지도 데이터를 받지 못했습니다: ${error.message}`; }
    finally { status.hidden = true; loading = false; }
  };
  refresh();
  const timer = setInterval(refresh, 10_000);
  return () => { clearInterval(timer); stopState(); stopCapabilities(); stopCommissioning(); map.destroy(); };
}
