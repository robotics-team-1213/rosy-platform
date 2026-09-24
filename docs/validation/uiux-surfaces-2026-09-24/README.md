# UI/UX 표면 — 공예 회차 (2026-09-24, D-201·D-202·D-203)

운용자 세션의 요청으로 네 표면을 **계측된 눈**으로 다시 본 회차다. D-153의
세 계층(G1·G2·G3)이 아니라 그 아래 **공예 층위** — 적합(fit)·경보 대비·계산
척급 — 을 처음으로 측정했다. 회차 1(2026-09-21)이 전화 뷰포트만 찍고 비운
자리(노트북·사이트 PC·경기 노트북)에서 결함 다섯이 나왔다.

- 회차 조건: Windows HOST, 작업 트리 uncommitted(G-79). 증거 상한 LOCAL.
- 계측 수단: 저장소 브라우저 하네스(`test_dashboard_browser.py::_launch_page`
  를 그대로 재사용) + 계산 스타일 센서스(폰트 크기·대비·지오메트리·스크롤).
- 본 세션의 평가자는 픽셀을 직접 보지 못한다 — 대신 DOM·계산값·픽셀 통계를
  재는 계측으로 보았고, 그 한계를 여기에 기록한다(D-91 정신: 증거 계층을
  속이지 않는다). 사람 눈의 G3 최종 판정은 BENCH 회차의 몫으로 남는다.

## Result

| 표면 | 발견 | 처분 | 판정(LOCAL 한정) |
|---|---|---|---|
| 운용 콘솔(operate) | **F-15** 조작 열 분쇄 — 1536×864에서 모드 분절 제어가 44px→**2px**로 눌려 사라짐. 조작 열 자연 높이 1168px(프레임 729px) | D-201: 정책 편집→점검 현장 설정 카드, 차선·교통 계기값→감지 영역, `flex-shrink: 0`, 간격 최소 단계 | GO — 적합 게이트 4조합 통과 + 변이 증명 |
| 운용 콘솔(양 뷰) | **F-16** 계산 척급 누수 — 13.33/16.38/11.67px(em 체인·`<small>` UA 기본값·라벨 규칙 누락 h3) | D-203: 공용 라벨 규칙 보강, `ui-button small` 기본 규칙(web_common), em→토큰 | GO — 센서스 게이트 off-scale 0 + 변이 증명 |
| Fleet console | **F-12** 1920×1080에서 문서 755px 넘침 — 지도 캔버스가 정사각으로 자라고(1438×1438) 신호등·대형이 접힘 아래 | D-201: `object-fit: contain` + 뷰포트 상한, 로스터 패널 flex(목록만 내부 스크롤, 신호등·대형 항시 노출), 큐 패널 grid 영역 고정 | GO — 적합 게이트 + 변이 증명 |
| Fleet console | **F-13** `.tag.crit`가 위험색을 **글자**로 씀 — 실측 대비 **2.24:1** | D-202: 종이 잉크 + 위험 채움(ui-tag와 같은 얼굴), `.log .bad`도 채움 행 | GO — 따뜻한 글자 대비 게이트(전 노드 ≥4.5) + 변이 증명 |
| Fleet console | 큐 패널 토글이 `style.display` — 실서버 CSP `style-src 'self'`에서는 무시됨(옵트인 시험이 못 잡은 잠재 결함) | `hidden` 속성으로 교체 | 코드 증거 |
| 게임 보드 | **F-14** 1280×800에서 정지 행이 y=806 — 접힘 아래 | D-201: 피치 `max-height` 상한(초점 물체는 줄어들 수 있어도 정지를 밀 수 없다) | GO — halt 가시 게이트 + 변이 증명 |
| 로봇 얼굴(웨이크·부팅 카드) | **F-17** 경보 문장이 crit **글자** — E-STOP·FAILED·위험 배터리 숫자가 어두운 바탕 위 2.2:1. 회차 1의 팔레트 게이트는 *값*을 지켰지만 칠하는 *방식*은 재지 않았다 | D-202 얼굴 번역: `_draw_alarm` — 위험 채움 위 종이 잉크 칩. 배터리 게이지 봉은 이미 채움이라 그대로 | GO — 칩 픽셀 게이트 3종 + 정상 무색 게이트 + 변이 증명(칩→crit 글자 복귀로 적색) |
| 로봇 얼굴 / control 진단 | 진단은 PARKED(D-77) — 이 회차 미대상 | — | 변동 없음 |

