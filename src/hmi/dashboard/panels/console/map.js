import { createFieldMap } from "/assets/map.js";

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "지도 및 위치");
  const status = el("p", "surface-message", "지도를 불러오는 중입니다."); status.setAttribute("role", "status");
  const layers = el("div", "surface-actions"); layers.setAttribute("aria-label", "지도 레이어");
  for (const [id, label] of [["occupancy", "점유 지도"], ["costmap", "비용 지도"], ["path", "경로"]]) {
    const button = el("ui-button", "", label); button.type = "button"; button.dataset.mapLayer = id; layers.append(button);
  }
  const clicks = el("div", "surface-actions"); clicks.setAttribute("aria-label", "지도 작업");
  for (const [id, label] of [["pose", "초기 위치 설정"], ["goal", "주행 목표 설정"]]) {
    const button = el("ui-button", "", label); button.type = "button"; button.dataset.mapClick = id; clicks.append(button);
  }
  const empty = el("ui-empty", "", "맵 데이터를 기다리는 중입니다.");
  const canvas = el("canvas", "surface-map-canvas"); canvas.setAttribute("aria-label", "점유 지도. 화살표 키로 십자선을 이동하고 Enter 키로 위치를 선택합니다.");
  const mapStatus = el("p", "surface-message", ""); mapStatus.setAttribute("role", "status");
  const action = el("p", "surface-message", ""); action.setAttribute("role", "status");
  const mapFrame = el("div", "surface-map-frame"); mapFrame.append(empty, canvas);
  root.append(head, status, layers, clicks, mapFrame, mapStatus, action);

  let state = null;
  let capabilities = null;
  const map = createFieldMap({
    canvas, empty, status: mapStatus, layerRoot: root, api: ctx.api,
    apiMaybe: async (path) => { try { return await ctx.api(path); } catch (_error) { return null; } },
    getPose: () => state?.pose,
    getNavigation: () => state?.navigation,
    canGoal: () => ctx.role !== "viewer" && capabilities?.navigation?.goal_navigation === true,
    setAction: (text) => { action.textContent = text; },
  });
  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (payload) => { state = payload; map.setPose(); }, (error) => { state = null; mapStatus.textContent = `로봇 상태를 읽지 못했습니다: ${error.message}`; map.setPose(); });
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 10_000, (payload) => { capabilities = payload; map.setPose(); }, (error) => { capabilities = null; mapStatus.textContent = `Navigation 지원을 확인하지 못해 지도 조작을 막았습니다: ${error.message}`; map.setPose(); });
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
