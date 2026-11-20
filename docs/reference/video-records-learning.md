# 학습 데이터 영상 기록 (09-19 ~ 11-20)

English: [video-records-learning.en.md](video-records-learning.en.md)

목적: 학습 데이터가 텔레옵 녹화에서 LeRobot export와 HF를 거쳐 셀 모델 검증에 돌아오는 흐름을 영상으로 보여 준다.

## 핵심 결론

- 보여 주는 것: 텔레옵 원본 22편(전방 카메라, 팔 없음), LeRobot export, HF 왕복, 79회차 재생이다.
- 보여 주지 못하는 것: sidecar 없는 9편의 로봇명·과제와 세션별 성패다. export·정책 영상은 시뮬 렌더다.
- 다음 영상: 실물 3단 적층 안착 장면과 11-18~20 묶음의 HF 왕복 기록이다.

### 1 텔레옵 녹화 — 수집 (09-19 ~ 10-05)

사람 텔레옵 학습 녹화 mp4 원본은 22편이다. inventory 24행에서 오탈자 행 1과 retired 사본 1을 뺀 수다. sidecar가 있는 13편(8kcn 7·9dfk 6)은 과제를 확인했다: 보정 6, 차선 주행 2, 교차로 2, 시범 3. 22편 모두 로봇 전방 카메라 화면이고 팔은 한 편에도 나오지 않는다. sidecar가 없는 9편(part 7편·teleop_201 2편)의 로봇명·과제는 미확인이다.

### 2 LeRobot export (10-21 ~ 10-22)

텔레옵 원본을 LeRobot 에피소드 형식으로 export했다. batch 7·9·10·11·12·14·15를 각 3회, object·contact-hold를 1회씩 내보냈다. 기록은 고정 cohort 25/25 시연과 전체 66,080프레임 readback 통과를 적는다. export 영상 장면은 프레임 확인에서 시뮬 렌더로 나왔다.

### 3 학습 실행 (10-23)

export 결과를 학습 도구에 넣는 연결을 합성 장치로 시험했다. ACT 2-step 학습과 새 프로세스 재적재가 통과했다. paired record loop는 저장 action과 실제 전송 action이 일치함을 보였다.

### 4 HF 업로드·왕복 (10-24)

SIM scripted-teacher 에피소드 1건을 private 데이터셋에 올렸다가 다시 받았다. 1,613파일·1,587프레임의 SHA와 reader 검증이 통과했다. 데이터셋은 `robotteam/rosy-omx-sim@5a7a5952` 리비전에 고정한다.

### 5 셀 모델 검증 재사용 (11-18 ~ 11-20)

학습에 쓰인 과거 사람 시연 pinky_v1 79회차를 셀 모델 검증 자리에서 재생했다. Isaac Sim 성공 회차도 위치 표본 재생으로 확인했다. 수집한 데이터가 검증 단계에서 다시 읽히는 흐름을 이 영상들이 보여 준다.

## 영상 표

링크는 파일 이름만 적었다. 표지는 11-20 프레임 확인에 따라 [실물]·[시뮬]·[화면]을 구분해 붙였다.

