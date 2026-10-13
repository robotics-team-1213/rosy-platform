# S2 Perception 판단·adapter 기능 배치

기준 main: 535edb5da. 브랜치: refactor/perception-judgment-s2. 계약: D-738, D-747.

**현재 상태 (2026-10-13):** SOURCE·독립 source/Safety/구조 검토 완료, 통합 후보 2b391c534. 등록 시험 PC 3곳 SSH 불가로 600초 대기 후 원격 재검증이 실행되지 않아 local main 착지 HOLD. 첫 후보의 NEW 3은 branch에서 수정했으며 최종 PASS로 집계하지 않는다. 상세 증거와 재개 순서는 [검증 기록](../validation/perception-judgment-s2-2026-10-13/result.md)에 둔다.

**후속 지시:** 사용자가 주소/VPN 설정 변경을 확인하고 local merge까지만 요청했다. 원격 NOT RUN 기록을 유지하고 lint와 ff-only 착지만 수행하며 push하지 않는다. 이 지시는 첫 HOLD 뒤의 착지 범위를 변경한다. 실제 착지는 Git와 X 세션 landing readback으로 확인한다.

1. 실제 출력별로 14개 파일을 byte content 그대로 옮긴다. 전용 adapter를 같은 holder에 둔다.
2. 기존 source path 합성을 재사용해 control.* imports/entrypoints/monkeypatch identity를 유지한다. sdist와 wheel, source audit, 실행 소비자, active ceiling/backlog 경로와 현재 안내를 갱신한다.
3. standalone sdist/wheel에서 각 모듈이 정확히 한 번 설치되고 내용이 source와 같으며 독립 import와 provider identity 및 map STL bytes가 유지되는지 확인한다.
4. 독립 Safety 검토, 원격 perception·CORE 회귀와 구조·closure·native 계약 시험, known_failures NEW 0, lint 이후 main을 ff-only로 착지한다. main 변경이 있으면 합쳐서 영향 검증을 반복한다.
5. 커밋 SHA·종료 코드·terminal summary·착지를 기록한다. push/CI/ARM64 image/Jazzy transport/장치/현장 증거는 별도다.

보정 motion/transport/storage, recording/pilot process·eviction, executor/TF/web IO는 S3 잔여 조립. 이미 이동한 Drive는 다시 이동하지 않는다. 새 namespace wrapper나 dependency를 만들지 않는다. 되돌림은 경로와 mapping/소비자를 함께 돌리는 새 커밋이다.
