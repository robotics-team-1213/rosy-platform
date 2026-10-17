# 주제에서 ROSY Cell 작업까지 연결

사용자 요청은 주제를 받아 ROSY가 task를 실행하고 관제와 시뮬레이션이 결과를 주고받는 것이다.
기존 D-770·D-403의 owner와 승인·결과 의미를 유지한다. 새 모터 writer나 API는 만들지 않는다.

## 이번 구현

`operations/fleet/fleet/server/work/cell_task_client.py`는 에이전트가 해석한 사용자 주제와 명시적인 등록 레시피·셀
ID/hash·workcell/instance를 받아 기존 Cell app의 compile/proposals API를 호출한다.
자유문장을 해석하는 모델 자체는 이 도구에 포함하지 않는다. 에이전트는 수행 가능한 등록
스킬과 문서에만 요청을 연결하고, 불명확한 대상·위치는 추가 관측이나 사용자 입력으로 해결한다.
문장만 주고 임의 좌표를 생성하거나 실물 드라이버를 고르는 기능은 없다.

원본 주제와 binding을 새 디렉터리에 먼저 저장한다. 제출 INTENT를 먼저 남기고, POST는
한 번만 보낸다. 실패/응답 유실은 원본을 보존하며 자동 재시도하지 않는다.
request key는 새 요청 UUID와 원본·문서·instance의 canonical hash다. 같은 주제도 새 요청이면
별도 작업이 되며, 불명 제출을 같은 출력 경로에서 재전송하지 않는다. 재시도 판단은 기존 Fleet 조회로 한다.
compile 결과의 recipe/cell hash가 요청과 일치해야 proposal을 제출한다.

제안 응답은 mission ID와 상태를 보존한다. 별도 `status` 명령은 기존 cell-jobs GET을 사용한다.
PROPOSED/READY/RUNNING/ACTION_SUCCEEDED/GOAL_CONFIRMED/HOLD를 그대로 기록하고,
GOAL_CONFIRMED에서만 task_success=true다. 통신 불명·타임아웃은 작업 실패나 성공으로 꾸미지 않는다.
별도 `admit` 명령은 저장된 원본과 현재 Fleet 제안을 대조하고 명시적인 generation으로
기존 named operator 승인 API를 한 번 호출한다. READY 응답은 실행 성공이 아니다.
이 도구는 자동 admit/rearm/reset, 직접 ROS, serial, 별도 명령 소유자를 제공하지 않는다.
인증은 기존 named operator token 파일과 검증된 HTTPS다. HTTP는 loopback에서만 허용한다.

## 실행·검증 순서

- [x] 실제 Fleet 앱을 사용하는 테스트: compile→proposal→PROPOSED, 문서 변경 차단,
  불명 제출 재전송 금지, 실제 상태 조회와 독립 goal 결과 구분, 원본 보존.
- [x] 커밋된 RED를 모델/AI PC에서 확인한다. 노트북 pytest는 실행하지 않는다.
- [x] 최소 HTTP client와 CLI를 구현하고 같은 원격 테스트와 기존 Cell API 회귀를 확인한다.
- [ ] 독립 계약 리뷰 후 로컬 착지한다. 실제 사이트 활성화·구동 수용은 별도 증거다.
- [ ] 비현장 PC의 Gazebo 자원이 확보되면 기존 G2 Fleet→UDS→OMX owner→Gazebo→
  독립 goal evidence 경로를 실행한다. 모의 API 시험으로 Gazebo 성공을 대신하지 않는다.
- [ ] 기존 collection raw→검토→LeRobot reader→ACT→새 process 재적재를 연결한다.
  SIM 데이터와 실물 모방학습 데이터를 구분하며 실제 episode가 없으면 실데이터 학습을 시작하지 않는다.

현재 물리 진단에서는 indirect/direct ACK가 성공해도 cyclic goal readback이 바뀌지 않았다.
실물 제어 수용을 완료로 표시하지 않고, Fleet의 simulation-only guard를 실물용으로 해제하지 않는다.

## 에이전트 사용

기존 Fleet 환경의 Python에서 실행한다. `binding.json`은 `recipe_id`, `recipe_digest`, `cell_id`,
`cell_digest`, `workcell_id`, `instance_id` 여섯 필드다. 문서 목록·현재 digest는 기존
`GET /api/fleet/cell-app/documents`로 조회한다. 원문을 이해하고 적합한 등록 스킬·문서를 고르는
에이전트가 binding을 작성하며, 이 도구 자체가 자유문장을 해석했다고 표시하지 않는다.

```text
python -m fleet.server.cell_task_client --fleet-url https://<fleet-host>:<port> --token-file <operator-token-file> --ca-file <site-ca> prepare --topic "박스를 등록된 팔레트로 옮겨" --binding <binding.json> --out <new-request-directory>
python -m fleet.server.cell_task_client --fleet-url https://<fleet-host>:<port> --token-file <operator-token-file> --ca-file <site-ca> admit --prepared <request-directory> --expected-generation <current-generation> --out <new-admission-directory>
python -m fleet.server.cell_task_client --fleet-url https://<fleet-host>:<port> --token-file <operator-token-file> --ca-file <site-ca> status --mission-id <returned-mission-id> --out <new-status-directory>
```

인증정보는 인자 문자열이나 영수증에 넣지 않는다. 제출 후 기존 Fleet 승인 경로를 사용한다.
status는 현재 원장 조회이며 폴링·정지·재무장 권한을 새로 만들지 않는다.
