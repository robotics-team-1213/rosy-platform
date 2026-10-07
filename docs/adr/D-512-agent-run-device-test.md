## D-512 에이전트가 실기 시험을 직접 수행한다 — 카메라 사전 점검, 안전 장치 유지, 증거와 원상복구

**Status:** Proposed (2026-10-08). 도구 `tools/device_test/`는 호스트 단위 시험(가짜 전송)까지만 했다. 이 ADR로 로봇을 움직인 적은 없다. 첫 장치 실행이 이 ADR의 DEVICE 증거가 된다.

사용자 결정(2026-10-08): "케이블이 있는데 괜찮아. 너가, 그리고 카메라로 볼 수 있으니까 그렇게 해서 너가 하는 걸로 ADR로 기록하고 아예 할 수 있게 해."

### Context

- 실기 시험마다 사람이 현장을 보고 "움직여도 된다"고 답했다. 에이전트는 그 답을 기다렸고, 답이 늦으면 시험이 멈췄다.
- 2026-10-07부터 Fleet가 켜져 있으면 에이전트가 9dfk·8kcn을 움직일 때 동작마다 승인을 받지 않는다(사용자 결정). 로봇은 여러 세션이 같이 쓴다.
- 현장에는 머리 위 Rosy Cam(D-257/D-261, 사이트 PC Vision 미리보기 lease D-318)과 로봇 전면 카메라가 있다. 에이전트는 두 영상을 직접 볼 수 있다.
- 2026-10-07 D-491 현장 세션의 교훈(`docs/solutions/workflow-issues/field-scripts-driving-a-real-robot-need-clearance-identity-and-wall-pose-2026-10-07.md`): 다른 로봇을 9dfk로 잘못 골랐다, 스크립트에 몸체 판정이 없어 벽에 닿았다, 명령 고리가 300 ms 감시보다 느렸다, 응답을 확인하지 않았다, 로봇 위 케이블은 LiDAR가 못 본다, 끝에서 IDLE로 돌려야 한다.
- 로봇 설정을 시험 동안만 바꾸는 방법은 CORE 설정 겹 `~/.rosy/rosy.yaml`이다. 장치에서는 `rosy-core.service`의 `HOME=/var/lib/rosy/core`라서 `/var/lib/rosy/core/.rosy/rosy.yaml`이다(D-189 D3, D-495 결정 6). 바꾼 뒤 CORE를 다시 시작해야 읽힌다.
- D-476 결정 7은 bridge 승격 순서를 재생 → 시뮬 → 장치로 정했다.

### Decision

1. **누가.** 에이전트 세션이 실기 시험을 직접 수행한다. 사람에게 동작마다 묻지 않는다. 판단 근거는 카메라와 CORE 상태이고, 판단과 근거를 기록으로 남긴다. 사용자는 언제든 멈출 수 있다(Fleet 정지, E-Stop, 증거 디렉터리의 `STOP` 파일, Ctrl-C).
2. **사전 조건.** 아래가 모두 참이어야 로봇을 바꾸거나 움직인다.
   1. 동료 확인: 에이전트가 `ListAgents`(있을 때)와 Fleet 화면으로 그 로봇을 쓰는 세션이 없음을 보고, 무엇을 봤는지 `--peer-check-ok`에 적는다. 로봇의 D-412 자동 업데이트 `precheck`에 다른 holder의 hold, claim, 또는 읽을 수 없는 `hold.json`이 있으면 동료 충돌로 중단한다(불분명한 hold는 비어 있지 않은 것으로 본다). 이 도구의 이전 hold가 남아 있으면 `--restore`를 쓰라고 알리고 중단한다. 없으면 시험 동안 hold를 건다(`agent-device-test`, 1 h).
   2. 신원: SSH `hostname`이 대상 이름과 같아야 한다. 카메라 판정(3항)에서 머리 위 영상의 그 로봇이 대상임을 다시 본다. 대상인지 확실하지 않으면 작은 이동(`tools/capture/edge_drive.py nudge`)을 영상으로 확인한 뒤에 시험한다.
   3. 건강: `rosy-core` active, `online`, E-Stop 아님, 배터리가 계획의 하한(기본 40 %) 이상, line-follow가 `OFF`(다른 누군가 운전 중이 아님), D-395 위치 추정이 `LOCALIZED`이고 `pose_frame`이 `odom`이 아님(`localization`이 null인 로봇은 D-395 이전 로봇). 위치 추정은 겹 적용 뒤 CORE가 다시 시작한 다음, 출발 전에 한 번 더 본다.
