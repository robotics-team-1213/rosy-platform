# 플랫폼 UI 표준화 통합 검증

등록된12개 표면의 공통 컴포넌트·토큰·레이아웃 이행과 통합 검증을 마쳤다. 최종 source와 실제 캡처의 독립 검토에서 남은 P1/P2는 없다. 이 문서는 각 SHA·실패·수정·skip·소유 예외를 구분한다. 공개 게시·배포·실제 장치/사람 라벨/Hugging Face 쓰기는 수행하지 않았다.

## 소스와 통합 경계

- topic: `uiux/platform-ui-consistency`, 생성 기준 local main `135bd760eb`.
- 기존 `fix/robot-pilot-learning-ux`는 main과 foundation/storage/class/Games/SSH/Fleet/Pilot/Cam/SIM/LCD refs를 `5c67e7e2e8`까지 통합했다. 새 topic은 이 기준을 일반 merge로 포함한다. 기존 `4a54292f87` ref와 실패 재현 이력은 보존했다.
- UUID cherry-pick의 중간 commit이 Map 763→764줄을 증가시켜 per-commit 크기 검사에 실패했다. 새 topic은 해당 commit을 조상으로 포함하지 않고, 검증 기준 이후 25개 source/test 파일의 동일성을 확인한 뒤 지원 분리와 호출 추가를 `fe2f5c1ef0`에서 함께 반영했다. 검사 규칙·ratchet을 늘리거나 이력을 재작성하지 않았다.
- 웹 통합 runtime `42508b116edd75e002204f344e3bcf4d758dccbb`, Learning 리본 `c38009ec42`, 계정 여백 `817e1cac6a`, 공유 Escape `a82292062e`를 구분한다. Pilot primary focus는 `dab8ddacf2`에서 실제 RED, `42c6716d8a`에서 수정 후 동일 APK로 두 화면을 검증했다. 후속 `bc7c624833`은 dialog 회귀만 추가한다.
- 등록부 재대조: 12개(웹9/native2/LCD1), 추적 HTML31개. 웹9개 중 web-common은 라이브러리, lane-live-view는 비제품 SIM, control-diagnostic은 PARKED다. HTML 수는 route·동적 패널·설치본 수가 아니다.

## 검증된 통합 단위

등록 표면별 이행 범위는 아래와 같다. HTML 수는 정적 진입 문서이며 내부 route·fragment·동적 패널을 대체하지 않는다. 각 단위의 기존 검증 기록과 이번 통합 로그를 함께 보존한다.

| surfaces.yaml ID | 화면·범위 | 공통화와 근거 |
|---|---|---|
| monitoring | index, 신선도·reader·오류/지연/빈 상태 | 기존 공통 컨트롤·dialog·dark/light 유지. 10/26 정본151pass와 이번108 browser 선택에 포함. 설정·복구 명령 권한 없음 |
| pinky-review | learning/catalog/index/pixels/tasks/evaluate/accounts/workspaces/camera/omx/sim/vlm, 12문서 | 공통 shell/controls·저장소·분류·SSH, 본문 inset/폭·리본·결정 패널. 단위 storage/class/SSH 및 이번14·8회귀 |
| robot | index/styleguide/surface, dashboard/console/setup/device와 등록 패널 | 공통 토큰/역할 부품과 본문 inset. 넓은 화면 rail·본문 폭과6개 최종 상태 캡처 |
| console | accounts/cell/index/install/learning/login/profile/site-map/policy, 9문서와 작업 패널 | 공통 계정/상태/정지 셸·명시 인증·초점·공통 UUID. 72·41·dialog4회귀, 새96캡처 |
| game-board | index, 경기장·결과·문서 | 공통 조작/타이포/초점, pitch는 소유 팔레트 예외. scoped61pass와18캡처 |
| control-diagnostic | diagnostic 단일 진단 | 공통 자산 계약 유지. PARKED(D-266)의 타이포/dialog 유예를 유지하며 운용 표면 수용으로 승격하지 않음 |
| pilot | index, connect/drive/arm·입력/녹화 시트 | 공통 조작/타이포/토큰·녹화 목록 초점/조회 수명. scoped39pass와20캡처, 설치·SW 목록 계약 |
| web-common | gallery/template, 2문서와 부품 라이브러리 | 토큰·controls·shell·dialog·theme·wiring 정본. 통합137pass, 후속48pass·12개 Node 회귀 |
| lane-live-view | SIM 레인 단일 뷰어 | 공통 간격/tag/초점·긴 결과 wrapping. scoped26pass·32캡처, 제품 외 SIM 예외 |
| robot-face | boot/info/login/QR와 감정 출력 | 토큰 사본·208px 행 예산·공통 primitive. scoped208pass/4skip·34캡처, LCD 실물 판독 수용 별도 |
| pilot-shell | Android 목록·상태·주요/보조 조작·APK 자산 | 생성 색/metrics·공통 inset·목록 초점. 기존110pass/1skip·두 구성5건씩에 이번 primary 회귀 추가 |
| cam | Android 촬영/회복·LAN 연결 안내 | 생성 토큰/공통 아이콘·상태/초점. scoped JVM443pass/skip0, 두 density에서4건씩·24캡처. 해당 source는 정본과 동일 |

