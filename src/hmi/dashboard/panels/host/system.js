// Administrator readback for host runtime, identity and advertised CORE capabilities.
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
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
  overview.append(identityStatus, capabilityStatus, runtimeStatus);
  const detail = el("details", "surface-disclosure host-system-detail");
  detail.append(el("summary", "", "호스트·로봇 신원·기능 세부 정보 및 이름 변경"), runtime.wrap, identity.wrap, capabilities.wrap);
  const message = el("ui-status", "", "");
  message.hidden = true;
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
    runtimeStatus.textContent = data.unavailable?.length
      ? `호스트 런타임 일부 확인 불가: ${data.unavailable.join(", ")}`
      : `호스트 ${data.hostname || "이름 미확인"} · 런타임 확인됨`;
    runtimeStatus.setAttribute("state", data.unavailable?.length ? "warning" : "ready");
  }, (error) => { runtimeStatus.textContent = `호스트 런타임 확인 불가: ${error.message}`; runtimeStatus.setAttribute("state", "error"); });

  const stopIdentity = ctx.store.poll("/api/v1/system/info", 30_000, (data) => {
    fields(identity.body, [["로봇 ID", data.robot_id], ["표시 이름", data.robot_name || data.name],
      ["로봇 번호", data.robot_number], ["ROS Domain ID", data.ros_domain_id],
      ["ROS namespace", data.ros_namespace], ["하드웨어 모델", data.hardware_model],
      ["실행 모드", data.runtime_mode]]);
    identityStatus.textContent = `${data.robot_name || data.name || data.robot_id || "로봇 이름 미확인"} · 실행 모드 ${data.runtime_mode || "확인 불가"}`;
    identityStatus.setAttribute("state", "ready");
    if (ctx.role === "administrator" && !identity.body.querySelector("form")) {
      const form = el("form", "ui-form");
      const input = el("input"); input.name = "robot_name"; input.maxLength = 64;
      input.value = data.robot_name || data.name || ""; input.setAttribute("aria-label", "로봇 표시 이름");
      const save = el("ui-button", "", "이름 저장"); save.setAttribute("kind", "primary"); save.type = "submit";
      form.append(input, save);
      form.addEventListener("submit", async (event) => {
        event.preventDefault(); save.disabled = true;
        try { await ctx.api("/api/v1/system/info", {method: "PUT", body: JSON.stringify({robot_name: input.value.trim()})}); message.textContent = "표시 이름 저장 요청을 보냈습니다. 다음 로봇 신원 조회로 결과를 확인하세요."; message.hidden = false; }
        catch (error) { message.textContent = `표시 이름 저장 실패: ${error.message}`; message.hidden = false; }
        finally { save.disabled = false; }
      });
      identity.wrap.append(form);
    }
  }, (error) => { identityStatus.textContent = `로봇 신원 확인 불가: ${error.message}`; identityStatus.setAttribute("state", "error"); });

  let capabilityData = {};
  let inventoryData = {};
  function renderInventory() {
    const descriptors = (inventoryData.descriptors || []).filter((item) => item.state !== "not_provided");
    capabilities.body.replaceChildren();
    if (!descriptors.length) capabilities.body.append(el("dd", "", "제공된 기능이 없습니다."));
    else for (const item of descriptors) {
      capabilities.body.append(el("dt", "", item.id), el("dd", "", [item.state, item.reason].filter(Boolean).join(" · ")));
    }
    capabilityStatus.textContent = `기능 인벤토리 ${descriptors.length}개 · Navigation ${capabilityData.navigation?.goal_navigation === true ? "사용 가능" : "제한 또는 미제공"} · SLAM ${capabilityData.slam === true ? "사용 가능" : "제한 또는 미제공"}`;
    capabilityStatus.setAttribute("state", "ready");
  }
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 15_000, (data) => { capabilityData = data; renderInventory(); }, (error) => { capabilityStatus.textContent = `기능 capability 확인 불가: ${error.message}`; capabilityStatus.setAttribute("state", "error"); });
  const stopInventory = ctx.store.poll("/api/v1/system/inventory", 15_000, (data) => { inventoryData = data; renderInventory(); }, (error) => { capabilityStatus.textContent = `기능 인벤토리 확인 불가: ${error.message}`; capabilityStatus.setAttribute("state", "error"); });

  return () => { stopRuntime(); stopIdentity(); stopCapabilities(); stopInventory(); };
}
