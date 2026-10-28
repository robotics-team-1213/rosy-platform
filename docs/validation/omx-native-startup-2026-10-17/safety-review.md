# OMX native startup: 독립 Safety-Review 범위

2026-10-17, reviewer `/root/review_native_cycle`.

`middleware/devices/omx/adapter/omx_adapter/action_api.py`의 UnixActionServer
listener 수명 조회 변경 8줄을 독립 검토했고 APPROVE했다.
검토 기준은 이 작업 브랜치의 `cd45dd7179`까지 원본과 그 위 해당 파일 diff다.

- `_serving`은 bind·chmod·listen 성공 뒤에만 설정되고 teardown에서 지운다.
- `is_serving`은 기존 stop Event가 설정되면 accept thread 종료를 기다리지 않고 false다.
- peer 인증, socket 권한, dispatch admission, cancellation, replay 규칙을 바꾸지 않는다.
- listener 수명 조회이며 실제 응답성·물리 정지 증거가 아니다.

전체 startup 구현은 별도 검토 범위다. 같은 리뷰에서 기록/fsync가 startup cancel과
기존 Fleet cancel fanout을 지연시킬 수 있다는 P2를 지적했다. 변경은 두 취소 시도를
동기 진단 기록보다 먼저 수행하고, 기록 callback을 실제로 막아도 두 취소가 이미
관측되어야 한다는 회귀 테스트로 검증한다. 해당 테스트는 수정 전 원격에서 실패했다.

이 문서는 native 격리 실행·Gazebo task 성공·장치 수용을 승인하지 않는다.
