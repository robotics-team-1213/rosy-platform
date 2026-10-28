# OMX native 실행 변경의 통합·크기 검증 계획

> Historical plan recovered on 2026-10-19. Preserve its original decisions and sequence as context; current repository instructions and independently reviewed recovery commits govern execution. This plan is not approval to deploy or activate hardware.

기존 `feat/omx-native-auto-deploy`의 원격 시험·실제 실행 이력을 보존한다.
해당 브랜치의 중간 커밋 다섯 개가 D-766의 package/file 상한을 초과해
`tools/land.py --tests auto`가 원격 통합 시험 전에 거절했다. 뒤에서 크기만
줄이는 커밋을 추가해도 과거 각 커밋의 위반은 해소되지 않는다.

기존 브랜치를 재작성하지 않고 gateway로 만든 `fix/omx-native-ready`에 최신
main 대비 최종 변경을 옮긴다. 원본 source `7e62492aa`와 기존 validation 기록은
원래 실행의 증거로 유지하며 새 통합 커밋의 검증과 구분한다.

`omx_adapter/contracts`는 command 설정·관절 상태·trajectory DTO와 기존
manipulation/camera/gripper/target evidence의 ROS-free 타입·검증을 맡는다.
단일 owner의 상태·clock·guard·취소 정책은 기존 command_owner에 남긴다.
기존 import 경로는 같은 canonical 객체를 재노출한다. validation·오류·provider
호출 순서를 바꾸지 않으며 runtime·명령 권한이나 센서 의미를 옮기지 않는다.

| 결정 | 적용 |
|---|---|
| D-427 | 같은 OMX adapter 내부의 타입 경계다. 새 최상위 holder나 배포 주체가 없다. |
| D-429 | Fleet admission·OMX 명령 owner와 상태 소유권을 유지한다. |
| D-430 | 옮긴 validation의 safety coverage와 독립 review를 유지한다. |
| D-766 | 자연스러운 1,000행 이상 unit과 600행 미만 owner 파일로 나누며 상한·ratchet 예외를 추가하지 않는다. |

완료 조건은 새 커밋의 크기·safety 검사, 기존 adapter 및 import 동일성 회귀,
전체 affected 원격 검증과 gateway 병합이다. 시뮬레이션 결과·실물 episode·학습
수용은 각각의 실제 실행 증거로 판단한다. 실패/skip을 통과로 합치지 않는다.
