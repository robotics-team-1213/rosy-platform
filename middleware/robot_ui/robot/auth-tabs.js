// K9 tabs: the two login methods of the auth drawer (robot screen code / API token). One definition for both routes;
// entry-router.js mounts it before any module captures element ids, so #code-form and #auth-form keep their ids.
import {createTabs} from "/common/interaction-controls.js";

export function mountAuthTabs(drawer) {
  const slot = drawer.querySelector("[data-auth-tabs]");
  const forms = {code: drawer.querySelector("#code-form"), token: drawer.querySelector("#auth-form")};
  for (const form of Object.values(forms)) { form.removeAttribute("role"); form.removeAttribute("aria-labelledby"); }
  const tabs = createTabs({
    id: "auth-login", label: "로그인 방법",
    tabs: [{id: "code", label: "로봇 화면 코드", content: forms.code, panelId: "auth-panel-code"},
      {id: "token", label: "API 토큰", content: forms.token, panelId: "auth-panel-token"}],
    onChange: (key) => drawer.querySelector(key === "code" ? "#code-input" : "#token-input").focus(),
  });
  tabs.element.dataset.authTabs = "";   // the tabs take the slot's hook
  slot.replaceWith(tabs.element);
  return tabs;
}
