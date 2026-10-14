# OMX 녹화 probe 개선과 원격 검증

2026-10-14. branch `feat/omx-sim-preparation`. 실제 Gazebo나 장치 수용 기록은 아니다.

## 재현과 수정

기존 녹화 probe는 ROS `SUCCEEDED`와 frame 수만으로 성공을 기록했다.
관절이 실제로 움직이지 않는 성공 응답을 거절하지 못했고, 기존 조작 probe의
상태 충돌 1회 재시도를 사용하지 않았다. 갱신 worker의 예외도 caller에 전해지지 않았다.

`feffe7396`의 원격 RED는 3 failed, 1 passed이며 알려진 실패 비교에서 NEW 3이었다.
`Probe.run_jog`의 기존 관절 이동·목표 오차와 fresh-state/request-id 재시도를
재사용하고, 갱신 예외를 저장해 caller에서 거절했다. `c7be854b5`의 관련 원격
회귀는 32 passed, NEW 0이었다.

독립 리뷰에서 close/다음 recording 생성 중 늦게 도착하는 갱신 오류가 빠질 수
있음을 찾았다. 실제 스레드로 해당 타이밍을 재현한 `b4bf457`은 1 failed,
4 passed, NEW 1이었다. `b3d6f4cd5`는 공유 HTTP client의 10초 socket timeout을
고려해 worker를 11초 기다린 뒤 실제 종료 여부를 확인한다. 종료 불명이면 실패다.
의도적 lease-expiry 타이머는 worker 종료와 갱신 오류 확인 뒤에 시작한다.
정리 중 종료 검사가 실패해도 seat DELETE를 시도한다. 독립 재검토에서 추가 소스
차단 사항은 발견되지 않았다.

socket timeout은 전체 요청 deadline이 아니다. peer가 응답을 늘어뜨려 worker가
계속 남으면 성공 판정을 거절하며, 물리 정지나 transport 취소를 주장하지 않는다.

## 시험 범위와 실행 한계

- 새 recording probe 회귀: 움직이지 않는 ROS 성공 응답 거절, fresh 상태로 1회 재시도,
  갱신 실패와 close 중 in-flight 갱신 실패 거절, 정상 출력의 pairing/token 비노출.
- 기존 Pilot probe는 실제 SIM HTTP API/runtime에 fake arm을 연결하는 host 시험이다.
  기존 녹화 capture/API·독립 Compose 회귀도 함께 실행한다.
- 최종 `b3d6f4cd5` 원격 시험은 33 passed, NEW 0이다. terminal exit 0이며
  `test/known_failures.py`로 비교했다. FastAPI/httpx/anyio deprecation 경고 2개가 있다.
- 비현장 SIM 자원 재확인에서는 예약 반영 메모리가 8 GiB 최소보다 작았다.
  AI PC의 read-only Docker 진단은 `docker: command not found`였다. Docker 설치나
  권한 변경, laptop/현장 PC Gazebo 우회 실행을 하지 않았다.
- 이전 모델 PC Docker 소켓 접근 실패와 별개로 새 이미지 build/live Gazebo,
  실제 episode export/ACT·HF readback·실물 수용은 이번에 수행하지 않았다.

로그는 `X:/DevTemp/projects/rosy-platform/2026-10-14--035840--omx-sim--9a5dea/logs/`의
`recording-red`, `recording-green`, `recording-late-red`, `recording-final`에 보존한다.
실행 준비와 후속 조건은 [준비 계획](../../plans/2026-10-14-omx-simulation-preparation.md),
[D-756](../../adr/D-756-omx-imitation-preparation-and-resumption-gates.md)을 따른다.
