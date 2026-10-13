# D-745 학습 관리 센터의 소유 실행기 수동 제어

**Status:** Accepted (2026-10-13, 사용자 요청: 수동 시작·중지·재시도 추가)

## 결정

- 기존 검수 서버의 선택 `--learning-control`은 호스트 운영자가 마련한 private binding만 읽는다. binding은 `rosy.learning.control/1`, workspace_id, service, config_path, out_path를 가진다. 서비스는 `rosy-review-pipeline[-<topic>].service`이며 timer는 같은 이름이다.
- 같은 사용자 systemd의 해당 서비스·타이머만 제어한다. 단일 ExecStart는 D-446의 고정 실행기 `exec training/review_pipeline.py`와 binding의 config/out을 사용해야 한다. unit/config binding 변조, drop-in, 다른 workspace는 거절한다. HTTP 입력으로 unit, 경로, argv, PID를 받지 않는다.
- 상태 version에는 실제 서비스 invocation을 포함한다. 다른 실행으로 바뀐 오래된 화면 요청은 거절하며 실행기 원장과 산출물을 초기화하지 않는다.
- 기존 GET `/api/learning`의 선택 control은 실제 systemd 상태·현재 invocation·가능한 동작을 읽는다. POST `/api/learning/control`의 본문은 action(start/stop/retry)과 version만 받는다. 기존 Host/Origin/작업대 token 검사를 유지하고 상태 충돌은 409다. loopback 결정 조회에는 쓰기와 제어를 추가하지 않는다.
- start는 자동 timer와 소유 서비스를 시작한다. stop은 timer를 끄고 소유 service의 control group만 중지한다. retry는 중지 상태의 소유 서비스를 한 번 실행한다. 상태는 다시 읽으며 명령 접수를 학습 완료로 표시하지 않는다.
- 완료·품질 거절·시도 한도 소진 상태는 재시도로 초기화하지 않는다. 승인·source pixels·fixed eval·TTL·철회·서명 환경과 GPU 잠금은 기존 owner가 다시 검증한다. UI 수동 제어는 학습 데이터 수용이나 모델 승격 권한이 아니다.
- 이 binding이 없는 검수 앱과 연결된 일반 보고서는 읽기 기능을 유지한다. UI는 기존 공용 버튼과 Ctrl+K 기능 검색을 사용하며 실제 실행 중에는 상태를 재조회한다.

## 관계와 시험

| 계약 | 관계 |
|---|---|
| D-427/D-429 | curation의 UI·제어 접점, training의 owner와 기존 bare imports 유지 |
| D-430 | CORE·ROS·cmd_vel·장치 명령과 별개 |
| D-446/D-561 | 고정 서명 실행기와 검수 릴리스·private state 분리 유지 |
| D-464/D-742 | 소유 실행 요청만 추가, 독립 데이터 admission과 현재 결정 조회는 유지 |

원격 시험은 binding/인증/상태 충돌/완료 및 거절 보호와 keyboard UI를 확인한다. 실제 운영은 승인 0장의 대기·시작·중지·재확인만 수행한다. 격리 synthetic GT와 별도 systemd unit에서 실제 GPU 학습 중지·재시도·중복 실행 차단을 확인한다. 실제 사람 정답 품질과 장치 수용은 별도다.
