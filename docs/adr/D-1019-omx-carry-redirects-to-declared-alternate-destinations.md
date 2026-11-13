## D-1019 OMX 운반은 도착지에 자리가 없으면 선언된 대체 도착지로 자동으로 옮긴다

**Status:** Accepted (2026-11-13, 사용자 결정 "위치가 바뀌었을 때 다른 슬롯이나 구역을 바꾸는 것도 자동으로 허용"). 코드·원격 시험까지다. 실물 수용은 아직 없다.

잇는 결정: [D-911](D-911-omx-native-reviewed-operating-envelope.md)(검토된 실물 작업 범위) · [D-1014](D-1014-unified-area-xyz-coordinate-directive-from-middleware-to-cell.md)(셀 위치 지시) · [D-326](D-326-agent-loop-boundary.md)(모델은 후보만)

### Context

1. 실물 운반의 유일한 경로는 `cell_auto_pick.run_auto`이고, `cell_task_runner`가 작업을 운반 목록으로 펴서 하나씩 부른다(2026-11-13 조사, `Rosy/docs/workspace-records/2026-11-13/vla-scenario-pipeline-handoff.md` 조각 0).
2. 도착지가 차 있으면 `cell_place_fit.options`가 같은 사이트 안에서만 위치·±90°를 찾는다. 찾지 못하면 모든 물체를 `place: …`로 거부하고 운반이 멈춘다. 이때 팔은 움직이지 않았다. 다른 사이트로 바꾸는 실물 경로는 없었다(`redirect_place_on_zone_obstruction`은 시험에서만 쓰였다).
3. `run_auto`는 도착지 점유를 시도 전에 한 번만 봤다. 시도 사이에 도착지가 바뀌면 낡은 점유로 골랐다.

### Decision

1. **도착지 사이트는 설정에 대체 도착지를 순서대로 선언할 수 있다:** `sites.<이름>.alternates: [<사이트>, …]`. 설정에 있는 사이트이고 그 운반의 출발지·원래 도착지가 아닌 것만 쓴다. 선언이 없으면 지금처럼 멈춘다.
2. **대체 도착지는 "자리가 없어서 팔이 움직이기 전에 멈춘" 경우에만 쓴다.** `run_carry`의 `dest_full`은 셋이 모두 맞을 때만 참이다.
   - 시도가 **하나뿐**이고 그 시도가 고르기 단계에서 끝났다(행의 `error`가 정확히 `no usable object`; `run_auto`가 움직이기 전에만 쓰는 값이다. 피벗 뒤 실패는 다른 문구다). 둘째 시도가 있거나, 한 물체를 자리 때문에 거부하고 다른 물체를 옮기다 멈춘 경우는 이미 움직였으므로 대체하지 않는다.
   - 그 시도의 거부가 모두 `place:`이다.
   - 거부 사유에 `something is already there`가 있고, 나머지는 `does not fit on the surface`뿐이다. 지도 없음(`no map at the destination`)·아래층 없음(`nothing under it at the lower tier`)은 자리 문제가 아니므로 대체하지 않는다.
   파지·계획·가드 정지는 대상이 아니다. 강제 정지를 재시도로 바꾸지 않는 규칙은 그대로다.
   **교환(`swap`)은 대체하지 않는다.** 교환은 어느 물체가 어디에 끝나는지가 목적이라, 대체하면 작업이 `done`인데 교환이 안 된 상태가 된다(2026-11-13 Codex 검토).
3. **대체 도착지마다 새로 관찰한다.** 각 시도는 `run_auto`를 처음부터 다시 부르고, `run_auto`는 시도마다 도착지를 다시 본다.
4. **물체를 따라간다.** 대체 도착지로 놓았으면, 원래 도착지에서 그 물체를 가져가기로 한 다음 운반 하나만 대체 도착지에서 가져간다. 그 뒤의 운반은 다른 물체이므로 바꾸지 않는다.
5. **D-911을 넓히지 않는다.** 대체 도착지로 가는 경로도 `Gate`가 검사한다. 자동 모드에서는 사람이 검토하지 않은 경로를 hold한다. 사람 확인 없이 고르는 것은 "어느 선언된 사이트로 갈지"뿐이고, 팔 명령의 승인 조건은 바뀌지 않는다.
6. **결과에 남긴다.** 대체 운반 단계는 `redirected_from`을 단다. 작업 결과 JSON에 원래 도착지와 시도한 대체 도착지가 모두 남는다.

### Consequences

- 자리가 없을 때 사람을 부르지 않고 선언된 곳으로 간다. 어디로 갈 수 있는지는 사람이 설정으로 정한다(모델이 정하지 않는다).
- 적층(`stack`) 작업의 층 사이트도 대체 도착지를 선언할 수 있다. 다른 열로 옮기면 그 열의 층 순서가 달라지므로, 층 사이트에는 같은 층의 다른 열만 선언하는 것이 맞다(설정 책임).
- 대체 운반의 성공·실패를 `cell_choices`로 쌓아 순서를 바꾸는 것은 후속이다(인계 문서 조각 3).

### 관계

| 결정 | 관계 |
|---|---|
| D-911 | 바꾸지 않는다. 대체 경로도 `Gate`의 검사와 hold를 그대로 받는다 |
| D-1014 | 바꾸지 않는다. 이 결정은 사이트 이름 경로(`cell_auto_pick`)에 적용된다. AreaXYZ 실행 경로는 아직 실물 호출자가 없다 |
| D-427·D-429·D-430 | 구조 변경 없음. `deploy/robot/omx` 안의 기존 모듈만 바꾼다 |

### 증거

- `deploy/robot/omx/cell_task_runner.py`(`run_carry` `dest_full`, `alternates`, `run_task`), `deploy/robot/omx/cell_auto_pick.py`(시도마다 도착지 관찰).
- `test/test_omx_cell_task_runner.py`: 순서대로 대체, 모르는 사이트·출발지 제외, 자리 외 정지에는 대체 없음, 물체 따라가기는 다음 운반 하나만, `dest_full` 판정.
