# OMX 환경 상태·양방향 카메라 복구 — 2026-10-17

## 판정

사용자는 어둠에 대한 보정뿐 아니라 밝음·어둠 등 환경 변화를 미리 고려하는 구조를 요구했다.
[D-770](../../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)과
[환경 범위·수집/학습 계약](../../plans/2026-10-17-omx-environment-readiness.md)에 기준을 정리했다.
카메라의 정적 조건 판단·시간에 따른 상태 전이·제한된 제어·이력을 분리해 구현했다.
Fleet PC에 v3 source와 unit을 실제로 설치하고 두 카메라 원본 producer를 유지했다.

이는 카메라의 환경 관측·복구 구현이다. 실제 강조도·역광·깜빡임의 현장 수용이나
수집 executor의 환경 저하 중단, episode/학습 manifest binding이 완료됐다는 결과가 아니다.
실제 움직임과 시연·IL eligible 데이터는0회다. 환경 상태가 정상이어도 물체·집게·기계 간격·
보정·정지 수용을 대신하지 않으며 motion_admitted=False다.

## 구현과 source 검사

- `camera_quality.py` policy v3는 NORMAL/UNDEREXPOSED/OVEREXPOSED/MIXED_LIGHTING/
  LOW_CONTRAST/LOW_SPATIAL_SIGNAL을 구분한다. 혼합 명암을 먼저 판정한다.
  원본 이미지의 지표이며 lux나 원인 진단의 정답이 아니다.
- `camera_environment.py`는 entry/exit 각3회의 advancing sample로 상태를 확인한다.
  각 epoch가 best·후보 소진을 따로 가진다. 어둠에서 고른 설정을 밝은 epoch에 재사용하지 않는다.
  temporal brightness 변화는 hold하며 전원 주파수 flicker 측정으로 표시하지 않는다.
- dark와 bright 후보가 별도다. 실제 범위를 확인하고 적용 완료/readback 뒤5초 cooldown,
 1초 host receive cutoff 이후의 sample을 재검사한다. exposure timestamp 수용은 아니다.
- durable rolling budget은 두 카메라 합계 분당6개 attempted batch를 센다. partial/failed 및
  best 선택도 포함하고 재시작·wall clock rollback으로 초기화하지 않는다. 최종 baseline 복구는
  별도로 시도한다. budget 소진은 cooldown 후 다시 평가하며 무한 빠른 쓰기를 하지 않는다.
- 원본 baseline과 이전 profile은 보존했다. append-only environment.jsonl과 만료되는
  readiness에는 run/profile identity, 환경 epoch, control generation과 시각 경계가 있다.

`bfef87bf1`에서 환경 classifier·양방향 전이·단발성 정상 오판·stale·cutoff·persistent budget의
RED를 확인했다. 독립 리뷰에서 적용 전에 시작된 cooldown이 느린 쓰기로 소진될 수 있음을
찾았다. `a9b5a4722`의 실제 RED 후 완료 시각 기준으로 수정했다. `d9d06a48d` 관련103개 원격
검사가 실제 Chromium 포함 통과했다. `62f94db6b`의 추가 통합 시험은 fake scene/control backend와
실제 monitor/FSM/budget/저장/이력/복구 helper를 사용해 dark800의 높은 과거 score를 bright80보다
선호하는 회귀를 검출한다. 이 묶음34개가 원격 통과했다. 시뮬레이션 fixture 데이터셋 수집은 아니다.

독립 read-only 리뷰는 완료 뒤 cooldown과 epoch 격리 통합 시험을 확인했고 남은 material finding을
보고하지 않았다. reviewer는 실제 장치나 pytest를 실행하지 않았다.

## 실제 카메라 실행과 설치

기존 v2 tuner가 device control lock을 갖고 있으므로 그 옆에서 두 번째 tuner를 켜지 않았다.
독립 cleanup이 등록된 bounded unit 안에서 소유한 v2 tuner만 중지하고 v3를16초 실행했다.
별도 read-only ROS viewer는 port8768을 사용했다. 원본 두 VideoCapture producer는 그대로다.

실제 unit RuntimeMaxSec=35·TimeoutStopSec=35·Restart=no와 ExecStopPost를 기록했다.
저장 assessment60개에서 두 카메라 전체 photometric readiness는0회였다. top은
UNDEREXPOSED와 OBSERVING/SETTLING/COOLDOWN/EXHAUSTED/STALE을, front는
UNDEREXPOSED/NORMAL과 OBSERVING/SETTLING/COOLDOWN/NORMAL/STALE을 관측했다.
front NORMAL은 이미지 screening이며 물체 판독이나 성공 수용이 아니다.

정상 main 종료 뒤 원본값 readback 복구와 별도 ExecStopPost 복구·기존 v2 tuner 재시작을 확인했다.
강제 main 사망을 주입한 시험은 이번 카메라 실행에 포함하지 않았다.

그 뒤 원본 복구를 다시 확인하고 v2 tuner/viewer를 중지했다. 이전 설정·unit bytes를 보존한 뒤
source/profile/unit을 v3로 교체했다. 새 state directory는
`~/.local/state/rosy/omx-camera-environment/`이며 v2 baseline은 남겼다.
실제 사용자 runtime directory로 systemd unit을 검증하고 시작했다. 기존 spice-vdagent unit의
warning 외 두 unit 검증은 성공했다. 설치 후 enabled·active·v3 fresh sample·정확한 두 role의
환경 상태·만료 전 receipt와 카메라별 sole producer를 확인했다. 설치 시 두 role은 UNDEREXPOSED였다.

## 원본 위치와 남은 수용

Fleet private `~/rosy-test/omx-camera-environment-62f94db6b/`에 source hash, 실제/probe profile,
이전 설정 bytes, bounded unit start/cleanup helper, assessment, unit 결과, original restoration,
legacy 재시작 및 migration receipt와 설치 후 JPEG를 보존했다. 실제 device identity와 raw 영상은
공개하지 않는다. source는 `62f94db6b`이며 product source는 `d9d06a48d`와 같다.

현재는 실제 암실 camera-only 증거다. 실제 강조도·명암 불균형·가림·움직임·주파수별 flicker,
물체/집게 식별·환경별 시연·학습·독립 실물 평가는 미완료다. 첫 실제 데이터셋 완료 기준은 유지한다.
