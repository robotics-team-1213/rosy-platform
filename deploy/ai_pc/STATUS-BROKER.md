# D-720 상태 숙고 브로커 설치와 수용

Fleet의 기존 기명 Discord receipt가 tasks DB의 channel model job으로 이어진다.
최초 활성화 이전 요청은 재생하지 않는다. 호출 예약, 고정 SSH/stdin 브로커,
schema 2 판단, 현재 관측 재검증, 결과와 기존 Discord outbox의 원자 기록,
provider 원문 reference 확인 순서로 수용한다. CORE 사건·명령·기명 계정을
자동 생성하지 않는다. `GET /api/fleet/channel-requests/{id}/deliberation`과
Console 요청 검토에서 상태와 모델 ID를 확인한다.

## 관리자 작업 전 준비

검토·원격 검증을 통과한 한 commit의 source closure와 SHA manifest를 만든다.
closure에는 `contracts/foundation`, `operations/decision/src`, `deploy/ai_pc`,
`deploy/site/deliberation_sandbox.py`, `deliberation_preflight.py`,
`deliberation_install.py`, `requirements-fleet.txt`, `install-status-client.py`를
포함한다. site에서 새 broker 전용 ed25519 키를 생성하고 private key는
`/home/robttt/.rosy/status-incoming/broker.key`의 소유자·0600을 유지한다.
public key만 bundle에 넣는다. 기존 host-control key를 사용하지 않는다.

bundle 전체 SHA는 installer, manifest, source, public key를 함께 고정한다.
관리자는 private staging bundle을 새 `/root/rosy-status-reviewed/<commit>/`
디렉터리에 복사한 뒤 승인된 SHA를 검증하고 압축을 풀어야 한다.
user-writable staging에서 Python을 root로 실행하지 않는다. 실제 세션의
승인된 digest를 넣은 정확한 명령은 별도 검증 자료로 남긴다.

root snapshot의 source 디렉터리에서 실행한다:

```sh
PYTHONPATH=. python3 deploy/ai_pc/install-status-broker.py \
  /root/rosy-status-reviewed/<commit>/source \
  /root/rosy-status-reviewed/<commit>/manifest.json \
  /root/rosy-status-reviewed/<commit>/broker.pub \
  --manifest-sha256 <approved-manifest-sha256>
```

`--check`는 입력 소스 검증만 수행한다. 설치·SSH·정상 추론·격리·독립 보정·
운영 왕복의 PASS가 아니다. 실제 설치는 root-owned 버전 source/venv,
고정 forced-command ingress, 정확한 sudo command, 별도 host pin을 구성한다.
외부 파일·symlink·다른 계정·변경된 키는 덮어쓰지 않는다.

## 독립 수용과 비용

primary는 정확한 local 모델 digest/context와 실제 schema 응답을 검증한 뒤
root가 명시적으로 `d720-read-only-status-v1` 정책을 수락한다. 이 정책은
읽기 전용 상태 표시의 action calibration 면제이며, 모델 자유 문장을
사실로 사용하거나 모델 판단으로 장치를 실행하도록 허가하지 않는다.
일반 CORE 사건의 기존 calibration/admission을 변경하지 않는다.

GLM은 기본 미수락이다. 기존 독립 검증과 실제 계정·키·plan 증빙을 가진
관리자가 `/etc/rosy-deliberation/status-reviewer-admission.json`을 root-owned
0640, deliberation 그룹 읽기로 준비한 경우만 검토한다. 필드는 정확히
`reviewer_admission`(독립 status AdapterCapabilities)과 `billing_policy`
(TrustedIncludedPlanPolicy)다. profile SHA는 새 status reviewer 전체 profile에
결속해야 하며 기존 domain의 readiness나 billing 파일을 그대로 복제하면
안 된다. installer는 현재 보호 key fingerprint, policy 만료, 실제 기존
offline sandbox preflight를 검증한다. provider usage/receipt 없는 비용을
0으로 단정하지 않는다.

`/var/lib/rosy-deliberation/smoke/glm-first-review.spent`는 기존 1회 smoke의
공유 한도다. 설치·profile 변경·rollback·UNKNOWN에서도 삭제하거나
초기화하지 않는다. 이미 사용된 경우 reviewer는 미수락으로 유지한다.
추가 호출 정책 없이 paid reviewer의 지속 운영을 선언하지 않는다.

## 사이트 구성과 실제 수용

검증된 AI 설치 receipt에서 source_commit·valid_until·admitted flags를 읽고,
기존 신뢰 SSH 접속에서 읽은 ed25519 host key를 한 줄 known_hosts로 만든다.
BrokerConfig와 host pin을 각각 digest로 고정해 root snapshot에 넣는다.
site의 `install-status-client.py`는 그 승인된 digest와 public key를 검증하고
`/etc/rosy/fleet-deliberation`에 private client를 설치한다. private key·token·
credential을 저장소나 채팅에 넣지 않는다.

서명 Fleet 후보를 배포한 뒤 source/image/profile을 읽고, 신규 실제 사용자
메시지 하나로 receipt → job/attempt → 모델 응답 → result/outbox → Discord
provider reference를 대조한다. GLM은 실제 primary의 유효한 추가 검토 사유가
있을 때만 호출한다. 임의로 문제를 CORE 막힘으로 바꾸거나 E-stop을 풀지 않는다.

## 복구

먼저 site의 status.json을 관리자 보관 경로로 옮겨 optional worker를 끄고
해당 서명 배포의 정상 복구 절차를 따른다. 기존 AI broker가 있었다면
`status.json.before-<commit>`과 `status-broker.before-<commit>`을 해당 root
목적지에 원래 그룹·mode로 복구한다(config0640, wrapper0750).
첫 설치를 끄려면 이 설치의 정확한 sshd/sudoers 파일만 `.disabled` 이름으로
보관하고 `sshd -t`·ssh reload를 수행한다. 계정·기존 AppArmor·protected
credential·spent marker·원장·버전 source는 삭제하지 않는다.
