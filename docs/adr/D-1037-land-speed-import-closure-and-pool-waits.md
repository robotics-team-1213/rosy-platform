## D-1037 착지 시험 선택: 모듈 시험 디렉터리는 import 폐포로 좁히고, 꽉 찬 시험 PC·줄어드는 대기열은 기다린다

**Status:** Proposed (2026-11-17, 사용자 지시 "착지·게시가 너무 오래 걸린다"; 패널 발견 7일 실측. 노트북 시험은 없고 원격 시험 PC 결과만 있으며, 실제 착지 시간 단축은 며칠 측정 뒤 확인)

잇는 결정: [D-436](D-436-change-scoped-test-tiers.md)(변경 범위 시험) · [D-803](D-803-landing-queue-before-delta-rerun.md)(착지 대기열) · [D-584](D-584-tests-never-run-on-operator-laptop.md)(노트북 pytest 금지)

### Context

7일 실측(143건 착지): `middleware/core/gateway/test` 179회(21.6 h), 루트 `test` 47회(17 h), `operations/fleet/test` 75회(16.4 h)가 파일 한 줄을 고칠 때마다 디렉터리째 다시 돌았다. "landing queue full (12/12)" 정지 121회, "no test host reachable after 3600 s" 54회였고 대부분 호스트가 닿지 않은 것이 아니라 꽉 찬 것이었다.

### Decision

1. **D-436 선택 좁히기:** 모듈에 등록된 시험 *디렉터리*는, 바뀐 `.py`를 정적 import 폐포(절대·상대 import, 점 경로 접미사 일치로 풀어 넓게 잡음)로 닿는 시험 파일만 고른다. 시험 파일이나 그 폐포의 시험 쪽 도우미가 `importlib`·`subprocess`·`spec_from_file_location`·`runpy`로 동적 적재하면 그 파일도 함께 고른다. 다음은 지금처럼 등록 디렉터리 전체다: 바뀐 것이 `.py`가 아니다, `conftest.py`·`__init__.py`다, 어느 시험도 import하지 않는다, `conftest.py`가 닿는다. safety 태그 경로는 지금 층(FULL)을 그대로 둔다. 텍스트로 이름을 가리키는 시험(`referencing_tests`)은 그대로 더한다. 못 읽는 파일은 넓은 쪽(고른다)으로 진다.
2. **D-584 대기:** `remote_pytest`는 "닿는 호스트가 없다"(WAIT_S 3600 s 뒤 D-584 실패 유지)와 "닿지만 모두 가득 찼다"를 구분한다. 후자는 "hosts full"을 찍고 최대 12 h까지 기다리며, 노트북에서는 절대 돌리지 않는다.
3. **D-803 대기열 대기:** `land_async`는 대기열 가득 참(`ROOM_WAIT_S` 3600 s) 뒤에도 그 창 동안 티켓이 착지하거나 풀려 대기열 구성이 바뀌었으면 기다림을 갱신한다. 한 창 내내 아무것도 안 움직였을 때만 멈춘다.
4. **빠른 계약 선행(D-803):** 큐 티켓을 잡기 전에(`admit`) 정적 계약 시험 7개(ROS·브라우저 없음, 1분 안쪽, `tools/land_quick.py` 등록부)를 시험 PC에서 차례 우선으로 돌린다. 확정 NEW 실패면 티켓 전에 멈춘다. 호스트가 없거나 180 s 안에 비지 않으면 건너뛰고 본 라운드가 기다린다(`ROSY_LAND_NO_QUICK=1`로 끔).
5. **실패 우선 순서(D-436):** 호출 시작 순서는 예상 90 s 이하인 것을 (과거 실패율+0.01)/실행초 큰 순으로 먼저, 긴 것은 비용순으로 뒤에 둔다(`work_queue.order`, `rosy-land-events.jsonl` 근거). 첫 확정 실패 시 나머지 취소는 이미 있는 `on_done` 경로다. 고침 커밋 뒤에는 `land_cache`의 조상 재사용이 통과한 호출을 그대로 두고 실패·변경분만 다시 돌린다(시험 추가).
6. 이 ADR은 `BROWSER_PER_HOST`·브라우저 포트 규칙·known_failures 의미·FULL 증거 규칙을 바꾸지 않는다.

### Consequences

- 게이트웨이 비safety 파일 12개 표본에서 선택 시험 파일이 평균 225개에서 82개로 줄었다(측정은 `affected_closure` 직접 호출, 안전 쪽 과선택은 허용).
- 폐포 근사는 문자열·설정으로 파일을 읽는 동적 경로를 import로 못 본다. 그런 읽기는 `referencing_tests`와 동적 적재 감지가 맡고, 나머지는 게시 전 CI FULL이 그물이다.
- 대기열·호스트 대기가 길어질 수 있으나 정지(수동 재시도)가 줄어든다. 12 h 상한은 영구 가득 참(디스크 등)이 좀비 착지를 남기지 않게 하는 안전판이다.
