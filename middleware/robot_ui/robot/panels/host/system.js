// Administrator readback for host runtime, identity and advertised CORE capabilities.
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

// D-359 US-009 — CORE가 이름 붙인 빠진 원천(core/system/runtime.py)을 운용자 말로 옮긴다.
// 원래 키는 title에만 둔다. 모르는 키는 받은 그대로 보인다.
const RUNTIME_SOURCE_LABEL = {
  os_release: "운영체제", hostname: "호스트 이름", uptime: "가동 시간", load: "부하",
  cpu: "CPU", memory: "메모리", temperature: "온도", storage: "저장소",
  network_counters: "네트워크 통계", ros_graph: "ROS 그래프",
};

/** {text, title} for the runtime status line when some sources are missing, else null. */
export function runtimeGap(unavailable) {
  const keys = (unavailable || []).map(String);
  if (!keys.length) return null;
  const title = keys.join(", ");
  const hostKeys = Object.keys(RUNTIME_SOURCE_LABEL).filter((key) => key !== "ros_graph");
  if (hostKeys.every((key) => keys.includes(key))) return {text: "호스트 런타임 정보를 받지 못했습니다", title};
  return {text: `호스트 런타임 일부 확인 불가: ${keys.map((key) => RUNTIME_SOURCE_LABEL[key] || key).join(", ")}`, title};
}

function section(title) {
  const wrap = el("section", "ui-readback");
  wrap.append(el("h3", "", title));
  const body = el("dl", "ui-readout");
  wrap.append(body);
  return {wrap, body};
}

function fields(body, values) {
  body.replaceChildren();
  for (const [label, value] of values) {
    body.append(el("dt", "", label), el("dd", "", value == null || value === "" ? "—" : String(value)));
  }
}