| revision | 실제 실행 | 범위와 제한 |
|---|---|---|
| 5c67e7e2e8 | 원격137 passed/skip0/NEW0 | 공용 registry/controls/tokens/parity, Fleet components/header, browser selector, 설치 자산. 전체 렌더 아님 |
| 045e636f9d | 원격9 passed/skip0/NEW0 | LAN HTTP CSPRNG 초기화, trusted localhost native crypto, import/문서 계약. 최초 fixture HOST 불일치404는 제품 RED가 아님 |
| e282d3ab52 | Chromium·계약47 passed/skip0/NEW0 | 네 Fleet 문서 고정 헤더. 후속 실제 이미지에서 authenticated320 상태 label 잘림을 추가 발견 |
| 002a7aad1f → 6365eb3287 | RED8fail16pass → 24pass/skip0/NEW0 | dark/light·3폭·4문서의 authenticated 연결 끊김. 이전96PNG 검토 뒤 최종 common Stop padding 복구는 아래6910/425로 따로 검증 |
| 5ab28d26f5 | 첫 회귀2pass, 원격 전체125pass/skip0/NEW0 | Map·프로필·도면·import·설치 자산. 분리 전 baseline2pass, 분리 후 실제 background free-variable 오류를 반환값으로 해결. 점의 좌표·그리기 순서를 유지 |
| 6910f504b8 | Chromium29 passed/skip0/NEW0 | 명시 인증 성공/거절·외부 초점 보존·두 테마 기하·기존 헤더. Cell 입력 잠금 전 focusOrigin과 재활성화 후 복원을 검증 |
| 0bc653977c | 원격55 passed/skip0/NEW0 | 새 canvas 판정과 기존 HTTP consumer2개 등록, Node 헤더 대역의 contains/초점/부모자식 복구. backend request/증거는 변경하지 않음 |
| 42508b116e | Chromium42 passed/skip0/NEW0, 134PNG 전수 독립 검토 | Fleet 상태96·입력/닫힘 초점32·Robot6. common Stop padding12를 유지한 최종 캡처. 명령 성공·실물 수용 아님 |
| 42508b116e | Chromium8 passed/skip0/NEW0, 20PNG 전수 독립 검토 | Learning/Robot 본문 확장, pixel DOM 왕복·체크·승인 disabled·초점 및 실제 hit-test. root가 후속 도구 리본 가림을 별도로 발견했으므로 리본 수용까지 확대하지 않음 |
| c38009ec42 | Chromium14 passed/skip0, 새24PNG 전수 독립 검토 | 도구 리본의 appbar 아래 sticky 위치, 객체/pixel 왕복 배치·초점·hit-test. 이전425의20장과 별도이며 새 P1/P2 없음 |
| c38009ec42 | native exporter1 passed/skip0 | 명시 opt-in으로 실제 생성 실행. 색/metrics의 정본·변경·잘못된 scalar 검증 |
| 42508b116e → 817e1cac6a | 전체1794 중1784pass/10fail/skip0 → 관련72pass/skip0 | 공통 계정 padding12 복구, 열린 메뉴를 Escape로 닫는 재접속 경로, CSP를 유지한 wait predicate 함수화. 전체1794건을 최종 SHA에서 다시 실행했다는 의미가 아님 |
| 4db9234a95 → a82292062e | 실제 trigger Escape RED → Chromium/Node gate41pass/skip0 | 네 문서·4초점 위치16건과 기하24건·Node gate1건. Node 개별12건도 통과. 열린 메뉴만 닫고 외부 초점과 dialog가 취소한 Escape를 존중 |
| dab8ddacf2 → 42c6716d8a | AVD6 중 primary1fail → 두 크기에서 각6pass, 시각 검토 P2 | 경계 픽셀은 바뀌었지만 새30PNG의 primary가 기본과 약2px 축소 정도로만 구별됐다. 검사 통과를 시각 수용으로 삼지 않고473c에서 수정했다 |
| 42c6716d8a | SDK35 debug/test APK 빌드 성공, JVM110pass/1skip | 선택적 ShellPageProbe skip 유지. APK의 common components/tokens/ui 및 Pilot layout.css가 해당 source와 byte 동일. emulator 결과는 실제 장치 수용이 아님 |
| 473c39803f | Chromium dialog4pass/skip0, shared/Node gate48pass/skip0 | 실제 공용 dialog가 첫 Escape를 처리하고 메뉴·기존 초점을 보존한다. 잘못된 asset 경로의 이전4실패는 fixture 오류이며 수정 후 실행했다 |
| 473c39803f | SDK35 build 성공, JVM110pass/1skip, 두 AVD 구성 각각6pass | 동일 app/test APK로 최종30PNG 전수 독립 검토. primary 시각 P2 해결·새 P1/P2 없음. 중심 fill·글자/아이콘·blur·disabled와 실행0회 검증. source 독립 검토도 새 P1/P2 없음 |

