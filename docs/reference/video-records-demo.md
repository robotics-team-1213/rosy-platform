# 실물·시뮬 시연 영상 기록 (11-07 ~ 11-20)

English: [video-records-demo.en.md](video-records-demo.en.md)

목적: 11-10 실물 3단 적층 real2sim, 양팔 비교, 발표 GIF, 11-16 실물 클립을 한 문서로 모아 보여 준다.

## 핵심 결론

- 보여 주는 것: 11-10 실물 시도(Trial 1~12와 autocal), MuJoCo·Isaac 짝 시뮬, 양팔 비교, 발표 GIF다.
- 보여 주지 못하는 것: 실물 3단 적층 성공 장면이다. 기록 없는 시도 영상은 쌓임 장면까지만 보인다.
- 다음 영상: 사후 검증을 마친 실물 3단 안착 장면과 끊긴 11-16 클립 2개의 복구본이다.

### 11-10 실물 3단 적층 real2sim

arm_b 셀에서 컨테이너 1·2·3단 적층을 Trial 1~12로 구동했다. 결과의 placed·PASS는 당시 프로그램 판정이며 실물 적층 확인이 아니다(11-13 정정). 실측 스냅샷 20261110-1231을 MuJoCo와 Isaac에 옮겨 짝 시뮬레이션을 돌렸다.

### 11-07·08 양팔 시뮬

MuJoCo에서 두 팔 협응과 한 팔 순차를 같은 과제로 비교했다. 두 팔 동시 적층이 한 팔 순차보다 9~10% 짧았고 반출도 짧았다. ACT 1라운드 평가는 63단계 중 0통과로 실패했다.

### 발표 GIF

발표 덱에 쓴 하이라이트 GIF를 모았다. 프레임을 직접 보아 실물 9종·시뮬 3종·그래픽·지도 2종으로 구분했다. 원본 시도·결과 기록은 없고 Trial 7과 가장 가까움은 확정 아님으로 적었다.

### 11-16 실물 클립

프레임을 직접 보아 실물 셀 카메라 영상임을 확인했다. 1280x480은 셀 top(왼쪽)과 손목(오른쪽) 화면을 나란히 붙인 것이다. 움직인 팔 이름·시도 번호를 적은 기록은 여전히 없다.

### 11-20 발췌·기준

11-20에 A·B 기준 영상과 Trial 9 발췌를 만들었다. 이 날 발견한 기록 없는 실물 시도 영상 한 편도 이 표에 넣었다.

## 영상 표

같은 시도의 top·side·wrist는 한 행에 묶고 링크는 파일 이름만 적었다.

### 11-10 실물 시도(arm_b 셀)

<details><summary>11-10 실물 시도(arm_b 셀)</summary>

| 번호 | 무엇을 | 언제·어디서 | 결과 | 길이·근거·링크 |
|---|---|---|---|---|
| 1 | 1차 실물 구동 pallet-l0→pallet-l1(구동 ID 20261110T042820Z-001) | 11-10 13:28 · 셀 top·wrist·병합 | approach 0.04 강등, overload-hold, restore_caps 버스 타임아웃 인시던트. 적층 성공 아님 | 47.3초 · 640x480 10fps · [실물] · `real-20261110-132822-{top,wrist,top-wrist}.mp4` |
| 2 | Trial 3: 1열 Row2 집어 올림 | 11-10 17:04 · 셀 top·side·wrist | park 중 jaws 5.0 units 부족, holding 239 mA. 이송·적층 미완 | 62.8초 · 640x480 10fps · [실물] · `real-20261110-170442-{top,side,wrist}.mp4` |
| 3 | Trial 8: 2단 verify_placed | 11-10 18:49 · 셀 top·side·wrist | 프로그램 판정 placed(off_mm 7.6)·PASS이며 실물 적층 확인이 아님. 기울어진 장면 있음 | top 547.2초·side 222.1초·wrist 221.9초 · 640x480 · [실물] · `real-20261110-184942-{top,side,wrist}.mp4` |
| 4 | Trial 9: 2단 적층 뒤 3열 보정 | 11-10 19:07 · 셀 top·side·wrist | 프로그램 판정 placed이며 실물 적층 확인이 아님. 사진에 1열 위 직립 컨테이너 | 628.7초 · 640x480 10fps · [실물] · `real-20261110-190708-{top,side,wrist}.mp4` |
| 5 | Trial 10: 3열 파지 | 11-10 19:23 · 셀 top·side·wrist | 우측 모서리 경계 확인, jaw_margin 0.8 mm. 코드 수정으로 연결 | 723.3초 · 640x480 10fps · [실물] · `real-20261110-192301-{top,side,wrist}.mp4` |
| 6 | Trial 11: 2단→3단 pallet-l1→l2 | 11-10 20:00 · 셀 top·side·wrist | 팔 동작 진행, 3단 안착·전체 적층 미검증. 판정도 프로그램 기준이며 실물 확인이 아님(11-19 문서도 성공 증거 아님) | 320초 · 640x480 10fps · [실물] · `real-20261110-200031-{top,side,wrist}.mp4` |
| 7 | Trial 12: autocal grasp | 11-11 01:33 · 셀 top·side·wrist | 3열 grasp_pick 54.36/172 mA, grasp_debate proceed, arm-cal-arm_b.json 생성 | 61.3초 · 640x480 10fps · [실물] · `real-autocal-grasp-{top,side,wrist}.mp4` |
| 8 | Trial 1·2·4~7 | 11-10 16:29~18:33 · 셀 top·side·wrist | 1 jaws 공간 없음, 2 contact_z 0.0173, 4 슬립, 5 슬립 뒤 park, 6·7 bias 시험(기록 인용). 7 파일은 사본 real-omx-{top,side,wrist}.mp4와 sha256 앞 16자리 동일 | 154.7·287.2·385·427.8·415.1·425.1초 · 640x480 · [실물] · `real-20261110-{162917,163649,173931,180705,181816,183300}-{top,side,wrist}.mp4` |

