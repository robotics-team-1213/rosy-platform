## D-218 웹 확인은 결과를 묻고, 없는 조작은 버튼이 되지 않는다

**Status:** Accepted (2026-09-25).
잇는 결정: D-92 제5항은 두 번째 웹 표면이 생기며 `window.confirm` 을 불가역 확인의 공유 문법으로 둔다. F-20은 모의 안내를 거짓 조작으로 본다.

**Context:** Fleet 콘솔은 개입이 필요할 때 `kind=irreversible` 버튼 "조종 (WebRTC)"를 그리고, 누르면 `alert(... Mock)` 만 띄웠다. 그 서버에는 원격 조종 능력이 없다. 경보가 할 수 없는 일을 할 수 있는 것처럼 말했다.

**Decision:**

1. **콘솔·Fleet·게임 표면에서 `alert` 와 `prompt` 는 쓰지 않는다.** 모의 성공 안내도 쓰지 않는다.
2. **`window.confirm` 은 핀된 파일과 횟수만 쓴다.** 지금 핀은 `app.js` 9, `settings.js` 11, `map.js` 1, Fleet `console.js` 1(전체 정지)이다. 횟수를 늘리는 커밋이 이 핀을 같이 고친다.
3. **확인 문장은 결과를 묻는다.** `까요`, `니까`, `확인` 중 하나로 무엇을 할지 말한다.
4. **없는 능력은 버튼을 만들지 않는다.** 개입 요청은 로봇 이름과 로봇 화면에서 확인하라는 문장만 남긴다. 원격 조종은 그 로봇의 대시보드에서 일어난다.

**Consequences:** Fleet 콘솔의 모의 WebRTC 버튼은 없다. 브라우저 네이티브 `confirm` 은 그대로 확인 문법이다.

**Validation:** `test/test_web_dialog_contract.py` 와 `src/site/fleet/test/test_console_queues_contract.py` 8건이 2026-09-25에 통과했다.
