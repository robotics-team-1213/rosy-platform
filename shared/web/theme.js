// D-359 §2.4 — 화면 테마 선택. `<head>`에서 tokens.css 바로 뒤에 동기로 싣는
// 평범한 외부 스크립트다(CSP가 인라인을 막는다). 첫 그림 전에
// `<html data-theme>`과 `meta[name=theme-color]`를 정한다.
//
// 선호는 `localStorage` `rosy.theme` = dark | light | system. 없거나 틀리거나
// 저장소를 못 읽으면 dark다(관제실·현장 조명 계약). system은
// `prefers-color-scheme`을 따르고 바뀌면 따라간다.
// `<html data-theme-pin="dark">` 표면은 선호와 무관하게 그 테마로 고정된다.
//
// API: window.RosyTheme = { get(), set(pref), resolved(), choices }. 바뀌면 document에
// `rosy:theme` 이벤트({theme, preference})를 낸다. choices는 선택지의 단일 출처다
// ([{value, label, icon}], 얼린 배열) — /device 화면 패널이 이것으로 버튼을 그리고, Fleet의
// 정적 버튼은 시험(test_theme_choices.py)이 이것과 대조한다.
// `[data-theme-choice]` 버튼(공용 segment)은 여기서 한 번에 이어진다 — 누르면
// set, 바뀌면 aria-pressed가 따라간다.
(function () {
  "use strict";

  var KEY = "rosy.theme";
  // 새 테마 = tokens.css의 팔레트 블록 하나 + 여기 한 줄(system 앞). system은 테마가 아니라
  // 기기 설정을 따르라는 선호다.
  // 선택지의 얼굴은 actionIcon 이름이다(D-405 — 어둡게=달, 밝게=해, 시스템=모니터).
  // 한국어 이름은 sr-only·title로 남는다. 그림은 ui.js가 그리고 크기는 .ui-icon이다.
  var CHOICES = [
    { value: "dark", label: "어둡게", icon: "theme-dark" },
    { value: "light", label: "밝게", icon: "theme-light" },
    { value: "system", label: "시스템", icon: "theme-system" },
  ];
  var PREFERENCES = CHOICES.map(function (choice) { return choice.value; });
  var FALLBACK = "dark";
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;

  function valid(value) {
    return PREFERENCES.indexOf(value) >= 0 ? value : FALLBACK;
  }

  function stored() {
    try {
      return valid(window.localStorage.getItem(KEY));
    } catch (error) {
      return FALLBACK;
    }
  }

  var preference = stored();

  function resolve(pref) {
    var pin = root.getAttribute("data-theme-pin");
    if (pin) return pin;
    if (pref === "system") return media && media.matches ? "light" : "dark";
    return pref;
  }

  function paintThemeColour() {
    var ground = window.getComputedStyle(root).getPropertyValue("--ground").trim();
    if (!ground) return;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "theme-color");
      (document.head || root).appendChild(meta);
    }
    meta.setAttribute("content", ground);
  }

  function syncChoices() {
    var buttons = document.querySelectorAll("[data-theme-choice]");
    for (var i = 0; i < buttons.length; i += 1) {
      var chosen = buttons[i].getAttribute("data-theme-choice") === preference;
      buttons[i].setAttribute("aria-pressed", chosen ? "true" : "false");
    }
  }

  function apply(announce) {
    var theme = resolve(preference);
    root.setAttribute("data-theme", theme);
    paintThemeColour();
    syncChoices();
    if (announce) {
      document.dispatchEvent(new CustomEvent("rosy:theme", {
        detail: { theme: theme, preference: preference },
      }));
    }
  }

  function set(pref) {
    var next = valid(pref);
    try {
      window.localStorage.setItem(KEY, next);
    } catch (error) {
      // 저장하지 못해도 이 페이지에서는 바꾼다. 다음 방문은 기본값이다.
    }
    if (next === preference) return;
    preference = next;
    apply(true);
  }

  if (media) {
    var follow = function () {
      if (preference === "system") apply(true);
    };
    if (media.addEventListener) media.addEventListener("change", follow);
    else if (media.addListener) media.addListener(follow);
  }

  document.addEventListener("click", function (event) {
    var target = event.target && event.target.closest ? event.target.closest("[data-theme-choice]") : null;
    if (target && !target.disabled) set(target.getAttribute("data-theme-choice"));
  });
  document.addEventListener("DOMContentLoaded", syncChoices);

  window.RosyTheme = {
    get: function () { return preference; },
    set: set,
    resolved: function () { return resolve(preference); },
    choices: Object.freeze(CHOICES.map(function (choice) { return Object.freeze(choice); })),
  };

  apply(false);
})();
