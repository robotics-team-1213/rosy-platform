# Fleet–CORE–LeRobot SIM 전체 연동 설계

사용자 요청: 기존 CORE 경로를 통해 OMX와 LeRobot을 전체 연동하고 실제 동작을 확인한다. 사용자는 학습 체크포인트가 아직 없다고 답했고 SIM 고정 정책부터 진행하도록 선택했다. 기존 커밋·머지 요청을 유지한다. 물리 장치 활성화와 GitHub push는 이 작업의 수용 조건이 아니다.

## 완료 조건

동일 실행에서 실제 Fleet HTTP 인증·SQLite 승인 창·lease 발급, 장치의 lease 수신·갱신·만료, CORE HTTP, 별도 LeRobot 프로세스, 기존 OMX owner와 vendor Gazebo를 연결한다. 목표 전송만으로 성공을 판정하지 않고 ROS goal UUID·terminal과 joint-state 변화량을 기록한다. 승인 창 폐쇄/갱신 거절 또는 연결 상실 뒤 해당 session의 HOLD·목표 취소와 재시작 거절을 확인한다. 고정 SIM 목표를 학습된 모델 추론이나 Fleet Mission 작업 성공으로 표시하지 않는다.

## 소유권과 최소 변경

Fleet은 기존 policy governance 원장과 승인·lease 발급을 소유한다. 장치의 선택적 SIM composition이 기존 Fleet GET policy state와 POST lease를 인증된 HTTP로 소비한다. CORE는 기존 observation/action/stop API와 동일 프로세스의 port를 제공하고, OMX owner는 기존 관절 admission·ROS Action·watchdog를 유지한다. SDK는 lease·정책 설치·identity·승인을 주입할 수 없다.

새 CORE lease 주입 endpoint를 만드는 대신 장치가 기존 Fleet API를 읽는 방식을 택한다. Fleet→장치 push는 장치 수신 인증과 새 wire 계약이 추가되므로 현재 SIM 연결에 필요하지 않다. 단순 callback으로 Fleet store를 직접 참조하는 방식은 HTTP 인증·clock 경계를 검증하지 못하므로 전체 연동 증거로 쓰지 않는다.

장치 실행 wheel에 lease 소비기와 명시적 composition을 둔다. 설치 loader에는 network dependency를 넣지 않는다. 기본 bootstrap은 비활성 상태를 유지한다. SIM이 아닌 installed policy, 불명확한 owner identity, 잘못된 camera/stop/journal/runtime binding은 실행 전에 거절한다.

## 신뢰·시간·실패 규칙

- accepted release에서 받은 설치 binding과 현재 owner identity를 사용한다. 검사 대상 manifest에서 binding을 역생성하지 않는다. SIM 시험 fixture의 합성 설치는 증거에 명시한다.
- 승인 창 ID, policy revision, rig/calibration, 실행 가능한 창 종류를 신뢰된 SIM 실행 설정에 대조한다. lease의 workcell·episode·owner session·window ID가 모두 일치해야 한다. 다른 창으로 자동 전환하지 않는다.
- 기존 Fleet lease에는 Mission AttemptIdentity와 모델 digest 서명이 없다. 로컬 trusted SIM AttemptIdentity와 기존 installed policy 검증을 사용하며, 이를 Fleet Mission admission 또는 실물 배포 권한으로 간주하지 않는다. 독립 계약 리뷰 결과에 따라 필요한 wire 변경은 별도 ADR/API 변경으로 분리한다.
- lease의 Fleet wall timestamp를 장치 시각으로 직접 비교하지 않는다. 요청 시작의 local monotonic 시각에 반환 lease duration을 더해 보수적 만료를 계산한다. 요청 왕복 시간 전체가 lease 예산에서 소비된다. 로컬 lease 예산을 넘는 응답·만료 응답·역행·재정렬을 거절한다.
- 네트워크 작업은 ROS poll/owner lock 밖의 별도 bounded worker에서 한다. authority callback은 검증된 현재 로컬 lease만 읽는다. 유효한 갱신의 전후 handoff에서도 기존 lease를 지키며 session.renew를 거친다.
- 갱신 거절·통신 실패·expiry·identity 변경은 한 방향 fault로 닫힌다. 기존 session watchdog이 HOLD와 자기 active goal 취소를 수행한다. 늦은 응답이나 재연결은 HOLD를 해제할 수 없다.
- Fleet 창 폐쇄는 다음 갱신에서 거절되고, 장치가 받지 못해도 기존 짧은 lease가 만료된다. 즉각적인 분산 취소나 물리 정지라고 표시하지 않는다.
- 토큰은 private 파일에서 읽고 로그·receipt에 남기지 않는다. 원격 origin은 인증된 TLS, HTTP는 명시적인 loopback SIM에 한정한다. redirect를 따라 다른 origin으로 자격증명을 보내지 않는다.

## 검증과 증거

먼저 원격 단위 시험으로 RTT 차감, scope/replay/expiry/renew race, 거절·disconnect·영구 HOLD를 확인한다. 실제 Fleet HTTP/auth/SQLite와 장치 consumer를 묶는 통합 시험을 추가한다. 마지막으로 remote_sim runner에서 기존 vendor overlay와 SIM 카메라를 사용해 실제 SDK 프로세스→CORE→owner→Gazebo 관절 readback, 갱신, 창 폐쇄→CANCELED/HOLD를 측정한다.

모든 pytest는 committed SHA를 원격 runner로 실행한다. Gazebo는 remote_sim으로만 실행한다. 시험 전에 목표 이동·오차·정지 안정성 한도를 정하고, 실패를 숨기는 retry·timeout/freshness 완화·quarantine 추가를 하지 않는다. 날짜별 검증 기록은 실제 실행 SHA·명령·실행/skip 수·로그 hash·남은 경계를 구분한다.
