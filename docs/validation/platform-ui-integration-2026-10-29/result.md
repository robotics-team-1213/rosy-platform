# 플랫폼 UI 통합 검증 — 진행 중

전체 UI 표준화 목표는 아직 완료되지 않았다. 이 문서는 분리 단위의 검증과 현재 통합 실행을 연결하며, 실행 중·생략·실패를 통과로 계산하지 않는다. 공개 게시·배포·실제 장치/사람 라벨/Hugging Face 쓰기는 수행하지 않았다.

## 소스와 통합 경계

- topic: `uiux/platform-ui-consistency`, 생성 기준 local main `135bd760eb`.
- 기존 `fix/robot-pilot-learning-ux`는 main과 foundation/storage/class/Games/SSH/Fleet/Pilot/Cam/SIM/LCD refs를 `5c67e7e2e8`까지 통합했다. 새 topic은 이 기준을 일반 merge로 포함한다. 기존 `4a54292f87` ref와 실패 재현 이력은 보존했다.
- UUID cherry-pick의 중간 commit이 Map 763→764줄을 증가시켜 per-commit 크기 검사에 실패했다. 새 topic은 해당 commit을 조상으로 포함하지 않고, 검증 기준 이후 25개 source/test 파일의 동일성을 확인한 뒤 지원 분리와 호출 추가를 `fe2f5c1ef0`에서 함께 반영했다. 검사 규칙·ratchet을 늘리거나 이력을 재작성하지 않았다.
- 웹 통합 runtime `42508b116edd75e002204f344e3bcf4d758dccbb`와 후속 Learning 도구 리본 `c38009ec42`를 구분한다. Pilot primary focus는 새 시험 `dab8ddacf2`만 추가한 상태이며 제품 수정·실행 RED가 아직 없다.
- 등록부 재대조: 12개(웹9/native2/LCD1), 추적 HTML31개. 웹9개 중 web-common은 라이브러리, lane-live-view는 비제품 SIM, control-diagnostic은 PARKED다. HTML 수는 route·동적 패널·설치본 수가 아니다.

## 검증된 통합 단위

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

6910의 공식 넓은 영향은 네 호출이다. run1: 6143pass/565skip와 등록누락2fail, run2:488pass/28skip, run3:11377pass/1358skip와 Node대역1fail, run4:1897pass/36skip와 UDS 시간1fail(자동 단독 재실행1pass). 세 등록/대역 실패는0bc의55pass로 수정 검증했다. 이들을 합산해 고유 건수나 전체 GREEN이라고 쓰지 않는다. 브라우저 skip은 실제 실행으로 세지 않는다.

## 현재 열려 있는 검증

- 등록된 browser target108파일을425 SHA에서 실제 실행 중이다. 약40% 지점에 실패2건이 표시됐으며 최종 JUnit/로그와 원인을 확인해야 한다. 새 c380 리본 수정은 이 회차의 소스에 없다.
- 리본의 sticky top이 appbar 아래가 아닌12px에 고정되는 문제는 e235의 dark/light2 RED로 재현했다. c380은 객체·pixel 공용 review-tool-ribbon의 top을 appbar/space 토큰으로 통일했다. 해당 실제 GREEN과 새 이미지 검토는 대기다.
- native token exporter는 명시 opt-in으로 요청했지만 host admission 대기다. 이를 실제 실행 통과로 세지 않는다.
- Pilot primary는 foreground fill과 같은 색 stroke를 사용한다. 실제 다시 찾기·함께 조종에서 쓰이는 부품이다. dab8은 기존 무동작 native fixture에 DPAD·실제 drawable edge/disabled 우선순위·callback0회 회귀를 추가했다. RED build/instrumentation과 수정 후 검증이 남는다.
- 425 SDK 대기 작업은 소유 working-directory 확인 후 제어 종료해 MainPID0/inactive/success를 확인했다. 빌드 완료가 아니다. 새 시험 SHA의 별도 SDK 작업을 생성했다.
- Cam·LCD·SIM은 각 정본 ref와 해당 소비자 source diff가 없음을 확인했다. Pilot Android의 기존 native 정본과 차이는 layout.css APK 자산 포함이다. 이전 scoped evidence를 전 표면 통합·기기 수용으로 확대하지 않는다.
- Pilot SW는 main의2026-10-22 키에서2026-10-28 키로 바뀌고 layout.css를 shell에 포함한다. CORE/OMX allowlist도 포함한다. import/cache/설치 계약과 실제 APK 결과를 함께 확인해야 한다.

## 의도된 예외와 수용 경계

색·글꼴·여백·일반 조작 표적은 공통 토큰/부품이 소유한다. 1px 경계는 선이며 SVG/지도/렌즈·로봇 좌표는 해당 producer의 데이터다. 표면의 열·폭·위치는 task grammar owner가 소유하며 임의 paint/spacing 예외로 확대하지 않는다.

Games의 pitch 팔레트(root 한 블록), Pilot 영상 바깥 검정·dark 운전석, Perception PARKED 진단의 제한된 root/타이포/dialog 유예는 surfaces.yaml의 기존 소유와 근거를 유지한다. LCD 픽셀/QR/회전·감정 기하는 Face, native dp/inset·영상비율은 Pilot/Cam이 소유하며 팔레트/서체·일반 표적은 생성 계약을 따른다. Fleet Map 파일 입력3개는 기존 ui-field/type=file과 공용 file-selector-button을 쓰므로 별도 중복 배선을 만들지 않는다.

실제 로봇 정지·조종, 실제 라벨/학습/HF 쓰기, 실제 폰/태블릿, LCD 거리·판독 시간·QR 스캔·SPI, ARM64 이미지·서명 release·FIELD·배포/게시 수용은 이 호스트/fixture 증거와 별도다.

CE: 해당 없음 — 기존 child clipping 교훈을 적용했고 새 상태 조합·지원 분리·입력 잠금·sticky 가림의 판단은 코드·회귀·검증 기록에 남는다. 미완료 native와 전체 검증을 해결 교훈으로 기록하지 않는다.
