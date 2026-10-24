# 군집 수명주기 의미 보존 추출 검증

`refactor/swarm-reference-stream`의 소비자 보호 구현 전 준비 변경이다. D-870의 시간 수용이나 새 신선도 동작을 구현한 증거는 아니다.

- CORE 기준 `b29f3ff855`: 기존 7개 suite 원격 137개 통과. 추출 `77826ac7e1`: 같은 suite와 경계 변이 검증 2개를 합쳐 139개 통과, skip0/NEW0.
- Fleet 기준 `77826ac7e1`: session/arming/relay/anchor 관련 원격 108개 통과. 추출 `4ed200d0ee`: 같은 범위와 motion capability 회귀를 합쳐 123개 통과, skip0/NEW0.
- 외부 로그 root: `%LOCALAPPDATA%/Temp/rosy-swarm-freshness/`. 하위 `extraction-baseline`, `extraction-green`, `fleet-extraction-baseline`, `fleet-extraction-green`의 `run-1.txt`를 보존했다. pytest는 노트북에서 실행하지 않았다.

SwarmManager의 네 메서드는 같은 패키지의 SwarmReferenceStream으로 원문을 보존해 옮겼다. manager는 691→561줄이고 기존 상수 export·잠금·세션 검사를 유지한다. 전송 경계 검사는 두 파일을 읽으며, socket/rclpy import를 읽기 경로에 주입한 뒤 실제 거절과 복원을 확인한다.

FormationSession의 네 메서드는 SessionArming으로 옮겼고 두 enum은 session_state로 옮겼다. 기존 session export와 logger를 유지한다. session은 628→520줄이다. 이동한 본문과 남은 메서드의 원문, 원본 위치에서의 제거를 확인했다. 두 oversized ratchet 행은 각 추출과 같은 커밋에서 제거했다.

기존 manager/새 reference stream과 Fleet session/arming/relay를 실제 안전 모듈·앵커로 등록했다. 독립 `/root/time_sync_review`는 각 추출의 MRO·import·정리 순서·export·분류 변경에 차단 사항이 없다고 검토했고 각 소스 커밋에 한정된 Safety-Review trailer가 있다. 검토자는 시험·장치를 실행하지 않았다.

이 브랜치는 군집 수명주기 준비라는 한 관심사로 묶고, 공유 계약 및 실제 동작 소비자와 분리한다. 공식 FULL 착지 검증은 아직 남아 있다. 배포·UTC50ms·실물 정지·radio·FIELD를 수용하지 않는다.

CE: 해당 없음 — 추출은 동작을 보존하며 판단은 원문 비교·회귀·D-870에 직접 남긴다.