3. **카메라 사전 점검.** 도구가 머리 위 Rosy Cam 프레임(사이트 `POST /api/fleet/vision/lease` → frame), 로봇 전면·원본 프레임, LiDAR 스캔 하나를 저장한다. 기계 판정은 RobotBody 몸 간격 하나다(D-424, 권고. CORE D-422 정지가 권위). 에이전트가 프레임을 보고 판정 파일에 다섯 값을 참·거짓으로 적고 `judged_by`에 자신을 적는다: 시작 자세에 있음, 본 로봇이 대상임, 계획 경로가 비었음, 케이블이 보임, 케이블이 경로·바퀴에 걸림. 경로가 비지 않았거나 케이블이 경로·바퀴에 걸리면 중단한다. 로봇 근처의 케이블은 **사용자가 받아들인 위험**(2026-10-08)이다. 보이면 기록하고 진행한다. 판정은 닫힌 쪽으로 실패한다: 값이 참·거짓이 아니거나, `judged_by`가 비었거나, 판정한 머리 위·전면 프레임이 없거나 그 `sha256`이 지금 파일과 다르거나, 기본 300 s보다 오래됐거나, 지금 자세나 그때 자세를 모르거나, 그 뒤 로봇이 0.05 m 넘게 움직였으면 중단하고 다시 찍는다.
4. **안전 장치는 끄지 않는다.** D-422 몸 기준 정지, 300 ms 원격조종 감시, IR 가드(D-344 §12, D-491 횡단보도 구간), 속도 상한(겹의 `cruise_speed`·`max_linear` ≤ 0.10 m/s), line-follow 운전자 hold(`hold_s` ≤ 1 s 세션, 0.1 s마다 갱신), D-500이 들어오면 그 L0 한도. 시험 계획의 겹은 정해진 키만, 키마다 정한 값 규칙으로 쓴다(`tools/device_test/plan_rules.py` `RULES`): `bridge_enabled`·`recovery_local_enabled`는 참·거짓, `ir_guard_enabled`는 참만, `cruise_speed`·`max_linear`는 0.10 m/s 이하. `bridge_*` 값은 `LineFollowConfig` 검증 범위 안에서 `rosy_default.yaml` 기본값보다 보수적인 쪽으로만 바꾼다: 무장 관문(`bridge_arm_*`)은 더 엄하게, `bridge_coast_m`·`bridge_slow_scale`은 기본값 이하, `bridge_slow_m`은 재무장 거리로도 쓰여 작게 해도 엄해지지 않으므로 기본값(0.25)만, `bridge_coast_m` ≤ `bridge_slow_m`, `bridge_distance_scale`(주행 거리 부풀림)과 `bridge_time_margin_s`(LOST 시계보다 먼저 끝내는 여유)는 기본값 이상. 두 값은 클수록 bridge가 일찍 끝나므로 이쪽이 보수적이다. `bridge_lookahead_m`은 안전한 방향이 없어 받지 않는다. 바닥 증명을 대신하는 현장 선언(`bridge_site_no_dropoffs`, `junction_turn_site_accepted`, `site_floor_map_id`)은 계획의 `accepted_risks:`에 그 키, `accepted_by`, ISO 날짜 `date`, `reason`이 있을 때만 받는다. 목록에 없는 키는 모두 거부한다. 겹 경로는 `/var/lib/rosy/core/.rosy/rosy.yaml` 하나로 고정한다. 시험 고리가 멈추면 바퀴를 세우는 권한은 CORE에 있다: hold가 `hold_s` 안에 오지 않으면 CORE가 CAMERA_LINE을 `OFF`(`driver_released`)로 내린다. 고리의 각 호출은 재시도 없이 짧은 시간 제한(0.25 s)으로 한 번만 하므로 한 틱은 약 1 s를 넘지 않는다. `/robot/state`는 틱마다 읽고, 연속 5번(0.5 s) 실패하면 자세와 E-Stop을 모르는 것으로 보고 중단한다.
5. **중단 조건.** 계획이 정한 CORE 정지 사유(예: `obstacle_ahead`, `lane_departure`, `driver_released`), 계획이 정한 이벤트(기본 `safety.*`), E-Stop, CORE 응답 또는 hold가 1 s 넘게 실패, 거리 상한이 있는데 자세를 모름, 출발 거부(예: 409 `NOT_LOCALIZED`), 카메라 판정 실패, 동료 충돌, 운영자 정지(`STOP` 파일, Ctrl-C, SIGTERM). 접촉은 직접 재지 못하므로 `still_s`보다 오래 멈췄는데 그 사유가 계획의 `ok_still_reasons`에 없으면 접촉 의심으로 중단한다(목록이 비면 모든 멈춤이 중단). 중단은 실패이고(종료 코드 2), 원인을 요약에 적는다.
6. **설정 변경은 임시이고 반드시 되돌린다.** 로봇에 처음 쓰기 전에 증거 디렉터리에 `RESTORE_PENDING.json`(로봇, 겹 경로, 로봇 쪽 사본 이름, 원래 내용과 이번에 쓴 내용의 `sha256`, hold 주인)을 쓰고, 복원이 확인된 뒤에만 지운다. 겹 파일을 읽어 증거에 남기고 로봇에 `.bak-<시각>` 사본을 둔다(실패하면 중단). 계획의 키만 병합해 UTF-8로 임시 파일에 쓰고, 로봇에서 그 파일의 `sha256`과 YAML 해석 결과가 의도와 같은지 본 다음에만 `mv`로 바꾼다. 있던 디렉터리와 파일의 주인·권한은 그대로 두고, 없을 때만 `rosy-core` 것으로 만든다. CORE에는 실제 적용된 `line_follow` 값을 읽는 API가 없다. 그래서 CORE를 다시 시작한 뒤 새 프로세스(PID가 바뀜)의 환경(`ROSY_CONFIG` 또는 `HOME`)이 바로 그 겹 경로를 읽고, 그 프로세스의 journal에 설정 오류(`ConfigError`·`ValueError`·거부)가 없고(journal을 읽지 못하면 실패), `systemctl restart`가 성공하고, 5 s 뒤에도 같은 PID로 active이며, 다시 읽은 파일 값이 계획과 같아야 출발한다. 90 s 안에 준비되지 않거나 하나라도 다르면 움직이기 전에 중단한다. 무엇이 실패하든(Ctrl-C·SIGTERM 포함) 정리는 line-follow `OFF` → `IDLE` → 녹화 정지 → 겹 파일을 원래 바이트 그대로 복원(없었으면 삭제)·바이트 비교·CORE 재시작 확인 → hold 해제 → 사후 프레임 순으로 한다. 정리 동안 SIGINT·SIGTERM은 무시하고, 한 단계가 실패해도 다음 단계를 한다. 각 단계는 HTTP 200 또는 종료 코드 0이어야 성공이다. 녹화 상태를 읽지 못하면 정지로 보지 않는다. hold는 `precheck` 출력에 정확히 `hold by agent-device-test:`가 있을 때만 이 실행의 것으로 보고 푼다. 다른 `hold by `, `hold.json` 문구, `claim held by`가 있거나 `precheck`가 0·3(사유 있음) 밖의 코드로 끝나면 불분명으로 보고 풀지도, 없다고 보지도 않는다(정리 실패, 표지 유지). D-412 갱신기에는 주인을 지정한 해제가 없어서, 읽은 뒤 해제하기 전 사이의 경합은 남는다(갱신기는 이 ADR의 범위 밖). 실패는 오류로 남기고 실행을 종료 코드 2(`CLEANUP FAILED`)로 끝낸다. 복원이 확인되지 않으면 hold를 풀지 않고 `RESTORE_PENDING.json`을 남긴다. 프로세스가 죽었거나 복원이 실패했으면 `run.py --restore <증거 디렉터리>`가 그 표지에서 복원·확인·hold 해제를 다시 한다. `--restore`는 먼저 읽기만 해서 로봇이 이번 실행이 남긴 그대로인지 본다: 표지의 겹 경로가 고정 경로와 같고, hold가 없거나 위 규칙으로 `agent-device-test`의 것이고(불분명하면 거부) claim이 없고, line-follow가 `OFF`이고, 지금 겹 파일의 `sha256`이 이번에 쓴 것이나 원래 것과 같아야 한다. 하나라도 아니면 로봇에 아무것도 보내지 않고 사람에게 넘긴다. SIGTERM 처리는 최선의 노력이다. Windows의 종료는 TerminateProcess라 처리기가 돌지 않으므로, 그때는 표지와 `--restore`만이 로봇을 지킨다. hold를 걸기 전에는 로봇이 동료의 것일 수 있으므로 IDLE도 보내지 않는다.
7. **증거.** D-379 녹화(시험 동안), CORE line-follow 상태 10 Hz `status.jsonl`, 이벤트 `events.jsonl`(`since_seq`), 전후 카메라 프레임, LiDAR 스캔, 판정 파일, 겹 파일 사본. 원본은 공개 저장소 밖(기본 `X:/DevTemp/device-test/`)에 두고, `docs/validation/<topic>-<date>/`에 `summary.json`(단계, 관찰한 상태·사유·이벤트, 결과, 원본마다 `sha256:` 요약)과 README를 둔다. 요약의 문자열 키와 값(동료 확인, 중단 사유, 관찰한 사유 이름 등)에서 IP 주소, URL, `.local` 호스트 이름, Bearer 값과 토큰 모양 문자열을 JSON으로 쓰기 전에 지운다. `sha256:` 요약, 녹화 id, 릴리스 id는 남긴다. 기대한 상태·사유가 보이지 않으면 완료지만 불합격이다(종료 코드 1).
8. **D-476 rev 2 장치 시험의 순서 예외.** 사용자 결정(2026-10-08)으로 D-476 결정 7의 재생 → 시뮬 → 장치 순서를 rev 2 장치 시험에 한해 바꾼다. 장치 시험을 먼저 하고, 그 녹화가 결정 7 단계 1(실주행 재생)의 자료가 된다. 장치 통과가 bridge 기본값 승격을 뜻하지는 않는다(D-468 결정 8). 계획은 `tools/device_test/plans/d476_bridge_9dfk.yaml`이다. D-507 9항이 착지하면 그 계획의 `bridge_site_no_dropoffs`를 `site_floor_map_id`로 바꾼다.
9. **도구.** `python tools/device_test/run.py --robot <이름> --plan <계획.yaml>`. 먼저 `--preflight-only`(바꾸거나 움직이지 않음), 그 다음 `--camera-verdict <파일>`. 남은 변경은 `--restore <증거 디렉터리>`. `--dry-run`은 네트워크·SSH 호출 없이 계획과 단계만 보인다. 주소·토큰·사이트 URL은 명령줄이나 환경 변수로만 받고 저장소에 두지 않는다.

