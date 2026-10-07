# Site Link Repair Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 현장 Fleet이 TLS 로봇을 평문 `http`로 폴링해 오프라인으로 보이는 고장, 테일넷에서 닫힌 관제 8443, 꺼진 발견 광고를 이미 있는 절차로 고치고, 그 고장을 관제에서 한 단어로 보게 한다.

**Architecture:** 새 모니터·새 프로브·스킴 자동 변경은 없다. 모니터링은 D-499가 이미 정한 사이트 경로 세 줄과 로봇 링크 단어다. `protocol`의 수리는 [등록된 HTTPS 연결 설정](../../deploy/site/enrolled-tls-runbook.md)이다. 테일넷 관제는 [tailnet-remote-access.md](../deployment/tailnet-remote-access.md) 4절의 `tailscale0` 허용이다. 발견은 이미 설치돼 있는 광고 유닛 세 개를 켜는 것이다. 제품 코드를 고치기 전에 Task 1이 지금 돌고 있는 이미지와 등록 상태를 읽는다. 그 결과가 이 갈림과 다르면 현장에서 멈추고 별도 계획을 연다.

**Tech Stack:** 사이트 호스트 `robttt` (`tailscale ssh robttt@100.82.51.8`), Docker Compose 사이트 스택, systemd, 기존 Fleet SQLite `/var/lib/rosy/fleet.sqlite3`. 이 계획의 호스트 시험은 문서가 저장소에 있는지만 본다. ROS와 로봇 주행은 열지 않는다.

**기준:** [D-499](../adr/D-499-console-site-path-and-robot-link.md)는 Proposed로 둔다. 등록·재페어링은 [D-361](../adr/D-361-site-console-enrolls-robot-by-screen-code.md), 발견은 [D-452](../adr/D-452-network-peer-discovery-and-identity-targets.md), 테일넷 콘솔 허용은 D-477 런북. 2026-10-07에 적은 현장 상태(이미지 `5eb726c13271`, HTTP 폴링, 광고 유닛 꺼짐, Tailscale 8443 닫힘)는 그때의 기록이다. Task 1이 오늘 값을 다시 읽기 전에는 그 기록을 아직 참이라고 쓰지 않는다.

**작업 위치:** 워크트리 `rosy-platform/.worktrees/site-link-repair`, 브랜치 `docs/site-link-repair`. 공유 `main` 체크아웃에는 쓰지 않는다. 현장 변경(site.env, systemctl enable/restart, 스택 재시작, 릴리스 설치)은 각 태스크의 사용자 확인 뒤에만 한다. 확인 없는 태스크는 읽기만 한다. `sudo` 암호는 없다. 암호 프롬프트가 나오면 멈추고 관리자에게 넘긴다. 토큰, 로그인 코드, CA PEM, `site.env`의 비밀 값은 출력·기록·채팅에 남기지 않는다.

스크래치와 명령 출력은 `X:\DevTemp\site-link-repair\`에 둔다.

---

## 갈림

Task 1의 여섯 값을 이 표에 넣는다. 표에 없는 조합이면 Task 2에서 멈추고, 본 계획의 Task 4부터는 실행하지 않는다.

| 읽은 값 | 다음 |
|---|---|
| Fleet 이미지 안에 `fleet.server.link_class`가 없다 | 모니터가 현장 이미지에 없다. Task 3은 사용자에게 사이트 릴리스를 요청하는 데서 끝난다. 이 계획이 릴리스를 만들거나 후보 트리에서 `docker compose build` 하지 않는다 |
| `link_class`가 있다 | 관제 등록 로봇 칸에 사이트 경로 세 줄이 보여야 한다. Task 5의 확인에 그 세 줄을 포함한다 |
| `ROSY_ENROLLED_TLS_BINDINGS_FILE`이 비어 있고 `robot_enrollment_tls.origin`은 `https://`이다 | 마커는 있는데 프로세스에 바인딩이 없다. Task 4는 런북의 공개 바인딩 파일을 관리자가 넣는 길이다. HTTP로 내리지 않는다 |
| 바인딩 파일이 있고 origin이 그 파일의 `https://hostname:port`와 같다 | Task 4는 스택이 그 파일을 이미 쓰는지 확인하고, 폴링이 아직 `protocol`이면 검토된 Fleet 재시작만 한다 |
| 바인딩 파일의 hostname·port·CA 지문이 origin과 다르다 | 재시작해도 거절된다. Task 4에서 멈추고 관리자에게 보인다. DB·마커·credential key를 지우지 않는다 |
| `ROSY_SITE_LAN_IFACE`에 `tailscale0`이 없다 | Task 5 |
| 광고 유닛 셋 중 하나라도 `inactive` 또는 `failed` | Task 6 |
| 로봇 행 `state`가 `needs_new_code` | 링크 수리로 토큰을 연장하지 않는다. 관제의 기존 재등록 안내로 남긴다 |

