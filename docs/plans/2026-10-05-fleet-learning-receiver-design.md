# Fleet 학습 증거 수신

기존 `rosy.learning-fleet-export/1`을 내부 수신 함수와 CLI로 받는다.
새 HTTP 경로·인증·Task dispatch·승격·학습 요청은 추가하지 않는다.
기존 파일 export는 그대로 유지한다. 운영 관제 설치는 별도 단계다.

수신은 export, Episode manifest, 원본 receipt와 Episode source/stream/evidence
파일의 정확한 bytes를 함께 고정한다. 기존 profile validator와 공용 metadata
binding 함수를 적용한다. producer와 receiver는 같은 binding 계산을 사용하되,
receiver는 자기 snapshot의 파일 closure와 export input SHA를 독립 검증한다.
OMX demonstration/native execution과 Pinky recording을 그대로 지원하며
검증기가 없는 Pilot은 계속 거절한다.

SQLite FULL/WAL transaction에 전체 captured bundle과 SHA를 저장한다.
같은 export revision의 같은 bytes는 idempotent다. 다른 bytes와 같은 revision은
충돌이며 원래 행을 변경하지 않는다. 실패는 행을 만들지 않는다. 재시작 뒤
재독출은 저장 bytes와 profile·binding을 다시 검증한다. 입력 파일의 사후 삭제나
변경으로 이미 수신한 snapshot을 바꾸지 않는다. 저장 bytes·hash·profile·binding의
불일치를 거절한다. 전체 bytes와 metadata를 같이 재봉인하는 공격자를 인증할
외부 anchor는 없으며 DB schema와 uniqueness도 매 transaction에서 확인한다.
원본 bundle은 metadata 근거이며 live receipt 인증·현재 권한·독립 과제·학습 GT
또는 물리 주행 수용으로 승격하지 않는다. task unknown/null policy를 보존한다.

검증은 원래 producer 회귀, 실제 profile fixture, 중복·재시작·동시 수신,
rollback·bundle 변조·resealed binding 변조·입력 SHA 불일치·source 누락과
symlink 거절을 포함한다. 마지막으로 이전 native 실행에서 보존한 두 terminal
bundle을 격리 수신 DB에 넣고 재독출한다. 이전 native 결과를 새로 실행했다고
주장하지 않으며 운영 receiver나 장치 배포 증거로 확대하지 않는다.

Owner: `feat/fleet-learning-receiver`. 실제 주행은 모든 로봇·시도·관성 이동의
합계 0.20m 상한과 기존 설치·현재 안전 상태·보정·제동 여유 조건을 유지한다.