### 기존 결정과 관계

| ADR | 관계 |
|---|---|
| D-379 | 시험 녹화 경로를 그대로 쓴다 |
| D-412 | 시험 동안 자동 업데이트 hold. 다른 holder의 hold·claim은 동료 충돌 |
| D-422 / D-424 | CORE 몸 기준 정지는 켠 채로 둔다. 도구의 RobotBody 판정은 권고 |
| D-430 | 안전 분리는 그대로다. 도구는 안전 경로를 바꾸지 않고 CORE API만 쓴다 |
| D-468 / D-476 | 결정 8: rev 2 장치 시험 순서 예외. 장치 녹화는 D-476 결정 7 단계 1 자료 |
| D-491 | IR 가드와 횡단보도 구간은 계획의 겹 설정대로 둔다 |
| D-500 (Proposed) | CORE 명령 입구 판정이 들어오면 그 L0 한도 아래에서 시험한다 |
| D-507 (Accepted, 구현 전) | 현장 바닥 선언 키가 바뀌면 계획의 겹 키를 바꾼다 |

### Alternatives

- **매번 사람에게 묻는다.** 지금 방식이다. 응답을 기다리느라 시험이 멈추고, 사람의 "괜찮다"는 기록이 남지 않는다. 기각.
- **카메라 판정 없이 LiDAR만 본다.** LiDAR는 얇은 케이블과 바닥 아래를 못 보고, 신원을 확인하지 못한다(2026-10-07). 기각.
- **영상 판정을 도구가 자동으로 한다.** 아직 검증된 검출기가 없다. 기계 판정은 몸 간격과 자세 변화만 두고 영상은 에이전트가 본다. 검출기가 생기면 다시 본다.

