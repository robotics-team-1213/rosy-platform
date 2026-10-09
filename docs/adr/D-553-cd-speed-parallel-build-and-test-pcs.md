## D-553 CD 속도 — fleet·sensing CI 샤딩, CI와 나란히 ARM64 빌드, 끝나지 않는 CD 거래 종료, 시험 PC 둘 동시 사용

**Status:** Accepted (2026-10-09, 사용자 지시 "CI/CD를 줄이고 ADR을 쓰고 처리").

잇는 결정: [D-436](D-436-change-scoped-test-tiers.md)(CI 범위·병렬 matrix) · [D-412](D-412-robots-self-update-from-signed-github-releases-when-idle.md)(로봇 자동 업데이트, 카나리) · [D-225](D-225-update-without-reflash-and-faster-card-writes.md)(페이로드 릴리스) · [D-437](D-437-github-hosted-builds-and-offline-local-signing.md)(빌드는 GitHub 러너, 서명은 운영 PC).

### Context

2026-10-09에 잰 시간(main push → 서명된 롤아웃):

| 단계 | 시간 | 병목 |
|---|---|---|
| CI (`ci.yml`, 실행 37876875654) | 11–12분 | `fleet` 한 잡 578 s. 그다음 `sensing` 381 s, `root-test-3of3` 361 s |
| CI 끝 대기 | CI 전체 | `robot_cd.py`가 CI 성공 뒤에야 빌드를 보냄 |
| ARM64 페이로드 빌드 (`build-native-payload.yml`) | 5–6분 | colcon 245 s, apt 66 s |
| 내려받기·서명·게시 | 약 2분 + 카나리 | |

`RosyRobotCD`(운영 PC 예약 작업)는 2026-10-05 18:06 이후 릴리스 045(sha `5bc111a9`)의 `preparing`에 머물렀다. 준비 거부(`RuntimeError`)가 `audit()` 전에 올라가 감사 기록이 남지 않았고, 단계가 끝나지 않아 5분마다 다시 시도했다. 046–056은 손으로 냈다. 045가 통과했다면 로봇의 056보다 오래된 릴리스를 게시했을 것이다.

### Decision

1. **느린 묶음을 파일 단위로 나눈다.** `tools/harness/affected_tests.py`의 `SUITE_SHARDS = {"fleet": 3, "sensing": 2}`. 루트 샤드(`ROOT_SHARDS`)처럼 정렬한 시험 파일을 `i::n`으로 나누고 이름은 `fleet-1of3`처럼 붙인다. 파일이 샤드 수보다 적으면 나누지 않는다. CI 임계 경로가 약 12분에서 약 6–7분이 된다.
2. **빌드는 CI와 나란히 돈다.** `robot_cd.py`는 main이 움직이면 그 sha의 릴리스 번호를 잡고 서명 없는 ARM64 빌드를 곧바로 보낸다. 서명(`preparing`)은 그 sha의 `ci.yml` push 실행이 성공해야 시작한다. 그 실행이 실패로 끝나면 거래는 `failed`가 되고 빌드는 버려지며 잡아 둔 번호는 빈자리로 남는다. 서명 없는 빌드는 비밀을 보지 않으므로 먼저 돌려도 신뢰 경계가 바뀌지 않는다. 약 6분이 준다.
3. **끝나지 않는 거래를 끝낸다.**
   - 서명 전에 번호가 더 큰 `payload-<date>-NNN` 태그가 있으면 `superseded`로 끝낸다. 오래된 릴리스로 로봇을 되돌리지 않는다.
   - 내려받기·준비 실패는 `prepare_failures`와 `last_error`에 남기고, 세 번째에 `failed`로 끝낸다.
   - tick이 예외로 멈추면 `stopped: <종류>: <내용>`을 감사 기록에 남긴 뒤 멈춘다.
4. **로컬 게이트는 시험 PC 둘을 같이 쓴다.** `tools/remote/remote_pytest.py`는 invocation이 둘 이상이면 닿는 호스트(`ROSY_TEST_HOSTS`, 기본 모델 PC·AI PC)에 `k % n`으로 나눠 동시에 돌린다. 호스트마다 커밋을 한 번 보내고 venv를 한 번 만든다. 결과 코드는 invocation 순서로 돌려준다. 한 호스트가 커밋 전송이나 venv에서 실패하면 그 몫은 성공한 호스트가 이어 돌린다. 둘 다 실패해야 게이트가 실패한다. invocation이 하나면 예전처럼 처음 닿는 호스트 하나만 쓴다. pre-push와 `tools/land.py`가 그대로 혜택을 본다.
5. **쓰지 않는 것.**
   - 우리 PC를 GitHub self-hosted 러너로 붙이지 않는다. 저장소가 공개라 포크 PR이 러너에서 코드를 돌릴 수 있고, 페이로드는 ARM64 빌드라 x86 PC로는 줄지 않는다.
   - 현장 PC(robttt)는 시험 호스트에 넣지 않는다. 라이브 Fleet 스택이 돈다.

### Consequences

- push → 서명 롤아웃이 약 18–20분에서 약 7–8분(+카나리)이 된다.
- CI가 실패한 sha마다 ARM64 빌드 한 번과 번호 하나가 버려진다(공개 저장소 러너라 비용 없음). CI 실패는 그 sha에 대해 끝이다. 같은 sha의 CI를 다시 돌려 초록이 되어도 그 sha로는 다시 릴리스하지 않고, 다음 main 커밋을 기다린다. 서명이 끝난 `publishing` 단계는 CI 재실행 결과로 끝내지 않는다(카나리 감시를 버리지 않는다).
- 설치된 서명 스냅샷은 고정이라, 이 변경은 착지 뒤 `install_robot_cd.ps1`로 새 스냅샷을 설치해야 동작한다. 새 스냅샷의 첫 tick이 멈춘 045를 `superseded`로 끝낸다.
- 시험 PC 둘을 동시에 쓰면 AI PC가 다른 일로 바쁠 때 그쪽 invocation이 느려질 수 있다. `ROSY_TEST_HOSTS`로 한 호스트만 줄 수 있다.
- 시험: `test/test_affected_tests.py`(샤드), `test/test_robot_cd.py`(CI와 나란한 빌드, CI 실패·superseded·세 번 실패 종료), `test/test_remote_pytest.py`(호스트 분배·순서).
