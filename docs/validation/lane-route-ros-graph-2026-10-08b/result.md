# 지도 밖 자세의 굽이 기억 거절: 격리 ROS 노드 재생

2026-10-08, [정상 자세의 ROS 그래프 재생](../lane-route-ros-graph-2026-10-08/result.md)과 동일한 `line_observer_node`, `route_a` 파라미터, ROS domain 97을 사용했다. 원본 226프레임에서 영상·stamp·명령은 그대로 두고, [변환 스크립트](evidence/make_offroute.py)로 첫 경계 공백 frame 192의 odom 위치만 경로 왼쪽으로 0.080 m 옮겼다. 바뀐 NPZ SHA-256은 `37654a0c47891090ca48a4afd522e7e1f3360e358da06ef5959dc79b268b126e`이며, 같은 스크립트로 다시 만든 파일의 해시가 일치했다. 녹화된 실측 자세가 아니라 **합성 위치 오차 반례**다.

[재실행 스크립트](evidence/run_route_graph_offroute.sh)로 frame 76~200을 발행해 카메라 관측 **125/125**를 수신했다([출력](evidence/result.json), SHA-256 `315c129c48463dfc1fd30802d3932d19143cd10016b2f8310e59d257c8679680`). frame 191은 `visible=true, confidence=0.6`, 교란한 frame 192는 **`visible=false, confidence=0, error=null`**, 원래 자세로 돌아온 frame 193은 다시 `visible=true, confidence=0.6`이었다. 정상 자세 재생의 frame 192는 `visible=true`였다. 같은 영상에서도 지도 정렬이 깨지면 기억 후보를 거절한 것이다. 종료 뒤 domain 97에는 노드가 남지 않았다.

재현 순서는 원본 `X:/DevTemp/lane-blind-ros-sim/guard1-frames.npz`(SHA-256 `08e8598bd0aa9736b8ba90ba8a7ec3bc8a77c44a00025f4f546bd3e73f1bfd63`)로 `python evidence/make_offroute.py <원본> <출력>`을 실행하고, 출력 NPZ와 앞선 재생의 `route_graph_replay.py`·파라미터를 모델 PC의 `~/rosy_lfstop_ws/graph_replay/`에 둔 뒤 이 기록의 셸 스크립트를 실행하는 것이다. 원본·변형 NPZ는 대용량 로컬/모델 PC 자료이며 저장소에는 넣지 않았다.

이 증거는 ROS **관측 노드**의 거절 결과다. CORE의 명령 수용, 연속적인 위치 오차, Gazebo 폐루프, 실제 벽·분기·가림 영상의 사람 정답, 실물 주행 안전을 검증하지 않는다. 활성 Fleet 지도·버전·위치 권한도 이 실험자가 고정한 경로 파라미터로 대체되어 있다. 운영 주행은 기존 완전 미관측 STOP을 유지한다.
