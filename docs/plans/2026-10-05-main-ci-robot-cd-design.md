# main CI에서 로봇 업데이트까지 자동 연결

사용자 승인 범위: main에 올린 변경을 GitHub CI/CD로 빌드하고 실제 로봇 업데이트까지 연결한다. 키는 기존 운영 PC에 보관한다.

현재의 로봇 auto-update는 게시된 서명 Release를 받는 기능이다. 추가된 robot_cd.py는 승인된 고정 설치본에서 main push CI 성공을 확인하고 기존 native unsigned workflow를 요청한 뒤 ABI 검사·로컬 서명·기존 카나리 publisher를 실행한다. CI가 실패하면 빌드와 서명은 대기한다. GitHub runner에는 개인키가 없다.

소스 SHA, repo/workflow 정체성, main 조상 관계, artifact source-revision을 검증한다. 설치본과 모든 실행 helper는 해시로 고정하며 새 main 코드는 이 PC에서 실행하지 않는다. release ID는 GitHub 예약 tag와 영속 트랜잭션 상태로 묶는다. 다른 signed rollout은 재개하지 않는다.

운영 설치는 검토·커밋된 소스에서 tools/release/install_robot_cd.ps1로 한다. 로봇 주소를 포함한 설정은 저장소 밖에 둔다. 설정에는 repo, repo_id, state_dir, robots, canary, key_name, 선택 사항 ssh_jump를 적는다. trusted_root는 설치 도구가 승인된 snapshot 경로로 넣는다. state_dir은 관리되는 X: 세션의 실행 상태/다운로드 경로다. gh 인증과 기존 서명 키를 가진 현재 사용자로 5분마다 실행하며 그 사용자가 로그인하지 않거나 PC가 꺼지면 발행 전 단계가 대기한다.

자동화는 장치의 MANUAL, hold, 보정 세션, 다른 claim을 해제하지 않는다. 업데이트 timer·서명/해시·배터리/IDLE·카나리·정상 상태 검사·롤백은 D-412를 따른다. 철회된 릴리스를 다시 열지 않는다. 내비게이션의 G4 승인, 지도 및 map 위치 확정은 별도다.

실행 순서:

1. 거부 조건과 재개 회귀 시험을 통과시키고 독립 리뷰를 받는다.
2. 사용자가 승인한 commit·main 착지·push 뒤 해당 SHA CI를 확인한다.
3. 승인된 snapshot과 current-user 예약 작업을 설치하고 실제 task readback을 확인한다.
4. 새 main의 CI 성공부터 native build, 서명 게시, canary committed, 다른 장치 installed SHA까지 읽는다.
5. 실패나 현장 조건 대기는 해당 단계로 기록한다. host 시험 통과를 장치 업데이트 완료나 자율 주행 수용으로 표시하지 않는다.
