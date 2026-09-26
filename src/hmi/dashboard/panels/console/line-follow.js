function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "차선 추종");
  const status = el("p", "surface-message", "차선 추종 상태를 읽는 중입니다."); status.setAttribute("role", "status");
  const facts = el("dl", "ui-readout");
  const form = el("div", "ui-form");
  const label = el("label", "ui-field-label", "추종 모드");
  const select = el("select"); select.setAttribute("aria-label", "차선 추종 모드");
  for (const [value, text] of [["IR_LINE", "적외선 센서"], ["CAMERA_LINE", "카메라"]]) {
    const option = el("option", "", text); option.value = value; select.append(option);
  }
  label.append(select);
  const start = el("ui-button", "", "추종 시작"); start.setAttribute("kind", "primary"); start.type = "button";
  const stop = el("ui-button", "", "추종 중지"); stop.setAttribute("kind", "quiet"); stop.type = "button";
  form.append(label, start, stop); root.append(head, status, facts, form);

  let current = {mode: "OFF"};
  let navigationAvailable = false;
  let pending = false;
  function render() {
    facts.replaceChildren(el("dt", "", "모드"), el("dd", "", current.mode || "OFF"),
      el("dt", "", "상태"), el("dd", "", current.state || "OFF"),
      el("dt", "", "센서"), el("dd", "", current.source || "—"),
      el("dt", "", "추종 오차"), el("dd", "", current.error == null ? "—" : Number(current.error).toFixed(3)),
      el("dt", "", "신뢰도"), el("dd", "", current.confidence == null ? "—" : `${Math.round(Number(current.confidence) * 100)}%`),
      el("dt", "", "중지 사유"), el("dd", "", current.reason || "—"));
    start.disabled = pending || !navigationAvailable || current.mode !== "OFF";
    stop.disabled = pending || current.mode === "OFF";
  }
  const stopState = ctx.store.poll("/api/v1/line-follow", 1_000, (data) => { current = data; status.textContent = `차선 추종 ${data.mode || "OFF"}`; render(); }, (error) => {
    status.textContent = `차선 추종 상태를 읽지 못했습니다: ${error.message}`; current = {mode: "OFF"}; render();
  });
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 5_000, (data) => {
    navigationAvailable = data?.navigation?.goal_navigation === true;
    render();
  }, (error) => { navigationAvailable = false; status.textContent = `Navigation capability를 확인할 수 없습니다: ${error.message}`; render(); });
  async function setMode(mode) {
    if (pending || (mode !== "OFF" && !navigationAvailable)) return;
    if (mode !== "OFF" && !window.confirm("차선 추종을 시작할까요? 주변 안전을 확인하세요.")) return;
    pending = true; render();
    if (mode !== "OFF") window.dispatchEvent(new Event("rosy:stop-motion"));
    try {
      current = await ctx.api("/api/v1/line-follow/mode", {method: "PUT", body: JSON.stringify({mode})});
      status.textContent = mode === "OFF" ? "차선 추종을 중지했습니다." : `${mode} 추종 시작을 요청했습니다.`;
    } catch (error) { status.textContent = `차선 추종 요청 실패: ${error.message}`; }
    finally { pending = false; render(); }
  }
  start.addEventListener("click", () => setMode(select.value));
  stop.addEventListener("click", () => setMode("OFF"));
  render();
  return () => { stopState(); stopCapabilities(); };
}
