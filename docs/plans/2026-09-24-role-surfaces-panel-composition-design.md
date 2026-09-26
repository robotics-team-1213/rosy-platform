# 역할별 화면과 패널 조립 설계

- 날짜: 2026-09-24
- 상태: 설계 승인됨 (구현 계획 전)
- 관련: concept 16 §2/§8/§9, D-23, D-68, D-75, D-77, D-101, D-12, D-129, D-130, D-157, D-193, D-194, D-196(초안)
- 예정 ADR: **D-204 — 역할별 CORE 화면과 패널 계약**

## 1. 문제

CORE `/dashboard` 한 페이지가 서로 다른 사람의 서로 다른 질문을 모두 받는다.

- 현장 운용(모드, 텔레옵, 지도 목표), 작업 준비(SLAM, 웨이포인트, 도크 등록, 교통 정책),
  설치·정비(호스트, 네트워크, ROS 그래프, 릴리스, 토큰, 안전 한계)가 `운용`/`점검` 두 뷰에 섞여 있다.
- `app.js` 1548줄이 로그인, WebSocket 두 개, 텔레메트리, 비전, 라인 추종, 교통, 텔레옵, 호스트 카드,
  ROS 그래프, 이벤트를 모두 소유한다. JS에는 D-168 같은 파일 예산이 없다.
- 패널은 HTML에 항상 존재하고, capability 판단은 JS 곳곳(`app.js:58,226,588,633,648,734`,
  `settings.js:101`, `triage.js:51`)에 흩어져 있다. concept 16 §8의 "`not_provided`는 생략, 회색 금지"가
  구조로 보장되지 않는다.
- 자산 허용목록(`api/app.py:76-87`)은 손으로 적는 목록이라 모듈을 추가할 때마다 서버 코드가 바뀐다.

concept 16 §2는 이미 Robot console과 Device runtime을 다른 화면으로 정의했지만, Device runtime은
여전히 `/dashboard`의 한 뷰로 살고 있다.

## 2. 결정 요약

1. **조립 축은 역할→화면, 기능→패널이다.** 화면은 역할(누가 어떤 질문을 하는가)로 나누고,
   화면 안의 패널은 로봇이 선언한 capability로 끼운다. 기기(device family)는 renderer를 싣지 않는다(concept 16 §8).
2. **CORE는 화면 세 개를 제공한다.** `/console`(운용), `/setup`(작업 준비), `/device`(설치·정비).
3. **조립은 서버 매니페스트와 동적 `import()`로 한다.** 패널 레지스트리(YAML)를 CORE가 capability와
   요청자 역할로 걸러 매니페스트로 내주고, 셸은 그 목록의 패널 모듈만 불러 mount한다.
4. **범위.** 이번 스펙은 CORE 세 화면과 패널 계약·레지스트리까지다. Fleet 콘솔은 같은 계약으로 옮기는
   후속 스펙(S5)이다. control 진단 페이지(D-77/D-150)와 Gazebo lane viewer는 디버그 화면으로 동결하고
   이 작업에서 기능을 늘리지 않는다. Games 보드(D-101)는 범위 밖이다.

## 3. 화면

| 화면 | URL | 질문 | 기본 최소 역할 | 문법(D-130) |
|---|---|---|---|---|
| 운용 | `/console` | "지금 이 로봇을 보내도 되나?" | viewer | spatial: sense / observe / act |
| 작업 준비 | `/setup` | "작업할 준비가 됐나?" | operator | procedural |
| 설치·정비 | `/device` | "기기가 제대로 서 있나?" | administrator | procedural |

- 화면의 최소 역할은 기본값이다. 실제 노출은 패널별 `min_role`로 정하고, 보이는 패널이 하나도 없는
  화면은 화면 전환기에서 빠진다.
- UI의 역할 판단은 표시용일 뿐이다. 권한의 정본은 여전히 API의 `require_role`이다(`api/v1/common.py:14-16`).
  UI가 API보다 엄격한 것은 허용하고, 느슨한 것은 금지한다.
- **e-stop은 패널이 아니다.** 세 화면 모두 셸의 같은 고정 위치에 하나만 둔다(concept 16 §9.2).
  `POST /safety/stop`은 viewer 권한이므로 로그인한 누구에게나 보인다. 해제(`/safety/release`, administrator)는
  운용 화면 act 슬롯의 패널이다.
- 상단바에는 역할이 열 수 있는 화면만 나오는 전환기, whoami 배지, 로그인 서랍(D-193)을 둔다. 셸 소유다.
- `/dashboard`는 이관 기간에 `/console`로 리다이렉트하고, S4 완료 후 한 릴리스 뒤에 제거한다.
- 각 화면은 한 문법만 쓴다. 운용 화면에 설정 폼이 들어오거나 정비 화면에 지도 목표 지정이 들어오면 잘못이다.

