# D-856 중립 팔 사전검사 검증

API v1.299의 **simulation 읽기 경로**를 검증했다. 중립 팔 grant·동작 실행·Harbor 업무 완료·실물 수용의 증거는 아니다. [상세 계약](../../plans/2026-10-24-neutral-arm-preflight-design.md), [전체 계획](../../plans/2026-10-24-harbor-rosy-application-action-boundary.md)을 따른다.

## 소스와 검증 결속

| 소스 SHA | 검증 | 결과 |
|---|---|---|
| `c193c5e53c` | 신규 wire/owner/Fleet 계약 RED | 36 failed, 1 passed; 모델·operation·route 누락 |
| `7615a5cfd8` | 초기 구현·UI schema·기존 SIM pose binding | 109 passed, skip0 |
| `9c033f883d` | 설치 transform 대조 RED | 1 failed; helper의 신뢰된 transform 인수 누락 |
| `f18ea17d01` | transform 수정·실제 HTTP/UDS 포함 | 111 passed, skip0 |
| `72cec3a1e0` | 단독 HTTP suite와 서버 source bootstrap | 1 passed, skip0 |
| `364a579f47` | v1 거절 envelope 보존 RED | 1 failed; v1 요청에 v2 오류 응답 |
| `7d40743637` | 고정 code/reason 결속 RED | 3 failed; 다른 reason 허용 |
| `1c66d5cfa555c61ef858454c7af3a8769b2410d9` | 최종 신규 계약/HTTP와 기존 ActionApi·Cell runner/owner·UI·SIM pose 회귀 | 213 passed, skip0, 0 NEW; 공식 원격 runner exit0 |

위 SHA는 실제 시험한 당시 커밋이다. ActionApi의 안전 태그를 확인한 뒤 독립 검토 근거를 빠진 `Safety-Review:` trailer에 보완했다. 이 세션의 깨끗한 격리·미게시 브랜치만 재작성했고, 원래 이력은 `refs/wip/2026-10-24/d856-public-preflight-before-safety-trailer`에 보존했다. 재작성 head `f5bba002ecb76a427ae9155fe727078576c85ec6`과 시험 head `1c66d5cfa5`의 **전체 tree diff는 0**이다. 안전 태그 변경 commit은 `33ea1dec63`이다. 이후 이 기록·생성 문서 변경은 별도 metadata이며 새 SHA의 FULL 통과로 대신하지 않는다.

`ba9f37897a..f5bba002ec` 크기 검사는 9 commits 모두 통과했고 lint는 0 errors/33 warnings다. schemas facade는 UI DTO를 별도 leaf로 옮겨 1170→1142줄, app은 기존 SIM binding 검증 helper를 분리해 908→905줄로 낮췄다. canonical UI import·JSON 형식과 SIM binding 조건은 기존 시험으로 확인했으며 ratchet을 올리지 않았다.

최종 집중 실행을 같은 SHA로 재현하는 명령은 다음과 같다. 로그는 저장소 밖 `Temp/rosy-public-preflight-final/run-1.txt`에 보존하고 `test/known_failures.py`로 비교했다. 플랫폼 pytest는 개발 PC에서 실행하지 않았다.

```text
python tools/remote/remote_pytest.py --sha 1c66d5cfa5 --log-dir <external-log-dir> -- contracts/foundation/test/test_arm_transfer_preflight_contract.py middleware/devices/omx/adapter/test/test_transfer_preflight_api.py middleware/devices/omx/adapter/test/test_transfer_preflight.py middleware/devices/omx/adapter/test/test_transfer_motion.py middleware/devices/omx/adapter/test/test_omx_action_api.py middleware/devices/omx/adapter/test/test_omx_cell_transfer_runner.py operations/fleet/test/test_arm_transfer_preflight_api.py operations/fleet/test/test_arm_transfer_preflight_http.py test/test_platform_cell_owner_assembly.py test/test_platform_cell_owner_workflow.py middleware/core/api/test/test_ui_route.py test/test_native_gazebo_map_pose.py
```

## 실제로 통과한 경계

별도 server process는 `rosy.processes`·`rosy_cell`·`rosy_agent`·`rclpy`와 Cell compiler import를 차단한다. 고정 checkout의 adapter source와 foundation으로 실제 `ArmCommandOwner`를 만들고, 합성 관절 상태를 admission한 뒤 읽기 helper를 연결한다. Fleet 기본 bounded transport가 임시 Unix socket의 SO_PEERCRED 검사를 거쳐 `CheckTransfer`를 호출한다. HTTP는 실제 loopback uvicorn 서버다.

별도 client process는 `python -I -S`와 표준 라이브러리만 사용한다. core_common/fleet/omx_adapter가 import 가능한 설치 경로에 없음을 확인하고 HTTP 성공, 요청 전체 결속, sequence/나이·지원 범위, 없는 물리 참조·다른 catalog digest·viewer 거절을 단언한다. actuator port를 건드리면 시험이 실패한다. 서버·소켓·임시 DB는 시험이 종료할 때 닫는다.

서버 공정 독립성은 **import 차단**으로 증명했다. 실제 wheel을 설치한 뒤 palletizing 패키지를 제거한 환경 검증은 아니다. 초기 단독 HTTP RED는 시험 server subprocess에 adapter source path가 빠져 발생했고, bootstrap을 명시한 뒤 단독 실행을 통과했다. 이 실패를 제품의 transform 거절 증거나 정상 통과로 기록하지 않는다.

## 보존한 권한과 확인 한계

기존 proposer 인증과 설치 workcell→instance를 재사용한다. simulation 밖과 잘못된 target은 owner I/O 전에 거절한다. 새 operation에는 submit·claim·latch 해제·rearm 포트가 없고 dispatcher 없이 동작한다. owner가 admission한 snapshot의 calibration을 보존하며 transform은 신뢰된 owner 설치 값과 catalog를 대조한다. 계산 전후 freshness/clock·계획 출력 검증을 유지한다.

독립 계약 검토는 초기 transform 대조 누락을 지적했고 수정 재검토에서 닫았다. 마지막 소스 검토는 기존 LocalStopApi/UnixActionServer 본문이 base와 AST 동일함을 확인했다. 이는 계약 검토이며 물리 안전 attestation이 아니다. 단일 UDS 루프의 계산 중 stop 처리 지연은 측정하지 않았다.

clock·관절 상태·profile은 합성 simulation fixture다. 충돌 장면, 실물 기하/하중·보정, 실제 ROS 상태, 장치 정지와 현장 수용은 확인하지 않았다. 과거 `f3d7d3fba5` FULL은 실패 기록이며 이번 집중 GREEN으로 FULL 통과로 바꾸지 않는다. 기존 기동 회귀 수정의 충전 HTTP pipeline은 별도 `34ff5f55c1`에서 10 passed/skip0로 확인했다.

CE: 해당 없음 — 판단과 수정 조건을 코드·회귀·이 검증 기록에서 복원할 수 있다. 운영 장애나 장치 수용을 해결한 기록은 아니다.
