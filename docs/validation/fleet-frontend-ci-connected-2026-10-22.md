# Fleet 프런트 CI와 실제 API 화면 검증

2026-10-21~22 원격 시험 PC에서 실행한 코드 검증 기록이다. 공개 GitHub 실행, 운영 배포, 실장치·현장 수용 결과는 포함하지 않는다. 기존 [프런트 개발 분리 기록](fleet-frontend-development-2026-10-21.md)과 [HTTP 성공 경로 기록](fleet-frontend-http-success-2026-10-21.md)은 보존한다.

## CI 필수 검사

로컬 main `2b6f93281b80c9bf2154a6dfcc73d2e239d2620f`에 앱 Chromium 설치·브라우저 활성화와 FULL의 필수 `app-fleet` 항목이 반영됐다. affected에서도 앱 시험에 브라우저 플래그를 적용한다. 기존 Fleet shard와 account SSO, 다른 CORE 브라우저의 opt-in 범위는 유지했다.

| 실행 | 소스 | 결과 |
|---|---|---|
| workflow 실행 코드·FULL/affected matrix·browser scope | `8d0684cd6a` | 116 passed, skip 0, NEW 0 |
| 앱 Chromium 명시 활성화 | `fa2e8e3544` | 79 passed, skip 0 |
| 정식 착지 G1 | `2b6f93281b` | 267 passed, NEW 0 |
| 정식 착지 FULL 23묶음 | `2b6f93281b` | 30,551 passed, 1,999 skipped, NEW/known/flaky 0 |

FULL은 일반 실행에서 앱 브라우저 32건을 skip했다. 별도 명시 활성화 결과와 구분한다. 별도 앱 실행과 최종 착지의 앱 subtree는 `8f120231d5a3a4e6eabefce541cc7b495deb8869`로 같았다. 위 숫자는 실행 건수이며 중복 제거한 시험 개수는 아니다. 독립 검토가 최종 소스와 로그 연결을 확인했다.

## 실제 API 화면 흐름

검증 소스: `fcdf36bdc18fe9fe907e4c5cd626901cce7e09ff`.

`operations/fleet/test/test_app_connected_browser.py`는 API interception 없이 실제 앱 문서를 개발용 connected HTTPS 호스트에서 연다. 공유 `connected_fleet` fixture는 검증된 upstream TLS, 실제 Fleet `create_app`, 임시 SQLite 작업 원장과 `FakeRobot`을 제공한다. 브라우저만 시험용 자체 서명 인증서를 허용하며 upstream CA·호스트 검증은 유지한다.

화면에서 로그인 → 프로필 저장·새로고침 → 로봇 선택 → 지도 목표 확인·요청 → QUEUED 작업 취소 → 로그아웃·로그인 링크 이동을 조작했다. 실제 API에서 `QUEUED → CANCELED`, 취소 뒤 task readback과 로그아웃 뒤 세션 401을 확인했다. 가상 장치의 `navigation_goal` 호출이 없음을 검사한다. dispatcher는 꺼져 있으므로 장치 실행 전 대기 작업의 생성·취소 범위다. 두 서버와 브라우저는 fixture 종료 시 정리한다.

```powershell
python tools/remote/remote_pytest.py --sha fcdf36bdc18fe9fe907e4c5cd626901cce7e09ff --log-dir "$env:TEMP/fleet-connected-check" -- ROSY_RUN_BROWSER_TESTS=1 operations/fleet/test/test_app_connected_integration.py operations/fleet/test/test_app_connected_browser.py applications/fleet/test
```

결과: **81 passed, skip 0, NEW/known/flaky 0**, 87.32초. 두 connected 시험과 앱 시험 79건을 함께 실행했다. FastAPI/Starlette의 기존 deprecation warning 2건이 있었다.

## 실패 검출과 수정 이력

| 소스 | 관찰 |
|---|---|
| `b825278a17` | 공유 fixture 추출 전 예상 import/collection 오류 |
| `5610838f4f` | HTTP 시험 통과. 브라우저는 로그아웃 뒤 inline 입력창을 가정해 실패; 실제 로그인 링크를 따라가도록 시험 수정 |
| `027fbc2d3c` | 합동 81건 통과. 이후 독립 검토에서 미하달 assertion의 기록 키 `goal`이 실제 `navigation_goal`과 다름을 발견 |
| `b4e8878d18` | 시험 fixture에서 취소 API에 503 주입. 브라우저가 실제 취소 응답 검사에서 실패 |
| `2bd42baec2` | 실제 FakeRobot `navigation_goal` 호출 주입. 수정한 미하달 assertion에서 실패 |
| `fcdf36bdc1` | 두 장애 주입을 제거하고 전체 81건 재통과 |

주입은 시험 fixture에만 적용했고 최종 소스에는 남아 있지 않다. 기대한 실패를 제품 결함이나 정상 통과로 집계하지 않는다. 독립 재검토에서도 수정된 기록 키와 주입 코드 제거를 확인했다.

원본 로그는 Windows `%TEMP%`의 `rosy-fleet-ci-*`, `rosy-land/fix-fleet-app-browser-ci`, `rosy-fleet-connected-ui-*`에 있고, 우산 작업 공간의 `artifacts/receipts/fleet-frontend-ci-connected-20261022/`에 복사·SHA256 대조해 보존했다. 운영 자격 증명·DB·장치 연결은 사용하지 않았다.

## 적용 범위

제품 소스는 공개 단일 레포와 기존 Fleet 배포 구성을 유지한다. 이번 후속 변경은 시험·실행 안내이며 API 경로, 서비스 권한, CORE 최종 명령 권한을 바꾸지 않는다. 실제 로봇 주행·정지, 영상 장치, 이미지 빌드, staging 설치·복구·롤백, 현장 수용은 별도 검증이다. 기존 후보 빌드와 private 운영 설정의 승격 절차를 사용하며 이 기록으로 배포 상태를 READY로 변경하지 않는다.
