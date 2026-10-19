# OMX CORE 연동 게시와 남은 실물 준비

사용자 요청: 기존 SIM 연동을 GitHub에 push하고, 실제 학습 체크포인트를 찾아
없으면 준비 방법을 설명한다. 종료 경고는 원인을 확인한 뒤 수정·재검증한다.

공유 main의 다른 작업은 포함하지 않는다. origin/main에서 만든
`feat/omx-policy-chain-publish`에 CORE·SDK·lease·검사와 필수 계약만 이식한다.
원격의 station docking, owner executor와 실물 learned-policy 거부는 보존한다.
새 소스는 이전 SIM 실행 commit과 다르므로 새 commit의 실행 증거가 필요하다.

- [x] producer/consumer 전체를 이식하고 독립 계약 리뷰를 받는다.
- [x] 원격 host 검사와 실제 SDK/native ROS 경로를 검사한다.
- [x] 전체 Gazebo 경로에서 종료 경고의 traceback을 수집하고 원인을 재현한다.
- [x] 원인을 수정한 commit에서 실행·취소·정지·종료를 다시 검사한다.
- [ ] 게시 commit의 pre-push 검사를 통과하고 GitHub branch/PR과 CI를 확인한다.
- [x] 체크포인트·데이터 조사 결과와 실물 준비 순서를 기록한다.

공유 안전 manifest는 새 모듈을 가리킨다. 해당 모듈 없이 먼저 게시하면
참조 검사가 실패하므로 이번 공개 이식과 같은 단위로 검사한다.
이전 로컬 22파일 차이만 게시하면 CORE 진입점과 SDK가 빠져 연결되지 않는다.

실물 수용에는 실제 시연 데이터, 학습·독립 평가, 고정 policy revision,
장치·카메라·보정 binding, 대상 workcell/instance와 운영 승인 기록이 필요하다.
합성 시험 모델이나 채팅 승낙으로 이 기록을 만들지 않는다.
