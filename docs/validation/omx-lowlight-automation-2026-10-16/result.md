# OMX 기존 카메라 저조도 자동 조정 — 2026-10-16

## 결과

[D-770](../../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)의 기존 카메라 경로에
자동 노출 조정·원본 프레임 품질 검사·웹 상태 표시·종료 복구를 연결했다.
Fleet PC에 두 새 user service를 설치했고 readiness service가 enabled·active다.
`Linger=yes`를 읽었지만 실제 재부팅 시험은 하지 않았다. 원본 두 camera producer는
계속 active이며 각각 장치의 sole PID다. 추가 VideoCapture나 robot serial 접근은 없다.

**현재 실제 영상은 여전히 관측 불충분이다.** 자동 조정이 암실에서 물체 판독을
보장한다는 결과가 아니다. 실제 시연·IL eligible 데이터는0회이고 구동하지 않았다.

## 자동 경로

1. 기존 두 preview를 읽기 전용 ROS subscriber가 받는다. JPEG 인코딩 전 원본에서
   밝기·암부·포화·전체 대비와4×4 tile 평균의 공간 대비를 계산한다.
2. localhost viewer가 JPEG와 같은 sample lifetime에 품질을 묶는다. stale이면 품질도 제거한다.
3. tuner는 fresh·유한하며 증가하는 source stamp·정수 sequence와 정확한 품질 policy를
   요구한다. `usable=False`인 관측에서만 후보 설정을 적용한다.
4. 실제 V4L2 제어 범위를 확인하고, 원본 제어값·장치 identity·단독 producer를 기록한다.
   file·directory fsync를 마친 뒤 manual mode부터 설정한다. 현재 후보는40/80ms다.
5. 설정별 readback과 settling을 확인한다. 후보를 소진하면 관측한 공간 대비가 가장 나은
   설정을 선택하고 readback한다. 이후 프레임을 계속 검사한다. 무한 탐색하지 않는다.
6. 두 영상 각각 세 advancing sample이 조건을 만족해야 photometric readiness가 열린다.
   receipt는750ms 후 만료된다. 종료 시 invalidate·원본 복구하며 독립 ExecStopPost도 복구한다.

제어는 같은 실제 device number별 flock으로 직렬화한다. profile/device/producer가 바뀌면
진행하지 않는다. 기록 실패가 원본 복구를 건너뛰지 않게 finally를 분리했다.
영상 품질 threshold는 프로젝트의 초기 screening 값이며 검증된 물체 인식 성능 기준이 아니다.
`motion_admitted=False`·`physical_acceptance=False`를 유지한다. 이 receipt만으로 팔을 움직이거나
성공 라벨을 만들지 않는다. 수집 중 품질·시각·개입을 원본과 함께 보존하는 결선은 후속 과제다.

## 실제 시험과 발견

- `4ab1fff89` camera-only10초 실행: 두 후보를 자동 적용하고 원본값으로 복구했다.
  top은 평균 약8.96에서 일부 설정에서1.41로 악화했다. front는 약3.27에서38.80으로
  밝아졌으나 저장 영상에서 강한 노이즈를 확인했다. 두 영상 readiness는 한 번도 열리지 않았다.
- 이 결과로 uniform-noise regression을 추가했다. 공간 대비 검사와 best 설정 선택을
  추가했고 구형 viewer의 밝기-only `v1` 결정을 거부하도록 policy를 `v2`로 올렸다.
  `6908b22d3` private source는 staging만 했고 실행하지 않았다.
- `6596cf3f6` camera-only10초 실행:39개 저장 assessment, 두 카메라 후보 readback,
  best 선택, 종료 및 ExecStopPost 복구를 확인했다. 두 영상 readiness는0회다.
  top 원본은 당시 평균 약0.94, 후보 중 최대 약1.51이었다. front는 최대 약34.90으로
  밝아졌고 일부 sample에서 photometric 조건을 만족했지만 물체 판독 수용은 아니다.
- 두 실행 모두 top의 원본 brightness−10/gain4/gamma10/auto3/exposure80과
  front의 gain0/gamma100/auto3/exposure156 readback이 복구됐다. control readback은
  장면·자동 노출의 원래 시각적 결과가 동일하다는 증거가 아니다.
- 최종 두 service 설치 뒤 advancing/fresh 관측, enabled·active, 두 sole producer,
  만료 전 receipt와 `INSUFFICIENT`·`photometric_ready=False`를 재확인했다.

첫 설치의 `systemd-analyze --user verify`는 SSH의 XDG_RUNTIME_DIR 누락으로 실패했다.
이미 만든 설정의 정확한 bytes를 확인한 뒤 실제 사용자 runtime directory를 지정해 검증·설치를
이어갔다. 파일을 덮어쓰거나 원본 producer를 재시작하지 않았다. 시스템의 기존 spice-vdagent
unit warning은 출력됐지만 두 새 unit 검증과 시작은 성공했다.

## 검증 범위와 보존

새 검사 RED→GREEN을 원격 PC에서 확인했다. 원본 회귀9개, 리뷰에서 찾은6개,
uniform noise 및 구형 policy 거부를 각각 실패 상태에서 확인하고 수정했다.
`6596cf3f6`의 관련 원격 검사88개가 통과했으며 opt-in 실제 Chromium도 실행했다.
독립 read-only 리뷰는 최종 source와 두 service에서 남은 material finding을 보고하지 않았다.
pytest·카메라 control 실행·웹 표시·실물 구동·실데이터 학습을 구분한다.

Fleet private `~/rosy-test/omx-camera-auto-4ab1fff89/`와
`~/rosy-test/omx-camera-auto-6596cf3f6/`에 source hash, 실제 profile, 원본 제어값,
후보별 readback, 전후 JPEG, assessment, unit 결과와 restoration receipt를 보존했다.
최종 경로의 installation/followup receipt는 실제 설치와 최신 상태를 보존한다.
상시 상태는 `~/.local/state/rosy/omx-camera-readiness/`, 설정은
`~/.config/rosy/omx-camera-readiness.{env,json}`다. 실제 identity와 raw 영상은 공개하지 않는다.