또한 이 회차 중 발견: `test_gather_failure_names_itself_on_the_pill`이 옛
선택기(`class="bad"`)를 단언하고 있었다 — pill은 이미 `status="crit"` 속성으로
말하고 있었다. 옵트인 시험이 돌지 않으면 서류가 되는 실례(회차 1 F-11과 같은
계열). 단언을 현 계약으로 고쳤다.

## 게이트 (신설, 변이 증명 완료)

| 게이트 | 파일 | 변이 → 적색 |
|---|---|---|
| 조작 열 적합·무분쇄 (1536×864·1366×768 × fresh·safe-stop) | `test/test_dashboard_browser.py` | `flex` 원복 + 고블록 → `modeHeight: 2` 적색 |
| 계산 척급 폐쇄 (보이는 전 노드, 양 뷰) | 같은 파일 | h3 라벨 규칙 제거 → 16.38/18.72px 적색 |
| Fleet 문서 적합 + 신호등·대형 뷰포트 내 | `test/test_fleet_console_browser.py` | 지도 상한 제거 → 725px 적색 |
| Fleet 따뜻한 글자 대비 ≥4.5:1 | 같은 파일 | crit 글자 복귀 → 적색 |
| 게임 halt 행 뷰포트 내 | `test/test_games_board_browser.py` | 피치 상한 제거 → 429px 적색 |
| 얼굴 경보 침 = 종이 잉크 + 위험 채움 | `src/face/emotion/test/test_info_screen.py`·`test_info_screen_boot.py` | 칩을 crit 글자로 되돌림 → 3종 적색 |

## 증거

- `metrics-before/see_index.json`, `metrics-before/see_rest.json` — 수정 전
  계측(분쇄 439~479px, 대비 2.24:1, off-scale 7노드, 문서 넘침 755/88px).
- `metrics-after/see_after.json` — 수정 후 계측(전 항목 적합·off-scale 0).
- `captures/` — 콘솔 laptop·phone(operate/inspect) 6, Fleet 2, 게임 2,
  로봇 얼굴 웨이크 4 + 부팅 2(칩 렌더링 이후 재생성 —
  `ROSY_FACE_CAPTURE_DIR` 재현 경로는 위 Reproduce 참조).
  콘솔 laptop 캡처는 이 회차 신규(회차 1엔 전화만 있었다).

## Reproduce

```powershell
# 게이트(G1 언어) — 이 회차의 모든 판정은 이 명령들로 재현된다
$env:ROSY_RUN_BROWSER_TESTS="1"
python -m pytest test/test_dashboard_browser.py test/test_fleet_console_browser.py test/test_games_board_browser.py -q

# 로봇 얼굴(웨이크 4종 + 칩 게이트)
$env:PYTHONPATH="src/face/emotion"
python -m pytest src/face/emotion/test -q
# 캡처 재생
$env:ROSY_FACE_CAPTURE_DIR="docs\validation\uiux-surfaces-2026-09-24\captures"
python -m pytest src/face/emotion/test/test_info_screen_capture.py -q
```

## 다음 회차 과제

1. BENCH — 실물 뷰포트(노트북 1366×768 최소 높이 실측, 사이트 PC, 경기
   노트북)에서 같은 게이트를 연다. 로컬 적합은 실물 분량이 아니다(D-91).
2. 감지 영역 스크롤 분량(768−729=39px)은 문법이 허용하지만, 패널 배치
   재조정으로 0에 가깝게 만들 여지가 있는지 다음 회차에서 본다.
3. 게임 보드의 `#frame`(천장 프레임)과 피치가 동시에 보일 때의 적합은
   이 회차가 재지 않았다(play 상태만).

## 재검증 노트 (2026-09-25)

동시 세션의 커밋 6건(fleet succession·D-206/207·병합) 이후 전 게이트 재검증:
브라우저 43+13 passed, 단위 565 passed, 얼굴 47 passed, harness lint 0 오류.
한 번의 플레이크 — `test_warm_coloured_text_stays_readable`가 최대 경합
상태의 조합 실행에서 1회 적색 후 재현 없음(단독·파일·조합 재실행 4연속
통과). F-02와 같은 처분: 원인 미확인 종결. 게이트의 위반 목록 출력은
살아 있으니 재발 시 목록이 요소를 지목한다 — 실패 당시 실행자의 콘솔
필터가 목록을 버린 것이 유일한 손해였다. 기계 경합이 의심되는 근거:
같은 묶음의 소요가 113초→388초로 3.4배까지 늘어났다가 회복.

**ADR:** [D-201](../../adr/D-201-fixed-grammar-surfaces-fit-contract.md),
[D-202](../../adr/D-202-danger-is-a-fill-alarm-text-contrast-contract.md),
[D-203](../../adr/D-203-computed-type-scale-closure.md)