### 3.1 기존 기능의 배치

| 기존 패널 (`index.html` 줄) | 화면 / 슬롯 | `requires` | `min_role` |
|---|---|---|---|
| 안전·모드 hero (95-110) | console / sense | — | viewer |
| 텔레메트리 (115-133) | console / sense | — | viewer |
| triage 배너 (85-93) | console / banner | — | viewer |
| 전방 카메라 + 인지 overlay (149-168) | console / observe | `vision.enabled` | viewer |
| 지도·costmap·경로, 목표 지정 (169-200) | console / observe | `navigation.goal_navigation` | viewer (목표 지정 동작은 operator) |
| 모드 IDLE/MANUAL/NAV (205-224) | console / act | — | operator |
| 안전 해제 (205-224 일부) | console / act | — | administrator |
| 라인 추종 (225-244) | console / act | 라인 추종 capability | operator |
| 교통 인지 상태 (245-283 읽기 부분) | console / sense | 교통 capability | viewer |
| HITL (284-288) | console / act | — | operator |
| 저속 텔레옵 (289-307) | console / act | `teleop` | operator |
| 도킹 실행: dock/undock/cancel (605 일부) | console / act | `docking.supported` | operator |
| 초기 위치 설정 (map.js) | setup | `navigation.goal_navigation` | operator |
| SLAM 세션 (585) | setup | `slam` | operator |
| 웨이포인트 편집 (528) | setup | `navigation.goal_navigation` | operator |
| 도크 등록·유형 (605 일부) | setup | `docking.supported` | operator |
| 교통 정책 stage/apply, SIM 신호 (245-283 쓰기 부분) | setup | 교통 capability | operator |
| 호스트 상태 (317-353) | device | — | administrator |
| 네트워크 (355-402) | device | — | administrator |
| ROS 격리·그래프 (404-442) | device | — | administrator |
| 릴리스·커미셔닝 (444-477) | device | — | administrator |
| identity (487) | device | — | administrator |
| API 토큰 (503) | device | — | administrator |
| 안전 한계 정책 (547) | device | — | administrator |
| capability / inventory (134-144) | device | — | administrator |
| 최근 이벤트 (642) | device | — | administrator |

- `requires`의 정확한 CAP-001 키 이름(라인 추종, 교통)은 S1에서 `capabilities.*.yaml`을 기준으로 확정해
  레지스트리에 적는다. 키가 없는 기능은 새 키를 만들지 않고 `requires: []`로 둔다.
- 스웜/Fleet 설정 카드(628)는 정적 문구뿐이고 `web/AGENTS.md`가 로봇 콘솔의 Fleet UI를 금지하므로 삭제한다.
- 대시보드가 아직 쓰지 않는 라우터(`/diagnostics`, `/logs`, `/metrics`, `/power`, `/sensors`)는
  이 작업에서 패널을 새로 만들지 않는다. 필요해지면 레지스트리 한 줄과 패널 파일 하나로 `/device`에 붙인다.

## 4. 패널 계약

패널은 레고 블록 하나다. 한 capability의 한 역할을 한 화면에서 그린다.

```js
// web/panels/<domain>/<id>.js
export function mount(el, ctx) {
  // el: 셸이 슬롯 안에 만든 빈 컨테이너
  // ctx.store  : 공유 상태 구독. ctx.store.select(fn, onChange) → unsubscribe
  // ctx.api    : client.js의 인증된 fetch 래퍼
  // ctx.role   : "viewer" | "operator" | "administrator"
  // ctx.panel  : 매니페스트 항목 { id, state, reason }
  return function unmount() { /* 구독 해제, 타이머 정리 */ };
}
```

규칙:

1. 패널은 다른 패널을 import하거나 호출하지 않는다. 공유는 `ctx.store`와 `ctx.api`로만 한다.
2. WebSocket은 셸이 하나만 연다. 패널은 연결을 열지 않는다. 느린 폴링이 필요하면 `ctx.store`의
   폴링 등록 API를 쓴다(셸이 지금의 `refreshSlowData()`처럼 묶어서 돈다).
3. 화면은 `web_common`의 `ui-*` 요소로만 그린다(D-194). inline `style=`, `el.style`, inline script는 없다(CSP).
   패널 전용 CSS가 필요하면 레지스트리의 `css`로 선언한다. 색은 토큰으로만 쓴다(D-129).
4. 데이터 신선도(staleness)는 패널이 스스로 판단하고 `ui-evidence`로 표시한다(concept 16 §9.3).
5. 되돌릴 수 없는 동작(Law 3)은 셸이 제공하는 공용 확인 절차를 거친다.
6. `mount`가 예외를 던지면 셸이 그 슬롯만 `ui-empty`와 오류 문구로 바꾸고 다른 패널은 계속 돈다.
7. 파일 예산: 패널 JS 400줄, 셸 JS 300줄. 테스트로 강제한다.

