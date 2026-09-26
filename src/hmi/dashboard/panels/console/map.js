import { createFieldMap } from "/assets/map.js";

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "지도 및 위치");
  const status = el("p", "surface-message", "지도를 불러오는 중입니다."); status.setAttribute("role", "status");
  const layers = el("div", "surface-actions map-layer-actions"); layers.setAttribute("aria-label", "지도 레이어");
  for (const [id, label] of [["occupancy", "점유 지도"], ["costmap", "비용 지도"], ["path", "경로"]]) {
    const button = el("ui-button", "", label); button.setAttribute("kind", "segment"); button.type = "button"; button.dataset.mapLayer = id; layers.append(button);
  }
  const clicks = el("div", "surface-actions"); clicks.setAttribute("aria-label", "지도 작업");
  for (const [id, label] of [["pose", "초기 위치 설정"], ["goal", "주행 목표 설정"]]) {
    const button = el("ui-button", "", label); button.setAttribute("kind", "segment"); button.type = "button"; button.dataset.mapClick = id; clicks.append(button);
  }
  const clickReason = el("p", "surface-message", "내비게이션 지원을 확인하는 중입니다.");
  clickReason.id = "map-action-reason";
  clickReason.setAttribute("role", "note");
  for (const button of clicks.querySelectorAll("[data-map-click]")) {
    button.setAttribute("aria-describedby", clickReason.id);
  }
  const empty = el("ui-empty", "", "맵 데이터를 기다리는 중입니다.");
  const canvas = el("canvas", "surface-map-canvas"); canvas.setAttribute("aria-label", "점유 지도. 화살표 키로 십자선을 이동하고 Enter 키로 위치를 선택합니다.");
  const mapStatus = el("p", "surface-message", ""); mapStatus.setAttribute("role", "status");
  const action = el("p", "surface-message", ""); action.setAttribute("role", "status");
  const mapFrame = el("div", "surface-map-frame"); mapFrame.append(empty, canvas);
  root.append(head, status, layers, clickReason, clicks, mapFrame, mapStatus, action);

  let state = null;
  let capabilities = null;
  const syncMapActions = () => {
    const operator = ctx.role === "operator" || ctx.role === "administrator";
    const supported = capabilities?.navigation?.goal_navigation === true;
    const enabled = operator && supported;
    clickReason.textContent = enabled
      ? "지도를 선택하면 확인 후 위치 또는 주행 목표를 전송합니다."
      : operator
        ? "이 로봇 프로필은 위치·주행 목표 설정용 Navigation 기능을 제공하지 않습니다."
        : "위치·주행 목표 설정에는 운용자 권한이 필요합니다.";
    for (const button of clicks.querySelectorAll("[data-map-click]")) {
      button.disabled = !enabled;
    }
  };
  syncMapActions();
  const map = createFieldMap({
    canvas, empty, status: mapStatus, layerRoot: root, api: ctx.api,
    apiMaybe: async (path) => { try { return await ctx.api(path); } catch (_error) { return null; } },
    getPose: () => state?.pose,
    getNavigation: () => state?.navigation,
    canGoal: () => ctx.role !== "viewer" && capabilities?.navigation?.goal_navigation === true,
    setAction: (text) => { action.textContent = text; },
  });
  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (payload) => { state = payload; map.setPose(); }, (error) => { state = null; mapStatus.textContent = `로봇 상태를 읽지 못했습니다: ${error.message}`; map.setPose(); });
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 10_000, (payload) => { capabilities = payload; syncMapActions(); map.setPose(); }, (error) => { capabilities = null; syncMapActions(); mapStatus.textContent = `Navigation 지원을 확인하지 못해 지도 조작을 막았습니다: ${error.message}`; map.setPose(); });
  let loading = false;
  const refresh = async () => {
    if (loading) return;
    loading = true;
    try { await map.refresh(); }
    catch (error) { mapStatus.textContent = `지도 데이터를 받지 못했습니다: ${error.message}`; }
    finally { loading = false; }
  };
  refresh();
  const timer = setInterval(refresh, 10_000);
  return () => { clearInterval(timer); stopState(); stopCapabilities(); map.destroy(); };
}
