# D-963 제어 PC의 USB 카메라 역할은 Fleet 설치 화면에서 승인한다

**Status:** Accepted (2026-11-02, 사용자 요청. 구현·시험은 증거가 있고, 실물 카메라 수용은 별도)

## Context

OMX 제어 PC에 새 USB 카메라를 꽂으면 역할(top, 팔 손목 등)은 셸 명령 `omx_cameras.py approve NODE ROLE`로만 줄 수 있었다. Rosy Cam(Android)은 같은 Fleet 설치 화면에서 승인한다. 사용자는 Rosy Cam·Rosy Vision이 Ubuntu/Android에서 수동 설정 없이 동작하길 원한다.

## Decision

1. 제어 PC의 USB 카메라 역할 승인은 Fleet 설치 화면의 Rosy Cam 승인 옆 패널에서 이름 있는 운영자가 한다.
2. 카메라 레지스트리(`~/.config/rosy/omx-cameras.json`)의 쓰는 주체는 제어 PC의 `omx_cameras.py bind --apply` 하나다. Fleet은 운영자 결정(작업셀, 카메라 키, 역할, 운영자)만 SQLite에 저장한다. 장치 경로는 PC 밖으로 나가지 않고 Fleet에는 장치 이름의 해시 키만 간다.
3. 인증은 그 작업셀의 팔 관측 토큰을 다시 쓴다. 이미 그 작업셀의 제어 PC를 식별하는 자격이고 새 호스트 자격을 만들지 않는다. 보고와 결정 수령은 한 요청이다(`POST .../{workcell_id}/usb-devices`가 결정을 응답으로 돌려준다). Fleet에서 호스트로 미는 경로는 없다.
4. 보고는 `workcell_observation_bridge`가 20초마다 읽기 전용으로 보내고, 받은 결정을 `~/.local/state/rosy/omx-camera-decisions.json`에 쓴다. `bind --apply`가 이 파일의 키가 현재 제안과 맞을 때 기존 `approve`와 `save`로 적용하고 항목을 지운다. Fleet 오류는 팔 관측 전송에 영향을 주지 않는다.
5. 화면은 추천 역할을 미리 채우되 출처를 말하고("같은 USB 허브의 팔", "같은 모델이 빠진 역할") 사람이 확인해 승인한다. 새 역할 이름도 받는다(`/<role>_camera/image_raw`).
6. 키가 더는 보고되지 않으면(적용됨, 뽑힘) Fleet은 그 결정을 지운다.

## 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-341, D-456 | Fleet에서 승인하는 같은 모양을 USB 카메라 역할에 적용한다. 승인 대상은 기기 자격이 아니라 역할 이름이다. |
| D-943 | 추정으로 역할을 주지 않는다. 힌트만 보이고 사람이 결정한다. |
| D-777 | 짧은 문서. 정본은 이 결정과 API 참조 v1.350이다. |
| 영상 비중계 | 경로에 video·stream·camera 등을 쓰지 않는다(`usb-devices`). 영상은 지나가지 않는다. |

## Consequences

작업셀 매니페스트에 없는 제어 PC는 보고할 수 없다. 보고가 60초 넘게 끊기면 화면은 그 작업셀의 후보를 숨기고, 결정은 다시 보고될 때까지 보관한다. 이동한 같은 카메라(`follow`)는 `bind`가 스스로 옮기므로 후보에 올리지 않는다. 호스트 시험은 이 변경에서 새 계약·라우트·병합 시험으로 확인했고, 실제 카메라를 꽂아 승인하는 현장 수용은 아직 하지 않았다.
