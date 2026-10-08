# 기존 Dashboard 지도 위치 추정 게이트 (2026-10-08)

## 문제와 변경

새 `/console`은 위치 증거가 fresh이고 `LOCALIZED/map`일 때만 지도 위 로봇을 표시한다. 기존 `/dashboard`는 pose 증거만 fresh이면 `SUSPECT/odom`에서도 로봇과 마지막 경로를 그렸고 주행 목표 버튼을 열어 두었다. 현재 `main`에서 두 뷰포트 모두 목표 버튼이 활성화되는 것을 재현했다 (`X:/DevTemp/projects/rosy-platform/2026-10-08--legacy-localization-4c8e/logs/before.txt`, 2 failed).

`/dashboard`도 위치 추정이 확인되지 않거나 내비게이션 증거가 오래되었거나 `SAFE_STOP`이면 지도상의 로봇·경로와 주행 목표를 제한한다. 초기 자세 설정은 위치 추정을 회복할 수 있도록 계속 제공한다. localization 필드가 없는 구형 CORE의 목표 가능 여부는 기존 pose freshness 계약을 유지한다. 지도 위 로봇 표시는 새 Console과 같이 명시적인 `LOCALIZED/map` 증거를 요구한다. 위치 추정이 불확실할 때 이전 목표 좌표 표시도 지운다.

## LOCAL 화면 증거

실제 `/dashboard` 모듈과 Chromium을 사용한 합성 지도·상태다. 로봇 또는 현장 경로 증거는 아니다.

| 상태 | 뷰포트 | PNG | SHA-256 |
|---|---|---|---|
| 수정 전 `SUSPECT/odom` | 390×844 | `X:/DevTemp/projects/rosy-platform/2026-10-08--legacy-localization-4c8e/evidence/before/compat-map-suspect-390x844.png` | SHA-256 `FF79C9196A89738B9A32913050FDDFA8 EF67BF9F81FCA2E50CBF06C1E8C942F6` |
| 수정 후 `SUSPECT/odom` | 390×844 | `X:/DevTemp/projects/rosy-platform/2026-10-08--legacy-localization-4c8e/evidence/after/compat-map-suspect-390x844.png` | SHA-256 `7D609561A37A60EB39B23D5C4641C1D7 8C142DD2D1BDCDC2D3126A15B3998B53` |
| 수정 후 `SUSPECT/odom` | 1366×768 | `X:/DevTemp/projects/rosy-platform/2026-10-08--legacy-localization-4c8e/evidence/after/compat-map-suspect-1366x768.png` | SHA-256 `D07823AD0D8CA060B4C3AD09D0A273FC E4BAED5B924B0B77E6D931E64F86FCC8` |

수정 후 목표 버튼은 위치 확인 이유와 함께 비활성화되고 초기 자세 버튼은 활성화된다. 로봇·경로는 사라지며 `LOCALIZED/map` 복구 후 목표와 경로가 다시 나타난다. `SAFE_STOP`에서도 목표·경로가 제한되고 초기 자세는 남는다. 이 동작은 390×844 및 1366×768에서 시험했다.

## 검증과 남은 평가

- 관련 Chromium·패키지 시험 **24 passed** (`X:/DevTemp/projects/rosy-platform/2026-10-08--legacy-localization-4c8e/logs/regression-final.txt`); `known_failures.py` **0 NEW**. `node --check`, `py_compile`, `git diff --check` 통과.
- 기존 키보드 지도 목표 시험은 현재 `main`에서도 지도 응답 `{}` 때문에 실패했다 (`logs/main-keyboard.txt`). 실제 지도 모듈에 10×10 합성 지도를 주도록 시험을 고쳐 목표 확인창·POST 경로가 다시 검증된다.
- 데스크톱 캡처의 기존 Dashboard 우측 조작 열은 1366px에서 일부 내용이 잘려 보인다. 이 변경은 지도 신뢰성에 한정했다. 전체 앱 레이아웃 G2/G3 평가와 실제 장치에서 localization 전이·Nav2 경로·초기 자세 readback은 계속 **HOLD**다.
