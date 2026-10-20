# Road-surface 원본 프레임 검증

MODEL-PC에서 실제 검수 DB의 source 선언과 원본 PNG·MP4를 읽어 검증했다.
24/24장의 원본 PNG RGB가 선언된 동영상 frame index의 디코딩 RGB와 정확히
일치했다. 최대 픽셀 차이와 평균 절대 오차는 모두 0이다. 이미지·영상의 선언 SHA256도
실제 bytes와 일치했다. 검수 전후 mask 상태는 모두 pending 24개였다.

| 실제 원본 H.264 영상 | 검증 프레임 | 크기 | Time base | 선택 프레임 상대 PTS 범위 |
|---|---:|---|---|---|
| teleop_rosy_26_20261008T163945Z.mp4 | 8 | 320×240 | 1/15828 | 0–66.33813495072025초 |
| teleop_rosy_26_20261008T164108Z.mp4 | 16 | 320×240 | 1/15928 | 0–218.48317428427924초 |

첫 영상은 1,364,041 bytes, SHA256
`d806a8a2d4e7e2bfe099ca8342bf1bab2fa1b0a345bbfc5095cf8dde78a9b378`이다.
둘째 영상은 4,222,312 bytes, SHA256
`176f00cc193d179d6feec7f641b4da48802d7f82ba79148eb70c404a4acff1d5`다.
선택 frame index별 원래 PTS·time base·영상 상대 시각·두 RGB SHA256을 결과에 보존했다.

이 검증은 영상 안의 상대 시각을 확인한다. UTC 촬영 시각과 camera profile은
미확인이다. 사람 검수는 0/24개이며 human-review 입고·학습·owner 수용·배포는
이 결과에 포함되지 않는다. DB·mask·기존 proof 필드는 수정하지 않았다.

- 실행 source: `7fc62565ca53b67480ba07a444a5f12db07e370d`
- 별도 검증 recipe: [verify_road_video_frame_origins.py](C:/DevTemp/pipeline-completion-20261021/verify_road_video_frame_origins.py), SHA256 `6b20146ee773bf0276795240f39c2bc16e8a79106b8e14098499847fbbf7eace` (위 checkout에 포함되지 않은 원격 명령)
- 실제 실행: MODEL-PC native 8 CPU/6GiB, exit 0
- [프레임별 검증 결과](C:/DevTemp/pipeline-completion-20261021/road-frame-origin-native-2/out/road-frame-origin-result.json), SHA256 `bed175ebdffd1d61a531f94ff1e116eee93450bd349544628911494b354eedcd`
- [원격 실행 로그](C:/DevTemp/pipeline-completion-20261021/road-frame-origin-native-2/run.txt), SHA256 `a3b6f864813bd2e9c0b27d8f49fe195520180a5385e5987e2e2db904df178cef`
- 검증한 source 선언 SHA256: `72d4861d1ca3977cc50f5f1a715fe62b4a48cc7b571d33b4f1f8f912d2d4ac24`
