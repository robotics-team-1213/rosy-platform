# 업데이트 운영 CLI (`tools/remote/update_ops.py`) 설계 — 2026-11-02

상태: Accepted (2026-11-02 사용자 승인). 결정 기록은 [D-957](../adr/D-957-update-ops-cli.md). 실행 계획·레저는 작업 공간 `Rosy/docs/superpowers/plans/2026-11-02-update-ops-cli-plan.md`.

## 1. 의도와 배경

자동 업데이트는 이미 전 표면에 존재한다(로봇 D-412, 사이트 D-441, 모델 PC D-446, PC 서비스군 D-805/D-871). 없는 것은 **운영자의 즉시 트리거와 일시중지를 표면마다 다른 명령으로 기억해야 한다는 점**이다. 로봇은 `rosy_auto_update.py`, 사이트는 `/usr/local/lib/rosy-site/rosy_site_autoupdate.py`, PC 유닛은 `systemctl --user`, 잠금은 각기 다른 형식(로봇 ≤168h, 사이트 무기한, PC 유닛은 타이머 disable뿐이고 사유 기록 없음).

하나의 CLI로 이 운영 동작을 구조화한다. 2026-11-02 사용자 결정: 범위 **전체 표면**, 강제 = **즉시 시도·게이트 유지**, 주기 = **현행 유지**.

## 2. 목표

- 모든 업데이트 채널에 동일한 동작 4개 + 사이트 전용 1개: `status` / `run-now` / `hold` / `resume` (+ `forget-failed <tag>`)
- `run-now`는 타이머 대기만 건너뛴다. 유휴·배터리·서명·freeze 게이트는 각 표면의 기존 판정이 그대로 권한을 가진다.
- 대상 해석은 기존 정본만 사용: 로봇 = `lab_hosts.robots()`(SD 등록 + `private/lab-hosts.json`), 호스트 역할 = `lab-hosts.json` + `deploy/hosts/services.yaml`(`channel: updater` 유닛)
- PC 유닛 홀드의 who/why를 운영 PC 장부(`private/update-holds.json`)에 기록 — 호스트에는 상태가 없으므로
- 호스트 측 코드 변경 0줄. 이미 설치된 CLI·systemd 유닛을 SSH로 호출하기만 한다.

## 3. 비목표 / 반목표

- 게이트 우회(유휴 무시·배터리 무시 강제 적용) — D-412 eligibility 약화. 필요해지면 별도 ADR + 독립 안전 검토
- Fleet 콘솔의 조작 버튼 — D-871(2026-10-26 개정)이 명시적으로 보류. 이 CLI는 개발/운영 PC 경로일 뿐 그 결정을 되살리지 않는다
- 타이머 주기·정책 변경 — 전 현행 유지
- 서명 PC(Windows 예약작업 `RosySiteAutoSign`) 제어 — 수동 `Disable-ScheduledTask` 유지
- 3개 업데이트 엔진(site/robot/omx) 공통화 리팩터링
- 이전 버전으로 강제 다운그레이드 — 모든 표면이 forward-only + rollback-previous 설계

## 4. 접근법

| 안 | 내용 | 판단 |
|---|---|---|
| **A (채택)** | 운영 PC의 얇은 SSH 래퍼 `update_ops.py`. services.yaml을 유닛 목록 정본으로 재사용 | 호스트 코드 0줄, 기존 검증된 명령 경로만 사용, 위험 최소 |
| B | 각 호스트에 통합 run-now/hold CLI 설치 | 안전 크리티컬 호스트 코드 전면 수정, 이점 없음 |
| C | Fleet UI에 조작 버튼 | D-871 보류 결정 번복 필요 + Fleet에 GitHub 토큰 문제 재발 |
| D | 공통 업데이트 엔진 추출 | 대규모 재작성, 사용자 가시 기능 0 |

## 5. 동작 설계

### CLI 형태

```
python tools/remote/update_ops.py targets                     # 대상 해석만 출력 (read-only)
python tools/remote/update_ops.py status   <selector>
python tools/remote/update_ops.py run-now  <selector>         # 즉시 1회 시도
python tools/remote/update_ops.py hold     <selector> --reason R [--hours H]
python tools/remote/update_ops.py resume   <selector>
python tools/remote/update_ops.py forget-failed site <tag>    # 사이트 전용
```

- `selector`: `all` | `robots` | `site` | 로봇 이름(예: `pinky01`) | SSH 대상(`user@host`)
  - `site` = site_host의 모든 채널(스택 + 공존하는 omx/site-tools 유닛 포함)
  - `--unit <이름>` 옵션으로 호스트 내 특정 업데이터 유닛으로 좁힌다
