// Admin-only credential and safety policy controls. Generated credentials are
// rendered once in a live status node and are never persisted by this module.
function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
function numberField(labelText, name, max = 100, min = 0.01) {
  const label = el("label", "ui-field-label", labelText); const input = el("input");
  input.type = "number"; input.min = String(min); input.max = String(max); input.step = "any"; input.name = name; label.append(input);
  return {label, input};
}

export function mount(root, ctx) {
  const head = el("ui-head", "", "보안 및 안전 정책");
  const notice = el("ui-status", "", "설정을 불러오는 중입니다.");

  const tokenSection = el("section", "ui-readback"); tokenSection.append(el("h3", "", "접근 토큰"));
  const tokenForm = el("form", "ui-form");
  const roleLabel = el("label", "ui-field-label", "역할");
  const role = el("select"); role.name = "role"; roleLabel.append(role);
  for (const value of ["viewer", "operator", "administrator"]) { const option = el("option", "", value); option.value = value; role.append(option); }
  const label = el("input"); label.name = "label"; label.maxLength = 64; label.setAttribute("aria-label", "토큰 이름표"); label.placeholder = "이름표";
  const add = el("ui-button", "", "새 토큰 생성"); add.setAttribute("kind", "primary"); add.type = "submit"; tokenForm.append(roleLabel, label, add);
  const tokenList = el("ul", "diagnostic-list"); tokenList.setAttribute("aria-label", "접근 토큰 목록");
  tokenSection.append(tokenForm, tokenList);

  const safetySection = el("section", "ui-readback"); safetySection.append(el("h3", "", "안전 정책 한계"));
  const safetyForm = el("form", "ui-form");
  const fields = [numberField("수동 선속도 (m/s)", "manual_linear", 10, 0), numberField("수동 각속도 (rad/s)", "manual_angular", 20, 0),
    numberField("배터리 경고 (%)", "battery_warning_percent"), numberField("배터리 위험 (%)", "battery_critical_percent"), numberField("배터리 심각 (%)", "battery_deep_percent")];
  const fleet = el("select"); fleet.name = "fleet_loss_policy"; fleet.setAttribute("aria-label", "연결 끊김 정책");
  for (const value of ["STOP", "HOLD", "RETURN_HOME", "CONTINUE"]) { const option = el("option", "", value); option.value = value; fleet.append(option); }
  const batteryPolicy = el("select"); batteryPolicy.name = "battery_critical_policy"; batteryPolicy.setAttribute("aria-label", "배터리 위험 정책");
  for (const value of ["STOP", "RETURN_HOME"]) { const option = el("option", "", value); option.value = value; batteryPolicy.append(option); }
  const fleetLabel = el("label", "ui-field-label", "연결 끊김 정책"); fleetLabel.append(fleet);
  const batteryLabel = el("label", "ui-field-label", "배터리 위험 정책"); batteryLabel.append(batteryPolicy);
  const save = el("ui-button", "", "정책 저장"); save.setAttribute("kind", "primary"); save.type = "submit";
  safetyForm.append(...fields.map((item) => item.label), fleetLabel, batteryLabel, save);
  safetySection.append(safetyForm); root.append(head, notice, tokenSection, safetySection);

  let tokens = [];
  function renderTokens(payload) {
    tokens = payload.tokens || []; tokenList.replaceChildren();
    if (!tokens.length) tokenList.append(el("li", "", "등록된 토큰이 없습니다."));
    for (const token of tokens) {
      const row = el("li", ""); row.dataset.tokenId = token.id;
      row.append(el("span", "", [token.label || token.id, token.role, token.source, token.current ? "이 기기" : ""].filter(Boolean).join(" · ")));
      const remove = el("ui-button", "", "삭제"); remove.setAttribute("kind", "irreversible"); remove.type = "button"; remove.disabled = token.current === true;
      remove.addEventListener("click", async () => {
        if (remove.disabled || !window.confirm("이 토큰을 삭제할까요? 되돌릴 수 없습니다.")) return;
        try { await ctx.api(`/api/v1/system/tokens/${encodeURIComponent(token.id)}`, {method: "DELETE"}); await loadTokens(); }
        catch (error) { notice.textContent = `토큰 삭제 실패: ${error.message}`; }
      }); row.append(remove); tokenList.append(row);
    }
  }
  async function loadTokens() { renderTokens(await ctx.api("/api/v1/system/tokens")); }
  const stopTokens = ctx.store.poll("/api/v1/system/tokens", 30_000, renderTokens, (error) => { notice.textContent = `토큰 목록을 가져오지 못했습니다: ${error.message}`; });
  tokenForm.addEventListener("submit", async (event) => {
    event.preventDefault(); add.disabled = true;
    try {
      const created = await ctx.api("/api/v1/system/tokens", {method: "POST", body: JSON.stringify({role: role.value, label: label.value.trim()})});
      notice.textContent = created.token ? `토큰이 생성되었습니다. 다시 볼 수 없으니 지금 안전한 곳에 기록하세요: ${created.token}` : "토큰이 생성되었습니다.";
      label.value = ""; await loadTokens();
    } catch (error) { notice.textContent = `토큰 생성 실패: ${error.message}`; }
    finally { add.disabled = false; }
  });

  const stopSafety = ctx.store.poll("/api/v1/safety/state", 15_000, (data) => {
    const limits = data.limits || {}; const battery = data.battery || {};
    fields[0].input.value = limits.manual_linear ?? ""; fields[1].input.value = limits.manual_angular ?? "";
    fields[2].input.value = battery.warning_percent ?? ""; fields[3].input.value = battery.critical_percent ?? ""; fields[4].input.value = battery.deep_percent ?? "";
    fleet.value = data.fleet_loss_policy || "STOP"; batteryPolicy.value = battery.critical_policy || "STOP";
  }, (error) => { notice.textContent = `안전 정책을 읽지 못했습니다: ${error.message}`; });
  safetyForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = fields.map((item) => Number(item.input.value));
    if (!values.every(Number.isFinite) || !(values[4] < values[3] && values[3] < values[2])) {
      notice.textContent = "배터리 임계값은 심각 < 위험 < 경고 순서여야 합니다."; return;
    }
    save.disabled = true;
    try {
      await ctx.api("/api/v1/safety/limits", {method: "PUT", body: JSON.stringify({manual_linear: values[0], manual_angular: values[1], battery_warning_percent: values[2], battery_critical_percent: values[3], battery_deep_percent: values[4], fleet_loss_policy: fleet.value, battery_critical_policy: batteryPolicy.value})});
      notice.textContent = "안전 정책을 저장했습니다.";
    } catch (error) { notice.textContent = `안전 정책 저장 실패: ${error.message}`; }
    finally { save.disabled = false; }
  });
  return () => { stopTokens(); stopSafety(); };
}