비상 정지, 위치 추정, 바닥 IR, 램프는 이 계획의 링크 고장이 아니다. 로스터에 이미 있는 칸으로 두고 여기서 해제하거나 주행하지 않는다.

---

### Task 1: 사이트 호스트를 읽기만 한다

**Files:**
- Create: `X:\DevTemp\site-link-repair\diagnose.txt` (저장소 밖)
- Read: `deploy/site/enrolled-tls-runbook.md`, `docs/deployment/tailnet-remote-access.md`, `deploy/site/README.md`의 LAN access·Advertise and locate

**Step 1: 접속과 유닛**

운영 PC에서 Tailscale SSH만 쓴다. LAN 22는 닫혀 있다.

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' ssh robttt@100.82.51.8 -- systemctl is-active rosy-site-stack.service rosy-site-firewall.service rosy-site-firewall-check.timer rosy-fleet-advertise.service rosy-overhead-advertise.service rosy-mdns-bridge.timer avahi-daemon.service
```

Expected: 한 줄에 하나씩 `active` 또는 `inactive` 또는 `failed`. 암호 프롬프트가 나오면 멈추고 `diagnose.txt`에 `sudo-password-required`만 적는다.

**Step 2: 돌고 있는 사이트 이미지**

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' ssh robttt@100.82.51.8 -- docker ps --filter name=rosy-site- --format '{{.Names}} {{.Image}} {{.Status}}'
```

Expected: `rosy-site-proxy-1`, `rosy-site-fleet-1`, `rosy-site-vision-1`의 이미지 태그가 출력에 있다. `docker compose build`는 하지 않는다.

**Step 3: 그 이미지에 D-499 분류가 있는지**

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' ssh robttt@100.82.51.8 -- docker exec rosy-site-fleet-1 python -c "import importlib.util; print(importlib.util.find_spec('fleet.server.link_class') is not None)"
```

Expected: `True` 또는 `False` 한 단어. `ModuleNotFoundError`는 `False`와 같이 적는다.

**Step 4: 바인딩 환경과 TLS 마커**

환경 변수는 이름 하나만 출력한다. `printenv` 전체는 쓰지 않는다.

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' ssh robttt@100.82.51.8 -- docker exec rosy-site-fleet-1 python -c "import os; v=os.environ.get('ROSY_ENROLLED_TLS_BINDINGS_FILE',''); print('set' if v else 'empty')"
```

SQLite는 스킴과 상태만 읽는다. `ciphertext` 열은 고르지 않는다.

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' ssh robttt@100.82.51.8 -- docker exec rosy-site-fleet-1 python -c "import sqlite3; c=sqlite3.connect('/var/lib/rosy/fleet.sqlite3'); print('tls', list(c.execute('select robot_id, origin, length(ca_sha256) from robot_enrollment_tls'))); print('rows', list(c.execute('select robot_id, hostname, state from robot_enrollments')))"
```

Expected: `origin`은 `https://<name>.local:8080` 형태이거나 행이 없다. `ca_sha256`은 길이만 나온다. 주소 열 `address`는 이 명령에 없다. 폴링 스킴은 이 표에 없고, Task 4의 바인딩 파일이 정한다.

`/etc/rosy/site/site.env`는 `robttt`가 읽지 못한다. 읽기 시도가 거부되면 `site.env unreadable`만 적는다. `sudo cat`으로 우회하지 않는다.

