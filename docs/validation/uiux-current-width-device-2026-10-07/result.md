# ROSY 역할 화면 폭과 Pilot 실물 설치본 재확인 — 2026-10-07

2026-10-07 20:39 KST까지의 읽기 전용 점검이다. 기준 소스는 로컬 `main` commit `befcc5d05f4e6d8e8d2b0da699635514d4285af9`다. 화면 캡처는 `961b5d654`에서 시작했고 실행 중 공유 `main`이 전진했지만, 두 커밋 사이에 로봇 화면·CORE 웹·공용 웹·캡처 도구 파일 변경은 없었다. 현재 후보의 제품 UI/UX 판정은 **HOLD**다.

## 로봇 역할 화면 — LOCAL

`python tools/capture_surface_round.py --out-dir X:/DevTemp/rosy-g1-current/robot-round`로 실제 FastAPI 화면을 합성 개발 인증 fixture에서 `/console`·`/setup`·`/device` × dark/light × 1280×800, 390×844, 320×568, 총 **18셀** 캡처했다. 18셀 모두 인증된 본문이 렌더됐고 문서 가로 넘침은 0이다. `/console`의 네 동등 패널 폭은 dark 기준 1280px에서 395.66–395.67px, 390px에서 모두 366px, 320px에서 모두 296px이었다. light도 같은 폭이며 320px에서 세 역할 화면의 비상 정지가 첫 화면에 보였다.

캡처 도구는 exit 1을 반환했다. `/console` 여섯 셀에서 합성 fixture의 지도·costmap GET이 404였고 `/device` 여섯 셀에서 호스트 SSH 상태 GET이 503이었다. 이는 **12셀의 응답 문제**이며 정상 지도·장치 상태 G2 증거로 쓸 수 없다. 보고서 `X:/DevTemp/rosy-g1-current/robot-round/report.json` SHA-256은 `8b16d2558cedd10cd69b8b0a0d0ddb7d43d5b19616e410ca5a0c7ac718aeb2fe`다. 캡처 18장은 같은 X: 폴더에 있다.

D-153이 이름 붙인 현존 G1 시험 네 파일(`test_palette_gates.py`, `test_ui_token_contracts.py`, `test_grammar_separation.py`, `test_evidence.py`)은 호스트에서 **81 passed**, `known_failures.py` **0 NEW**였다(`X:/DevTemp/rosy-g1-current/g1.txt`, SHA-256 `c8b2cb4643fae31fa2df55781ad3314f22e3ed730f36793ad5c3d57e4597dcb6`). 공유 `main`이 실행 중 전진했으므로 이 결과를 단일 불변 SHA의 전체 G1 수용으로 승격하지 않는다.

## Lenovo Pilot 로비 — DEVICE 관찰

연결된 Lenovo TB-J606F의 **이미 전경에 있던** Pilot 화면을 ADB로 읽었다. 물리 패널 1200×2000px, 캡처 방향 2000×1200px, 밀도 240dpi다. 설치 앱은 `0.1.0`, 마지막 갱신 시각은 2026-10-07 17:43:39 KST였다. 현재 화면에는 두 로봇 후보가 같은 시작점·폭의 카드로 보이고, 다시 찾기와 연결 행동이 보인다. 상단에는 이전 연결 실패 안내가 남아 있다. 이 한 화면은 후보 연결 성공이나 운전 가능성의 증거가 아니다. 설치·선택·페어링·주행·정지 조작은 하지 않았다.

원본 `X:/DevTemp/rosy-g1-current/lenovo-pilot-foreground.png` SHA-256은 `88d1d3f13468352764ec5fea56658d5910dc10f10cbd255a08b9f2699e3b28c4`다. 원본에는 로봇 신원이 있어 공개 저장소에 넣지 않았다. 설치 APK를 읽기 전용으로 가져온 `lenovo-installed-base.apk` SHA-256은 `e69fac43e2b08ad533073ebdc8d35da5ecdcc662e686e03855a2603db06cd578`다. 번들 `assets/pilot/`·`assets/common/` 50개를 현재 소스와 SHA-256으로 대조해 **47개 일치, 3개 차이**를 확인했다. 다른 파일은 `pilot/screens/connect.js`, `pilot/screens/drive.js`, `pilot/styles.css`다. 비교 원본 `X:/DevTemp/rosy-g1-current/lenovo-asset-compare.json` SHA-256은 `40c1c408be7656034b5710550f8b79dd6fb13810a66e0612ca00da2f699286fa`다.

따라서 실물 로비 화면은 **설치된 빌드의 부분 DEVICE 근거**이고 현재 소스 후보의 G2/G3 수용 근거가 아니다. 다음 실물 단계는 현재 후보와 설치 APK의 동일성을 증명한 뒤 선언 폭·상태 화면 및 요청자의 실제 작업 독회를 남기는 것이다. 사이트 PC의 현재 Fleet 설치본과 로봇 제어 readback도 별도로 필요하다.