6910의 공식 넓은 영향은 네 호출이다. run1: 6143pass/565skip와 등록누락2fail, run2:488pass/28skip, run3:11377pass/1358skip와 Node대역1fail, run4:1897pass/36skip와 UDS 시간1fail(자동 단독 재실행1pass). 세 등록/대역 실패는0bc의55pass로 수정 검증했다. 이들을 합산해 고유 건수나 전체 GREEN이라고 쓰지 않는다. 브라우저 skip은 실제 실행으로 세지 않는다.

## 통합 검증의 경계

- 등록 browser target108파일의425 실행은 종료됐다. JUnit1794건의 실패10건은 계정 padding2·재접속 안내1·CSP predicate7건이며817의72건으로 수정 검증했다. 이후 리본·Escape·native는 각 SHA와 범위를 따로 검증한다.
- 리본은 e235의 dark/light2 RED 뒤 공용 top을 appbar/space 토큰으로 수정했다. c380의14건과 새24PNG에서 앱 바 가림이 없어졌다.
- primary의 첫 수정은 edge 회귀를 통과했어도 이미지에서 구별이 약해 P2로 판정했다.473c는 primary/quiet의 focus를 기존 pressed fill·foreground stroke/글자색으로 통일하고 아이콘 tint도 상태별 글자색을 따른다. 회귀는 중심 fill·focus/blur 글자색·아이콘과 disabled 우선순위까지 확인한다.
- 소유 AVD를 종료해 browser의 host-exclusive admission과 충돌을 해소했다. 초기 SDK 대기 종료·잘못된 node id로 끝난 수집 오류는 제품 통과로 계산하지 않는다.
- Cam·LCD·SIM은 각 정본 ref와 해당 소비자 source diff가 없음을 확인했다. Pilot Android는 layout.css APK 포함과 primary focus의 추가 근거를 위 표에 연결한다. 이전 scoped evidence를 실제 기기 수용으로 확대하지 않는다.
- Pilot SW는 main의2026-10-22 키에서2026-10-28 키로 바뀌고 layout.css를 shell에 포함한다. CORE/OMX allowlist도 포함한다. import/cache/설치 계약과 실제 APK 결과를 함께 확인해야 한다.

