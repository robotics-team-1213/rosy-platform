# 공통 UI 조합 부품 확충 — 구현과 검증

2026-10-23. 공통 부품은 기존 `shared/web` 패키지에 추가했다. 제품 API·원장·인증·명령 권한은 바꾸지 않았다. 이 기록은 웹 구현·합성 자료·호스트 브라우저 검증이며 장치·현장 수용이 아니다.

## 소스와 분리된 변경

| 범위 | 브랜치 | 기준 커밋 |
|---|---|---|
| 공통 부품·견본 | `uiux/shared-component-kit` | `56601412aa` |
| Fleet 적용 | `uiux/component-fleet-adoption` | `1cc26ebd37` |
| Robot 적용 | `uiux/component-robot-adoption` | `006787ecb7` |
| 독립 검토 후 수정 | `uiux/component-kit-review-fixes` | `050c0da738` |

위는 순서대로 쌓인 주제 브랜치다. main 착지·push·배포는 하지 않았다. 슬롯 상한을 지키기 위해 같은 작업 디렉터리에서 앞선 브랜치의 커밋을 보존하고 다음 브랜치를 만들었다.

기존 큰 `ui.js`·`components.css`에 새 기능을 몰아넣지 않았다. `ui.js`의 비활성 탭 순서 한 줄은 수정했으나 파일 줄 수는 늘리지 않았다. 별도 프레임워크·빌드 도구·런타임 의존성도 추가하지 않았다.

## 실제 사용

- 기존 Robot `/styleguide`에서 [상호작용 견본 장](../../../shared/web/component-gallery.html)으로 이동한다. 같은 장은 `/common/component-gallery.html`로 서비스한다. 모든 예제는 합성 자료이며 실제 장치·계정·작업을 바꾸지 않는다.
- Fleet 관제의 개입 동작 모음이 공통 줄바꿈 규칙을 사용한다. 지도 머리의 `로봇 선택으로 이동`은 기존 선택 영역을 열고 초점을 보낸다. API 요청을 보내지 않는다.
- Robot 준비 화면의 웨이포인트 폼은 공통 오류 요약·입력 설명을 사용한다. 기존 최신 위치·중복 제출 차단은 유지하고 저장 실패 뒤 입력을 보존한다.