L1.5 headless 로직(evidence 판정, 지도 좌표 변환 같은 순수 함수)은 둘 이상의 화면이 쓰게 될 때
`web_common`으로 올린다(D-157). 그리기(renderer)는 화면에 남는다.

## 5. 레지스트리와 매니페스트

### 5.1 레지스트리

`src/core/core_api_web/core_api_web/web/panels.yaml`:

```yaml
version: 1
surfaces:
  console: { min_role: viewer,        grammar: spatial,    slots: [banner, sense, observe, act] }
  setup:   { min_role: operator,      grammar: procedural, slots: [main] }
  device:  { min_role: administrator, grammar: procedural, slots: [main] }
panels:
  - id: drive.teleop
    surface: console
    slot: act
    order: 40
    requires: [teleop]          # CAP-001 키, 전부 참이어야 함
    inventory: mobility.teleop  # 선택: inventory 설명자에서 동적 state/reason
    min_role: operator
    module: panels/drive/teleop.js
    css: [panels/drive/teleop.css]
```

CORE는 기동할 때 레지스트리를 검증하고, 틀리면 기동을 거부한다.

- surface·slot 이름이 선언과 다름
- `id` 중복, 같은 슬롯 안의 `order` 중복
- `module`·`css` 파일 없음, `web/panels/` 밖을 가리키는 경로
- 모르는 역할 이름
- `requires`가 CAP-001 스키마에 없는 키

### 5.2 매니페스트 API

`GET /api/v1/ui/surfaces/{surface}` (viewer 이상):

```json
{
  "surface": "console",
  "grammar": "spatial",
  "revision": "sha256:…",
  "surfaces": ["console", "setup"],
  "panels": [
    { "id": "drive.teleop", "slot": "act", "order": 40,
      "module": "/console/assets/panels/drive/teleop.js",
      "css": ["/console/assets/panels/drive/teleop.css"],
      "state": "available", "reason": null }
  ]
}
```

필터 규칙:

1. `requires` 중 하나라도 CAP-001에서 거짓이면 그 패널은 **목록에서 빠진다**(`not_provided`, concept 16 §8).
2. 요청자 역할이 `min_role`보다 낮으면 빠진다.
3. `inventory`가 있으면 그 설명자의 `state`/`reason`을 싣는다. `blocked`는 `reason`이 반드시 있어야 한다.
   inventory가 없거나 설명자가 없으면 `available`이다.
4. `surfaces`는 요청자가 열 수 있는(보이는 패널이 하나 이상인) 화면 목록이다.

CAP-001과 inventory를 합치지 않는다(D-68). 매니페스트는 둘을 읽기만 하고, 두 문서의 본문은 바뀌지 않는다.
매니페스트는 요청마다 계산하고 본문 해시를 `revision`으로 함께 내준다. capability가 런타임에 바뀌면
(D-62 슬라이스, US-010) 셸이 다시 조립해야 한다. S1에서 `/ws/state`에 이미 capability·inventory 변경을
알 수 있는 필드가 있는지 확인한다. 있으면 그 변경에 맞춰, 없으면 셸의 느린 폴링 주기에 매니페스트를
다시 받아 `revision`이 바뀌었을 때만 다시 조립한다. 이 때문에 WebSocket 계약을 새로 늘리지 않는다.

### 5.3 자산 서빙

- 허용목록은 셸 파일 집합과 레지스트리의 `module`·`css`에서 기동 시 만든다. 여전히 정확히 일치하는
  집합이며 폴더 스캔이 아니다(`app.py:78-79`의 경로 순회 방어 의도 유지).
- CSP는 바꾸지 않는다. 동적 `import()`는 `script-src 'self'`로 허용된다.
- 매니페스트에서 빠진 패널의 자산도 허용목록에는 있다. 자산은 권한 경계가 아니고, 권한은 API가 지킨다.

### 5.4 로봇마다 달라지는 방식

로봇별 화면 차이는 코드가 아니라 capability가 만든다. profile과 capability YAML(지금은
`deploy/robot/config/capabilities.*.yaml`, D-196 이후에는 `ROSY_ROBOT`이 고르는 `share/<robot.model>/config/`)이
참인 키를 정하고, 매니페스트가 그에 맞는 패널만 내준다.

예: OMX 팔을 붙이려면 `panels/manip/grip.js` 하나와 레지스트리 한 줄(`requires: [omx.enabled]`,
`surface: console`, `slot: act`)을 추가한다. 레이아웃은 역할이 정하므로 다른 패널 위치는 바뀌지 않는다(§9.1).

로봇별 레이아웃 파일이나 사용자 배치 저장은 만들지 않는다.

## 6. 파일 구조 (목표)