## 보존 원본

`reports.sha256`는 초기 종료17회차의 원본 로그를, `captures.sha256`는425의 shell134장과 workspace20장(합계154장)을 묶는다. `final-evidence.sha256`는 전체1794 JUnit/로그, 실패10건 수정72건, Escape RED/GREEN·dialog·계약·exporter·리본 로그와 새 캡처, native RED·시각 구별이 약했던 중간 결과·최종 JVM/AVD 자료를 추가 보존한다. 이는 서로 다른 범위이며 고유 시험 건수로 합산하지 않는다.

원본 저장 기준은 외부 scratch의 `rosy-ui-standardization/`이다. 초기 `shell-42508/`는 `delivery-shell-final-captures/`, `workspace-42508/`는 `workspace-width-visible-captures/`에 대응한다. final manifest는 상대 경로 그대로다. 최종 header96·리본24·native30 이미지는 각각 독립 전수 검토했다. 중간 native30장은 시각 P2가 남았던 기록이며 최종 이미지와 구분한다.

최종 native app SHA256는 `5b2b411a495160bd4c6eb8b611d62bb45635489a1078eda5a301ae81f71508b5`, test APK는 `2569cd71d0a90fe2950518a317fda0365bdbf4996b5bd32f416779e3e6458790`이다. 두 구성 receipt의 해시가 같다. 최종 APK도 common components/tokens/ui와 Pilot layout.css가 source와 byte 동일하다. 마지막 source 검토 기준은473c39803f이며 이후 변경은 이 검증 기록·owner 로그와 생성 index다. final manifest257개 원본의 SHA256을 다시 대조했고 harness lint는0error/40warning이다. 경고는 기존 모듈 검증 기준의 오래됨/미커밋 표기이며 이 작업에서 검증되지 않은 gate를 올리지 않았다.

전체108 browser invocation에는 Gazebo 레인 viewer의 host-exclusive 대상이 포함됐다. 작은 검사는 이전 실측(단일 native exporter788MiB, 폭/초점375MiB)을 기준으로 같은 선택·SHA를2GiB/1core 직렬 요청으로 구성했다. 초기 대기 요청의 제어 종료143을 통과로 세지 않는다. 이후 소유 AVD도 host-exclusive browser에 자리를 내주도록 종료했다.

## 의도된 예외와 수용 경계

색·글꼴·여백·일반 조작 표적은 공통 토큰/부품이 소유한다. 1px 경계는 선이며 SVG/지도/렌즈·로봇 좌표는 해당 producer의 데이터다. 표면의 열·폭·위치는 task grammar owner가 소유하며 임의 paint/spacing 예외로 확대하지 않는다.

Games의 pitch 팔레트(root 한 블록), Pilot 영상 바깥 검정·dark 운전석, Perception PARKED 진단의 제한된 root/타이포/dialog 유예는 surfaces.yaml의 기존 소유와 근거를 유지한다. LCD 픽셀/QR/회전·감정 기하는 Face, native dp/inset·영상비율은 Pilot/Cam이 소유하며 팔레트/서체·일반 표적은 생성 계약을 따른다. Fleet Map 파일 입력3개는 기존 ui-field/type=file과 공용 file-selector-button을 쓰므로 별도 중복 배선을 만들지 않는다.

실제 로봇 정지·조종, 실제 라벨/학습/HF 쓰기, 실제 폰/태블릿, LCD 거리·판독 시간·QR 스캔·SPI, ARM64 이미지·서명 release·FIELD·배포/게시 수용은 이 호스트/fixture 증거와 별도다.

CE: 해당 없음 — 기존 child clipping 교훈을 적용했고 새 상태 조합·지원 분리·입력 잠금·sticky 가림·Escape 우선순위·native 대비 판단은 코드·회귀·검증 기록에 남는다. 별도 교훈 문서를 중복 생성하지 않는다.
