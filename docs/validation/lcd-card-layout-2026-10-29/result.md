# LCD 상태바 아래 카드의 크기·행 배치

2026-10-29 · `uiux/lcd-card-consistency` · 기준 `1bae8682470c` · 지원 분리 `909b3c30831a` · runtime `e7a526c6b7c9` · 최종 시험 `928ff48d1454`.

## 문제와 수정

실제 native 경로는 rosy-face의 release module import→face_card_renderer.card_renderer→render_overlay→render_card→render_bar 합성→to_panel이다. 상태바32px을 제외한320×208을 전달했지만 render_card가 size를 무시하고 기본 profile320×240으로 그렸다. 이를 y32에 붙여 배터리 게이지 하단과 wake 주소를 잘랐다. 기존 시험은 외부 이미지320×240과 내용 존재만 확인했고 기존7장도 단독 카드여서 놓쳤다.

render_card는 명시 size를 우선하고 생략하면 profile.size를 사용한다. compact208에서 wake의 MODE/NAV/HEALTH와 주소, drive의 속도/NAV/목표/배터리 label을 별도 공간에 배치했다. 목표 좌표가 있으면 NAV 폭을 예약한다. 이 폭 보완은240px에도 적용되며, 나머지 기본240 배치는 유지한다. 전체 이미지를 축소하거나 글자 크기를 강제로 줄이지 않았다. 기존 font fitting은 보존했다.

먼저 별도 지원 브랜치에서 기본 그리기 부품을 분리하고 검증한 뒤 통합했다. 그 기록은 [LCD 부품 분리](../lcd-primitives-2026-10-29/result.md)가 소유한다. info_screen은 현재566줄이고 palette의6개 assignment는 기준과 같다. 기존 import/API 이름을 re-export하며 renderer·primitive·native consumer의 blob을 runtime에 결합했다. CORE/producer·명령/승인·로그인·실제 자격·라벨·HF·로봇 기하는 바꾸지 않았다.

## 원격 증거

원본 scratch는 `C:/DevTemp/rosy-ui-standardization/`이다. reports16개, 최종PNG34개, 수정 전overlayPNG2개의 해시를 각각 보존한다. 모든 pytest는 승인된 시험 PC에 커밋 SHA를 전달했다.

| SHA / 로그 경로 | 실제 결과·판단 |
|---|---|
| `1bae868247`, lcd-initial/run-1.txt | 기존195 pass/4 skip/10 warnings·5subtests. 잘림 경로의 수용 근거가 아님 |
| `dfa70cc66f`, lcd-overlay-red/run-1.txt | 4 failed/1 passed. explicit size2건·전체 overlay 비교2건 실패, profile 기본값1건 통과 |
| `e7a526c6b7`, lcd-overlay-green/run-1.txt |6 passed. size/overlay 및 built renderer |
| `a0715f7260`, lcd-overlay-layout/run-1.txt |11 passed. 크기·profile·전체 crop·compact glyph 경계/상호중첩, overlay8장 |
| `a0715f7260`, lcd-layout-full/run-1.txt |207 passed/4 skipped/10 warnings·5subtests |
| `edf204f98e`, lcd-native-built/run-1.txt |1 passed. 실제 native consumer 소스와 build_py renderer의 python -I cold import/합성/RGB565 |
| `edf204f98e`, lcd-layout-affected/run-1.txt |1318 passed/1 skipped/46 warnings. 이후 capture 시험 추가 전 |
| `928ff48d14`, lcd-native-matrix/run-1.txt |2 passed/2 warnings. 내부208크기 assertion·native dispatch19종 캡처/패킹. 캡처19장을 시험19건으로 합산하지 않음 |
| `928ff48d14`, lcd-final/run-1.txt·junit.xml |208 passed/4 skipped/12 warnings·5subtests. 최종34 PNG |
| `928ff48d14`, lcd-final-affected/run-1.txt |공식 affected1318 passed/2 skipped/46 warnings. CI/FULL·장치 실행이 아님 |
| `928ff48d14`, lcd-native-token-export/run-1.txt |명시 ROSY_RUN_NATIVE_TOKEN_TESTS=1에서1 passed. 실제 Gradle wrapper의 canonical 생성·역할 변경 반영·비scalar 거절 |
| `c08e77be2e`, lcd-affected-skip-details/run-1.txt·junit.xml |1353 passed/2 skipped/46 warnings. 지원 문서 merge 뒤 공식 선택에 JUnit 옵션만 더해 skip을 확인. 이전1318과 합산하지 않음 |