**Step 5: 광고와 8443**

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' ssh robttt@100.82.51.8 -- python3 -c "import socket; s=socket.socket(); s.settimeout(3); print('lan', s.connect_ex(('192.168.1.230',8443))); s.close(); t=socket.socket(); t.settimeout(3); print('ts', t.connect_ex(('100.82.51.8',8443)))"
```

Expected: `lan 0`은 LAN에서 포트가 열린 것이다. `ts`가 0이 아니면 테일넷 경로의 8443은 닫혀 있다. 인터페이스 이름은 Task 5에서 관리자가 `site.env`로 확인한다. 이 단계에서는 iptables를 바꾸지 않는다.

**Step 6: 기록**

`X:\DevTemp\site-link-repair\diagnose.txt`에 시각, 이미지 태그, `link_class` 유무, 바인딩 환경 `set`/`empty`, TLS origin과 지문 길이, 등록 `state`, 유닛 여섯 개의 active 여부, `lan`/`ts` 숫자만 남긴다. 이 파일을 저장소에 넣지 않는다.

**Step 7: Commit**

이 태스크는 저장소 파일을 만들지 않는다. 커밋하지 않는다.

---

### Task 2: 갈림을 고르고 제품 버그면 멈춘다

**Files:**
- Modify: `X:\DevTemp\site-link-repair\diagnose.txt` (표 한 줄 추가)

**Step 1: 표를 채운다**

Task 1의 값을 위 「갈림」 표에 맞춘다. 맞는 행마다 `diagnose.txt`에 `next: task-3`처럼 적는다.

**Step 2: 제품 결함이면 멈춘다**

아래면 이 계획의 Task 4를 실행하지 않고 사용자에게 그 사실만 알린다.

- 바인딩 환경이 `set`이고 origin과 바인딩 파일의 hostname·port가 같은데, 관제 `link`가 `protocol`이다.
- `link_class`가 `True`인데 등록 로봇 칸에 사이트 경로 세 줄이 없다.

그때의 수리는 콘솔이 스킴을 바꾸는 버튼이 아니다. D-499가 그 버튼을 범위 밖으로 두었다. 등록된 base URL을 프로세스가 `https`로 올리는 기존 `EnrolledTlsBindings.endpoint`가 왜 비었는지를 별도 계획으로 연다.

**Step 3: Commit**

저장소 변경이 없다. 커밋하지 않는다.

---

### Task 3: 모니터가 없는 이미지면 릴리스를 요청만 한다

**Files:**
- Read: `docs/adr/D-499-console-site-path-and-robot-link.md`
- Read: `docs/plans/2026-10-07-console-site-path-and-robot-link.md`

**Step 1: `link_class`가 True이면 이 태스크를 건너뛴다**

현장 이미지가 이미 링크 단어를 낼 수 있다. 화면 확인은 Task 7이다.

**Step 2: False이면 릴리스 요청으로 끝낸다**

사용자에게 사이트 릴리스가 필요하다고 알린다. 릴리스 내용물은 로컬 `main`에 이미 있는 D-499 표시다. 이 브랜치에서 이미지를 빌드하거나 `/opt/rosy/candidate`를 고치거나 `docker compose build` 하지 않는다. 사용자가 릴리스를 말하기 전에는 Task 4의 재시작도 하지 않는다. 옛 이미지에 바인딩 파일만 넣고 재시작하면 그 이미지가 바인딩을 모르면 HTTP 폴링이 그대로다.

**Step 3: Commit**

저장소 변경이 없다.

---

### Task 4: 등록된 HTTPS 바인딩으로 폴링을 올린다

**Files:**
- Follow: `deploy/site/enrolled-tls-runbook.md` 전체. 이 태스크는 그 절차를 반복하지 않고 현장 값만 채운다.

사용자 확인 전에는 파일을 쓰지 않는다.

**Step 1: 공개 바인딩이 이미 있는지 확인한다**

Task 1에서 환경이 `set`이었으면 컨테이너 안의 그 경로를 읽는다. 출력은 `robot_id`, `hostname`, `port`, `tls_ca_sha256`의 길이뿐이다. PEM과 지문 64자는 채팅에 붙이지 않는다.

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' ssh robttt@100.82.51.8 -- docker exec rosy-site-fleet-1 python -c "import json,os; p=os.environ['ROSY_ENROLLED_TLS_BINDINGS_FILE']; d=json.load(open(p)); print([(r.get('robot_id'), r.get('hostname'), r.get('port'), len(r.get('tls_ca_sha256') or '')) for r in d.get('robots',[])])"
```