```
core_api_web/web/
  shell/            shell.html(화면 공통 틀), shell.js, store.js, client.js, dom.js, confirm.js, shell.css
  panels.yaml
  panels/
    safety/         hero.js, release.js
    telemetry/      summary.js
    vision/         front.js
    nav/            map.js, initial_pose.js, waypoints.js, slam.js
    drive/          mode.js, teleop.js, line_follow.js
    traffic/        status.js, policy.js
    docking/        run.js, register.js
    hitl/           request.js
    host/           status.js, network.js, release.js
    ros/            graph.js
    system/         identity.js, tokens.js, safety_limits.js, capabilities.js, events.js
  styleguide.html, styleguide.css   (그대로)
core_api_web/api/
  ui_registry.py    레지스트리 로드·검증 (ROS 비의존)
  v1/ui.py          매니페스트 라우터
```

`triage.js`는 운용 화면 banner 패널이 된다. `settings.js`는 해체되어 setup·device 패널로 흩어진다.

## 7. 이관 단계

각 단계는 그 자체로 배포 가능해야 하며, 끝날 때 `/dashboard`(또는 리다이렉트된 `/console`)가 동작한다.

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| S0 | ADR D-204 작성, concept 16 §2 표 갱신, 계약 테스트 골격 | ADR 머지 |
| S1 | `ui_registry.py`, `/api/v1/ui/surfaces/*`, 셸·store 추출, 허용목록 생성. 기존 패널은 임시로 "legacy" 패널 하나로 감싸 화면 변화 없음 | 기존 대시보드 테스트 통과, 매니페스트 테스트 통과 |
| S2 | `/device` 화면: 호스트·네트워크·ROS·릴리스·identity·토큰·안전 한계·capability·이벤트 패널 이관 | `/dashboard` 점검 뷰에서 해당 카드 제거 |
| S3 | `/setup` 화면: SLAM·초기 위치·웨이포인트·도크 등록·교통 정책 패널 이관 | `settings.js` 삭제 |
| S4 | `/console`: 남은 운용 패널 이관, `/dashboard` → `/console` 리다이렉트, `app.js` 삭제, JS 줄 수 예산 테스트 | legacy 패널 0개 |
| S5 | (별도 스펙) Fleet 콘솔을 같은 패널 계약으로, 지도 headless 로직 `web_common` 승격 | — |

## 8. 오류 처리

- 레지스트리 검증 실패: CORE 기동 거부, 원인을 로그에 한 줄로 남긴다.
- 매니페스트 요청 실패: 셸은 e-stop과 오류 배너만 남기고 5초 간격으로 재시도한다.
- 패널 모듈 import 실패 또는 `mount` 예외: 그 슬롯만 `ui-empty` + 패널 id + 오류, 나머지는 정상.
- capability 변경: 사라진 패널은 `unmount` 후 제거, 새 패널은 순서대로 삽입한다. 전체 새로고침은 하지 않는다.
- 역할이 낮아진 경우(토큰 교체 등): whoami 변경 시 매니페스트를 다시 받는다.

## 9. 테스트

- `ui_registry` 단위 테스트: §5.1의 각 검증 실패 사례.
- 매니페스트 필터 테스트: profile(core / motor / hardware) × 역할(viewer / operator / administrator) 조합에서
  기대 패널 집합을 고정한다. `not_provided` 패널이 목록에 없음을 확인한다.
- 허용목록 테스트: 레지스트리 밖 경로와 `..` 경로는 404.
- 문법 게이트(D-130, `test_shared_controls.py`)를 세 화면으로 확장: 화면당 `ui-shell grammar` 하나,
  inline style 없음, `ui-button kind` 필수.
- 줄 수 예산 테스트: `web/panels/**/*.js` ≤ 400, `web/shell/*.js` ≤ 300.
- 브라우저 확인: 세 화면 × profile 두 종의 스크린샷(sim 벤치). host pytest 통과는 기기 인수가 아니다.

## 10. 하지 않는 것

- 기기(device family)가 웹 코드를 싣는 구조. 패널은 모두 `core_api_web`에 산다.
- 사용자 드래그 배치, 로봇별 레이아웃 파일.
- 번들러, 프레임워크, 템플릿 엔진 도입(D-75).
- 로봇 콘솔의 Fleet/미션 UI(D-12), Games UI(D-101).
- control 진단 페이지와 lane viewer 개편.

## 11. 운영 메모

- 작업 트리에 커밋되지 않은 control 패키지 이동(`src/apps/control` → `src/core/control`)이 있고
  다른 세션이 같은 체크아웃에 커밋한다. 구현은 별도 worktree와 브랜치에서 한다.
- D-196(다중 로봇 구조)과 맞물리는 지점은 §5.4의 capability 출처 하나뿐이다. D-196이 먼저 들어와도
  이 설계는 바뀌지 않는다.
