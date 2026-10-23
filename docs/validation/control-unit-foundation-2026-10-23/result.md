# 관제 구성·영속 위임 기반 검증

## 범위와 상태

commit `56762a179e`의 Fleet 구성·저장 모듈을 검증했다. 독립·상하위·3수준 중첩의 정적 검증, 불변 위임 식별·동시 중복 접수, 로컬 승인 신원, owner/revision 결과 결속, 취소 요청 기록과 기존 TaskStore admission transaction의 결속이 범위다.

아직 HTTP 위임·백그라운드 왕복·하위 승인 화면·단절/재연결 종단·배치 연결은 구현하지 않았다. 이 기반 시험을 파이프라인 완성, production dispatch, 장치·현장 수용으로 해석하지 않는다. D-851은 Proposed로 유지한다.

## 실제 원격 검증

공식 `tools/remote/remote_pytest.py`로 커밋된 revision을 모델/AI 시험 PC에서 실행했다. 노트북 pytest는 실행하지 않았다.

| 실행 | 확인한 결과 |
|---|---|
| 구성 RED: commit `3c6fb6a9ff` | 모듈 미구현으로 해당 시험 실패 확인 |
| 구성 GREEN: commit `004612b444` | 구성·holder import 시험 종료 0 |
| 저장 RED: commit `913c88e530` | 저장 모듈 미구현으로 해당 시험 실패 확인 |
| 저장 GREEN: commit `65cb3f6ec8` | 구성·저장·holder import 시험 종료 0 |
| 결속 RED: commit `bb451a64ae` | task_admission 미구현 2건 실패 확인 |
| 결속 GREEN: commit `5eea233ff7` | 승인·동일 작업 재시도·재시작·교체 거절·원자 rollback 포함 종료 0 |
| null 승인 RED: commit `eaac3accc8` | 승인 없는 None 신원이 통과하는 회귀 1건 실패 확인 |
| 최종 집중 GREEN: commit `56762a179e` | 세 파일 30 cases 통과, runner 종료 0, known failures 0 new / 0 known / 0 flaky |

최종 호출은 `operations/fleet/test/test_control_unit_config.py operations/fleet/test/test_control_unit_store.py operations/fleet/test/test_server_holder_imports.py -q`다. 원본은 실행 요청 호스트의 외부 scratch `rosy-control-config-{red,green}`, `rosy-control-store-{red,green}`, `rosy-control-binding-{red,green}`, `rosy-control-null-approval-{red,green}` 아래 `run-1.txt`다. RED 결과를 성공으로 합산하거나 baseline에 추가하지 않았다. 브라우저·장치 시험은 포함하지 않는다.

## 독립 검토와 연결 조건

독립 검토가 approval 기록은 실행 claim이 아니며 작업 결속을 별도 transaction으로 하면 안 된다는 조건을 확인했다. 기존 `FleetTaskStore.create_task`의 admission callback을 사용해 위임 binding·history와 task 생성을 같은 DB transaction에 둔다. 동일 요청은 기존 task의 idempotency와 dispatch claim을 그대로 사용해야 한다. 후속 서비스는 같은 SQLite 파일을 사용하고 named operator 인증 후에만 승인 callback을 전달해야 한다.

검토가 찾은 nullable actor의 승인 우회는 실제 RED를 재현하고 비어 있지 않은 신원 검사와 회귀로 수정했다. 최종 검토·전체 영향 범위·병합 결과는 착지 기록과 후속 단계에 결속한다.

CE: 해당 없음 — 내부 구현의 승인·원자성 판단은 코드와 회귀 시험에 남는다. 별도로 관측한 작업 공간 제거의 원인은 미확인이며 작업 공간 기록에 증상·가설·복원 근거를 구분해 보존했다.
