# Cell Fleet HTTP와 Linux UDS 점검 — 2026-10-03

D-413 Tasks 4–7의 연결·장애 점검이다. 원본 2층·팔레트별 슬립시트 1장·팔레트 2개의 전체 Gazebo 수용 목표는 유지한다. 이 기록으로 Task 8이나 ROS-SIM 게이트를 완료 처리하지 않는다.

## 환경과 실행

- 소스 기준: `c7321b9f6`; 연결 종료 수정: `6fab54172`. 소스는 Docker에 읽기 전용으로 연결했다.
- Linux 이미지: `rosy-omx-pilot:d411c2`, image ID `sha256:5c905d91b62269c57f1be7e7ded03f34e5ddb9855b9e4e118158f4075b81052b`. Python 3.12.3, ROS 2 Jazzy 및 OMX overlay를 source했다.
- `--network none`, `ROS_DOMAIN_ID=91`, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`. 장치와 호스트 포트를 연결하지 않았다. 시험의 loopback HTTP와 UDS만 사용했다.
- 이미지에 `httpx`가 없어 X:의 별도 system-site-packages venv에 저장소 `deploy/site/requirements-fleet.txt`를 설치했다. 선언된 Fleet pin을 사용한 검증 환경이며 새 배포 이미지나 전체 전이 의존성 lock을 만든 것은 아니다.
- 스크립트·로그·venv·SQLite·소켓은 `X:/DevTemp/rosy-linux-cell-check`를 `/evidence`에 연결해 보관했다. 초기 검증 스크립트가 ROS `PYTHONPATH`를 덮어써 ROS 모듈 3개가 skip됐다. 상속 경로를 보존한 뒤 실제 ROS 시험을 다시 실행했다.

## 확인한 동작

`test/test_platform_fleet_fence_readback.py`의 Linux 분기는 실제 Fleet HTTP/SQLite, 실제 조합된 Cell owner API, `UnixLocalStopTransport`, `SO_PEERCRED`를 통과한다. allowlist는 실제 kernel UID를 사용하며 UDS mode `0660`과 owner identity 응답을 확인한 뒤 시험한다. viewer 재승인 거부, 운영자 재승인, 역방향 HTTP fence 조회, 사이트 정지·세대 변경·인증 실패·연결 상실 거부를 확인한다.

HTTP와 UDS는 실제 전송이지만 서버는 같은 Python 프로세스의 스레드다. Cell owner의 ROS runtime/goal/gripper 포트는 이 시험에서 대체한다. 서로 다른 서비스 프로세스, 별도 UID의 거부, 실제 ROS Cell 조작, 물체 이동과 독립 목표 평가를 증명하지 않는다.

클라이언트가 응답 전에 연결을 끊으면 기존 `UnixActionServer`가 `BrokenPipeError`로 종료하고 소켓을 제거했다. main에서도 기존 UDS 시험의 시간 초과 뒤 같은 종료가 재현됐다. 새 결정적 시험은 요청 처리 중 클라이언트를 닫아 수정 전 실패를 확인했다. 수정은 연결별 `TimeoutError`와 `ConnectionError`만 처리하고 다음 요청을 받는다. 원장 저장 오류를 포괄적으로 삼키거나 요청을 재실행하지 않는다. 새 시험은 다음 identity 조회와 닫힌 local stop을 확인한다.

## 결과와 남은 실패

- 수정 전 연결 종료 회귀: **1 failed**, `BrokenPipeError`와 후속 identity 조회 실패.
- Windows focused: **44 passed / 2 skipped**. OMX adapter 및 owner/readback 회귀: **377 passed / 7 skipped**. production flake8 통과.
- 최종 Linux readback 집중 실행: **20 passed**, skip 없음. 실제 UID·소켓 권한·HTTP 역조회와 연결 종료 뒤 owner 생존을 포함한다. quick tier와 문서 배치·네트워크 계약: **126 passed**, harness lint **0 errors / 26 기존 warnings**.
- ROS 경로를 복원한 넓은 Linux 실행: 수정 전 **27 passed / 2 failed**, 수정 후 **28 passed / 2 failed**, 후자는 서버 스레드 예외 없음.
- 남은 기존 UDS 시험은 X: bind의 SQLite 처리 중 0.5초 응답 제한으로 첫 결과가 `ACCEPTED` 대신 `UNKNOWN`이었다. 변경 전 main의 같은 시험도 실패했다. 배포용 timeout이나 UNKNOWN 보호를 완화하지 않았다.
- 느린 ROS feedback 시험은 처음 feedback 미수신, 수정 후 `joint_state_stale` HOLD로 실패했다. 같은 환경 main의 단독 비교에서는 통과했으므로 아직 안정성과 원인이 확정되지 않았다. 최신성 보호를 제거하거나 성공으로 바꾸지 않았다.

넓은 Linux suite는 통과하지 않았다. 실제 ROS ActionServer·camera fixture의 통과 항목은 vendor Gazebo나 전체 Cell owner 경로의 증거가 아니다. G7 전체 장애 (a)–(i), G9 seat exclusion, 2 mm 슬립시트 접촉, 전체 18개 transfer와 독립 goal evaluator, 설치·배포·실물 수용은 계속 열려 있다.

## 최신 main 통합

`289d2c828`을 통합하고 생성 index 충돌을 재생성으로 해결했다. OMX adapter/owner/readback **438 passed / 7 skipped**, quick·문서·focused 계약 **170 passed / 2 skipped**, Linux 집중 **20 passed**. lint **0 errors / 25 warnings**. 독립 리뷰는 Linux **20 passed**, Windows **40 passed / 2 skipped**, Critical/Important 지적 없음. 이 통합 검증도 위의 넓은 Linux 실패 2개나 전체 수용 미완료를 해소한 것으로 기록하지 않는다.
