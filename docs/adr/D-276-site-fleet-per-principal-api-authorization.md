## D-276 사이트 Fleet API는 개인별 credential과 역할로 요청을 인가한다

**Status:** Accepted (2026-09-26). 사이트 API의 소스 계약이다. Ubuntu 설치·사용자 토큰 전달·실제 CORE 명령·DEVICE/FIELD 수용을 뜻하지 않는다.

잇는 결정: D-59, D-267, D-268, D-269, D-275.

**Context:** 현재 Fleet API는 하나의 console Bearer를 모든 사용자에게 적용하고 task actor를 `site-console`로 기록했다. 이 구성은 읽기와 이동 요청을 분리하지 못하고 누가 요청했는지 복원할 수 없다. D-267 실행 계획은 개인 principal과 `viewer`, `operator`, `policy-admin`을 요구한다. 브라우저는 bearer header를 사용하며 쿠키 기반 세션은 없다.

**Decision:**

1. 각 사람은 서로 다른 고엔트로피 bearer credential을 사용한다. 서버 설정 `site-users.yaml`에는 고유한 `principal_id`, 역할, credential의 소문자 SHA-256 digest만 둔다. 원문 credential은 승인된 secret manager를 통해 별도로 전달한다. digest는 API 요청마다 비교하고 상수 시간 digest 비교를 사용한다. 형식 오류, 중복 principal/digest, 알 수 없는 역할, 미등록·폐기 credential은 시작 또는 요청 단계에서 거절한다. 사용자 credential은 CORE REST, CORE Agent pairing, Hub registry 및 vision source 자격 증명과도 서로 달라야 한다.
2. 역할은 계층 상속이 아니라 명시적인 허용 목록이다.

   | 역할 | 허용 | 금지 |
   |---|---|---|
   | `viewer` | Fleet 상태·지도·증거·task/history 조회 | 이동·정지·취소·신호 명령 |
   | `operator` | 조회와 수동 작업 요청·정지·취소 | 정책 조건 변경 |
   | `policy-admin` | 조회와 향후 정책 조건 등록·수정·활성화·비활성화 | 로봇 작업·명령 |

   현재 policy mutation endpoint는 없다. 이 역할 정의가 해당 endpoint를 추가하거나 D-268 자동 실행을 승인하지 않는다. 기존 CORE 안전 게이트는 모든 수동 요청에도 적용된다.
3. 인증은 브라우저/API Bearer header로만 한다. 토큰을 URL, query, 로그, 본문에 넣지 않는다. 배포 사이트에는 TLS가 필수다. 사용자의 digest 제거/교체는 해당 사용자를 폐기/회전하며, 현재 프로세스 메모리에도 반영되도록 Fleet을 재시작한다. 별도 로그인·토큰 발급·SSO 서비스는 만들지 않는다.
4. 사용자 자격으로 인증된 `/api/fleet/*` 변경 요청은 task SQLite의 append-only API audit에 principal, role, method, 경로, 결과 코드를 기록한다. 원시 bearer와 요청 본문은 감사 기록에 저장하지 않는다. 명령 처리 전 감사 시작 레코드를 쓸 수 없으면 요청을 `503 AUDIT_STORAGE_UNAVAILABLE`로 거절해 CORE 호출을 하지 않는다. sighting 제출은 사용자 API가 아니라 source credential로 인증되는 별도 service 경로다.
5. `/registry`의 CORE registry 조회 credential은 사용자 웹 API credential과 별도다. legacy `--token` 경로는 loopback 호환/Hub registry 용도로만 남긴다. 이를 쓰는 배포는 개인별 role authorization을 수용한 것으로 간주하지 않는다. 사이트 Compose는 `--users-file`을 명시해 웹 API에서 개인별 권한 검사를 켠다.

**Consequences:** operator navigation task와 append-only status history에는 실제 `principal_id`가 저장된다. 비-task API mutation도 같은 SQLite 파일에 actor와 응답 상태를 남긴다. `policy-admin` API, 사용자 관리 UI, 즉시 token reload, CSRF cookie session은 구현 범위에 없다. 사이트 구성 파일과 재시작을 통한 사용자 폐기는 운영 절차다.

**Validation / Transition:** `test_site_users.py`, Fleet HTTP/task/CLI 시험, `test_site_task_queue_deploy.py`, `test_site_candidate.py` 및 Docker Compose LOCAL 설정 검증을 실행한다. 결과는 SOURCE/LOCAL다. Ubuntu host, 실제 사용자 전달·회수, 실물 CORE readback과 FIELD 명령 결과는 별도 게이트다. D-268 자동 task는 계속 `HOLD`다.

**References:** [D-267](D-267-ubuntu-site-fleet-and-vision-workflow.md), [D-268](D-268-policy-eligible-vision-evidence-for-fleet-tasks.md), [D-269](D-269-device-server-contracts-and-ros-boundary.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md), [Fleet implementation plan](../plans/2026-09-26-ubuntu-site-fleet-vision-workflow.md).