사용법과 공개 함수는 [DESIGN의 조합 부품](../../../DESIGN.md#입력자료복구의-조합-부품)을 따른다. 표면은 `components.css` 다음 `component-controls.css`를 읽는다. 단계 견본에는 기존 `stage-strip.css`도 읽는다.

## 계획 항목과 구현의 대응

`제품 적용`은 이번 변경에서 새 소비가 생긴 항목이다. `견본 검증`은 구현·견본·시험이 있으나 아직 제품 화면에 강제로 넣지 않은 항목이다. `기존 재사용`도 같은 근거 범위를 넘겨 현장 수용으로 해석하지 않는다.

| 계획 | 구현·기존 기반 | 이번 성숙도 |
|---|---|---|
| C01 필드·그룹·오류 요약 | `form-controls.js` `createFormErrors` + native form/fieldset | 제품 적용: Robot 웨이포인트; 라디오 그룹 견본 시험 |
| C02 체크·라디오·선택·설정 토글 | 기존 `.ui-check`·`.ui-field`, native checkbox/radio/select, switch 의미 | 기존 재사용·혼합 체크/그룹 검증 |
| C03 비동기 상태 영역 | `createStatePanel`, 기존 ui-status/ui-empty | 견본 검증 |
| C04 메시지·오류 상세 | state panel의 설명·재시도 + disclosure/log | 견본 검증 |
| C05 반응형 동작 모음 | `createActionBar`, `.ui-action-bar` | 제품 적용: Fleet 개입·운행 재계획 |
| C06 탭·접힘 | `createTabs`, `createDisclosure`, 기존 task chooser | 견본 검증·기존 재사용 |
| C07 목록 도구 모음 | `createListToolbar` | 견본 검증 |
| C08 목록·기본 표 | `createDataTable`, 기존 taskRow/readout | 견본 검증 |
| C09 목록–상세 | `createPrimaryDetail`, 유실 통지·복귀 초점 | 견본 검증. Fleet에는 기존 선택 영역의 직접 이동 경로 적용 |
| C10 이름–값·요청 결과 | `createOperationResult`, 기존 readout/readback | 견본 검증·기존 재사용 |
| C11 파일 선택 | `createFilePicker`, native file | 견본 검증 |
| C12 확인·위험 동작 | 기존 confirmIrreversible/openLiveDialog | 기존 재사용, 견본의 정지 hit test |
| A01 페이지·더 불러오기 | `createPagination`, native action과 목록 추가 예시 | 견본 검증 |
| A02 다중 선택·일괄 동작 | `createDataTable`, `createSelectionBar`, 부분 실패 예시 | 견본 검증 |
| A03 검색 선택 | `createSearchSelect`의 검색 + native select | 견본 검증 |
| A04 동작 메뉴·보조 정보 | `createActionMenu`는 일반 Tab 순서의 disclosure; 기존 tooltip | 견본 검증·기존 재사용 |
| A05 단계·절차 | `createSteps` + 기존 stage strip | 견본 검증 |
| A06 미저장 편집 | `createDirtyGuard` | 견본 검증 |
| A07 진행·활동 이력 | `createProgress`, `createTimeline`, result 상태 | 견본 검증 |
| A08 보조 상세 패널 | `createSupplementPanel` | 견본 검증 |
| A09 기간 입력 | `createDateRange`의 native 달력 날짜 | 견본 검증 |
| A10 복사·코드·로그 | `createLogView`의 텍스트·복사·빈 기록·오류 복구 | 견본 검증 |

새 custom element 22개를 만든다는 의미는 아니다. 같은 공용 기초 부품·네이티브 동작을 조합하며 소유자가 모르는 상태를 UI에서 추정하지 않는다. 서버 검색·총량·전체 페이지 선택·진행률·완료 확인은 호출자가 제공한 사실만 표시한다.

## 검증 근거

| 소스 | 실행 범위 | 결과 |
|---|---|---|
| `6d12856432` | 최초 갤러리 회귀 | 미등록 자산 404 단언 실패 확인 |
| `0c232ab75a` | 빈 파일·중복 행 경계 | 예상 실패 2건, 수정 뒤 `55d5649c22` 새 부품+manifest 25 passed |
| `56601412aa` | shared/web 전체, Chromium 명시 활성화 | 385 passed, 1 native-token export skipped |
| `958a2358ff` → `1cc26ebd37` | Fleet 직접 이동·긴 동작명 및 기존 대기열·지도 | 4 failed → 33 passed |
| `4b723e4e28` → `006787ecb7` | Robot 폼 설명·실패 입력 보존·위치 준비 | 예상 1 failed → 3 passed |
| `f65966ba70` → `050c0da738` | 독립 검토 5항목·shared/web 전체 | 예상 5 failed → 390 passed, 1 native-token export skipped |

skip 1건은 `shared/web/test/test_native_token_export.py`의 별도 `ROSY_RUN_NATIVE_TOKEN_TESTS` opt-in이다. 이번 변경은 native export나 토큰을 바꾸지 않았으며 이를 실행한 것으로 계산하지 않는다. FastAPI/Starlette 사용 중단 경고 두 종류도 실행 로그에 남는다.

독립 검토는 `1f47f20905..006787ecb7`을 읽기 전용으로 수행했다. 필터 후 페이지 축소, 라디오 그룹, custom element 연결 뒤 탭 순서, 유실된 상세와 복귀 초점, 복사 재시도 상태를 각각 실패 재현 후 고쳤다. 수정 후 별도 재검토를 했다는 뜻은 아니며, 위 GREEN 시험이 수정 검증이다.

공통 자산은 `shared-assets.json`과 CMake install 목록 양쪽에 등록했다. 하네스의 최종 영향 선택 전체를 고정 SHA로 원격 실행하고, 각 로그를 `test/known_failures.py`와 비교한다. 마지막 실행의 SHA·선택 JSON·로그·캡처·해시는 작업 공간의 `Rosy/docs/workspace-records/2026-10-23/component-expansion-evidence/`와 완료 기록에 보존한다. 이 LOCAL 보관 위치는 공개 저장소 밖이다.

## 남은 수용과 정정

- 320/390/1366/1920px·양 테마의 갤러리/확인 캡처와 자동 hit test는 호스트 근거다. 실제 사용자 과업의 G3, 실물 단말, 로봇 물리 정지·현장 수용은 이번에 수행하지 않았다.
- 기존 화면 평가에서 `재개…`를 글자가 잘린 `재계…`로 해석한 부분은 소스로 정정했다. 기존 말줄임표는 확인 단계 표시이므로 라벨과 명령 의미는 유지한다. 긴 라벨 줄바꿈은 별도의 일반 품질 조건으로 검사한다.
- 초기 로그 행을 파일 머리에 넣은 순서 오류는 하네스가 검출했으며, 자신의 행만 시간순 맨 끝으로 옮겼다. 검사나 기존 이력은 약하게 만들지 않았다.

CE: 해당 없음 — 새 UI 구현에서 발견한 경계·수명 문제는 코드와 회귀 시험이 설명하고, 로그 순서는 기존 지침에 이미 있다. 별도 해결 교훈은 중복해서 추가하지 않았다.
