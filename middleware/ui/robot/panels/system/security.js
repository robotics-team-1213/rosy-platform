import {mountReceiverApprovals} from "/assets/peer-approval.js";
import { ROLE_LABEL, SAFETY_POLICY_LABEL, TOKEN_SOURCE_LABEL, enumLabel } from "/common/core_ui_logic.js";
import { confirmIrreversible } from "/common/ui.js";
// D-359 §5.3 — 끌 때 이유를 같이 준다. 켜거나 짧은 요청 중 잠금이면 이유를 지운다.
function setOff(control, off, reason = "") { control.disabled = Boolean(off); if (off && reason) control.setAttribute("reason", reason); else control.removeAttribute("reason"); }
// Admin-only credential and safety policy controls. Generated credentials are
// rendered once in a live status node and are never persisted by this module.
function el(tag, cls, text) { const node = document.createElement(tag); if (tag === "ui-status") node.setAttribute("state", "ready"); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
function numberField(labelText, name, max = 100, min = 0.01) {
  const label = el("label", "ui-field-label", labelText); const input = el("input", "ui-field");
  input.type = "number"; input.min = String(min); input.max = String(max); input.step = "any"; input.name = name; label.append(input);
  return {label, input};
}

export function mount(root, ctx) {
  const lifetime = new AbortController(); let disposed = false; let confirming = false;
  const head = el("ui-head", "", "보안 및 안전 정책");
  const tokenReadStatus = el("ui-status", "", "토큰 목록을 불러오는 중입니다.");
  const tokenActionStatus = el("ui-status");
  const tokenCredentialStatus = el("ui-status");

  const tokenSection = el("section", "ui-readback"); tokenSection.append(el("h3", "", "접근 토큰"));
  const tokenForm = el("form", "ui-form");
  const roleLabel = el("label", "ui-field-label", "역할");
  const role = el("select", "ui-field"); role.name = "role"; roleLabel.append(role);
  for (const value of ["viewer", "operator", "administrator"]) { const option = el("option", "", enumLabel(ROLE_LABEL, value)); option.value = value; role.append(option); }
  const label = el("input", "ui-field"); label.name = "label"; label.maxLength = 64; label.setAttribute("aria-label", "토큰 이름표"); label.placeholder = "이름표";
  const add = el("ui-button", "", "새 토큰 생성"); add.setAttribute("kind", "primary"); add.type = "submit"; tokenForm.append(roleLabel, label, add);
  const tokenList = el("ul", "diagnostic-list"); tokenList.setAttribute("aria-label", "접근 토큰 목록");
  tokenList.hidden = true;
  tokenSection.append(tokenForm, tokenActionStatus, tokenCredentialStatus, tokenReadStatus, tokenList);

  const safetySection = el("section", "ui-readback"); safetySection.append(el("h3", "", "안전 정책 한계"));
  const safetyReadStatus = el("ui-status", "", "안전 정책을 불러오는 중입니다.");
  const safetyActionStatus = el("ui-status");
  const safetyForm = el("form", "ui-form");
  const fields = [numberField("수동 선속도 (m/s)", "manual_linear", 10, 0), numberField("수동 각속도 (rad/s)", "manual_angular", 20, 0),
    numberField("배터리 경고 (%)", "battery_warning_percent"), numberField("배터리 위험 (%)", "battery_critical_percent"), numberField("배터리 심각 (%)", "battery_deep_percent")];
  const fleet = el("select", "ui-field"); fleet.name = "fleet_loss_policy"; fleet.setAttribute("aria-label", "연결 끊김 정책");
  for (const value of ["STOP", "HOLD", "RETURN_HOME", "CONTINUE"]) { const option = el("option", "", enumLabel(SAFETY_POLICY_LABEL, value)); option.value = value; fleet.append(option); }
  const batteryPolicy = el("select", "ui-field"); batteryPolicy.name = "battery_critical_policy"; batteryPolicy.setAttribute("aria-label", "배터리 위험 정책");
  for (const value of ["STOP", "RETURN_HOME"]) { const option = el("option", "", enumLabel(SAFETY_POLICY_LABEL, value)); option.value = value; batteryPolicy.append(option); }
  const fleetLabel = el("label", "ui-field-label", "연결 끊김 정책"); fleetLabel.append(fleet);
  const batteryLabel = el("label", "ui-field-label", "배터리 위험 정책"); batteryLabel.append(batteryPolicy);
  const save = el("ui-button", "", "정책 저장"); save.setAttribute("kind", "primary"); save.type = "submit";
  safetyForm.append(...fields.map((item) => item.label), fleetLabel, batteryLabel, save);
  safetySection.append(safetyForm, safetyReadStatus, safetyActionStatus);
  root.append(head);
  const stopReceiver=mountReceiverApprovals(root,ctx);
  root.append(tokenSection,safetySection);

  let tokens = []; let tokenMutationPending = false;
  let safetyDirty = false; let safetyPending = false;
  const safetyControls = [...fields.map((item) => item.input), fleet, batteryPolicy, save];
  function setStatus(target, text) { if (!disposed && target.textContent !== text) target.textContent = text; }
  function syncTokenControls() {
    add.disabled = tokenMutationPending;
    for (const button of tokenList.querySelectorAll("ui-button")) {
      const token = tokens.find((item) => String(item.id) === button.closest("li")?.dataset.tokenId);
      setOff(button, tokenMutationPending || token?.current === true, tokenMutationPending ? "" : "지금 쓰는 토큰");
    }
  }
  function syncSafetyControls() { safetyControls.forEach((control) => { control.disabled = safetyPending; }); }
  function renderTokens(payload) {
    if (disposed) return;
    tokens = payload.tokens || []; tokenList.replaceChildren(); tokenList.hidden = false;
    setStatus(tokenReadStatus, "");
    if (!tokens.length) tokenList.append(el("li", "", "등록된 토큰이 없습니다."));
    for (const token of tokens) {
      const row = el("li", ""); row.dataset.tokenId = token.id;
      row.append(el("span", "", [token.label || token.id, enumLabel(ROLE_LABEL, token.role), enumLabel(TOKEN_SOURCE_LABEL, token.source), token.current ? "이 기기" : ""].filter(Boolean).join(" · ")));
      // D-371 — 목록 행은 조용한 `삭제…`다. 위험 채움은 확인 대화상자의 실행 버튼에만 있다.
      const remove = el("ui-button", "", "삭제…"); remove.setAttribute("kind", "quiet"); remove.type = "button"; setOff(remove, token.current === true, "지금 쓰는 토큰");
      remove.addEventListener("click", async () => {
        if (disposed || confirming || remove.disabled || tokenMutationPending) return;
        confirming = true;
        const confirmed = await confirmIrreversible({message: `"${token.label || token.id}" 토큰을 삭제할까요? 되돌릴 수 없습니다.`, action: "토큰 삭제", signal: lifetime.signal,
          opener: () => (remove.isConnected ? remove : tokenList.querySelector(`li[data-token-id="${CSS.escape(String(token.id))}"] ui-button`))});
        confirming = false;
        if (!confirmed || disposed || tokenMutationPending || !tokens.some(item => item.id === token.id && item.current !== true && item.label === token.label)) return;
        tokenMutationPending = true; syncTokenControls();
        setStatus(tokenActionStatus, `${token.label || token.id} 토큰을 삭제하는 중입니다.`);
        try {
          await ctx.api(`/api/v1/system/tokens/${encodeURIComponent(token.id)}`, {method: "DELETE", signal: lifetime.signal});
          if (disposed) return;
          setStatus(tokenActionStatus, `${token.label || token.id} 토큰을 삭제했습니다.`);
          try { await loadTokens(); }
          catch (error) { tokensUnavailable(error, "삭제 결과는 유지하고 이전 목록은 숨긴 뒤 다시 확인 중입니다"); }
        } catch (error) { setStatus(tokenActionStatus, `토큰 삭제 실패: ${error.message}`); }
        finally { tokenMutationPending = false; if (!disposed) syncTokenControls(); }
      }); row.append(remove); tokenList.append(row);
    }
    syncTokenControls();
  }
  async function loadTokens() { if (disposed) return; renderTokens(await ctx.api("/api/v1/system/tokens")); }
  function tokensUnavailable(error, context = "이전 목록은 숨기고 다시 확인 중입니다") {
    if (disposed) return;
    tokens = []; tokenList.replaceChildren(); tokenList.hidden = true;
    setStatus(tokenReadStatus, `토큰 목록을 읽지 못했습니다. ${context}: ${error.message}`);
  }
  const stopTokens = ctx.store.poll("/api/v1/system/tokens", 30_000, renderTokens, tokensUnavailable);
  tokenForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (disposed || tokenMutationPending) return;
    tokenMutationPending = true; syncTokenControls();
    tokenCredentialStatus.textContent = "";
    setStatus(tokenActionStatus, "새 토큰을 생성하는 중입니다.");
    try {
      const created = await ctx.api("/api/v1/system/tokens", {method: "POST", body: JSON.stringify({role: role.value, label: label.value.trim()})});
      if (disposed) return;
      tokenCredentialStatus.textContent = created.token
        ? `생성된 토큰은 다시 표시되지 않습니다. 안전한 곳에 기록하세요: ${created.token}`
        : "토큰이 생성되었습니다.";
      setStatus(tokenActionStatus, "토큰 생성 요청을 CORE가 처리했습니다.");
      label.value = "";
      try { await loadTokens(); }
      catch (error) { tokensUnavailable(error, "토큰 생성 결과와 비밀값은 위에 유지하고 이전 목록은 숨깁니다. 다시 확인 중입니다"); }
    } catch (error) { setStatus(tokenActionStatus, `토큰 생성 실패: ${error.message}`); }
    finally { tokenMutationPending = false; if (!disposed) syncTokenControls(); }
  });

  function renderSafety(data) {
    if (disposed) return;
    const limits = data.limits || {}; const battery = data.battery || {};
    if (!safetyDirty) {
      fields[0].input.value = limits.manual_linear ?? ""; fields[1].input.value = limits.manual_angular ?? "";
      fields[2].input.value = battery.warning_percent ?? ""; fields[3].input.value = battery.critical_percent ?? ""; fields[4].input.value = battery.deep_percent ?? "";
      for (const [control, value] of [[fleet, data.fleet_loss_policy], [batteryPolicy, battery.critical_policy]]) {
        const raw = value == null ? "" : String(value);
        if (![...control.options].some(option => option.value === raw)) { const option = el("option", "", enumLabel(SAFETY_POLICY_LABEL, raw)); option.value = raw; control.append(option); }
        control.value = raw;
      }
      setStatus(safetyReadStatus, "안전 정책 현재값을 읽었습니다.");
    } else setStatus(safetyReadStatus, "수정 중인 입력값을 유지하고 있습니다.");
  }
  const stopSafety = ctx.store.poll("/api/v1/safety/state", 15_000, renderSafety, (error) => {
    setStatus(safetyReadStatus, `안전 정책을 읽지 못했습니다: ${error.message}`);
  });
  function markSafetyDirty() {
    safetyDirty = true;
    setStatus(safetyActionStatus, "저장되지 않은 수정 사항이 있습니다.");
  }
  safetyForm.addEventListener("input", markSafetyDirty);
  safetyForm.addEventListener("change", markSafetyDirty);
  safetyForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (disposed || safetyPending) return;
    const values = fields.map((item) => Number(item.input.value));
    if (!values.every(Number.isFinite) || !(values[4] < values[3] && values[3] < values[2])) {
      setStatus(safetyActionStatus, "배터리 임계값은 심각 < 위험 < 경고 순서여야 합니다."); return;
    }
    safetyPending = true; syncSafetyControls();
    setStatus(safetyActionStatus, "안전 정책 저장 요청을 보내는 중입니다.");
    try {
      const readback = await ctx.api("/api/v1/safety/limits", {method: "PUT", body: JSON.stringify({manual_linear: values[0], manual_angular: values[1], battery_warning_percent: values[2], battery_critical_percent: values[3], battery_deep_percent: values[4], fleet_loss_policy: fleet.value, battery_critical_policy: batteryPolicy.value})});
      if (disposed) return;
      safetyDirty = false; renderSafety(readback);
      setStatus(safetyActionStatus, "안전 정책을 저장했고 CORE 응답값을 화면에 반영했습니다.");
    } catch (error) { setStatus(safetyActionStatus, `안전 정책 저장 실패: ${error.message}`); }
    finally { safetyPending = false; if (!disposed) syncSafetyControls(); }
  });
  return () => { stopReceiver(); disposed = true; lifetime.abort(); stopTokens(); stopSafety(); };
}
