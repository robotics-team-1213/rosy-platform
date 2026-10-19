# Station integration 시험의 같은 소스 실패·통과 기록

공개 D-762의 한 번 재시험 분류를 위한 근거다. 원인 해결·변경 전부터 존재한 실패·장치 수용을 입증하지 않는다. `known_failures.txt`, 생산 코드, 기존 기대 결과·freshness·timeout은 변경하지 않는다. 등록 항목이 두 번 실패하면 계속 NEW다.

## 등록 후보와 증거

노드의 공통 접두어는 `middleware/core/gateway/test/`다. 원본 비공개 실행 기록은 Account rollout evidence bundle에 보관하며, 아래 상대 artifact 이름과 SHA-256으로 식별한다. 실제 주소·계정·호스트 경로는 공개하지 않는다.

| 정확한 노드 | 변경 없는 commit SHA | 실패와 통과 |
|---|---|---|
| `test_station_redeployment_http.py::test_real_runtime_renews_and_releases_only_after_native_and_measured_departure[True]` | commit `e26407972bad7012779557178e8c0ad0c543dbb3` | 첫 native pre-push는 나중 loop의 `CHARGE_DEPARTURE_UNVERIFIED`로 1 failed/11109 passed/532 skipped. 같은 SHA의 후속 정상 tier는 11110 passed/532 skipped/30 subtests. 완전한 동일 invocation에서 선택·실행된 항목이며 별도의 CI도 이 parameter의 PASSED를 명시한다. |
| `test_station_camera_pipeline.py::test_station_camera_http_pipeline_aligns_then_requires_contact_and_measured_stop[composed]` | commit `c5845a0bbbc94b332b77f220f0c783a809ef2f1c` | 원래 정상 tier의 세 번째 반환에서 HOLD. 같은 SHA의 정확한 한 항목 원격 실행은 1 passed/0 skipped/59.79초/NEW0. 이전 9개 departure 시험은 이 근거에 사용하지 않는다. |
| `test_station_camera_pipeline.py::test_station_camera_http_pipeline_aligns_then_requires_contact_and_measured_stop[shutdown_CHARGING]` | commit `1368d3a61a33dbafafeb5731fafa03cea1d437a5` | 원래 정상 tier의 첫 반환에서 HOLD와 후속 `CHARGE_RETURN_NOT_ARRIVED`. 같은 SHA의 정확한 한 항목 원격 실행은 1 passed/0 skipped/49.20초/NEW0. composed·다른 head의 통과를 이 parameter 근거로 사용하지 않는다. |
| `test_station_redeployment_http.py::test_real_runtime_renews_and_releases_only_after_native_and_measured_departure[False]` | commit `e26407972bad7012779557178e8c0ad0c543dbb3` | 원래 CI 첫 tick에서 UNDOCKING 대신 HOLD/CHARGE_DEPARTURE_UNVERIFIED: 1 failed/7155 passed/64 skipped. 원래 작업을 한 번 재실행한 attempt 2는 이 노드 PASSED를 명시하며 7156 passed/64 skipped, 후속 별도 invocation은 6 passed다. 원본 분류 NEW1, 재실행 분류 NEW0이며 자동 FLAKY 판정이었다고 하지 않는다. |

앞의 세 native 실패·통과 쌍은 AI 역할의 시험 호스트와 같은 venv 식별자로 연결됐다. 원래 실패 때의 전체 dependency freeze·부하가 남아 있지는 않으므로 동일 환경 전체를 입증하지 않는다. 단독 원격 보고서는 parameter 이름을 줄여 출력하지만, 보존된 원격 runner 명령·전체 SHA·선택 노드·exit0과 함께 대조했다. 서로 다른 parameter·SHA를 대신 사용하지 않았다. 네 번째 CI 쌍의 환경 경계는 아래에 별도로 기록한다.

