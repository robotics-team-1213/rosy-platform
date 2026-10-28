# Robot·Pilot·Learning UI/UX 후속 검증

기준은 `45e7b14e88`, 최종 제품 소스는 `fce9c60216`, 후속 정적 검사 소스는 `bc920d2dac`이다. 작업 브랜치는 `fix/robot-pilot-learning-ux`다. 실제 사람 라벨·운영 서비스·장치에는 쓰지 않고 합성 ReviewStore와 HTTP fixture를 사용했다.

## 변경과 경계

| 표면 | 문제와 수정 |
|---|---|
| Pilot | 비상 정지 응답을 버리던 표시를 요청 중·접수·거절·확인 불가로 구분한다. 접수는 물리 정지 완료를 뜻하지 않는다. 5초 timeout, 오래된 응답과 새 작업 안내의 수명을 구분하며 discovery 완료가 접수 문구를 지우지 않는다. 버튼은 계속 사용할 수 있다. |
| Robot | 긴 오류를 두 줄 높이의 키보드 스크롤 영역으로 제한하고 긴 단어를 줄바꿈한다. 데스크톱 브랜드가 줄어들어 오류와 겹치던 문제도 수정했다. |
| Learning | GET 오류는 회복 시 지우고 실패한 저장 오류는 보존한다. 진행 갱신 때 자료 선택과 조작 초점을 유지하고 완료 시 해당 실행 제목으로 돌려준다. |
| 공통 구조 | Learning 12문서의 헤더와 전역 메뉴 원본을 두 fragment로 모았다(D-910). 첫 응답은 완성된 정적 HTML이다. 기존 셸·간격·시각 토큰을 소비하며 하위 메뉴·업무 폼·API는 각 owner에 남긴다. |
| Pilot 배포 자산 | 기존 CSS를 선언 순서 그대로 기본503줄·배치442줄로 분리한 뒤 수정했다. HTML, CORE/SIM/dev allowlist, CMake, Android bundle, SW 캐시를 함께 맞췄다. |

CORE의 인증·stop latch·명령 권한과 OMX owner는 바꾸지 않았다. 독립 소스 검토가 `app.js → pinky_core.js → client.js → CORE safety.py`의 생산자·소비자 경로와 `estop=true`의 접수 의미를 확인했다.

## 원격 실행

원본은 외부 `C:/DevTemp/rosy-ui-product-surfaces/`에 보존한다. pytest는 승인된 시험 PC의 커밋된 SHA에서만 실행했다.

| 증거 | SHA | 결과 |
|---|---|---|
| Learning 조회/저장 오류·초점 RED | `35bb076f85` | 6 failed. 정상 fixture의 실제 동작 실패 |
| Robot 긴 오류 RED | `180c1adb9a` | 8 failed. 긴 한국어 오류의 높이·가로 넘침 |
| 정적 셸 RED | `76f00c62e3` | 4 failed. 합성 owner 부재 |
| 최초 동작 검사 | `a945d6c6cb` | Pilot33·Learning6 통과, Robot6은 End 직후 비동기 스크롤 판정 실패. 기다림을 보강 |
| 집중 검사 | `79b7970a93` | 55 passed, skip0. 첫 응답12문서×4폭 포함 |
| 실제 겹침 수정·캡처 | `67644fd74a` | 55 passed, skip0. Robot 브랜드 교차 검사 포함 |
| 설치 자산·라우트 검사 | `fce9c60216` | 20 passed, skip0. CMake/Android 등록·서빙 회귀, 실제 빌드 증거는 아님 |
| 최초 공식 영향 선택 | `724889ceb5` | 2 failed, 9274 passed, 796 skipped, 30 subtests passed. 기존 정적 검사2개가 분리한 CSS를 읽지 않음; `affected-final/run-*.txt` |
| 정적 검사 입력 보완 | `bc920d2dac` | 13 passed, skip0. 기존 assertion을 유지하고 실제 순서의 두 CSS를 읽음 |
| 공식 영향 재검증 | `bc920d2dac` | 실행 중; `affected-verified/run-*.txt` |
| 공식 브라우저56파일·9묶음 | `724889ceb5` | 실행 중; `browser-final/run-*.txt` |

최초 `interaction-red`와 `notice-red`에는 fixture 자체의 오류도 있었다. POST robots 경로 누락과 운영자 오류 정제에 의해 치환된 영문 메시지를 고친 뒤 위의 정상 RED로 재현했다. 원본 실패를 성공 기록으로 덮어쓰지 않았다. `79b`의 넓은 검사는 셸 주석 위치·CSS 크기2건과 discovery 접수 수명4건을 찾아 후속 소스에서 수정했다.

`fce9c60216`은 `724889ceb5`에서 설치 목록2곳과 해당 회귀만 바뀐다. `bc920d2dac`은 정적 검사2곳의 입력만 실제 두 CSS로 확장하며 기존 assertion을 유지한다. 실행 UI 소스와 생성 HTML은 같다. 최종 기록 검사는 별도로 결속한다.

## 화면과 독립 검토

320/390/768/1440px를 확인했다. `screenshots-final/` 58장 중 독립 검토는 Robot8·Learning23 전체와 Pilot 대표6, 총37장을 확인했다. 작성자도 Robot1440 밝게와 Learning 초점 화면을 직접 확인했다. 검토한 캡처에서 남은 P1/P2는 없었다. 초기35장에서는 Robot1440 두 테마의 실제 겹침을 찾아 수정했다.

Learning shell16장은 JavaScript를 끈 첫 응답 검사이며 빈 아이콘·로딩 문구를 완성 화면이나 실제 빈 자료 상태로 평가하지 않았다. 오류/회복4장과 초점3장은 일반 JavaScript 실행이다. Pilot은 기존 `data-theme-pin=dark`를 따른다. `light` 입력 파일 이름을 밝은 테마 수용으로 주장하지 않는다.

impeccable의 설계 검토와 화면 검토는 별도 읽기 전용 에이전트가 수행했다. 최종 소스 `45e7b14e88..fce9c60216`의 독립 검토는 CMake/Android 누락 해결 후 남은 P1/P2 없음이다. detector는 676 소스에서0건/exit0이며 `/common` 스타일시트 경로 해석 제한이 있어 실제 캡처·Chromium 검사와 함께 판단했다.

## 이력·크기·남은 수용

기존 작업 공간의 `a945d6c6cb`가 이미 큰 CSS를945→947줄로 늘린 사실을 범위 검사에서 확인했다. 원본 브랜치와 RED/GREEN 증거를 보존하고 gateway로 정상 직전 `76f00c62e3`에서 새 작업 공간을 만들었다. CSS를 먼저 분리한 전달 이력에 소유 변경을 다시 적용했다. 원본 실패 커밋은 이 전달 이력의 조상이 아니다. `size_range.py 45e7b14e88 fce9c60216`은12커밋을 통과했고 safety trailer 검사도 통과했다. 규칙·ratchet 허용치를 완화하지 않았다.

CE: 해당 없음 — 기존 `docs/solutions/workflow-issues/landing-blockers-cost-hours-2026-10-18.md`의 크기 이력 교훈을 적용했다. 이번 상태·초점·배포 자산 경계는 코드·회귀·D-910과 이 기록으로 복구할 수 있어 새 교훈을 중복 작성하지 않는다.

실제 태블릿·Android APK/ARM64 payload 빌드·물리 정지·현장·모델 평가·실제 HF 쓰기는 수행하지 않았다. 이 기록은 G2/G3 또는 FIELD 수용, 배포, 공개 push/merge의 증거가 아니다.
