# OMX 실제 관측 기록·원본 수신·웹 확인

2026-10-16 · [D-770](../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)

## 검증 범위

기존 두 카메라 producer를 구독하고 torque-off 실제 모터 관측을 함께 기록했다.
이 데이터는 관측 준비 검증용이다. 동작 명령은 0개이며 실제 자동 시연은 0회다.
`imitation_eligible=false`, `physical_task_success=null`을 유지한다.
정지 관측을 행동 라벨로 변환하거나 성공 시연으로 학습하지 않았다.

## 원본 기록과 모델 PC 수신

현장 session은 `~/rosy-test/omx-il-observation-sync-20261016T000134Z/`다.
모델 PC 원본은 `~/rosy-test/omx-il-data/observations/` 아래 동일 session 이름으로,
수신 receipt는 `~/rosy-test/omx-il-data/receipts/` 아래 동일 이름의 JSON으로 보존했다.
이 경로는 각 해당 호스트의 홈 기준이다. 영상과 장치 식별자는 private 원본에만 있다.

| 항목 | 실측 결과 |
|---|---|
| 종료된 MCAP 길이 | 14.432312137초 |
| `/top_camera/image_raw` | Image 145개, 640×480 bgr8 |
| `/front_camera/image_raw` | Image 145개, 640×480 bgr8 |
| `/omx_commissioning/joint_states` | 실제 6관절 JointState 145개 |
| 총 메시지 | 435개 |
| 카메라-직전 관절 시차 top | median 4.261ms / p95 6.693ms / max 7.383ms |
| 카메라-직전 관절 시차 front | median 4.887ms / p95 6.812ms / max 7.369ms |
| 원본 검증 | 8파일, 260,605,655 bytes, 크기·SHA256 일치 |
| 모델 PC 실제 재생 | Jazzy rosbag2_py MCAP reader로 435개 전부 읽음 |

위 시차는 호스트 source stamp를 기준으로 한 대응이다. 센서 노출 동기화나 명령-관측
지연 검증을 뜻하지 않는다. 전 구간 stamp 증가, 이미지 layout, 관절 수·유한값을 검사했다.
실제 observer snapshot 249개에서 torque/error는 모두 0이었고 전후 설정은 같았다.
기본 `/joint_states`의 synthetic publisher를 실제 피드백으로 사용하지 않았다.

모델 PC는 전송 전후의 파일 집합·크기·해시를 확인하고, 실제 reader 실행 후 다시 대조했다.
manifest 자체의 SHA256은 다음과 같다.

```
15bec14b3ef70b0502e27c9c3d43c317b630a153e8c8d8c9d647ba27c8de3008
```

MCAP 원본 SHA256은 다음과 같다.

```
e7ccb97b4cdd72184427ef8ca8be9543b7b4dee907c71071e2c8df8f9112bb56
```

처음 SIGINT timeout으로 종료한 두 기록은 최종 metadata가 없어 미완료로 보존했다.
설치된 ros2bag recorder의 SIGTERM 종료 경로를 확인한 뒤 TERM과 종료 대기를 사용했고,
최종 기록은 정상 metadata 생성과 실제 재독출로 확인했다. 미완료 시도를 완료 기록으로
덮어쓰거나 포함하지 않았다.

## 웹 관측

`deploy/robot/omx/commissioning_view.py`는 Fleet PC의 기존 ROS stream만 구독한다.
loopback HTTP와 인증 SSH forward를 사용하며 공유 Fleet API를 추가하지 않는다.
직렬장치 접근, 카메라 재개방, 명령 publish, profile 활성화는 없다.
관절 값은 별도로 실행한 읽기 전용 commissioning observer에서 오며 nominal radians다.

실물에서 확인한 항목:

- HTTP에서 두 640×480 JPEG의 advancing sequence와 약 0.02~0.08초 age를 확인했다.
- 실제 읽기 전용 observer를 15초 실행하고 6관절 표시를 확인했다. observer 중단 후
  2초가 지난 상태에서 `fresh=false`, `values=null`을 확인했다.
- 실제 Chromium에서 두 영상 decode·sequence 증가·page error 0을 확인했다.
  390px 모바일 viewport의 가로 overflow도 없었다.
- 밝은 영상에서 딸기·흰 그릇·바닥 가까이의 gripper 배치를 직접 확인했다.
  픽셀 위치를 물리 workspace 좌표나 허용 관절 범위로 바꾸지 않았다.

현장 viewer 실행 증거는 `~/rosy-test/omx-view-9cedbe0d9/`, 원격 실제 browser 증거는
AI PC의 `~/rosy-test/omx-live-web-check/`에 보존했다. 두 경로의 원본 영상은 비공개다.
수정본 `8bf84b67a`는 현장 `~/rosy-test/omx-view-8bf84b67a/`에 hash 대조 후 배치했다.
viewer는 영구 device service가 아닌 최대 1시간의 임시 user service로 실행했다.
사용법은 [adapter README](../../middleware/devices/omx/adapter/README.md)에 있다.

독립 검토에서 미래 stamp가 후속 정상 관측을 막는 문제와 영상 다운로드가 멈춰도
metadata 갱신만으로 이전 영상을 계속 보이는 문제를 발견했다. 두 경우를 RED로 재현하고
미래 stamp 저장 전 거절, decode 성공 후 교체, 표시 영상의 독립 만료로 수정했다.
`8bf84b67a`는 관절 표시도 별도 만료하도록 확장했다. state 요청 정체 후 오래된 관절 표시를 제거하는 browser 회귀도 RED로 재현했다.
최종 관련 검사 **17개 통과**, 독립 재검토에 남은 material finding은 없다.
초기 browser test의 CSP eval 오류도 locator assertion으로 고쳤다.

## 남은 작업

실물 보정·좁은 구동 범위·독립 정지와 hardware owner 수용, 실제 전달 명령 기록,
자동 교사 시연과 outcome 검토, 시연 데이터 train/eval/test 분할·실데이터 학습이 남았다.
카메라 관측과 원본 수신의 성공을 이 항목의 완료로 사용하지 않는다.

최종 회귀 `0583d7dd9`: adapter 전체·harness 계약·문서 배치 원격 검사
**621 passed / 5 skipped**, known_failures NEW 0. opt-in Chromium 관련 17개는 별도로 전부 통과했다.
수정본 현장 재배치 뒤 실제 Chromium에서도 두 영상 decode·sequence 증가·page error 0과
390px 가로 overflow 없음을 다시 확인했다. harness lint는 0 errors / 기존 경고 30개다.
