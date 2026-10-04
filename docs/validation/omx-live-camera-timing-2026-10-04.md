# OMX 실제 SIM 카메라 타이밍 측정

2026-10-04. source commit 87bc78ebf8b92dc0d439982d3612b0ed9942d163.
기존 ACT 입력 예산을 실제 Gazebo→ROS capture에서 검사한 SIM 관측 증거이다.
정책 dispatch, owner HOLD/cancel 실행, 독립 과제 성공 또는 장치 수용을 검사한 결과는 아니다.

## 실행 구성

기존 image sha256:faeb86d666c6848ec61478a72087f7cadfc55d6b23e54dff891202b21029efb2.
별도 container rosy-learning-camera-timing-20261004-v2, network none, cap-drop ALL,
no-new-privileges, CPU4/memory4GiB, source bind read-only와 X: evidence bind만 사용했다.
ROS domain77/LOCALHOST, 고유 GZ_PARTITION. hardware device/port mount 없음.
기존 Pilot 서버나 정책 action client를 시작하지 않고 Gazebo와 camera bridge만 실행했다.
Gazebo launcher의 controller/joint broadcaster는 실행됐으며 probe는 수신만 수행했다.

기존 ACT step1 policy revision:
4f5f3d148681483a05971a180ffb4d5d501b21adf7f2b5c6e479c88f74c5ff23.
원 policy-artifact.json bytes와 측정 입력 복사본이 일치했다. world SHA:
3cf7a3df5e7ddc609ee6536cac62af3ae992bdd047f294f4cb59be1829b85bc3.
camera calibration SHA d1b538c8a736b665e05433276033d8722519e8ff1533310f8d6ede6ae8ce00bc.

실제 RosCameraStreamRuntime으로 Image/CameraInfo의 exact capture stamp와 고정 camera
identity/optical frame/calibration을 검사했다. 각 수신 frame은 raw RGB bytes SHA,
rgb8/320×240/packed step960/230400bytes를 확인했다. 관측 예산50ms를 그대로 사용했다.
capture stamp는 Gazebo 시간이며 freshness 계산은 동일 프로세스의 monotonic receive time이다.
두 시간축을 서로 빼거나 host Windows clock으로 치환하지 않았다.

## 측정 결과

- 첫 accepted frame부터 약15초, frame130개, 약20ms watchdog sample658개.
- camera age50ms 초과370회(56.23%), 최대363.676706ms.
- receive interval 최소58.136887 / 중앙109.223230 / 최대375.930414ms.
- capture stamp 간격98 또는100ms. world camera update_rate10Hz와 일치하는 규모이다.
- joint state age50ms 초과 또는 아직 미수신7회. 처음3초를 제외한 보조 분석은
  sample526개, camera stale291회, joint stale0회였다. 이 제외 분석은 최초 수용 기준을 변경한 것이 아니다.
- 실제 owner/session poll이나 policy inference를 실행하지 않았다. 현 타이밍에서 camera stale
  rejection 조건이 존재한다는 증거이며 실제 HOLD/정지/rollback 완료의 증거가 아니다.

v1은 PYTHONPATH를 덮어써 rclpy import 실패로 exit1, ROS 경로를 보존한 v2는 exit0으로
종료됐다. 두 실행을 별도 container/evidence로 보존했으며 기존 실행을 재시작하지 않았다.

원 측정/스크립트/launch logs/container config/inventory:
X:/DevTemp/rosy-learning-audit-20261004/camera-timing-probe-v2/.
result.json SHA256 e8d133a7ffc0eb42b61902ab1fde97aa2e9d6cdb7c93e0ef06fe65855b3cca5c.

독립 reviewer /root/policy_registry_review가 v2 결과를 재계산했고 age/freshness flag
불일치0개, world/policy bytes와 container isolation/terminal exit0을 확인했다.
v2는 raw RGB/CameraInfo 본문을 저장하지 않아 본문 SHA/calibration/stamp를 독립적으로
재생성할 수 없다. 이 검사는 실제 probe의 assertion과 receiver gate에 근거한다.

## 별도 30Hz capture 실험 v3