Expected: 등록 행의 `robot_id`·`.local` hostname과 같고, 지문 길이는 64이다. origin의 호스트·포트와 다르면 멈추고 런북의 거절 조건을 사용자에게 보인다.

**Step 2: 비어 있으면 관리자 적용을 기다린다**

런북대로 공개 JSON과 CA를 `/run/rosy-config/`에 두고 `site.env`에 다음 한 줄을 넣는 일은 관리자다. `robttt`는 `site.env`를 쓰지 못한다.

```text
ROSY_SITE_ENROLLED_TLS_BINDINGS_FILE=/run/rosy-config/enrolled-tls-bindings.json
```

예시의 `rosy_01`과 예시 지문을 그대로 넣지 않는다. `robots.yaml`에 같은 로봇을 추가하지 않는다. 광고에서 CA를 내려받지 않는다. 마커가 있는 로봇의 origin·CA를 다른 값으로 바꾸지 않는다.

**Step 3: 적용 뒤 Fleet만 다시 읽게 한다**

관리자가 환경 줄을 넣었다고 확인한 뒤에만:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' ssh robttt@100.82.51.8 -- sudo systemctl restart rosy-site-stack.service
```

Expected: 암호 프롬프트면 관리자가 실행한다. 재시작 뒤 `docker ps`의 세 컨테이너가 healthy이고, Task 1의 Step 4를 다시 했을 때 바인딩 환경이 `set`이다. 등록 행의 `state`를 이 재시작이 `active`로 바꾸지 않는다. `needs_new_code`는 그대로다.

**Step 4: 폴링이 HTTPS로 끝났는지**

D-499가 있는 이미지이면 `GET /api/fleet/state`의 해당 로봇 `link`가 `up`이다. `protocol`이면 Task 2의 제품 결함 분기로 돌아간다. D-499가 없는 이미지이면 로봇 `GET /api/v1/robot/state`가 401인지(TLS로 닿아 인증만 거절)를 로봇 쪽에서 확인하고, 평문 HTTP의 `RemoteProtocolError`와 구분한다. 토큰을 붙여 200을 만들지 않는다. 목표·모드·정지 해제는 보내지 않는다.

**Step 5: Commit**

현장 파일은 저장소에 커밋하지 않는다.

---

### Task 5: 테일넷 인터페이스를 관제 허용에 넣는다

**Files:**
- Follow: `docs/deployment/tailnet-remote-access.md` 4절
- Follow: `deploy/site/README.md` "Recovering after the port was closed"

사용자 확인 전에는 `site.env`를 고치지 않는다.

**Step 1: 관리자가 인터페이스 줄을 확인한다**

LAN 인터페이스는 2026-10-07 기록에서 `wlp0s20f3`였다. Task 1이 다른 이름을 보여 주면 그 이름을 쓴다. 런북의 예시 `wlan0`을 현장 이름 없이 복사하지 않는다.

```text
ROSY_SITE_LAN_IFACE=<Task 1의 LAN 인터페이스>,tailscale0
```

줄은 `KEY=VALUE`만 둔다. `export`를 붙이지 않는다.

**Step 2: 방화벽 유닛만 다시 적용한다**

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' ssh robttt@100.82.51.8 -- sudo systemctl restart rosy-site-firewall.service
```

Expected: 5분 점검이 지나가기 전에 재시작이 끝나 있다. 인터페이스를 바꾸고 방화벽을 재시작하지 않으면 점검이 포트를 닫는다. 실패하면 `journalctl -u rosy-site-firewall -u rosy-site-firewall-check`의 이유만 보고, 프록시가 멈췄으면 README의 복구 순서(`check` 통과 뒤 `systemctl restart rosy-site-stack`)를 관리자가 실행한다.

**Step 3: 두 경로의 8443**

Task 1 Step 5를 다시 실행한다.

Expected: `lan 0`과 `ts 0`. 브라우저 확인은 `https://<site-pc>.<tailnet>.ts.net:8443/console`이다. 포트 포워딩과 공인 주소는 만들지 않는다. 인증서는 `tls_host`로 검증한다. IP로 연 인증서 경고를 고치려고 IP SAN을 추가하지 않는다.

**Step 4: Commit**

저장소 변경이 없다.

---

### Task 6: 발견 광고 유닛을 켠다