### Consequences

- 시험마다 사람의 시간이 들지 않는다. 대신 에이전트의 판정 파일과 프레임이 남아 나중에 검토할 수 있다.
- 겹 파일을 바꾸면 CORE가 두 번 다시 시작한다(적용·복원). 그 사이 로봇은 몇십 초 동안 API에 답하지 않는다.
- 판정은 에이전트의 눈이다. 잘못 본 판정은 CORE 안전 장치가 마지막으로 막는다.

### Validation

- 호스트: `python -m pytest tools/device_test/test -q`(가짜 로봇: 단계 순서, 중단·SIGTERM·정리 중 Ctrl-C 뒤 OFF·IDLE·복원·해제, 정리 실패가 종료 코드 2, 복원 실패 시 hold·표지 유지와 `--restore`, 임시 파일 검증·읽기 불일치·CORE 설정 경로·설정 오류 중단, 동료·불분명 hold, 판정 관문, 자세 모름, 설명 없는 멈춤, `NOT_LOCALIZED`, 겹 허용 목록, 요약 정리, 상태 읽기 연속 실패, 재시작 실패, 도중에 바뀐 hold 주인, 녹화 상태 모름, 남의 것이 된 로봇에서 `--restore` 거부, 겹 경로 고정, 사전 점검·dry-run 무변경).
- 장치: 첫 실행(9dfk, D-476 rev 2)의 `docs/validation/d476-bridge-9dfk-<date>/summary.json`. 호스트 pytest 통과는 장치·현장 수용이 아니다.
