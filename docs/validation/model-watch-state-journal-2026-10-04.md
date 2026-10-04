# 상시 model-watch 전달 이력과 설치 후보

기존 서비스는 ProtectHome=yes이고 새 전달 이력의 기본 경로는 사용자 홈 아래다.
system user의 홈을 실제로 쓸 수 있다고 가정하면 전달 전에 이력 생성이 실패한다.
ROSY_MODEL_DELIVERY_JOURNAL_DIR을 기존 StateDirectory 아래의 model-delivery로
명시했다. hardening, HOLD, 전용 키, 기존 활성화 조건은 유지한다.

## 검증

- 경로 누락 RED를 재현한 뒤 관련 HOST 53pass, 독립 HOST 47pass다.
  독립 검토는 writable state/hardening 호환을 승인했다. 실제 서비스 실행 증거는 아니다.
- 관제 운영 venv에는 pytest가 없어 첫 테스트 실행이 실패했다. 운영 의존성을 추가하지
  않고 native journal 생성/fsync와 installer dry-run을 실행해 exit0을 확인했다.
- Linux 회귀의 v2 묶음은 camera_nominal.yaml을 빠뜨려 203pass/1fail이었다.
  파일을 포함한 다음 archive의 v3 LAN 전송은 시간 초과했다. 실패 증거를 보존하고
  인증된 Tailscale 경로의 별도 v4 namespace에서 재개했다.
- 모델 PC의 v4 관련 6 suites는 204pass, exit0이다. 관제의 v4 native journal,
  installer dry-run, 관리자 스크립트 bash syntax 모두 exit0이다.
  전송 archive SHA256: c38b83cc42390aec9c8d19f2c7afd8014acded711cf801a1257f7e922ae31302.
  관제 source manifest는 446 files이며 archive SHA를 원격에서 다시 대조했다.
- 관리자용 v4 스크립트는 archive를 bytes로 읽고 고정 SHA를 검증한 뒤 동일 bytes를
  펼친다. 원래 source/venv/store/config가 있으면 중단한다. 이전 후보는 보존한다.
  사용자 선택에 따른 현장 관리자 요청서만 갱신했으며 외부 전송과 sudo 설치는 미실행이다.

실제 주소·계정·스크립트·실행 결과는 private 자료다. Windows 증거는
X:/DevTemp/rosy-learning-audit-20261004/site-watch-candidate-v2와
site-watch-candidate-v3에 있으며 마지막 디렉터리 안에 v4 결과를 보존했다.
model-watch 실제 서비스/계정 실행, robot key/host pin, 현재 로봇 통신,
shadow loader/rollback, 사람 라벨과 policy/owner/Fleet 인증 결과는 남는다.
운영 주행, HOLD 해제와 물리 명령은 실행하지 않았다.

## 배치 정정

이 문서의 관제 venv/dry-run은 당시 별도 재현 증거다. Accepted D-434와 계획 M1.5는
상시 model-watch를 모델 PC에 둔다. 관제 관리자 설치 후보는 실제 system 설치 전에
철회하고 중단시켰다. 현재 설치 대상과 증거는
[배치 정정 기록](model-watch-placement-correction-2026-10-04.md)을 따른다.
