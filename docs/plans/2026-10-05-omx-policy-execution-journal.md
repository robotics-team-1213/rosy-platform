# OMX 정책 실행의 실제 식별자 보존

기준은 `ffca54496`의 기존 SIM-only `OwnerPolicySession`과 ROS action transport다.
작업 브랜치는 `feat/omx-policy-execution-journal`이다. 정책 후보의 명령 UUID와
action server가 수락한 ROS goal UUID는 다르다. 기존 session의 결과만으로는
동일 실행의 원장·D-18 receipt·Episode·Fleet 결과 연결을 증명할 수 없다.

이번 단계는 private native evidence를 추가한다. 선택적으로 주입한 원장이
전송 전에 원래 lease/AttemptIdentity, Episode/policy revision, 후보와 생성한
명령을 WAL/FULL transaction으로 저장한다. 최종 fence 안에서 저장 후 시간과
관측을 다시 검사한다. 저장 실패·저장 중 만료는 driver 호출을 막는다.
실제 transport event sink는 원래 command/goal UUID, callback sequence/time과
결과를 저장한 뒤에만 True를 반환한다. 저장되지 않은 명령·변경된 goal·중복·
역순·terminal 뒤 이벤트는 거절한다. 하나의 snapshot으로 읽는다.

AttemptIdentity/Episode/policy/source-sequence의 UNIQUE intent key는 재시작,
새 command UUID 또는 lease ID로 같은 intent를 반복하는 것을 막는다. 저장된
intent가 이후 만료로 전송되지 않아도 자동 재시도하지 않는다. 기존 DB의 실제
PK/UNIQUE/FK 제약도 검사한다. 원장을 여는 행위는 replay나 복구 권한이 아니다.

독립 리뷰에서 sink의 None 반환과 동일 컬럼이지만 UNIQUE 제약이 없는 기존
DB 수용을 발견해 회귀 테스트와 함께 수정했다. 호스트 테스트는 기존 owner와
정책 검사, 가짜 transport 및 실제 runtime dispatch 메서드의 host seam을 쓴다.
ROS 실행·물리 결과·독립 과제 성공을 주장하지 않는다.

D-449는 Proposed를 유지한다. 이 기록은 Fleet Action 부모나 D-18 receipt를
만들지 않는다. 실제 composition이 transport sink를 연결해야 accepted goal
증거가 생긴다. 임의 learned command를 네 PICK_PLACE phase로 바꾸지 않는다.
다음 단계는 설치된 실제 artifact/controller bytes 보존, 기존 승인된 Action
context와의 동일 실행 연결, policy-bound Episode와 Fleet 결과 연계 및 실제
SIM 실행 검증이다. 학습·승격·장치 활성화 gate와 총 물리 이동 0.20m 제한은
별도로 유지한다. 이번 단계로 전체 파이프라인 목표를 완료 처리하지 않는다.
