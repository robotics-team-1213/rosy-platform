---
title: Fleet 배포는 등록·카메라·이름 해석·시작 조건을 함께 검증한다
date: "2026-10-03"
category: workflow-issues
module: site Fleet deployment
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "Fleet 이미지나 로봇 목록을 운영 사이트에 적용할 때"
  - "기존 동적 등록 또는 카메라 설정을 유지하며 mDNS를 개선할 때"
  - "설치 성공을 자동 연결이나 재부팅 검증으로 보고할 때"
tags: [fleet, deployment, enrollment, mdns, avahi, camera, preflight, verification]
---

# Fleet 배포는 등록·카메라·이름 해석·시작 조건을 함께 검증한다

## Context

2026-10-03 사이트 이름 해석을 개선하는 과정에서 정적 로봇 목록까지 교체한 설치가 실패했다. Fleet는 기존 카메라의 알 수 없는 대상 때문에 종료했고 외부 HTTPS는 `502 Bad Gateway`를 반환했다. 이미 동적으로 등록한 로봇을 정적 목록에도 넣은 후보는 `ROBOT_ID_CONFLICT`로 실패했다. 로컬에서 빌드한 이미지에 레지스트리 pull을 적용한 별도 단계는 `pull access denied`로 실패했다.

이미지 빌드, 호스트 mDNS, 개별 YAML 파싱이 성공해도 실제 Fleet 시작을 보장하지 않는다. 운영 배포는 이미지·명령·정적 설정·등록 저장소·카메라 대상·호스트 서비스가 함께 구성하는 실행 단위다.

## Guidance

### 실제 시작 구성을 먼저 검증한다

- 정적 목록과 저장된 동적 등록의 출처를 구분한다. `EnrollmentService.load()`는 등록 저장소와 복호화 자격이 사용 가능할 때 종료 대기 등록을 제외한 저장 행을 roster에 복원하고, roster는 기존 ID와의 충돌을 거절한다. 유효한 등록을 정적 목록에 복사하지 않는다.
- Fleet CLI의 최종 명령과 모든 overlay를 확인한다. 후보의 실제 CLI를 격리된 환경에서 시작해 인증 API와 예상 로봇 목록까지 확인한다. DB 검증이 필요하면 기존 앱의 정상 접근 경로에서 읽기 전용 원본의 일관된 백업을 만들고, 후보 전용 저장 공간에서 검증한다. 운영 DB나 등록 자격을 직접 수정하지 않는다.
- 같은 카메라 YAML을 소비해도 계약은 다르다. Fleet는 marker key가 `robot_ids`의 부분집합인 것을 허용하고 Vision은 두 집합의 일치를 요구한다. Fleet CLI는 등록·retired 상태를 고려하며 임의의 unknown target을 거절한다. 한 parser 통과를 다른 서비스의 시작 증거로 사용하지 않는다.
- 카메라의 기존 marker를 새 로봇에 추측으로 배정하지 않는다. 별도의 Fleet sightings 설정을 사용하는 후보라면 원래 Vision 설정·물리 marker·좌표를 보존하고 양쪽 parser와 실제 시작을 각각 검증한다. 위치 commissioning 전에는 영상 수신만 증명된 것으로 보고한다.

### 프로세스가 실제 사용하는 이름 해석을 확인한다

호스트 Avahi가 `.local`을 찾는 것과 컨테이너 NSS가 찾는 것은 별개다. Fleet 이미지의 `libnss-mdns`, `/etc/nsswitch.conf`, Compose의 호스트 `/run/avahi-daemon` 읽기 전용 **디렉터리** bind를 함께 확인한다. 디렉터리 bind는 Avahi가 socket을 교체해도 새 경로를 사용할 수 있다. `create_host_path: false`로 누락된 디렉터리를 빈 경로로 생성하지 않는다.

실행 UID로 Python `socket.getaddrinfo` 또는 `getent`를 사용해 로봇 `.local`과 Docker 내부 서비스 이름을 모두 확인한다. `nslookup`은 NSS 경로 검증을 대신하지 않는다. Avahi 없는 대조군과 socket 교체 후 재해석도 확인한다. 주소 발견을 TLS 신뢰로 취급하지 말고 원래 hostname과 CA 검증을 유지한다.

광고 파일은 Avahi가 읽을 수 있어야 한다. 관리자 광고가 고장 난 사이트에서 사용자 서비스로 복구할 때는 기존 linger, 광고 중복 방지, token 권한, timer 주기와 발견 lease를 함께 확인한다. 사용자 timer나 stack이 한 번 실행된 사실과 enabled 상태, Avahi 뒤의 시작 순서, 실제 PC 재부팅 성공은 각각 다른 증거다.

### 권한과 정지 증거를 별도로 다룬다

Fleet 운영자 인증과 OS sudo 인증은 서로 다른 권한이다. 운영자 토큰을 찾았다고 관리자 파일 쓰기가 가능해지는 것은 아니다. 현재 허용된 경로에서 자격을 확인하고 비밀값을 출력하지 않는다. SSH에 OS 권한이 없으면 검토·후보 검증을 먼저 끝낸 뒤 실제 관리자 인증이 필요한 명령만 사용자 터미널에 요청한다. Docker의 호스트 root mount나 직접 DB 수정으로 권한 경계를 우회하지 않는다.

