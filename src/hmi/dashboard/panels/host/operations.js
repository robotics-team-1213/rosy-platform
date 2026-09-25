// Read-only host-agent views. An unreachable agent remains visibly unavailable.
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function card(title, path, interval, ctx, describe) {
  const wrap = el("section", "surface-readback");
  wrap.append(el("h3", "", title));
  const body = el("dl", "surface-readout");
  const status = el("p", "surface-message", "상태를 불러오는 중입니다.");
  status.setAttribute("role", "status");
  wrap.append(body, status);
  const stop = ctx.store.poll(path, interval, (payload) => {
    body.replaceChildren();
    const commissioning = path === "/api/v1/host/commissioning";
    if (!commissioning && payload?.available !== true) {
      body.append(el("dt", "", "상태"), el("dd", "", "확인할 수 없음"));
      status.textContent = payload?.detail || "Host Agent 상태를 받지 못했습니다.";
      wrap.dataset.available = "false";
      return;
    }
    wrap.dataset.available = "true";
    const data = commissioning ? payload : (payload.data || {});
    for (const [label, value] of describe(data)) {
      body.append(el("dt", "", label), el("dd", "", value == null || value === "" ? "—" : String(value)));
    }
    status.textContent = payload.ok === false ? (payload.detail || "호스트 상태에 문제가 있습니다.") : (payload.detail || "서버가 보고한 상태입니다.");
  }, (error) => {
    wrap.dataset.available = "false";
    status.textContent = error.status === 403 ? "이 상태를 볼 권한이 없습니다." : `상태를 가져오지 못했습니다: ${error.message}`;
  });
  return {wrap, stop};
}

export function mount(root, ctx) {
  const head = el("ui-head", "", "네트워크 및 장치 운영 상태");
  const cards = [
    card("네트워크", "/api/v1/host/network", 10_000, ctx, (data) => [["모드", data.mode], ["SSID", data.ssid], ["액세스 포인트", data.ap_active == null ? null : data.ap_active ? "켜짐" : "꺼짐"], ["IPv4", data.ipv4], ["기본 경로", data.default_route], ["DNS", (data.dns || []).join(", ")], ["인터넷", data.internet == null ? null : data.internet ? "도달" : "도달 안 됨"], ["단말 접근", data.peer_reachable == null ? null : data.peer_reachable ? "가능" : "확인 필요"]]),
    card("릴리스", "/api/v1/host/release", 15_000, ctx, (data) => [["상태", data.state], ["현재 버전", data.current], ["이전 버전", data.previous], ["대기 버전", data.staged], ["마지막 실패", data.last_failure], ["리비전", data.git_revision], ["설정/데이터 스키마", data.config_schema == null ? null : `${data.config_schema} / ${data.data_schema}`]]),
    card("커미셔닝", "/api/v1/host/commissioning", 15_000, ctx, (data) => [["실행 모드", data.runtime_mode], ["동작 차단 사유", data.motion_reason], ["모터", data.motor_hold ? "승인 대기" : "확인됨"], ["LiDAR", data.lidar_hold ? "승인 대기" : "확인됨"], ["배터리", data.battery_hold ? "승인 대기" : "확인됨"], ["IMU", data.imu_hold ? "승인 대기" : "확인됨"], ["SLAM", data.slam_hold ? "승인 대기" : "확인됨"], ["Fleet", data.fleet_hold ? "승인 대기" : "확인됨"], ["세부 정보", data.detail]]),
  ];
  root.append(head, ...cards.map(({wrap}) => wrap));
  return () => cards.forEach(({stop}) => stop());
}