| 번호 | 무엇을 | 언제·어디서 | 결과 | 길이·근거·링크 |
|---|---|---|---|---|
| 1 | 텔레옵 7분할 시리즈 대표 part01 | 09-19 15:12 UTC · 실물, 로봇명 미확인 | 전방 카메라 주행 장면(화면 관찰), 성패는 미확인 | 100.5초 · 320x240 · [실물] · `teleop_20260919_151213_part01.mp4` |
| 2 | teleop_201 upright 녹화 2편 중 짧은 쪽 | 09-28 21:50 UTC · 실물, 로봇명 미확인 | 전방 카메라 주행 장면(화면 관찰), 성패는 미확인 | 250.3초 · 640x480 · [실물] · `teleop_201_20260928_215056_upright.mp4` |
| 3 | 8kcn 차선 주행 세션(백필 대상) | 09-30 12:47 UTC · 실물 rosy-pinky-8kcn | 차선 주행(sidecar), shadow 프레임 2,258개 전체 백필 뒤 선택 재료화, 성패는 미확인 | 282.2초 · 320x240 · [실물] · `teleop_rosy-pinky-8kcn_20260930T124745Z.mp4` |
| 4 | 8kcn 차선 주행 세션(shadow payload 보유) | 10-01 13:08 UTC · 실물 rosy-pinky-8kcn | 조사 세션 중 shadow payload가 있는 유일한 세션, 14,240프레임, 차선 주행(sidecar), 성패는 미확인 | 1,787.4초 · 320x240 · [실물] · `teleop_rosy-pinky-8kcn_20261001T130842Z.mp4` |
| 5 | 9dfk 시범(pilot) 세션 | 10-05 13:45 UTC · 실물 rosy-pinky-9dfk | pilot 시범(sidecar), 의도·성패는 미확인, 3중 사본 존재 | 470.9초 · 320x240 · [실물] · `teleop_rosy-pinky-9dfk_20261005T134540Z.mp4` |
| 6 | batch 7 export-1 시뮬 장면 | 10-21 · 시뮬 렌더(화면 관찰) | 묶음 전체가 cohort 25/25 시연·66,080프레임 readback 통과, 표본 7개는 큐브를 파란 판 위로 옮김 | 264.2초 · 320x240 10fps · [시뮬] · `file-000.mp4` |
| 7 | 정책 입력 webm 13편 대표(9447 inputs, 나머지 12편) | 10-21 ~ 10-22 · 시뮬 렌더(화면 관찰) | 12편 모두 같은 시뮬 장면, 정책 출력은 미확인 | 13.2초 · 320x240 8fps · [시뮬] · `omx-native-9447-inputs.webm` |
| 8 | contact-hold teacher full-rgb | 10-22 · 시뮬 렌더(화면 관찰) | contact-hold 수집 원장에 연결된 학습·재적재 완료 3개(10-23 기록) | 261.9초 · 320x240 10fps · [시뮬] · `omx-teacher-c7dedb9bfcfd-full-rgb.mp4` |
| 9 | atomic-teacher export 앞 화면 | 10-23 · 시뮬 렌더(화면 관찰) | 고정 teacher cohort CT20261023a566(25개 계획) 수집 맥락, 큐브가 파란 판 위로 이동 | 317.2초 · 320x240 5fps · [시뮬] · `file-000.mp4` |
| 10 | 양팔 합성 reader 영상 2종 | 10-23 · 합성 장치(SDK) | ACT 2-step 학습·새 프로세스 재적재 통과, 합성 연결 한정 | 0.5초·0.1초 · 32x32 30fps · [시뮬] · `file-000.mp4` 2종 |
| 11 | paired SDK record loop | 10-23 · 합성 장치(LeRobot 0.4.4) | 1 에피소드 9프레임 PASS, 저장·전송 action 일치 | 0.3초 · 128x128 30fps · [시뮬] · `file-000.mp4` |
| 12 | HF 왕복 payload 영상 | 10-24 · SIM scripted-teacher | 업로드 뒤 readback으로 1,613파일·1,587프레임 검증 완료 | 317.4초 · 320x240 5fps · [시뮬] · `file-000.mp4` · `robotteam/rosy-omx-sim@5a7a5952`(private) |
| 13 | Isaac 왕복 회차 경로 재생 | 11-19 재생 · 시뮬, Isaac Sim 성공 회차 | 원위치 복귀, 최종 안착 XY 최대 편차 1.859 mm(위치 표본 재생) | 30.2초 · 960x480 15fps · [시뮬] · `roundtrip-measured-trace.webm` · [GIF](../assets/video-records/av-learning-roundtrip.gif) |
| 14 | pinky_v1 79회차 재생 | 11-20 재생 · 학습 데이터 재생(top·wrist 카메라), 원본 수집 시각 미확인 | 물체가 Pinky에서 벨트로 이동하는 장면, PTS와 데이터 행 편차 1 ms 이내 | 18.3초 · 960x384 15fps · [실물] · `episode-79.mp4` |
| 15 | 셀 S 라이브 8초 기록·녹화 도구 3초 스모크 | 11-19 ~ 11-20 · 실물 셀 S 상단·손목 | 라이브 8초는 정지 상태 관찰, 32쌍 최대 시각차 102.11ms. 스모크는 12프레임 디코딩 확인 | 8.0초·3.0초 · 1280x524 4fps · [실물] · `cell-s-current-views.webm` 2종 |

## 대표 그림

![학습에 쓰인 pinky_v1 79회차 재생, 상단·손목 두 화면 [실물]](../assets/video-records/av-learning-episode79.gif)

![LeRobot export 결과 영상, batch 7 export-1 시뮬 장면 [시뮬]](../assets/video-records/av-learning-export.gif)

![Isaac Sim 왕복 회차의 위치 표본 재생 [시뮬]](../assets/video-records/av-learning-roundtrip.gif)

## 빠진 것

- batch 16(3회)·batch 17(1회) 시연의 export 영상이 이 목록에 없다.
- sidecar 없는 텔레옵 9편(part 7편·teleop_201 2편)의 로봇명·과제는 미확인이다. 22편의 세션 성패는 프레임 표본으로 판정하지 못했다.
- 정책 입력 webm은 13편 중 12편을 보았고 나머지 1편은 전달 목록에 없다.
- teacher-held-batch-input-proof·sampled-teacher 영상의 기록 근거는 미확인이다.
- 11-18~20 묶음 영상과 연결된 HF 업로드 기록을 찾지 못했다. 리비전 칸을 미확인으로 둔다.
- pinky_v1 79회차의 원본 수집 일시·HF 리비전·어느 팔 기록인지는 미확인이다.
- `robotteam/rosy-omx-data`라는 데이터셋 이름은 허용 기록에 없어 이 문서에서 쓰지 않았다.
- inventory 오탈자 행(`…mp414354493`)의 파일은 존재하지 않는다. 같은 이름의 정상 mp4가 retired에 있다.

## 근거

- `workspace-records/2026-10-21/pipeline-execution-2026-10-21.md`
- `workspace-records/2026-10-23/learning-pipeline-current-evidence.md`
- `workspace-records/2026-10-24/hf-private-roundtrip-result.md`
- `workspace-records/2026-10-24/hf-readback-recovery-solution.md`
- `workspace-records/2026-10-28/selection-strategy-experiment.md`
- `workspace-records/2026-10-28/recording-lerobot-hf-uiux-review.md`
- `workspace-records/2026-10-29/shadow-evidence-backfill-result.md`
- `workspace-records/2026-10-29/recording-shadow-gate-design.md`
- `workspace-records/2026-11-18/arm-s-model-onboard.md`
- `workspace-records/2026-11-19/omx-cell-s-act-shadow-check.md`

## 더 읽을 곳

보정 체계: [calibration-system.md](calibration-system.md) · 시연 영상: [video-records-demo.md](video-records-demo.md)

같은 글: 팀 Confluence·Notion
