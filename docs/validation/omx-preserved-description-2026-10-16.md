# OMX 설정을 보존하는 초기화 후보

2026-10-16 · [D-770](../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)

기존 수집 파이프라인 준비 변경은 `585885428`로 로컬 main에 병합했다.
병합용 검증은 영향 범위 1509 passed / 14 skipped, 구조·문서 247 passed,
브라우저 3 passed, known_failures NEW 0이다. 원래 작업 브랜치의 개별 RED/GREEN
커밋은 `feat/fleet-il-readiness`에 보존했다. 원격 push는 하지 않았다.

## 확인한 두 번째 시작 경로

기존에 고정·빌드한 `dynamixel_hardware_interface` source를 읽어 확인했다.
`InitItem()`은 GPIO의 mode·limit·gain 등 파라미터를 실제 register에 쓴다.
`Torque Enable`을 생략한 dxl GPIO는 기본 torque 활성화 목록에 들어간다.
`on_activate()`의 `start()`는 readback을 command에 맞춘 후 `WriteMultiDxlData()`를
호출하고, 그 목록의 torque를 켠다. 따라서 단순한 no-goal 기동도 읽기 전용은 아니다.

Fleet PC에서 고정 source의 실제 OMX-F xacro를 실물·비 mock 모드로 확장했다.
확장은 파일 처리만 수행했고 driver나 controller는 시작하지 않았다.
원래 설정은 6개 motor 모두 implicit torque enable이며, 현장에 남아 있는 mode와
다른 mode/limit/PID/profile/current 초기화 항목을 포함한다.

## 구현한 범위

`deploy/robot/omx/preserved_description.py`는 확장된 XML을 새 후보 디렉터리에 쓴다.

- 정확히 하나의 지정된 vendor plugin과 순서가 맞는 6개 follower ID를 요구한다.
- GPIO의 ID/type/model/communication/unit metadata와 interfaces는 보존한다.
- 명시적인 register 초기화 항목을 제거하고 `Torque Enable=0`, `Reboot=0`을 설정한다.
- `disable_torque_at_init=false`로 설정한다. 이미 torque가 켜진 장치는 초기화에서
  임의로 torque-off하지 않고 기존 vendor의 거절 경로를 사용하도록 하는 후보다.
- 원본 변경·출력 덮어쓰기를 거절하고 source/output hash와 미검증 항목을 receipt에 쓴다.

이 도구는 **파일 생성기**다. 변경된 driver 실행을 검증하거나 driver를 읽기 전용으로
만들었다는 뜻이 아니다. activation의 command write와 write service 권한, ROS 호환성,
실측 제한·보정·독립 stop·owner binding은 receipt에도 미검증으로 남긴다.
`motion_admitted=false`, `runtime_started=false`를 유지한다.

## 실행 결과

누락 구현으로 원격 RED를 확인한 뒤 `f812a9d85` 원격 시험 8개가 통과했다.
독립 검토에서 남은 material finding은 없다.

Fleet PC의 실제 확장 description에 생성기를 실행해 register 초기화 파라미터
**59개를 제거한 후보**를 생성했다. 6개 motor의 torque/reboot flag, metadata/interface,
원본 불변과 source/output hash를 실제 파일로 대조했다.
원본과 후보·receipt는 해당 호스트의
`~/rosy-test/omx-initialization-description-20261016/`에 보존했다.
serial은 수용된 장치 경로를 요구하는 placeholder이며 실행용 설정으로 배치하지 않았다.

다음 단계는 후보에서 아직 남아 있는 driver 시작/쓰기 경로와 owner 권한을 검증하고,
실측 구동 범위·독립 stop을 반영해 비구동 기동부터 검증하는 것이다.
첫 실제 자동 시연·실데이터 학습은 여전히 미완료다.