통과 로그는 known_failures NEW0/known0/flaky0이다. 부분·전체·반복 시험 수를 합산하지 않는다. 최종 JUnit의4 skip은 ROS 환경을 요구하는 ament copyright/flake8/pep257의 collection3개와 native token exporter opt-in1개다. exporter는 별도1pass로 확인했다. affected의2 skip은 LOCAL capture opt-in과 AP handoff 파일 fchown에 root가 필요한 기존 시험이다. JUnit에서 실제 node와 이유를 확인했고 root guard를 약화하거나 실행 통과로 바꾸지 않았다. exporter는 해당 affected 선택에 없으므로 위 두 skip과 혼합하지 않는다. 린터·AP handoff 권한 시험이 실행됐다고 표시하지 않는다.

## 실제 소비 경로와 렌더 검증

built 검사는 소스를 임시 package로 복사해 setuptools build_py 산출물을 만든다. 저장소 밖 cwd의 python -I에서 그 info_screen/lcd_primitives와 별도로 복사한 실제 face_card_renderer를 import한다. 각 __file__ 경로, 실제 overlay/bar 분기, 내부320×208과 crop 일치, RGB565 shape(320,240,2)/uint8, rclpy 미import를 검사한다. release 이미지·실제 colcon 설치·SPI 출력 증거는 아니다.

compact6종은 wake/stop/보정·도움 요청과 drive 목표/배터리 위험/충전이다. textbbox의 경계와 쌍별 중첩을 검사한다. 배경 칩·게이지 형상까지 bbox로 증명하는 것은 아니므로 시각 검토와 구분했다. 별도 native factory19종은 boot bright/dim·READY/FAILED/PROVISIONED·AP QR/과용량 fallback·기본/긴 STOPPED·update bright/dim·shutdown·recovery·producer 최대3 peer+CA·light assist·정상/주의/위험/결측 bar다. 실제 자격·장치·서비스를 읽지 않는 합성 입력이다.

최종34장은 baseline7+overlay8+native19이며 세 묶음의 기존 파일과 final 사본 모두 bytes가 일치한다. A는 지원/최종 runtime/마지막 시험을 독립 검토해 추가P1/P2를 찾지 못했다. B는34장을 모두 원본320×240으로 직접 검토해 해당 범위의 잘림·겹침 P1/P2가 없었다. Root도 overlay assist/critical을 직접 확인했다. 최초 grayscale/임시 fixture가 아니라 실제 renderer 합성이다. LCD에는 web detector를 적용하지 않았다.

## 매체 계약·예외·수용 한계

owner는 등록 robot-face의 장치 UI, 정본은 face/emotion과 D-190·D-221·D-394·D-433이다. 320×240/상태바32px, 표현부208px, 고정 배치·ASCII DejaVu/11px fitting 하한·crop·회전·RGB565·QR흑백·아이콘/게이지 기하는 LCD 매체 계약이다. 웹 버튼/서체/spacing 척도를 강제하지 않는다. palette는 등록된 token_copy를 통해 canonical dark와 일치한다. GIF/표현 경로와 crop은 유지했고 기존 모든 프레임 경계 회귀를 실행했다.

긴 사유·이름·상태와 QR 과용량의 PW는 최소 글자 크기에서도 길면 기존 말줄임 규칙을 사용한다. 전체 자격정보를 화면에서 복구할 수 있다는 근거가 아니다. 실제 AP/연결·QR 현장 스캔·물리 밝기·1.5m/0.5초 판독·실물 LCD·DEVICE/FIELD 수용은 하지 않았다. 카드 사례34개를 모든 입력/상태 조합의 수용으로 확대하지 않는다. 배포·착지·공개 push/merge도 하지 않았다.

CE: 해당 없음 — 기존 설치 배치 교훈을 cold import에 적용했고, size/profile 우선순위·하위 영역 경계·동작 보존의 원인과 해결은 코드·회귀·이 기록으로 복원된다. 중복 해결 교훈은 늘리지 않는다. 전체 제품의 이행/통합 검증은 계속 진행 중이다.