</details>

### 11-10~11 시뮬 짝

<details><summary>11-10~11 시뮬 짝</summary>

| 번호 | 무엇을 | 언제·어디서 | 결과 | 길이·근거·링크 |
|---|---|---|---|---|
| 9 | MuJoCo cell-stack t1·t2·t3(실측 스냅샷 20261110-1231 기반) | 11-10 · MuJoCo 4뷰 시뮬 | 각 3/3 pass, xy_mm 0.2 이하, tilt 0.0, completed true(시뮬 내부 판정) | 29.3·29.3·27.3초 · 1280x960 15fps · [시뮬] · `sim-cell-stack-t{1,2,3}.mp4` |
| 10 | Isaac 3단 연속 적재 | 11-11 · Isaac Sim 시뮬 | 팀 Confluence에 첨부. 13001프레임 순차 디코딩으로 1300초 실제 길이 확인, 판정 수치는 미확인 | 1300.0초 · 800x600 10fps · [시뮬] · `omx-20261110-stage2-isaac-3tier-video-d1fae1ff.mp4` |

</details>

### 11-07·08 양팔 시뮬

<details><summary>11-07·08 양팔 시뮬</summary>

| 번호 | 무엇을 | 언제·어디서 | 결과 | 길이·근거·링크 |
|---|---|---|---|---|
| 11 | 정답 동작 3x3x3 적층, 4카메라판 | 11-07 · MuJoCo 4카메라 | 정답 동작 첫 기록의 4카메라판, 수치 미확인(r08판은 9/9) | 53.3초 · 1280x960 15fps · [시뮬] · `stack-four-cameras.mp4` |
| 12 | 임시 칸 재취급, 4카메라판 | 11-07 · MuJoCo 4카메라 | 수치 미확인(r08판은 12/12) | 79.3초 · 1280x960 15fps · [시뮬] · `rehandle-four-cameras.mp4` |
| 13 | ACT 1라운드 평가(적층·재취급) | 11-07 · MuJoCo 학습 정책 | 실패: 63단계 중 0통과, 들어 올림 1, 끝까지 마친 태스크 0/6 | 18.6초·21.5초 · 640x480 · [시뮬] · `act-round1-stack.mp4`·`act-round1-rehandle.mp4` |
| 14 | r08 정격 배 적층·재취급 | 11-08 · MuJoCo 4카메라 | 적층 9/9, 재취급 12/12, 시드 3개 통과(배치는 추정) | 54.8초·78.5초 · 1280x960 · [시뮬] · `r08-stack-four-cameras.mp4`·`r08-rehandle-four-cameras.mp4` |
| 15 | 협응 적층 비교: 두 팔 동시 대 한 팔 B 순차 | 11-08 · MuJoCo 시드 0 | 두 팔 148.8 s·한 팔 163.4 s(9/9), 단축 9~10% | 49.9초·54.8초 · 1280x960 · [시뮬] · `coop-stack-two-arm-conc.mp4`·`coop-stack-one-arm-B-seq.mp4` |
| 16 | 협응 반출 비교: 두 팔 동시 대 한 팔 B 순차 | 11-08 · MuJoCo 시드 0 | 두 팔 165.7 s(10/10), 한 팔은 반출 2건 중 1건. 지도 변경 뒤 재생값 177.3 s(10/10) | 55.5초·31.1초 · 1280x960 · [시뮬] · `coop-outbound-two-arm-conc.mp4`·`coop-outbound-one-arm-B-seq.mp4` |
| 17 | 정답 동작 첫 기록(적층·재취급 짧은 판) | 11-07 · MuJoCo | 기록은 첫 기록으로만 적힘 | 160초·79.7초 · 1280x480 · [시뮬] · `stack.mp4`·`rehandle-short.mp4` |
| 18 | arm_b 시뮬 교사·모델 3라운드 | 11-07 · MuJoCo | 결과 수치 미확인 | 28.7초·34초 · 640x240 15fps · [시뮬] · `sim-teacher.mp4`·`sim-model-round3.mp4` |

