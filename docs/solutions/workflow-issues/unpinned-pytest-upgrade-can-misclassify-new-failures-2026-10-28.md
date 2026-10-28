---
title: 새 시험 환경의 pytest 변경을 소스 회귀로 오인하지 않는다
date: 2026-10-28
module: ROSY remote pytest and landing
problem_type: test_failure
component: development_workflow
severity: medium
symptoms:
  - "Fleet 시험 본문은 통과하지만 정리 단계에서 omx_instances KeyError가 발생함"
  - "후보의 단독 재시험은 실패하고 main 단독 재시험은 통과함"
root_cause: config_error
resolution_type: environment_setup
tags: ["pytest", "dependency-pins", "remote-tests", "main-red", "environment-identity"]
---

## 문제와 원인

`operations/fleet/test/test_work_sources.py`의 종류 판정 시험이 본문 통과 후
Starlette State를 복원하다 실패했다. 후보 revision `6007d3ceb8`의 단독 재시험도
`1 passed, 1 error`였고, main 재시험은 통과해 후보 소스의 회귀처럼 보였다.

두 시험 PC에서 실제 패키지와 설치된 MonkeyPatch 코드를 읽어 비교했다.
후보 환경은 pytest 9.2.0, main 환경은 9.1.1이었다. Starlette는 양쪽 모두 1.6.0이었다.
pytest 9.2.0의 속성 복원 기록은 인스턴스의 일반 속성 사전을 확인한다.
별도 사전에 값을 저장하는 State의 같은 속성을 거듭 패치하면 정리 과정에서
이미 지운 키를 다시 지우며 KeyError가 났다. 기존 Fleet 판정 조건을 바꾸지 않고
9.1.1을 설치한 환경에서는 같은 시험이 통과했다.

원격 설치 명령의 pytest 버전이 고정되지 않았다. 무관한 CI 입력 변경으로 새 환경이
생성되면서 시험기 버전까지 바뀌었다. 설치 레시피와 입력 Git 객체의 해시는
고정되지 않은 패키지가 실제로 어떤 버전으로 해결됐는지까지 증명하지 않는다.

## 해결과 검증

`tools/remote/remote_test_tools.py`의 기본 설치 레시피에 `pytest==9.1.1`을 명시했다.
기존 환경은 수정하거나 삭제하지 않았다. `remote_pytest.deps()`는 설치 레시피를
해시에 포함하므로 새 환경 이름이 자동 생성된다.

`test/test_remote_test_tools.py`는 과거 레시피에서 이 버전 고정 하나만 달라졌는지,
새 환경 해시가 과거 해시와 다른지, 추가 레시피 변경도 해시에 반영되는지 검사한다.
Fleet 시험의 상태 판정과 정리 조건은 그대로 유지했다.

아래 로그 표기는 소스 파일 경로가 아니라 Git 밖 작업 공간 영수증의 식별자다.
두 revision도 아직 공개 main에 게시되지 않은 로컬 시험 소스다.

- RED: `pytest-drift-red-6007/run-1.txt`, 기존 Fleet 시험 `1 passed, 1 error`.
- GREEN: revision `3d0cdfaa2c`, `pytest-pin-green-2/run-1.txt`, 관련 시험 167 passed,
  skipped 없음, known_failures 신규 실패 0. 실제 새 환경의 pytest 9.1.1도 확인했다.
- 위 로그는 작업 공간의 `2026-10-27-full-os-integration` 영수증 묶음에 보존했다.
  이 수정은 이 기록 작성 시점에 아직 main 착지 전이다. 공개 CI·이미지·SD 기록의
  통과 근거로 확장하지 않는다.

## 다음 적용과 복구

후보 실패를 main과 비교할 때 실제 시험기 버전과 모듈 위치를 먼저 확인한다.
다른 환경에서 main만 통과한 결과로 후보 소스에 원인을 확정하지 않는다.
pytest 업그레이드 때는 이 Fleet 시험을 정리 단계까지 실행하고 관련 전체 회귀를 확인한다.
이 고정은 모든 시험 도구의 전이 의존성을 고정했다는 뜻은 아니다.

설치 레시피는 요청한 소스 SHA만으로 정해지지 않고 실행 중인 원격 시험 도구에서 온다.
`land_checks.landed_copy()`가 main 도구로 위임하면 그 도구의 레시피가 사용될 수 있다.
현재 main을 먼저 병합한 뒤 정식 `--tests full` 실행을 시작하고, 위임 여부와 실제 환경
기록을 확인한다. 위임으로 옛 레시피가 선택되면 해당 실행을 정리하고 동기화한다.
소유 도구 강제 선택 환경변수나 수동 캐시 편집으로 관문을 우회하지 않는다.

속성 변경과 자동 복원 계약은 [pytest 공식 문서](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)를 참고한다.
버전별 원인 판단은 실제 실행 환경의 코드와 위 RED/GREEN 영수증에 근거한다.
