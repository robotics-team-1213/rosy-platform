# 모델 PC 서비스용 데이터 스냅샷

D-434의 모델 PC 배치를 유지하며 사용자 홈의 원본 store·canonical intake 이력·
재생 자료를 별도 서비스용 스냅샷으로 묶었다. `ProtectHome=yes`를 풀지 않고 향후
관리자 설치에서 읽을 수 있는 경로로 연결하기 위한 준비다. 이 단계는 sudo나
시스템 경로 설치가 아니라 모델 PC의 사용자 경로에서 실행했다.

- 5,980개 파일, archive 287,651,840 bytes, 실제 MP4 replay 19개.
- archive SHA256: `3037f8a00d8ef9095f7ec1ab863745e3209142c59c45c71f2ab0accc56ab5443`.
- manifest SHA256: `142242edf12410105a783f5cb2bde21ffa9f4edb9a58b94fdf9989468b21cbc8`.
- 원본 store·canonical intake 3건·state·gate·replay의 전후 해시가 일치했다.
  모델·dataset/eval bytes와 평가 임계값은 유지했다. gate의 eval 위치만
  서비스 store 위치로 바꾼 후보를 만들었다.
- 기존 strict alias pin의 공개 host key만 포함했다. 개인 키나 모델 PC의
  기존 private key를 복사하지 않았다. 서비스 자체 키 등록은 설치 뒤 단계다.

실제 모델 PC의 고정된 CPU venv와 검증 source로 복사된 자료의 intake를 실행했다.
평가 126장, mIoU 0.5185248134695789, lane line IoU 0.7242653772798793,
PASS를 확인했다. 기존 canonical 비교 이력을 별도 검증 출력에 보존했다.

최초 수집기는 `intake.run`이 `(exit_code, report)`를 반환하는데 이를 CLI 종료 코드로
잘못 넘겨 exit 1이었다. 저장된 보고서의 PASS를 시스템 성공으로 뭉뚱그리지 않았다.
수집기와 원본 결과를 보존하고 별도 검사로 내부 exit code 0·report PASS를 확인했다.
같은 평가를 다시 시작하지 않았다. 후속 archive 검사는 실제 tar의 모든 파일을 읽어
manifest와 검증된 payload의 5,980개 bytes/hash 일치를 확인했으며 exit 0이었다.
절대/상위 경로, link/special member, 중복 member를 거절했다.

독립 리뷰는 수집기를 재사용할 때 원본 accepted 폴더를 입력으로 쓰면 실패 report가
스냅샷에 추가될 수 있다는 결함과, 선언 파일만 비교하면 추가 파일을 놓치는 결함을
지적했다. v1 증거는 보존하고 v2에서 RUN 입력 복사본과 반환 report를 직접 사용했다.
archive 검사에는 전체 payload 파일 집합의 일치 및 모든 entry의 link/special 거절을
추가했다. 수정 소스 독립 리뷰·syntax 검사 승인 뒤 별도 v2 평가를 실행했다.
실제 v2는 exit 0·PASS·reasons 없음이었고, 종료 후 snapshot 전체 경로/해시가 일치했다.
이는 관측 timeout 때문에 원래 실행을 다시 시작한 것이 아니라 검증기 수정의 새 실행이다.

서비스 경로 import·서비스 사용자 접근·새 SSH key 등록·doctor·timer 설치/실행·
shadow/rollback은 아직 완료되지 않았다. 기존 로봇 HOLD, 포인터와 물리 제어를
변경하지 않았다. 라벨 및 owner/Fleet/DEVICE/FIELD 수용도 별도다.

비공개 evidence: `X:/DevTemp/rosy-learning-audit-20261004/service-data-*.json` 및
같은 폴더의 준비·검증 Python scripts. archive는 실제 모델 PC에 보관했다.
