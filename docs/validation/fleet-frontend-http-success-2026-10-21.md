# Fleet 프런트 API 성공 경로 후속 검증 · 2026-10-21

[초기 검증 기록](fleet-frontend-development-2026-10-21.md)의 거절 응답만 확인된 여섯 경로를 보완한다. 공개 레포·운영 배포 구조·API·권한 계약은 변경하지 않았다.

## 실행과 결과

- 소스: `a4fe41374e`. 원격 시험 PC에서 커밋한 소스를 실행했다.
- 명령: `python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- ROSY_CAPTURE_FLEET_APP_CONTRACTS=1 operations/fleet/test/test_app_frontend_success_contracts.py -q`.
- 결과: 6개 시험 실행, 모두 통과, skip 0, runner exit 0. `test/known_failures.py` 비교는 NEW 0·known 0·flaky 0이다.
- 원본 로그: 요청 PC의 시스템 임시 폴더 아래 `rosy-fleet-api-success-v4/run-1.txt`. 로그의 `FLEET_APP_HTTP_EVIDENCE`는 실제 HTTP 응답·통과한 시험 이름·소스 SHA를 기록하며 자격 증명이나 요청 본문을 저장하지 않는다.
- 앞선 세 실행은 각각 5개 통과·시작점 시험 설정 실패 1개였다. 영속 인증 저장소와 관측 source의 앱 구성 조건을 확인한 뒤, 기존 검증된 tracking 앱 fixture를 재사용했다. 이 세 실행을 여섯 경로 전체 통과 증거로 쓰지 않는다.

| API | 확인한 성공 결과 |
|---|---|
| 정책 관측 창 `POST …/windows/{window_id}/close` | 200, 이름 있는 운영자의 종료 사유 저장, 이후 새 lease 발급 거절 |
| Trip `POST …/{trip_id}/confirm-replan` | 200, 실제 planner의 우회 경로 채택, replan hold 해제, 다음 tick에서 진행 |
| Cell `POST …/{mission_id}/reconcile` | 200, 제출 응답을 잃은 Action의 성공 readback 저장, 추가 submit 없음 |
| 등록 로봇 `DELETE …/enrollment/robots/{robot_id}` | 200, idle 로봇의 등록 삭제, 목록에서 제거, 감사 주체 보존 |
| Legacy 카메라 `POST …/pairing/v1/requests/{request_id}/reject` | 200, pending 요청을 rejected로 종료, 휴대폰 상태 조회와 감사 주체 확인 |
| 시작점 `DELETE …/start-points/{source_id}` | 200, 현재 revision으로 삭제 후 목록에서 제거, 오래된 revision은 409 |

여섯 시험 모두 viewer의 403 거절도 확인한다. [기계 판독 수신 기록](../../applications/fleet/test/backend_http_evidence.json)은 이 소스의 정확한 통과 시험에 연결했고, [기능표](../../applications/fleet/test/feature_matrix.json)의 해당 여섯 행도 성공 응답으로 갱신했다. 이전 거절 시험은 계약 시험 목록에 유지했다. 이 기록 작성 시 수신 기록의 159개 항목은 모두 2xx/3xx 관찰 응답을 가진다. 이는 각 경로에서 최소 한 설정의 성공 응답을 관찰했다는 뜻이다.

## 검증 경계

실제 운영 router·인증 guard·서비스·원장을 사용한다. Trip 사례는 전체 `create_app` 대신 실제 router와 guard 및 실제 planner/runner를 조립했다. 다른 다섯 사례는 기존 `create_app` fixture를 사용한다. 장치 transport는 fake이다.

Cell은 `ACTION_SUCCEEDED` readback까지만 확인했다. 목표 달성·실물 동작 완료를 주장하지 않는다. 카메라 v1 거절 성공은 실제 카메라 영상 검증이 아니다. 정책 창 닫기는 새 lease 발급 차단을 증명하며 이미 장치에 전달된 임대의 물리 정지 시간을 증명하지 않는다.

모든 설정 조합·오류 분기·실제 장치·운영 배포·모델 품질·현장 수용·공개 push/CI는 이 기록의 검증 범위에 없다. 이후 회귀 검사와 로컬 main 착지 결과는 별도 결과로 보고한다.
