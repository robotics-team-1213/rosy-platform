## D-539 Rosy Cam 추적은 운영자가 다시 학습한 빈 트랙 배경을 재시작 뒤에도 쓴다

**Status:** Accepted (2026-10-09, 사용자 지시 "추적 배경 코드 수정"; SOURCE·호스트 테스트까지, 현장 배포와 실제 재시작 확인은 별도 증거).

### Context

D-457 3의 무마커 폴백은 Vision이 시작할 때 처음 30프레임·10초를 빈 트랙 배경으로 배운다. 현장 Vision은 자동 갱신(D-441)과 매일 06:08 재부팅 때 다시 시작하고, 그때 로봇은 보통 매트 위에 세워져 있다. 2026-10-09 현장(`site-af80a5b37eec`, `relearn_seq` 0)에서 두 로봇이 배경으로 굳어 "Rosy Cam이 rosy_26/rosy_60을 찾지 못합니다"가 떴고, 빈 곳 두 점(0.81,−0.46 / 1.35,−0.42)이 미확인으로 잡혔다. 운영자가 빈 매트에서 "배경 다시 학습"을 눌러도 Vision 컨테이너는 read-only이고 상태 볼륨이 없어 다음 재시작 때 그 배경을 잃는다.

### Decision

1. **운영자 재학습만 저장한다.** Fleet `relearn_seq` 증가로 시작한 학습은 D-457이 말하는 "빈 트랙" 선언이다. Vision은 그 학습의 마지막 30프레임을 calibration revision·작업 크기와 함께 source마다 파일 하나(`<state>/<source_id>.npz`, JPEG q95, pickle 없음)에 원자적으로 저장한다. 시작 학습과 `SCENE_CHANGED` 재학습은 저장하지 않는다.
2. **트랙 픽셀만 남긴다.** 저장 프레임은 승인 보정의 트랙 사각형과 그 둘레 8 px(JPEG 블록 경계 번짐 방지) 밖을 검게 지운다. 트랙 밖의 사람·책상은 디스크에 남지 않는다. 검출도 원래 트랙 마스크 안에서만 하므로 결과는 같다.
3. **재시작 때 한 번 재생한다.** 프로세스의 첫 학습에서 같은 revision·같은 작업 크기의 저장본이 있으면 그 프레임으로 MOG2를 세우고 바로 검출한다. 세워 둔 로봇은 첫 프레임부터 전경이다. revision·크기가 다르거나 파일을 읽지 못하면 지금처럼 실시간으로 배운다. 그 사이 조명이 바뀌었으면 첫 프레임이 `SCENE_CHANGED`로 실시간 학습에 들어간다. 재생은 프로세스당 한 번이라 되풀이되지 않는다.
4. **배포.** Vision에 `--track-state DIR`을 두고, 현장 compose는 named volume `vision_state:/var/lib/rosy-vision`(이미지에서 uid 10001 소유)과 `--track-state /var/lib/rosy-vision/track`을 쓴다. 저장 실패는 경고만 남기고 추적은 계속한다. 다음 재시작은 실시간 학습이다.
5. **바뀌지 않는 것.** 표시 전용(D-457 6), 마커 우선, Fleet은 영상을 받지 않음, 운영자 재학습은 빈 트랙에서 한다는 규칙은 그대로다. 카메라를 옮기면 paint-fit 보정을 다시 승인하므로 revision이 바뀌어 저장본은 쓰이지 않는다. 네 모서리 마커 보정은 site-cameras.yaml의 고정 revision을 쓰므로 조금 밀린 카메라에서는 저장본이 재생될 수 있다(크게 밀리면 `SCENE_CHANGED`). 로봇이 있는 채로 누른 잘못된 재학습도 저장되어 재시작마다 재생된다. 복구는 빈 매트에서 다시 학습하거나 `docker volume rm rosy-site_vision_state`다(deploy/site/README.md).

### 검증 시나리오

| 경우 | 기대 결과 |
|---|---|
| 빈 트랙에서 운영자 재학습 → 재시작, 로봇 주차 | 첫 프레임에 `OK`와 로봇 검출 |
| 저장본 없이 재시작, 로봇 주차 | 지금처럼 학습하고 로봇은 배경(변화 없음) |
| 시작 학습만 함 | 파일이 생기지 않음 |
| 보정 revision 변경 / 파일 손상 | 실시간 `LEARNING` |
| 좁은 트랙 사각형 | 저장 프레임의 트랙 밖 픽셀이 0 |

SOURCE·호스트 테스트(`test_overhead_track_blob.py`, `test_overhead_track_worker.py`)와 현장 배포 뒤의 실제 재시작 확인(빈 매트 재학습 → Vision 재시작 → 주차 로봇 검출)을 따로 기록한다.

**Related:** [D-457](D-457-overhead-marker-priority-and-markerless-fallback.md), [D-472](D-472-rosy-cam-map-and-lamp-identity.md), [D-515](D-515-fleet-camera-top-down-site-picture.md).
