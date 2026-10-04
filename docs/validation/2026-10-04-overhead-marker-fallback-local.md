# D-457 마커 우선·무마커 폴백과 지도 좌표 표시 — LOCAL 검증

- 브랜치: `fix/site-markerless-live-map`.
- 기준: 작업 시작 시 main `b58fed6fe`. UI/UX 리팩터링은 유보한다.
- 변경: 네 모서리 마커 측정 우선, 승인 사각형·차선 맞춤 보정 폴백. 로봇 마커는 인증 source의 명시적 대응으로 우선 표시하고, 무마커 검출은 신뢰 가능한 같은-map pose와만 이름을 대조한다. 불확실한 검출은 미확인으로 남긴다.
- 좌표: 현재 지도 프레임 X/Y(m), 소수점 두 자리. 마커 관측/무마커 추론/이름 미확정을 구분한다. 표시 해상도는 실물 정확도 주장이 아니다. 서버 age와 조회 지연을 뺀 최대 1초 표시 수명으로 만료되며 다음 조회가 멈춰도 지운다.

## 검증 결과

| 범위 | 결과 | 증거 위치 |
|---|---|---|
| 공유 payload, Vision 전체, Fleet tracking/CLI/server/boundary, 앱 역할 | 602 passed | `X:/DevTemp/rosy-live-console-20261004/final-tests.txt` |
| 좌표·보정 UI 서빙과 보정 영속 시험 | 33 passed | `X:/DevTemp/rosy-live-console-20261004/coordinates.txt` |
| Chromium: 좌표 전환·연결 지연 중 표시 만료·pagehide/BFCache·토큰 세대 | 14 passed, 1 deselected | `X:/DevTemp/rosy-live-console-20261004/expiry.txt` |
| 모듈/사이트 배포/프로토콜 정합성과 Fleet API·UI | 110 passed, 5 failed | `X:/DevTemp/rosy-live-console-20261004/final-guards.txt`; 실패 원인은 아래 기준 비교 |
| Node 순수 계산: 마커 우선·좌표·표시 수명·map-fit·레이어 | 34 passed | `node --test operations/fleet/test/web/{tracking-layer,map-fit,field-layers}.test.mjs` |
| 신규 Python 구현과 좌표 브라우저 시험 flake8 | exit 0 | max-line-length 120 |
| 독립 소스 리뷰 | 추가 중대 결함 없음 | 인접 로봇 일대일 중복 제거와 만료 회귀를 반영 |

Windows 수집 로그는 Python subprocess 바이트 출력으로 저장한다. 한글 오류가 포함되는 실행은 `PYTHONIOENCODING=utf8`을 설정한다. 시험에는 `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, X: basetemp를 사용했다. Fleet CLI의 기존 wheel 의존성은 operations/execution/src, contracts/skill/src, operations/processes/palletizing/src를 PYTHONPATH에 둔다. 관련 통과 로그는 `test/known_failures.py`로 비교했다.

## 기준 main에서 재현된 실패

깨끗한 `fix/map-baseline` worktree(`b58fed6fe`)에서 별도로 실행했다. 새 실패를 known_failures에 추가하지 않는다.

- `test_console_lifetime_browser.py::test_pending_confirmation_is_cancelled_and_cannot_submit_after_restore`: 기존 설치 화면의 접힌 카메라 요청 버튼에 click이 실패한다. 관련 만료 시험에서는 이 사례만 제외했다.
- `test_harness_contracts.py::test_every_module_log_is_valid`, full lint: 기존 deploy/logs.md 2407–2411의 깨진 한글·heading. main과 후보 lint 모두 같은 두 오류다.
- `test_module_structure.py::test_every_cross_package_use_is_declared`, `test_cross_domain_edges_follow_the_direction_table`: 기존 Fleet 캡처 도구의 games import 경계.
- `test_size_verdicts_are_well_formed_and_current`: 기존 sync-image-layer.py 1021줄이 1020의 zero-growth 기록을 초과한다. 후보가 추가한 Fleet 패키지·app composition·schema export 규모는 D-457 판정으로 기록했다.

깨끗한 기준 실행: `X:/DevTemp/rosy-live-console-20261004/clean-baseline.txt`. 후보가 만든 tracking scope·규모·API 문서 버전 실패는 수정 후 재검증했다. 공통 검사 전체가 녹색인 것으로 표현하지 않는다.

## 현장 상태와 남은 확인

- 실제 관제 PC 조회에서 등록 로봇 2대는 online이고 천장 영상은 수신된다. 이전 정적 로봇 항목 하나는 offline이며 등록 신원과 충돌한다.
- 현장 서버 `/api/fleet/tracking`은 아직 404다. 이 변경은 실행 중인 사이트에 배포되지 않았다.
- 등록 로봇의 map_id/localization이 없어 익명 검출을 실명으로 확정할 수 없다. odom을 map 위치로 사용하거나 이름을 임의 대응하지 않는다.
- 배포는 서명 사이트 후보 경로를 따른다. 기존 등록·토큰·SQLite를 보존하고, 중복 정적 항목과 카메라 대상은 현장 구성에서만 수정한다. 운영자 sudo 인증이 아직 없으며 이를 우회하지 않는다.
- 배포 후 승인 보정 적용, 빈 트랙 30프레임/최소 10초 배경 학습, 실제 기준점과 좌표 오차 측정, 마커 가림/복원, 영상 단절/복구를 확인해야 한다. DEVICE/FIELD 및 실제 좌표 정확도는 미검증이다. 주행 명령·E-Stop 해제로 검증하지 않는다.
