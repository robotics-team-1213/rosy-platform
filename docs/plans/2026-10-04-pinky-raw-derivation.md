# Pinky MCAP와 학습 sidecar 대조

기준 `7a28608cb`. 이전 턴의 source snapshot 등록은 progress이며 전체 목표는 active다.
이번에는 직접 ROS 2 MCAP 메시지를 디코딩해 common Episode의 sidecar를 대조한다.

1. 원본 camera header/log 순서·크기·encoding, 실제 Twist 명령과 odom·JSON 관측·scan을 읽는다.
   여러 namespace가 섞이면 거부한다. mcap CRC 검증을 켜고 다른 message schema를 같은 단위로 읽지 않는다.
2. camera/log pair와 frame 수를 정확히 비교한다. 각 unstamped side entry는 원본의 최신 causal
   메시지, stamped entry는 같은 image stamp의 첫 eligible 메시지다. 반올림 dt도 원본 계산과 비교한다.
3. Scan NPZ의 float16 ranges·int64 stamp·float32 dt와 기하 scalar를 원본 선택 메시지에 대조한다.
   영상은 전체 decode의 frame 수·크기를 검사한다. 손실 압축 pixel provenance와 motion 파생은 인증하지 않는다.
4. 전후 DatasetManifest/Episode closure를 검사해 입력 변경을 거부한다. 생성한 보고서만 받아 신뢰하지
   않고 행동 입력 준비 CLI가 검증기를 직접 실행한다. 실패 시 출력/ready를 만들지 않는다.
5. 실제 기존 immutable 녹화에 실행하고 host/native 시험과 독립 리뷰를 남긴다. runtime writer 없음.

학습 명령은 관측된 CORE 최종 출력의 lookback 기록이다. expert intent·미래 목표·움직임 성공,
policy qualification·Fleet 과제/Action 결과로 해석하지 않는다. CameraProfile null과 unknown outcome은
유지한다. 이후 행동 학습 target/평가·owner 계약으로 이어가며 물리 주행 활성화는 별도다.
