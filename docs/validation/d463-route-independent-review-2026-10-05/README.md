# D-463 경로 요청의 독립 소스 검토

검토자: Codex `/root` (경로 구현 작성자가 아님). 상태: SOURCE/LOCAL 검토이며 실기 경로 주행 수용은 아니다.

검토 대상 git commit revision: `f8165b2a44d01ff628d5bd75ec923953bd09d000`.
이 커밋의 Safety-Review trailer 누락을 발견했다. 공유 main의 기존 커밋을 다시 쓰지 않고,
D-430의 검토된 역사 커밋 목록에 정확한 대상과 이 증거를 기록한다.

- 요청은 기존 `/goal`과 같은 operator guard와 principal을 사용한다. named 자격이 설정된 사이트에서는 해당 principal을 검증하며, 기존 console_token/no-auth 호환 정책도 유지한다. 새 named-owner 강제를 추가했다고 주장하지 않는다. durable task에서는 기존 Idempotency-Key가 필요하다. 추가 필드는 거절한다.
- 그래프 조회·연속성 검사와 다음 점 계산은 `fleet/lane_route.py`에 있다. 이 모듈은 CORE나 actuator를 호출하지 않는다.
- `FleetConsole.trusted_map_pose`는 기존 gather·trust 테이블 소유자 안에서 최신 LOCALIZED map pose와 finite 좌표를 확인한다. legacy/odom/untrusted pose는 경로 명령으로 전달하지 않는다.
- 경로에서 0.08 m 밖인 pose는 거절하고, 정상 pose는 polyline의 약 0.20 m 앞 점만 기존 goal 소유자에게 전달한다. 완료 위치에서는 새 goal을 보내지 않는다.
- command 발행, 제어 admission, 정지 및 localization hold의 소유자는 바뀌지 않는다. 승인된 API 호출이 실제 경로 정확도나 물리 안전 수용을 증명하지 않는다.

실행 증거: D-456과 D-463 통합 검사에서 42 PASS와 API 문서 header pin 1 FAIL을 확인했다.
통합 문서는 v1.101이며 envelope 1.0은 유지한다. 새 경로 시험의 header pin만 수정한 뒤
`operations/fleet/test/test_lane_route.py` 전체 11 PASS를 확인했다. 기존 권한·pose·경로·goal 단언은 유지했다.
원본 로그는 작업 환경의 `X:/DevTemp/rosy-ui-ship/peer-main-integrated-tests.log`와
`peer-main-route-version-fixed.log`에 보존한다.

D-362 크기 재판단: Fleet의 생산 코드 총계는 33,866줄, console은 1,159줄이다.
별도 `/root/ship_fleet_cam_merge`의 독립 SPEC/Quality/Safety 검토도 같은 측정과
상속된 세 runtime 파일의 해시 불변을 확인했다. D-463의 증가는 206줄이며
계산 모듈 113줄·accessor 20줄·dispatch 73줄이다. 기존 측정 기준 이후의 나머지 3줄도 보존한다.
계산 책임은 새 `lane_route.py`로 분리되어 있고 console에는 자신의 gather/trust 상태를
읽는 accessor만 추가됐다. package의 `split` 대기열, console의 단일 gather/scatter
소유자 판정, 파일의 성장 허용량 0과 package의 +150 규칙은 유지한다.
이 기록은 임계값 완화나 이후 임의 성장의 승인이 아니다.

CI·서명 배포·장치 주행은 이 검토에서 수행하지 않았다.