측정 전에 experiment.json으로30Hz/50ms/15초/20ms polling/CPU4/memory4를 고정했다.
새 world SHA d293a62cb737af02b13f210be663ad91322668f05fb0850ebaade33f88cd1f95이며
원 world와 차이는 update_rate10→30뿐이다. source_policy_world_compatible=false로 기록했다.
기존 policy artifact를 수정/승격하지 않고 capture-only 새 identity를 사용했다.

v3: frame302, sample557, age50ms초과48, joint stale44.
수신간격 중앙44.445593ms/최대216.220872ms. 처음3초 제외 sample437,
camera stale37/joint stale29. 사전 선언 zero-stale 목표는 실패했다.
전체302개의 raw RGB와 CameraInfo/imageheader를 X:에 저장했고 독립 reviewer가
모든 raw SHA/calibration fingerprint/exact capture stamp/frame binding을 재생성해 확인했다.
Docker isolation/terminal exit0도 확인했다.

계측 불일치2개: age는 raw 저장 전, gate freshness는 저장 후 확인했으므로
age기반 stale48/flag기반 stale50이다. 이 사실을 보존하며 같은시점 계측으로 별도 재측정한다.
원자료 저장 I/O가 추가됐으므로10Hz 대비 성능 차이를 camera rate만의 효과로 단정하지 않는다.
v3 result SHA256 57b0954753448bd48c9012840b5ac96e391caee606de43e9c35cd437303f314b.
경로 X:/DevTemp/rosy-learning-audit-20261004/camera-timing-probe-v3-30hz/.

## 같은 시점으로 계측한 최종 v4

v3를 덮어쓰지 않고 raw 저장 후의 now로 age와 gate freshness를 함께 계산했다.
world/profile/50ms 예산은 동일한30Hz 연구 조건이며 새 운영 binding을 만들지 않았다.
v4는 terminal exit0, frame252개/sample527개 중 camera stale92개, joint stale66개.
age/freshness flag 불일치0개. 원자료252개 전부 raw SHA/calibration/exact stamp/binding을
로컬 재검증했다. 처음3초 제외 sample423, camera stale60/joint stale36.
수신간격 최소35.620875/중앙51.249935/최대268.434915ms.
capture stamp 간격31/33/34ms. polling sample 간격 중앙23.879677ms/최대278.932434ms이다.

v4 result SHA256 d43174925133eacd128c4f7ff8beda3f1f54ad47dca48216143565fc4cf29bd0.
원자료 경로 X:/DevTemp/rosy-learning-audit-20261004/camera-timing-probe-v4-30hz/.
기록 I/O와 soft-rendering 및 실행 부하가 함께 있는 이 조건에서는30Hz 설정만으로
zero-stale 목표를 충족하지 못했다. 일부 긴 poll 간격 때문에 실제 지속적인 watchdog 검사보다
stale 상태가 적게 표집될 수 있으며, 이 probe를 실제 owner scheduler로 해석하지 않는다.
v2와 원자료 저장 여부/계측 조건이 다르므로 프레임 주파수만의 인과 효과를 주장하지 않는다.
추론 비용이나 실제 trajectory transport가 포함되지 않은 측정이며 장치 성능으로 일반화하지 않는다.

독립 reviewer /root/policy_registry_review가 v4 원자료252개와 모든 타이밍 집계,
age/flag 불일치0, Docker isolation/terminal exit0/restart0을 확인했다.
zero-stale 목표 실패 및 owner/authority/dispatch/task 수용 미검증 범위에 동의했다.

## 다음 조치와 범위

10Hz의 주기100ms는50ms 관측 예산보다 길다. 현재 입력 조건을 만족하는 연속 watchdog
운영을 주장할 수 없다. 예산을 늘리거나 기존 정책의 camera identity/world pin을 덮어쓰지 않는다.
더 빠른 camera capture 설정을 별도 world/profile revision으로 사전 고정해 다시 측정하고,
실제 계산/ROS 지연까지 포함한 observation/action 예산을 검증해야 한다. 새로운 world/profile은
기존 정책 설치 호환성이나 승격을 자동 충족하지 않는다.
원래 정책들은 품질 거절 상태이며 trusted issuer/lease, owner process composition,
독립 SIM 과제·stop readback, Fleet receipt, shadow/rollback, DEVICE/FIELD는 미완료이다.