export function mount(root, ctx) {
  const head = el("ui-head", "", "시스템 및 기능 상태");
  const runtime = section("호스트 런타임");
  const identity = section("로봇 신원");
  const capabilities = section("기능 인벤토리");
  const overview = el("div", "host-system-overview");
  const runtimeStatus = el("ui-status", "", "호스트 런타임 확인 중");
  const identityStatus = el("ui-status", "", "로봇 신원 확인 중");
  const capabilityStatus = el("ui-status", "", "기능 지원 확인 중");
  const inventoryStatus = el("ui-status", "", "기능 인벤토리 확인 중");
  overview.append(identityStatus, capabilityStatus, inventoryStatus, runtimeStatus);
  const detail = el("details", "surface-disclosure host-system-detail");
  detail.append(el("summary", "", "호스트·로봇 신원·기능 세부 정보 및 이름 변경"), runtime.wrap, identity.wrap, capabilities.wrap);
  const message = el("ui-status", "", "");
  message.hidden = true;
  message.setAttribute("role", "status");
  message.setAttribute("aria-live", "polite");
  let identityInput = null;
  let identityDirty = false;
  let savedName = null;
  if (ctx.role === "administrator") {
    const form = el("form", "ui-form");
    identityInput = el("input", "ui-field"); identityInput.name = "robot_name"; identityInput.maxLength = 64;
    identityInput.setAttribute("aria-label", "로봇 표시 이름");
    identityInput.addEventListener("input", () => { identityDirty = true; savedName = null; });
    const identitySave = el("ui-button", "", "이름 저장");
    identitySave.setAttribute("kind", "primary");
    identitySave.type = "submit";
    form.append(identityInput, identitySave);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (identitySave.disabled) return;
      const robotName = identityInput.value.trim();
      if (!robotName) {
        message.textContent = "로봇 표시 이름을 입력하세요.";
        message.hidden = false;
        message.setAttribute("state", "error");
        return;
      }
      identitySave.disabled = true;
      identityInput.disabled = true;
      message.textContent = "표시 이름 저장 요청 중";
      message.hidden = false;
      message.setAttribute("state", "pending");
      try {
        const result = await ctx.api("/api/v1/system/info", {method: "PUT", body: JSON.stringify({robot_name: robotName})});
        savedName = result?.robot_name || robotName;
        identityInput.value = savedName;
        message.textContent = "저장 요청을 접수했습니다. 다음 로봇 신원 조회에서 결과를 확인하세요.";
        message.setAttribute("state", "ready");
      } catch (error) {
        message.textContent = `표시 이름 저장 실패: ${error.message}`;
        message.setAttribute("state", "error");
      } finally {
        identitySave.disabled = false;
        identityInput.disabled = false;
      }
    });
    identity.wrap.append(form);
  }
  identity.wrap.append(message);
  root.append(head, overview, detail);

  const stopRuntime = ctx.store.poll("/api/v1/system/runtime", 10_000, (data) => {
    fields(runtime.body, [["호스트", data.hostname], ["운영체제", data.os?.pretty_name || data.os?.name],
      ["커널 / 아키텍처", [data.kernel, data.architecture].filter(Boolean).join(" / ")],
      ["가동 시간(초)", data.uptime_seconds], ["CPU 사용률", data.cpu?.usage_percent],
      ["메모리 사용률", data.memory?.used_percent], ["저장소 사용률", data.storage?.used_percent],
      ["온도(°C)", data.temperature_c], ["ROS 그래프", data.ros?.status],
      ["ROS Domain ID", data.ros?.domain_id], ["ROS Namespace", data.ros?.namespace],
      ["RMW", data.ros?.rmw], ["노드 / 토픽", data.ros ? `${data.ros.node_count ?? "—"} / ${data.ros.topic_count ?? "—"}` : null],
      ["DDS 격리", data.ros?.isolation?.mode],
      ["ROS 위험", (data.ros?.risks || []).map((risk) => `${risk.code || "UNKNOWN"}: ${risk.message || "상세 정보 없음"}`).join(" · ")]]);
    const gap = runtimeGap(data.unavailable);
    runtimeStatus.textContent = gap ? gap.text : `호스트 ${data.hostname || "이름 미확인"} · 런타임 확인됨`;
    if (gap) runtimeStatus.title = gap.title; else runtimeStatus.removeAttribute("title");
    runtimeStatus.setAttribute("state", gap ? "warning" : "ready");
  }, (error) => {
    fields(runtime.body, []);
    runtimeStatus.textContent = `호스트 런타임 확인 불가: ${error.message}`;
    runtimeStatus.removeAttribute("title");
    runtimeStatus.setAttribute("state", "error");
  });

  const stopIdentity = ctx.store.poll("/api/v1/system/info", 30_000, (data) => {
    fields(identity.body, [["로봇 ID", data.robot_id], ["표시 이름", data.robot_name || data.name],
      ["로봇 번호", data.robot_number], ["ROS Domain ID", data.ros_domain_id],
      ["ROS namespace", data.ros_namespace], ["하드웨어 모델", data.hardware_model],
      ["실행 모드", data.runtime_mode]]);
    if (identityInput) {
      const currentName = data.robot_name || data.name || "";
      if (savedName !== null) {
        if (currentName === savedName) {
          identityDirty = false;
          savedName = null;
          identityInput.value = currentName;
        }
      } else if (!identityDirty && document.activeElement !== identityInput) {
        identityInput.value = currentName;
      }
    }
    identityStatus.textContent = `${data.robot_name || data.name || data.robot_id || "로봇 이름 미확인"} · 실행 모드 ${data.runtime_mode || "확인 불가"}`;
    identityStatus.setAttribute("state", "ready");
  }, (error) => {
    fields(identity.body, []);
    identityStatus.textContent = `로봇 신원 확인 불가: ${error.message}`;
    identityStatus.setAttribute("state", "error");
  });

  function renderCapabilities(data) {
    const navigation = data.navigation?.goal_navigation === true;
    const slam = data.slam === true;
    capabilityStatus.textContent = `내비게이션 ${navigation ? "사용 가능" : "제한 또는 없음"} · SLAM ${slam ? "사용 가능" : "제한 또는 없음"}`;
    capabilityStatus.setAttribute("state", navigation && slam ? "ready" : "warning");
  }
  function renderInventory(data) {
    const descriptors = (data.descriptors || []).filter((item) => item.state !== "not_provided");
    capabilities.body.replaceChildren();
    if (!descriptors.length) capabilities.body.append(el("dd", "", "제공된 기능이 없습니다."));
    else for (const item of descriptors) {
      capabilities.body.append(el("dt", "", item.id), el("dd", "", [item.state, item.reason].filter(Boolean).join(" · ")));
    }
    inventoryStatus.textContent = descriptors.length
      ? `기능 인벤토리 ${descriptors.length}개 확인됨`
      : "기능 인벤토리 조회됨 · 제공된 기능 없음";
    inventoryStatus.setAttribute("state", "ready");
  }
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 15_000, renderCapabilities, (error) => {
    capabilityStatus.textContent = `기능 지원을 확인할 수 없습니다: ${error.message}`;
    capabilityStatus.setAttribute("state", "error");
  });
  const stopInventory = ctx.store.poll("/api/v1/system/inventory", 15_000, renderInventory, (error) => {
    capabilities.body.replaceChildren(el("dd", "", "인벤토리를 확인할 수 없습니다. 다시 확인 중입니다."));
    inventoryStatus.textContent = `기능 인벤토리를 확인할 수 없습니다: ${error.message}`;
    inventoryStatus.setAttribute("state", "error");
  });

  return () => { stopRuntime(); stopIdentity(); stopCapabilities(); stopInventory(); };
}