</details>

### 발표 GIF

<details><summary>발표 GIF</summary>

| 번호 | 무엇을 | 언제·어디서 | 결과 | 길이·근거·링크 |
|---|---|---|---|---|
| 19 | isaac 3단 하이라이트 | 11-12 · Isaac 시뮬 발췌 | 팀 Confluence에 링크, Isaac 3단 영상 앞 구간과 같은 장면(장면 관찰) | 3.8초 · 800x600 8.3fps · [시뮬] · `isaac-3tier-highlight.gif` |
| 20 | 실물 OMX top·side 하이라이트 | 11-12 · 실물 OMX | Trial 7(183300)과 가장 가까움(확정 아님), 발췌 구간·시도는 미확인 | 3.8초 · 640x480 · [실물] · `real-omx-top-highlight.gif`·`real-omx-side-highlight.gif` |
| 21 | 발췌 GIF 2종(적층 시도 side·팔 top) | 11-14 · 실물 OMX | Trial 7(183300)과 가장 가깝다(확정 아님), 표본 구간의 동작 변화는 보이지 않음 | 14.4초·14.6초 · 560x420 · [실물] · `omx-stack-attempt-side.gif`·`omx-arm-top.gif` |
| 22 | 협응 하이라이트 2종 | 11-16 · 시뮬(MuJoCo류 4분할 화면) | 시뮬 4분할 화면 확인, 원본 시도·끝 상태 9/9 여부는 미확인 | 10.5초 · 560x420 4fps · [시뮬] · `coop-one-arm-hold.gif`·`coop-two-arm-done.gif` |
| 23 | 절차 GIF(계획·이송) | 11-14 · 3D 그래픽·지도 화면 | step1은 3D 그래픽, step2는 사진 위 선·마커 지도 화면. 실제 계획·주행 기록인지는 미확인 | 17초·16초 · 420~480 폭 · [화면] · `step1-plan.gif`·`step2-transport.gif` |
| 24 | 절차 GIF(파지·내리기·적층·확인) | 11-14 · 실물 카메라(손목·top·side) | 실물 카메라 화면 확인, 어느 팔·시도인지와 파지 유지 여부는 미확인 | 8~10.2초 · 420~480 폭 · [실물] · `step3-grasp.gif`·`step3-unload.gif`·`step4-stack.gif`·`step5-check.gif` |
| 25 | omx z-sync 셔틀 영상 | 11-12 · 실물(로그 문구 표시 포함) | 셔틀 동작(원래 칸→임시 칸→복귀)과 Elapsed 표시 확인, 시도 번호·높이 복원 실제 여부는 미확인 | 86.8초 · 640x299 4fps · [실물] · `omx_z_sync_shuttle_preview.gif` |

</details>

### 11-16 실물 클립

<details><summary>11-16 실물 클립</summary>

