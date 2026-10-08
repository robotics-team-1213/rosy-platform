## D-524 Service Control. 관제는 사이트·AI·모델 Ubuntu의 재부팅과 허용된 서비스만 제어한다

**Status:** Proposed (2026-10-08, 사용자 지시 — 재부팅과 서비스 오류 복구는 관제 안의 관리 API. 이 브랜치에 구현. 현장 설치와 실제 재부팅은 아직 하지 않음)

**이름:** Service Control. 화면의 한국어 이름은 서비스 제어. Rosy Fleet 안의 기능이고, 새 앱이 아니다.

## 배경

- 사이트 관제(Rosy Fleet, `console`)가 로봇 모니터링을 이미 소유한다. 호스트를 재부팅하거나 서비스를 세우는 일은 그 관제 안에 둔다. 새 앱·새 로그인·새 서버는 만들지 않는다.
- 대상은 Ubuntu 세 대다. `site`는 관제 PC, `ai`는 AI PC, `model`은 모델 PC다. 로봇은 대상이 아니다.
- 세 계정 모두 일반 비밀번호 없는 sudo가 없다. 관제 프로세스는 Docker 안에 있고, 도우미가 설치되기 전에는 호스트를 재부팅할 수 없다.
- `pkill`에 프로세스 이름을 넘기면 ssh와 관제 프로세스까지 멈출 수 있다.

## 결정

1. **조작은 운영자 API 하나다.** `GET /api/fleet/hosts`는 호스트·동작·유닛 목록이다. `POST /api/fleet/hosts/{host}/control` 본문은 `{action, unit, operator_confirmed:true}`이고 추가 필드는 거절한다. `operator_confirmed`가 true가 아니면 거절한다.
2. **동작은 닫힌 집합이다.** `reboot`, `cancel-reboot`, `restart-unit`, `stop-unit`만 받는다. `pkill`, `kill`, 시그널, 셸 문자열, 프로세스 이름은 `UNKNOWN_ACTION`이다.
3. **재부팅은 10분 뒤다.** 도우미는 `shutdown -r +10`만 호출한다. `cancel-reboot`는 `shutdown -c`다. 전원을 바로 끊지 않는다.
4. **유닛도 닫힌 집합이다.** `site`는 `docker.service`, `rosy-site-stack.service`, `rosy-site-firewall.service`. `ai`는 Pinky 사용자 유닛 여섯 개(`pinky-backend`, `pinky-frontend`, `pinky-nav2`, `pinky-rosbridge-d12`, `pinky-rosbridge-d13`, `pinky-r2-watch`). `model`은 유닛이 없다. 학습 프로세스는 systemd 유닛이 아니라 여기서 멈추거나 다시 시작하지 않는다. 다른 유닛은 `UNIT_NOT_ALLOWED`다.
5. **실행은 로컬 도우미만 한다.** `deploy/site/rosy-host-control`은 인자 목록으로만 `shutdown` 또는 `systemctl`을 호출한다. 셸을 거치지 않는다. `ROSY_HOST_CONTROL_HELPER`의 파일 이름이 `rosy-host-control`이고 `ROSY_HOST_CONTROL_ROLE`이 그 호스트일 때만 Fleet이 호출한다. 아니면 503 `HOST_HELPER_UNAVAILABLE`이다. 다른 호스트는 409 `HOST_NOT_LOCAL`이다. Fleet은 SSH로 재부팅하지 않는다.
6. **AI 유닛은 그 사용자의 systemd다.** 도우미는 `systemctl --user --machine=ai@`만 쓴다.

## 범위 밖

- 관제 화면 버튼. API가 먼저다.
- 세 PC에 도우미를 설치하거나 sudoers를 넣는 일.
- 로봇 재부팅, Docker 컨테이너 이름, 임의 프로세스 종료.
- 모델 PC의 학습 프로세스를 멈추는 일.

## 검토한 대안

- 관제에서 `pkill` 패턴을 그대로 실행한다. 프로세스 이름 하나로 ssh와 Fleet을 멈출 수 있어 거절했다.
- 에이전트가 SSH로 `reboot`를 호출한다. 운영 경로는 이 API로 둔다.