- 각 ssh 명령은 실행 전에 그대로 출력(투명성). exit: 0 성공, 1 대상 실패/도달 불가, 2 사용법·selector 오류

### 표면별 동작 매핑 (구현의 정본)

| 표면 | 대상 해석 | run-now | hold | resume |
|---|---|---|---|---|
| 로봇 | `lab_hosts.robots()` | `sudo -n systemctl start rosy-auto-update.service` | `sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py hold --holder <id> --reason R --hours H` (1≤H≤168, **필수**) | `... release-hold` |
| 사이트 스택 | `site_host` | `sudo -n systemctl start rosy-site-autoupdate.service` | `sudo -n /usr/bin/python3 -I /usr/local/lib/rosy-site/rosy_site_autoupdate.py hold 'R'` (무기한) | `... resume` |
| PC 유닛 업데이터 | 역할 호스트 + services.yaml `channel: updater`·`run: oneshot` | `systemctl --user start <unit>` | `systemctl --user disable --now <unit>.timer` + 장부 기록 | `systemctl --user enable --now <unit>.timer` + 장부 삭제 |

- 유닛 집합(현재 services.yaml 기준): model=`rosy-model-code-update`, `rosy-review-release-update` / ai=`rosy-situation-autoupdate` / site=`rosy-site-tools-autoupdate` / omx=`rosy-omx-autoupdate`, `rosy-omx-devices-autoupdate`. `run: off`(retired)는 자동 제외
- `status`: 로봇은 `rosy_auto_update.py status --json`, 사이트는 `rosy_site_autoupdate.py status`, PC 유닛은 `update_status.py`의 PROBE·parse 재사용 + 장부 병합
- 로봇 hold의 `--hours`는 로봇 대상만 포함된 선택자에서만 허용(혼합 선택자와 함께 쓰면 오류)
- **hold와 run-now는 독립**: PC 유닛 hold는 타이머만 막는다. hold 상태에서 `run-now`를 치면 경고 줄과 함께 1회 실행된다(hold는 게이트가 아니라 주기 차단이므로). 로봇·사이트의 네이티브 hold는 업데이터 `run` 안에서 스스로 skip한다.

### 홀드 장부

`private/update-holds.json`(gitignored, D-226 기기 운영 상태): `{ "<host>|<unit>": {"reason", "holder", "at"} }`. hold에서 기록, resume에서 삭제. `status`는 장부와 live 타이머 상태를 **둘 다** 보여주고 추측하지 않는다(장부 없이 꺼진 타이머는 `OFF`로 표시). holder 기본값 `사용자@PC`, `--holder`로 덮어쓰기.

### SSH

- `ssh -o BatchMode=yes -o ConnectTimeout=15`(update_status.py와 동일)
- 로봇은 `rosy-update-hold.ps1`과 같은 경로: `%LOCALAPPDATA%\Rosy\ssh\rosy-operator-ed25519` 키 + `%LOCALAPPDATA%\Rosy\known_hosts` 핀, 대상은 user 접두 없으면 `rosy@` (sudoers `60-rosy-operator`는 `rosy ALL=(ALL) NOPASSWD:ALL`로 first-boot가 쓰고 `test/test_sd_operator_access.py`가 고정 — 원격 sudo 증명됨)
- 모든 원격 sudo는 `-n`(프롬프트 없이 실패). 사이트 ops 사용자의 sudo 권한은 README 고정 경로 사용, 권한 범위는 현장 확인

## 6. 테스트

`test/test_update_ops.py`(fake ssh runner 주입):
- selector 해석(robots/site/host/all, `--unit` 필터) — fake lab-hosts
- 표면별 명령 매핑 문자열 그대로 고정
- 로봇 `--hours` 검증(범위 밖·혼합 선택자 거부), reason/holder charset(rosy-update-hold.ps1 계약)
- 장부 쓰기/삭제/병합, 장부 없는 disable 타이머 표시
- services.yaml 읽기 재사용 시 `test_update_status.py` 회귀

시험은 원격 시험 PC에서만(D-584). 호스트 pytest 통과는 실장치·현장 수용을 대신하지 않는다.

## 7. 남는 확인

- 로봇 업데이트 유닛명 `rosy-auto-update.service` 실물 확인(시험은 유닛 매핑 문자열만 고정)
- 사이트 ops 사용자 sudo 범위 현장 확인