| Artifact | SHA-256 |
|---|---|
| `web-combined-push-e264.out` | `3b1b30aea97e5b1bd5089880abf1f07b808fbf354c16e881ffef580654c0db93` |
| `web-e264-successful-prepush/run-2.txt` | `26d392e0f9e721a5fa8fa72ce0cf72e049a6d83a1c154712f4ef2262f0b993fb` |
| `c584-run2-failure-20261020-033438380/run-2-complete.txt` | `c79684d9f84fa526fce55264ab98ce4b2171ae5596d9c783418368a610b9e775` |
| `station-c584-composed-exact-once/run-1.txt` | `bcdeff110b6c7a68ca28e4115dcfad29451e6c89080325211ba88367994ccf01` |
| `1368-normal-push-evidence-20261020-040528603/run-2-complete.txt` | `f6253df2a785e7904f6239cd3d058e6358507305d73308b444b20ed7cd6a4f28` |
| `station-1368-shutdown-exact-once/run-1.txt` | `eaab2e4ad121738d984b9eefb2ac996ca926f405375b62390993018a35450a8a` |

## 원래 CI 재실행과 환경 경계

[CI39296167842 attempt 2](https://github.com/robotics-team-1213/rosy-platform/actions/runs/39296167842/attempts/2)의 CORE 작업118338416022는 원래 작업118209784911과 같은 실제 checkout commit `02619277176e814b3750a1274f0ace783f501801`, tree `f026841cf176bd0e8d72355b89499949f303e21b`를 사용했다. 이 tree는 위 e264 head의 tree와 같다. 두 작업의 container digest는 `sha256:103b6c417973394659af6804d4917cd489b91e5ed22eb7bef263025a3bed2410`이며 Python3.12.3/pytest7.4.4/pluggy1.4.0과 로그의 pip 설치 목록이 일치한다. 그러나 runner 머신·지역이 달랐고 xserver-common·xvfb는 2:21.1.12-1ubuntu1.8에서1.9로 바뀌었다. 전체 환경·부하의 동일성이나 원인 해결을 주장하지 않는다.

| Artifact | SHA-256 |
|---|---|
| `ci-e264-run39296167842-job118209784911-full.log` | `3220830444bb3eb677a31ef3ee95c3da6a2c53abc4f59998136ccd1a05f5a5e8` |
| `ci-e264-attempt2-39296167842-20261020-071808429/core-118338416022-original.log` | `55350fcbe5e19d4c660d5c42836e8aecc32047b506dbb577ccb39946320e95ac` |

## 제외 항목과 경계

- departure `[False]`는 기존 native 통과를 대신 사용하지 않고 위 원래 CI의 재실행과 연결한다. `[True]`의 나중 loop 실패와 구분한다.
- 별도 미게시 fixture branch commit `3c18d33ae3f184b5a210219fdbce5cff5fcf4ff1`의 camera `[lifespan]` 일반 작업 완료 실패는 등록하지 않는다. 그 branch는 fixture 순서를 직접 바꿨고, 당시 실제 task/dispatcher 상태가 없어 도입 회귀를 배제할 수 없다. 제품 Web commit `a0278443f7fe4e0be8475e573306fbc63e76282d`에는 그 lock·후속 실험이 들어 있지 않다.
- fixture의 기본 AccountClient 설정은 null이며 수동 시험 Bearer를 사용한다. 변경된 Account HTTP 전송 경로는 해당 station 요청에서 실행되지 않는다. 새로운 suite 부하의 영향까지 배제하는 근거는 아니다.
- `[True]` departure는 나중 loop 실패, `[False]`는 첫 tick 실패다. c584 composed의 카메라 HOLD는 원래 예외를 남기지 않았다.1368 shutdown은 반환 adapter의 후속 `CHARGE_RETURN_NOT_ARRIVED`까지 확인됐지만, 그 원인이 된 실제 Trip 상태·원인은 남아 있지 않다. 별도의 navigation expiry 실험이나 나중 head 통과로 이 원인을 해결했다고 하지 않는다.

소유: Account rollout / CORE station integration. 2026-10-27까지 재검토한다. 각 항목은 담당자가 원래 실패 원인을 진단·수정하고 동일 항목이 재시험 없이 연속 10회 full tier를 통과하면 제거한다. 실제 기능 회귀가 확인되면 분류로 감추지 않고 먼저 수정한다.

## 검토와 새 head 검증

독립 검토는 같은 SHA의 원본 증거와 생산 호출 경계를 각각 대조했다. 이 파일과 분류 변경의 구체적인 독립 Safety-Review·새 commit 원격 정책 검사·정상 push·최종 CI 결과는 해당 PR에서 확인한다. 이 기록 작성만으로 게시·검증 완료나 앱 활성화를 선언하지 않는다.
