# Fleet Console 개발 세션 모바일 머리 복귀 — 2026-10-08

## 문제와 수정

현장 설치 화면에서 개발 세션 인증 후에도 좁은 화면의 설정 메뉴가 열린 채 남아, 390px 화면의 첫 약 294px을 접속·테마 조작이 차지했다. 원인은 첫 401에서 `markLocked()`가 설정을 자동으로 열고, 인증 성공 시 `connectionView.hide()`가 안내 띠만 숨긴 데 있다.

`connection-view.js`가 **잠금 때문에 자신이 연 메뉴**만 기억하고 인증 성공 시 닫는다. 사용자가 직접 설정 버튼이나 접속 안내 링크로 연 메뉴는 유지한다. 인증·토큰·로봇 조작 경로는 바꾸지 않았다. 개발 모드 표지와 비상 정지는 접힌 메뉴 밖에 계속 보인다.

## 재현과 검증

| 단계 | 결과 |
|---|---|
| 수정 전 390×844 Chromium | 개발 세션 발급 뒤 `#topbar-more[aria-expanded]`가 `true`인 채 남는 회귀 검사 실패. 나머지 직접 진입 3종은 통과. |
| 수정 후 390×844 Chromium | 인증 후 메뉴 접힘, 접속 안내 숨김, 지도 상태가 `auth`에서 벗어남, 상단 높이 170px 미만, 설정 버튼으로 재개방 확인. `1 passed`; `known_failures.py`: 0 new/known. |
| 1440×900 Chromium | 같은 세션에서 뷰포트를 바꿔 화면 캡처. 점유 지도가 없으면 `지도를 보내는 로봇이 없습니다`로 정직하게 표시. |
| 문법 | `node --check operations/fleet/fleet/server/web/connection-view.js` 통과. |
| 문서 | `rosy_harness.py generate` 뒤 `lint`: 0 errors, 23 warnings. 경고는 기존 모듈의 오래된 `last_verified` 기록. |
| D-153 G1 후보 | 관련 5개 suite에서 89 passed, 1 failed. 실패는 이 브랜치가 건드리지 않은 `learning/training/perception/dataset/review_app_web/app.js:242`의 `rgb(` 사용. `known_failures.py`: NEW 1. 깨끗한 기준 worktree `ac55defecd`에서 같은 단일 검사가 실패했고, 해당 파일과 검사 파일은 이 브랜치의 base까지 바뀌지 않았다. 현재 후보 G1은 HOLD. |

원본 캡처와 로그: `X:/DevTemp/projects/rosy-platform/2026-10-08--185314--fleet-dev-menu-return--0a3ef0/`.

| 파일 | SHA-256 |
|---|---|
| `evidence/fleet-dev-menu-390x844.png` | `F66D9747CF17B64C439E3C629C58A4973DA44C5469180882A917BB43BC7DFE21` |
| `evidence/fleet-dev-menu-1440x900.png` | `AFC22BB371478E1EC66B61BF19BD15340B6CE2179E5D4AA40408BA92F319A8D9` |

## 판정

이 변경은 **LOCAL 브라우저 회귀**다. `D-153` Fleet 화면 전체는 HOLD: 현재 후보 G1이 실패했고, G2 선언 상태·뷰포트 행렬과 G3 현장 사용자 수용도 끝나지 않았다. 현장 설치 태그 `ed006ce92`는 이 변경을 포함하지 않는다. 현장 2/2 연결과 카메라 관측은 이 메뉴 수정의 DEVICE/FIELD 수용이나 점유 지도·SLAM·경로 추종 증거가 아니다. 390px 화면에서 예외 요약과 로봇 카드 뒤로 지도가 밀리는 문제도 별도 우선순위로 남는다.