이번 Fleet 유지보수 검사에서는 `MANUAL`이라는 이유만으로 정지한 로봇을 보류한 조건을 수정했다. 허용 조건은 최신 online readback, zero velocity, navigation IDLE, activity 없음, line/swarm 작업 없음, Fleet goal/queue/yield/hold 없음, E-Stop 없음을 함께 확인하는 것이었다. 모드 하나로 정지나 작업 부재를 추정하지 않는다. 알 수 없거나 오래된 필드는 보류하며 파일 변경 전과 재시작 직전에 다시 검사한다. 별도 teleop lease API를 확인하지 못한 경우 모든 lease가 비활성이라고 보고하지 않는다.

이 조건은 해당 유지보수 검사에 한정한다. G3 commissioning은 별도의 IDLE·asserted E-Stop·zero velocity 계약을 갖는다. 배포 검사를 통과시키기 위해 E-Stop을 해제하거나 이동 명령을 보내지 않는다.

### 설치 명령의 의미와 검증 경계를 남긴다

로컬 이미지에는 실제 존재하는 태그·immutable image ID·pull/build 정책을 확인한다. `docker compose build` 성공 다음에 레지스트리 pull이 성공할 것이라고 가정하지 않는다. 실패 시 원래 설정과 이미지 복구뿐 아니라 서비스 시작과 인증 API 복구도 확인한다. 재시작 전 실패에는 불필요한 서비스 재시작을 추가하지 않는다.

설치 결과 문자열과 별도로 실제 image ID, 변경 파일의 hash, 유지된 등록·카메라, TLS API, 최신 online state, 발견 conflict, 카메라의 증가하는 frame sequence·서로 다른 JPEG를 읽는다. 관제 PC는 현재 운영 사이트로 식별하며 개발 PC나 다른 연결 태블릿을 대신 사용하지 않는다.

## Why This Matters

필요한 변경에 등록·marker 교체까지 섞으면 DNS 개선이 서비스 전체 장애가 된다. 이번에 운영 설치가 검증된 NSS 전용 수정은 기존 roster·카메라·동적 자격을 보존하고 Fleet만 재생성했다. 설치 후 실제 실행 UID의 이름 해석과 두 등록 로봇의 online readback을 확인했다. Fleet 재시작 뒤 S21에서 새 JPEG 세 장의 증가하는 sequence와 서로 다른 hash도 확인했다.

이 증거로 레거시 정적 항목의 발견 conflict 해소, 관제 PC 전체 재부팅, outbound 로봇 FleetAgent 설정, marker 기반 위치 산출까지 완료했다고 말할 수 없다. 이 문서를 기록한 시점에는 후속 설정 정리와 boot ordering 적용이 별도의 설치 단계였고, PC 재부팅 및 위치 commissioning은 검증되지 않았다. 이후 완료 여부는 최신 설치 receipt와 실제 readback으로 갱신한다.

## When to Apply

- 기존 운영 사이트에 이미지·DNS·discovery·로봇 목록 변경을 적용할 때.
- 동적 등록과 정적 구성 또는 Fleet와 Vision이 동일한 설정을 참조할 때.
- 자동 실행 설정, 실제 재부팅, 연결 성공, 물리 동작 수용을 구분해 보고할 때.

## Examples

| 변경 전 시도 | 다음 실행에서 확인할 조건 |
|---|---|
| 로봇 목록만 교체하고 `/healthz`를 기다림 | 동적 등록 복원과 camera 대상 검증을 포함한 후보 CLI 시작·인증 API |
| 동적 등록 ID를 정적 목록에도 기입 | ID의 출처와 중복 검사, 기존 sealed 자격 보존 |
| 호스트에서 이름 해석됨 | 실제 Fleet UID의 NSS, 내부 DNS, Avahi socket 교체 대조 |
| `MANUAL`이면 무조건 설치 보류 | 해당 유지보수 계약에 따른 최신 정지·작업·interlock 증거 |
| `installed`가 나오면 자동 복구 완료 | 실제 설정·image·연결 readback, enabled/순서 확인, 수행한 재부팅만 보고 |

## Related

- [등록 복원](../../../src/site/fleet/fleet/server/enrollment.py), [roster 충돌](../../../src/site/fleet/fleet/server/roster.py), [실제 시작 CLI](../../../src/site/fleet/fleet/cli.py).
- [Fleet sightings parser](../../../src/site/fleet/fleet/server/sightings_config.py), [Vision parser](../../../src/site/vision/rosy_vision/vision_config.py).
- [Fleet 이미지](../../../deploy/site/Dockerfile.fleet), [Compose](../../../deploy/site/compose.yaml), [사용자 discovery installer](../../../deploy/site/install-user-discovery.py), [사이트 운영 절차](../../../deploy/site/README.md).
- [별도 commissioning 계약](../../../deploy/robot/pinky_pro/commissioning_session.py).
- [이름과 CA를 고정하고 주소를 발견하는 사이트 클라이언트](../design-patterns/site-clients-pin-the-site-by-name-and-resolve-by-mdns-2026-10-01.md): 클라이언트 연결의 설계 원칙이며 이 문서는 Fleet 배포의 일관성과 검증을 다룬다.
- [확인 불가를 성공으로 기록하지 않는다](inability-to-check-recorded-as-clean-result.md).
