## D-957 업데이트 운영 CLI — 운영자는 즉시 시도·일시중지를 하나의 명령으로, 게이트는 그대로

**Status:** Accepted (2026-11-02, 사용자 결정: 범위 전체 표면, 강제 = 즉시 시도·게이트 유지, 자동 주기 현행 유지). 구현·원격 시험은 이 변경과 같이, 실장치 수용은 별개다.

잇는 결정: [D-412](D-412-robot-self-update-signed-releases.md)(로봇 자동 갱신) · [D-441](D-441-site-autoupdate.md)(사이트 자동 갱신) · D-446(모델 PC 코드) · [D-805](D-805-host-update-channels-and-site-freeze.md)(갱신 채널·freeze) · D-871(전 호스트 자동 갱신·읽기 전용 뷰) · D-852(services.yaml 단위 선언) · D-584(원격 시험)

### Context

자동 갱신은 전 표면에 이미 존재한다. 없는 것은 운영자 동작의 구조다. 즉시 트리거와 일시중지가 표면마다 다른 명령(`rosy_auto_update.py`, `/usr/local/lib/rosy-site/rosy_site_autoupdate.py`, `systemctl --user`)이고 홀드 형식도 제각각이다(로봇 ≤168h 상태 파일, 사이트 무기한 상태 파일, PC 유닛은 타이머 disable뿐이라 누가 왜 멈췄는지 기록이 없다). D-871은 Fleet 콘솔의 조작 버튼을 보류했다.

### Decision

1. **운영 PC의 얇은 SSH 래퍼** `tools/remote/update_ops.py`를 둔다. 동작은 `status` / `run-now` / `hold` / `resume` (+ 사이트 전용 `forget-failed`). 호스트 설치·호스트 코드 변경은 없다.
2. **대상 해석은 기존 정본만 재사용한다.** 로봇은 `lab_hosts.robots()`(SD 등록 + `private/lab-hosts.json`), 호스트 역할은 `lab-hosts.json` + `deploy/hosts/services.yaml`의 `channel: updater`·`run: oneshot|timer` 유닛.
3. **`run-now`는 타이머 대기만 건너뛴 즉시 1회 시도다.** 유휴·배터리·서명·freeze 게이트를 우회하지 않는다. 각 표면의 기존 판정·헬스 게이트·롤백이 그대로 권한을 가진다. 게이트를 무시하는 강제 적용, 이전 버전 다운그레이드, Fleet 콘솔 조작 버튼, 서명 PC 예약작업 제어는 이 결정의 범위 밖이다.
4. **홀드는 표면 네이티브를 우선한다.** 로봇은 `rosy_auto_update.py hold --hours`(≤168), 사이트는 `rosy_site_autoupdate.py hold`(무기한). PC 유닛은 타이머 disable + 운영 PC 장부 `private/update-holds.json`에 holder·사유·시각을 기록한다.
5. **hold와 run-now는 독립이다.** hold는 주기 차단이지 게이트가 아니다. hold 중 `run-now`는 경고 줄과 함께 1회 실행되고, freeze 중 `run-now`도 경고 후 진행한다(ExecCondition이 어차피 skip).

### Consequences and validation

- 원격 sudo·SSH 키 경로는 이미 증명된 경로(로봇 `60-rosy-operator`, 사이트 README 고정 경로, `rosy-update-hold.ps1` 패턴)만 쓴다.
- 시험: `test/test_update_ops.py`(fake ssh 주입 — selector 해석, 표면별 명령 매핑 문자열 고정, 로봇 `--hours` 검증, 장부 쓰기·삭제·병합). 원격 pytest(D-584) 통과는 실장치·현장 수용을 대신하지 않는다.
- 설계 문서: `docs/plans/2026-11-02-update-ops-cli-design.md`