**Files:**
- Follow: `deploy/site/README.md`의 `systemctl enable --now rosy-mdns-bridge.timer`와 advertise 유닛 절

사용자 확인 전에는 enable 하지 않는다. 유닛 파일이 `/etc/systemd/system`에 없으면 README의 설치 절을 관리자가 실행한다. 이 계획이 새 유닛을 만들지 않는다.

**Step 1: 꺼진 유닛만 켠다**

Task 1에서 `inactive` 또는 `failed`인 것만 대상이다. 예시로 셋이 모두 꺼져 있으면:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' ssh robttt@100.82.51.8 -- sudo systemctl enable --now rosy-fleet-advertise.service rosy-overhead-advertise.service rosy-mdns-bridge.timer
```

Expected: `systemctl is-active`가 세 유닛 모두 `active`. `failed`이면 `journalctl -u <unit> -n 40`의 이유를 `diagnose.txt`에 남기고, 유닛 파일을 현장에서 고치지 않는다.

**Step 2: 검색기**

호스트에서 `avahi-browse -rtpk _rosy._tcp`가 로봇 서비스 행을 한 번 보여 주면 광고는 나간 것이다. 관제 발견 패널은 **검색기 끊김**이 아니라 기기 목록이다. 45초 안에 브리지가 스캔을 못 보내면 패널이 빨강으로 남는다. 그때는 빈 스캔으로 마지막 성공을 덮어쓰지 않는다. 브리지 로그의 TLS 또는 Avahi 이유만 적는다.

**Step 3: Commit**

저장소 변경이 없다.

---

### Task 7: 관제에서 세 고장이 갈라져 보이는지 확인한다

**Files:**
- Read: `operations/fleet/fleet/server/web`의 사이트 경로 문장 (D-499 계획의 화면 문장 표)

**Step 1: LAN 콘솔**

`https://192.168.1.230:8443/console`을 연다. 사이트 CA를 믿지 않는 브라우저는 `ERR_CERT_AUTHORITY_INVALID`로 실패한다. 그 실패를 제품 결함으로 적지 않고, CA를 믿는 프로필로 다시 연다.

Expected:

- 프록시 줄은 `GET /healthz`가 200이고 본문이 `{"status":"ok"}`일 때 `정상`.
- Fleet 줄은 상태 조회가 끝나면 `정상`. 401은 토큰 안내로 남고 Fleet 끊김이 아니다.
- Vision 줄은 소스가 있으면 그 이름이다. `ceiling_north`가 있으면 그 이름을 적는다.
- `rosy_26`과 `rosy_60`의 `link`가 `up`이면 태그가 없다.
- `link`가 `protocol`이면 문장은 `등록된 base URL의 스킴으로 로봇 HTTP가 끝나지 않습니다.`이고 다음은 등록된 Fleet base URL이다. 스킴 버튼은 없다.
- 발견 패널에 **검색기 끊김**이 없다.

**Step 2: 테일넷 콘솔**

Task 5 뒤 `ts 0`인 주소로 같은 세 줄을 본다. LAN에서만 열리고 테일넷에서 안 열리면 Task 5로 돌아간다.

**Step 3: 수용으로 올리지 않는다**

호스트 시험, 화면이 열림, `link: up`은 장치 수용과 현장 수용이 아니다. 모드 변경, 정지 해제, 목표, 주행으로 이 확인을 통과시키지 않는다. D-499 Status는 Proposed로 둔다.

**Step 4: Commit**

증거 파일을 저장소에 넣지 않는다. 사용자가 기록 문서를 말하기 전에는 `docs/validation/`에 쓰지 않는다.

---

## 범위 밖

- 패킷 목록, 바이트 그래프, Docker CPU·메모리, 공유기 관리, 로봇 Wi-Fi 카드, `nmcli`.
- 콘솔이 `http`를 `https`로 바꾸는 버튼. 여섯 번째 `link` 단어. `/healthz` 본문을 세 서비스 상태로 늘리는 일.
- TLS 마커, enrollment DB, credential key를 지우는 일. 확인된 로그아웃 전의 등록 해제.
- `rosy_60` 비상 정지 해제, 위치 추정 기동, 램프, 바닥 IR 릴리스.
- D-499를 Accepted로 바꾸는 일. 로컬 `main` fast-forward. 푸시. 사이트 릴리스 빌드.