| 번호 | 무엇을 | 언제·어디서 | 결과 | 길이·근거·링크 |
|---|---|---|---|---|
| 26 | arm_a 라이브 녹화 | 11-16 01:17 · 실물 셀 top·손목 | 팔 2대와 판·받침이 보이는 셀 장면, 움직인 팔이 arm_a인지·파지 결과는 미확인 | 280.9초 · 1280x480 8fps · [실물] · `arm_a_live.mp4` |
| 27 | arm_s 라이브 녹화 | 11-16 01:07 · 실물 셀 S top·손목 | 팔이 벨트 쪽으로 뻗었다 기울어지는 장면, 컨테이너 이동 여부는 미확인 | 112.8초 · 1280x480 8fps · [실물] · `arm_s_live.mp4` |
| 28 | arm_s 픽 녹화 | 11-16 01:08 · 실물 셀 S top·손목 | 기울어진 팔 자세로 시작하는 장면, 파지 성공·물체 이동은 보이지 않음 | 225.4초 · 1280x480 8fps · [실물] · `arm_s_live_pick.mp4` |
| 29 | arm_s 라이브 2차 녹화 | 11-16 01:16 · 실물 셀 S top·손목 | 손목 화면에 받침·붉은 물체가 보이는 장면, 결과·움직인 물체는 미확인 | 167초 · 1280x480 8fps · [실물] · `arm_s_live2.mp4` |

</details>

### 11-20 발췌·기준

| 번호 | 무엇을 | 언제·어디서 | 결과 | 길이·근거·링크 |
|---|---|---|---|---|
| 30 | A·B 기준 영상 top·side | 11-20 01:22 · 실물 셀 | 8초씩 녹화, 중간 프레임에 팔·작업대 확인. 동작·배치는 미측정 | 8.0초 · 640x480 10fps · [실물] · `top.mp4`·`side.mp4` |
| 31 | Trial 9 two-tier 22초 발췌 | 11-20 발췌(원본 11-10) · 실물 셀 side | 220프레임, sha256 기록(clip 2ed61dc5·source c61a471a 앞 8자리). 2단 장면이며 실물 적층 성공이 아님(11-13 정정) | 22초 · 640x480 10fps · [실물] · `trial9-two-tier-22s.mp4` |
| 32 | 기록 없는 실물 3단 시도 영상 | 11-20 발견 · 실물 측면(side) | 집게가 컨테이너를 내려 쌓는 장면. 단수·팔·시도는 미확인이고 무너짐은 보이지 않음, 3단 성공 판정 아님 | 18.0초 · 640x480 10fps · [실물] · `omx-real-tier3-attempt-18s.mp4` |

## 대표 그림

![11-10 Trial 9 2단 장면 22초 발췌(11-20). 프로그램 판정 placed, 실물 적층 확인 아님 [실물]](../assets/video-records/av-real-trial9-2tier.gif)

![두 팔 동시 적층 9/9, MuJoCo 시뮬 4카메라 [시뮬]](../assets/video-records/av-real-coop-twoarm.gif)

![3단 적층 시뮬 4뷰, 내부 판정 3/3 [시뮬]](../assets/video-records/av-real-sim-t3.gif)

## 빠진 것

- Trial 11 이후 실물 3단 안착·정렬·사후 높이는 기록상 미검증이다(11-13 정정).
- 11-16 클립 2개(`arm_s_live_pick2.mp4`·`arm_s_live2_b.mp4`)는 녹화가 끊긴 미완성 파일(moov 없음)이다. 복구는 시도하지 않았다.
- 발표 GIF의 원본 시도·결과는 실물·시뮬 구분을 마친 뒤에도 미확인이다. Trial 7 영상 자체의 화면 변화가 작아 발췌 구간도 불확정이다.
- Isaac 3단 영상의 판정 수치는 미확인이다. 더미 단수도 시트 해상도로는 확정하지 못했다.
- 11-07 첫 기록 단계 통과 수치는 미확인이다. 같은 폴더에 수치 json이 없고 README는 r08 수치만 적는다.
- 11-10 실물 시도 전체와 11-16 클립의 HF 데이터셋·리비전은 기록에 없다.
- 11-19 리허설·11-20 이후 회차 영상은 이 범위에 파일이 없다.
- Pinky Gazebo 한 바퀴·world 시나리오 영상(11-16)은 OMX 범위 밖이라 이 문서에서 뺐다.

## 근거

- `workspace-records/2026-11-10/omx-tier-stack-real2sim/README.md`
- `workspace-records/2026-11-11/publish_d1012_confluence.py`
- `research/omx-two-arm-20261107/README.md`
- `research/omx-sim-reference-20261107/README.md`
- `presentation/assets/README.md`
- 작업 폴더 기록 `omx-ab-baseline-evidence-01a1f45e/result.md`
- 작업 폴더 기록 `omx-early-layer-visual-20261120/trial9-two-tier-index.json`

## 더 읽을 곳

보정 체계: [calibration-system.md](calibration-system.md) · 학습 데이터 영상: [video-records-learning.md](video-records-learning.md)

같은 글: 팀 Confluence·Notion
