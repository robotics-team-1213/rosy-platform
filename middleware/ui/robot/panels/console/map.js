import { createFieldMap } from "/assets/map.js";
import { EVIDENCE_LABEL, HeadlessState, NAVIGATION_LABEL, enumLabel } from "/common/core_ui_logic.js";

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "지도 및 위치");
  const status = el("ui-status", "", "지도를 불러오는 중…"); status.setAttribute("state", "pending");
  const readinessStatus = el("ui-status", "", "로봇 상태·내비게이션 기능·실행 모드를 확인하는 중입니다.");
  readinessStatus.setAttribute("role", "status"); readinessStatus.setAttribute("aria-live", "polite");
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
  action.setAttribute("role", "status"); action.setAttribute("aria-live", "polite");
  // D-359 US-009 — 읽기 실패는 무대 위 같은 ui-empty가 말하고, 그 곁에 다시 시도가 선다.
  const overlay = el("div", "surface-map-overlay");
  const retry = el("ui-button", "", "다시 시도"); retry.setAttribute("kind", "quiet"); retry.type = "button"; retry.hidden = true;
  overlay.append(empty, retry);
  const stage = el("div", "surface-map-stage");
  stage.setAttribute("role", "group");
  stage.setAttribute("aria-label", "주행 관측");
  const navStage = el("span", "", "주행 · 확인 중");
  const pathStage = el("span", "", "계획 경로 · 확인 중");
  const locationStage = el("span", "", "위치 추정 · 확인 중");
  const slamStage = el("span", "", "SLAM · 확인 중");
  stage.append(navStage, pathStage, locationStage, slamStage);
  const mapFrame = el("div", "surface-map-frame"); mapFrame.append(overlay, canvas, stage, targetReadout);
  root.append(head, status, readinessStatus, layers, clicks, mapFrame, clickReason, setupLink, mapStatus, action);

  let state = null;
  let mappingActive = null;
  let capabilities = null;
  let commissioning = null;
  let mapIdMismatch = false;
  const readErrors = {state: null, capabilities: null, commissioning: null};
  function setText(target, text) { if (target.textContent !== text) target.textContent = text; }
  function renderStage() {
    const evidence = new HeadlessState(state);
    const navigation = evidence.isFresh("navigation") ? state?.navigation : null;
    setText(navStage, `주행 · ${navigation && ["PLANNING", "NAVIGATING"].includes(navigation) && !goalPoseReady()
      ? "위치 확인 중" : navigation ? enumLabel(NAVIGATION_LABEL, navigation) : "상태 확인 불가"}`);
    const location = !evidence.isFresh("pose") ? EVIDENCE_LABEL[evidence.evidenceOf("pose")]
      : mapIdMismatch ? "지도 ID 불일치"
      : state?.localization?.state === "LOCALIZED"
        ? state.localization.pose_frame === "map" ? "지도 좌표 확인" : "지도 좌표 미확인"
        : state?.localization?.state === "CANDIDATES" ? "후보 확인 중"
        : state?.localization?.state === "SUSPECT" ? "위치 확인 필요"
        : state?.localization?.state === "UNKNOWN" ? "위치 미확인" : "상태 정보 없음";
    setText(locationStage, `위치 추정 · ${location}`);
    setText(slamStage, `SLAM · ${capabilities?.slam === false ? "미제공" : capabilities?.slam !== true ? "기능 확인 불가"
      : mappingActive === true ? "맵핑 세션 활성" : mappingActive === false ? "맵핑 세션 대기" : "세션 확인 불가"}`);
  }
  const baseMapAction = () => (ctx.role === "operator" || ctx.role === "administrator")
    && capabilities?.navigation?.goal_navigation === true && commissioning?.runtime_mode === "hardware";
  const goalPoseReady = () => state && new HeadlessState(state).isFresh("pose")
    && (state.localization == null || (state.localization.state === "LOCALIZED" && state.localization.pose_frame === "map"));
  const canMapAction = (mode) => baseMapAction() && (mode !== "goal" || goalPoseReady());
  function renderReadiness() {
    readinessStatus.hidden = false;
    const errors = [["로봇 상태", readErrors.state], ["내비게이션 기능", readErrors.capabilities], ["실행 모드", readErrors.commissioning]]
      .filter(([, reason]) => reason);
    if (errors.length) {
      readinessStatus.textContent = `조작 근거를 확인할 수 없습니다: ${errors.map(([source, reason]) => `${source}: ${reason}`).join(" · ")}`;
      readinessStatus.setAttribute("state", "error");
      return;
    }
    if (!state || !capabilities || !commissioning) {
      readinessStatus.textContent = "로봇 상태·내비게이션 기능·실행 모드를 확인하는 중입니다.";
      readinessStatus.setAttribute("state", "pending");
      return;
    }
    readinessStatus.textContent = "로봇 상태·내비게이션 기능·실행 모드를 읽었습니다.";
    readinessStatus.setAttribute("state", "ready");
    readinessStatus.hidden = true;
  }
  const syncMapActions = () => {
    const operator = ctx.role === "operator" || ctx.role === "administrator";
    const hardware = commissioning?.runtime_mode === "hardware";
    if (mapIdMismatch) clickReason.textContent = "로봇과 지도 ID가 달라 위치·주행 목표를 막았습니다. 지도 갱신을 기다리세요.";
    else if (baseMapAction() && !goalPoseReady()) clickReason.textContent = "현재 위치 추정이 확인되지 않아 주행 목표를 막았습니다. 초기 위치 설정은 사용할 수 있습니다.";
    else if (baseMapAction()) clickReason.textContent = "지도를 선택하면 확인 후 위치 또는 주행 목표를 전송합니다.";
    else if (!operator) clickReason.textContent = "위치·주행 목표 설정에는 운용자 권한이 필요합니다.";
    else if (readErrors.capabilities) clickReason.textContent = `내비게이션 기능을 확인할 수 없어 지도 조작을 막았습니다: ${readErrors.capabilities}`;
    else if (readErrors.commissioning) clickReason.textContent = `장치 실행 모드를 확인할 수 없어 지도 조작을 막았습니다: ${readErrors.commissioning}`;
    else if (!capabilities || !commissioning) clickReason.textContent = "내비게이션 기능과 장치 실행 모드를 확인하는 중입니다.";
    else if (!hardware) clickReason.textContent = "바닥 주행과 지도 목표 조작은 승인된 하드웨어 실행 모드에서만 가능합니다. 현재 지도를 볼 수는 있습니다.";
    else clickReason.textContent = "이 로봇에는 위치·주행 목표 설정에 쓰는 내비게이션 기능이 없습니다.";
  };
  syncMapActions();
  const mayOpenSetup = ctx.role !== "viewer"
    && (ctx.surfaces || []).some((surface) => surface.id === "setup");
  const map = createFieldMap({
    canvas, empty, status: mapStatus, layerRoot: root, api: ctx.api,
    onlyActivePath: true,
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
    getCurrentMapId: () => state?.map_id,
    onMapIdMismatch: (value) => { mapIdMismatch = value; renderStage(); syncMapActions(); },
    onPathReadout: (evidence) => { setText(pathStage, `계획 경로 · ${evidence.label}`); },
    getDisplayPose: () => new HeadlessState(state).isFresh("pose") && state?.localization?.state === "LOCALIZED"
      && state.localization.pose_frame === "map" ? state.pose : null,
    getNavigation: () => new HeadlessState(state).isFresh("navigation") && goalPoseReady() ? state.navigation : null,
    canGoal: canMapAction,
    goalReason: (mode) => mode === "goal" && baseMapAction() && !goalPoseReady() ? "위치 추정 확인 후 가능" : "",
    setAction: (text) => { setText(action, text); },
    onTargetReadout: (target) => {
      targetValue.textContent = target.unavailable
        ? "지도 데이터가 없습니다."
        : target.inside
          ? `X ${target.x.toFixed(2)} m · Y ${target.y.toFixed(2)} m`
          : "지도 영역 밖";
    },
  });
  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (payload) => {
    state = payload; readErrors.state = null; renderReadiness(); renderStage(); syncMapActions(); map.setPose();
  }, (error) => {
    state = null; readErrors.state = error.message; renderReadiness(); renderStage(); syncMapActions(); map.setPose();
  });
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 10_000, (payload) => {
    capabilities = payload; readErrors.capabilities = null; renderReadiness(); renderStage(); syncMapActions(); map.setPose();
  }, (error) => {
    capabilities = null; readErrors.capabilities = error.message; renderReadiness(); renderStage(); syncMapActions(); map.setPose();
  });
  const stopMapping = ctx.store.poll("/api/v1/navigation/state", 1_000, (payload) => {
    mappingActive = typeof payload?.mapping_active === "boolean" ? payload.mapping_active : null;
    renderStage();
  }, () => { mappingActive = null; renderStage(); });
  const stopCommissioning = ctx.store.poll("/api/v1/host/commissioning", 2_000, (payload) => {
    commissioning = payload; readErrors.commissioning = null; renderReadiness(); syncMapActions(); map.setPose();
  }, (error) => {
    commissioning = null; readErrors.commissioning = error.message; renderReadiness(); syncMapActions(); map.setPose();
  });
  let loading = false; let disposed = false;
  const refresh = async () => {
    if (disposed || loading) return;
    loading = true;
    try { await map.refresh(); }
    catch (error) { mapStatus.setAttribute("state", error.status === 403 ? "forbidden" : "error"); mapStatus.textContent = `지도 데이터를 받지 못했습니다: ${error.message}`; }
    finally {
      if (disposed) return;
      status.hidden = true; loading = false;
      const failed = ["error", "forbidden"].includes(map.mapState) || mapStatus.getAttribute("state") === "error";
      mapStatus.hidden = failed; // 같은 원인을 무대 밖에서 한 번 더 말하지 않는다.
      if (failed) {
        empty.hidden = false;
        empty.setAttribute("role", "alert");
        empty.textContent = map.mapState === "forbidden"
          ? "지도 데이터를 볼 권한이 없습니다." : "지도를 불러오지 못했습니다. 연결을 확인한 뒤 다시 시도하세요.";
      } else empty.removeAttribute("role");
      retry.hidden = !failed || map.mapState === "forbidden";
      // 선택 좌표는 지도가 쓸 수 있을 때만 뜻이 있다.
      targetReadout.hidden = map.mapState !== "ready";
    }
  };
  retry.addEventListener("click", () => { refresh(); });
  refresh();
  const timer = setInterval(refresh, 10_000);
  return () => { disposed = true; clearInterval(timer); stopState(); stopCapabilities(); stopMapping(); stopCommissioning(); map.destroy(); };
}
