# 후보 토론 호스트 격리 오류 해결과 관리자 적용

- Contract: D-640, D-672, D-516.
- Branch: `fix/deliberation-host-admission`.
- Scope: 전용 호스트 프로파일 설치, 실제 오프라인 격리 확인, scope 정리 readback. Discord·CORE·운영 모델 활성화는 별도 소유자다.

## 확인한 원인과 수정

Model PC와 AI PC에서 bwrap 0.9.0, systemd 255를 확인했다. 커널 audit는 `unprivileged_userns` 프로파일이 bwrap의 `setpcap`·`net_admin`을 거절함을 보여 준다. 단순 패키지 설치나 `unprivileged_userns_clone=1`만으로 해결되지 않는다. 두 접속 계정의 `sudo -n`은 관리자 암호를 요구하므로 적용은 아직 수행하지 못했다.

[Ubuntu 공식 정책](https://documentation.ubuntu.com/release-notes/24.04/#unprivileged-user-namespace-restrictions)에 따라 전용 실행 파일의 AppArmor userns 프로파일을 제공한다. 전역 sysctl을 바꾸지 않는다. `/usr/local/libexec/rosy-deliberation/bwrap`와 그 디렉터리는 root 소유, 전용 계정 그룹에만 `0750`으로 제공한다. 일반 로그인 계정에 namespace 예외를 주지 않는다.

`deliberation_install`은 root로 기존 배포판 bwrap의 SHA256을 확인하고, 고정 system 계정 `rosy-deliberation`·nologin·단독 그룹을 생성/검증한다. 기존 계정·파일의 내용이나 권한이 다르면 덮어쓰지 않고 HOLD다. 프로파일을 적재하고 그 계정의 user manager만 준비한다. 제공자·Fleet 서비스·장치 명령을 시작하지 않는다.

실제 systemd가 이미 수집한 scope의 kill은 exit 1을 반환했다. `cleanup_scope`는 종료 코드에 의존하지 않고 `LoadState=not-found`를 확인한 경우에만 정리 완료로 인정한다. 다른 서비스나 `--all`은 입력 단계에서 거절한다.

## 적용과 검증

운영 숙고 실행은 D-516에 따라 AI PC가 맡는다. Model PC는 독립 평가·학습을 맡으며 같은 도구의 오프라인 검증을 운영 추론 활성화로 해석하지 않는다. 선행 계획의 실행 호스트 선택 문구보다 이 역할 계약을 우선한다.

검증된 소스 checkout의 루트에서 AI PC 관리자가 한 번 실행한다. 아래 pin은 두 PC에서 읽어 확인한 배포판 bwrap 값이다. 설치 파일 원문과 digest가 바뀌면 새 값을 검수하고 입력하며 묵시적 업데이트하지 않는다.

```bash
sha256sum /usr/bin/bwrap
sudo python3 -m deploy.site.deliberation_install --bwrap-sha256 e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71
sudo install -d -o root -g root -m 0755 /opt/rosy-deliberation/deploy/site
sudo install -o root -g root -m 0644 deploy/site/deliberation_install.py deploy/site/deliberation_sandbox.py deploy/site/deliberation_preflight.py /opt/rosy-deliberation/deploy/site/
cd /opt/rosy-deliberation
sudo -u rosy-deliberation env XDG_RUNTIME_DIR=/run/user/$(id -u rosy-deliberation) python3 -m deploy.site.deliberation_preflight
```

위 staging은 검증된 세 코드 파일만 root 소유 경로에 둔다. `/opt/rosy-deliberation`이 이미 다른 용도로 사용 중이면 덮어쓰기 전에 중단하고 소유자를 확인한다. 개인 홈을 열어 주거나 운영 자격 증명을 복사하지 않는다. 관리자 암호는 현장 관리자 터미널에서 입력한다.

설치 후 그룹 가입 등 계정 상태가 바뀌면 preflight도 설치와 동일한 읽기 전용 불변식 검사를 통해 HOLD한다. preflight는 계정을 생성하거나 변경하지 않는다.

preflight는 전용 계정·파일 권한, namespace 분리, 빈 환경·호스트 경로 비노출·cap 제거·읽기 전용 runtime·loopback만 있는 네트워크, systemd와 실제 kernel cgroup 한계를 확인한다. 별도 세션에서 실제 살아 있는 자식의 PID와 해당 cgroup을 관측한 다음, 취소와 시간 초과 각각에 대해 자식 종료 및 빈 cgroup을 확인한다. 자식이 실행되지 않았거나 readback이 부족하면 PASS할 수 없다.

`PASS_HOST_OFFLINE_ONLY`는 호스트의 오프라인 실행 경계만 뜻한다. 실제 CLI·모델 ID·최소 제공자 접속·인증·비용 제한·JSON envelope·팀의 독립 정답과 정확도/지연 한계가 확인돼야 다음 후보 모델 smoke를 진행한다. 사람 검수 이름·한계 값을 만들어 넣거나 이 receipt로 FIELD를 승격하지 않는다.

## 후속 수용 순서

현재 결과: 팀 관리자 설치 및 수정 후 재검사에서 13개 검사 모두 true, PASS_HOST_OFFLINE_ONLY다. 로컬 Qwen 실제 호출과 기존 Supervisor의 관측 부족 HOLD까지 확인했다. [실제 증거](../validation/deliberation-host-admission-2026-10-12/local-qwen-smoke.md)를 기준으로 다음 제공자 수용을 진행한다. 앞의 sudo 불가/초기 HOLD는 당시 진단 기록이며 현재 HOST 결과를 대체하지 않는다.

AI PC의 관리자 적용 후 첫 실제 probe에서 나머지 12개 경계는 true였지만 `PWD`가 허용 목록에 없어 환경 검사만 HOLD였다. 실제 진단의 변수 이름은 HOME·LC_CTYPE·PATH·PWD였고 HOME/PATH는 고정값과 일치했다. 보정은 PWD를 `/tmp`로 제한하고 PATH도 고정값을 검사한다. 수정된 preflight의 실제 HOST 성공은 별도 재실행 결과로 확인한다.

1. source 회귀·독립 코드 검토 후 로컬 main에 병합한다.
2. AI PC 관리자가 설치를 적용하고 preflight readback을 남긴다.
3. 고정 공급자·모델 프로파일과 의존성을 stage한 뒤 실제 CLI version/envelope를 확인한다. 외부 인증·네트워크 접속은 승인된 경로만 추가한다.
4. 팀이 검수한 Pinky 사건 정답과 평가 한계로 기존 rules/single/deliberation 재생을 수행한다. 이전에 합의한 관측 부족·위험 누락·다른 사건 조치·정상 불필요 명령 0건 조건을 유지한다.
5. shadow·제한 장치·현장 수용을 각각 확인한다. 자동 실행·자동 학습 승격은 아직 활성화하지 않는다.
