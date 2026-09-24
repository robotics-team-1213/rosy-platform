## D-198 Docker 시대의 장치 운영면을 철거한다 — 안전 검증 게이트의 native 대체는 지금 만들고, 설치기·모드 전환은 대체 없이 폐기한다

**Status:** Accepted (2026-09-24). 잇는 결정:

- D-161: 제품 런타임은 native systemd다. Docker/Compose는 개발·CI 전용이며 제품 이미지에 설치하지 않는다.
- D-197: 제품 아티팩트 체인에서 Docker/OCI를 퇴역시키고 제품 경로의 신규 의존을 금지했다.
- D-33: 로봇 신원은 로봇 번호 하나에서 파생되며 미설정은 게이트를 닫는다.
- D-34: DDS baseline은 소비자 입장에서 잰다.
- D-179: 벤치 CORE 수정은 설치 트리 위의 읽기 전용 바인드다.
- D-164/D-173: 제품 장치는 서명된 디스크 이미지로만 만들고 첫 카드는 병합 커밋의 이미지를 고정해 굽는다.

**Context:** D-197이 빌드·릴리스 체인(`arm64_release_builder.py` → OCI → `bundle.py` → `docker image load`)을
닫았다. 그러나 장치에서 사람이 만지는 운영면이 여전히 Docker 세계에 있다.

1. **설치기:** `deploy/robot/install-pi.sh`는 download.docker.com apt 저장소에서 `docker-ce`와 compose plugin을
   설치하고, compose로 `rosy-core` 이미지를 빌드해 레거시 `rosy-runtime.service`를 enable 한다. Pi를 수동으로
   세팅하는 사실상의 유일한 경로이면서, 동시에 Docker를 장치에 심는 경로다.
2. **모드 전환:** `deploy/robot/runtime-mode.sh`는 core/motor/hardware 전환을 compose profile up/down으로 한다.
3. **레거시 유닛·스크립트:** `rosy-runtime.service`(`Requires=docker.service`), `rosy-release-runtime.service`,
   `rosy-release-recovery.service`, `rosy-release`, `release-recover.sh`.
4. **안전 검증:** `deploy/robot/verify/verify-motors.sh`의 모터 프로브 게이트는 `docker compose ps` 판정뿐이다.
   native 장치에는 docker가 없으므로 게이트가 닫힌 채 실패한다 — 오늘 native 벤치에서 이 표준 절차로 모터를
   검증할 수 없다. native 프로브 원시 도구는 이미 이미지 경로에 있다(`deploy/image/probe-io-runtime.py`,
   `deploy/image/device-python-requirements.txt`의 dynamixel 의존).
5. **검증·계측:** `deploy/robot/verify/verify-pi.sh`와 `deploy/robot/measure-dds-baseline.sh`(D-34)는 런타임
   상태와 DDS baseline을 compose ps/exec/stats로 잰다.
6. **readback:** `deploy/robot/verify/device_readback.py`는 CORE 상태를 `docker compose ps`·`docker inspect`·
   `docker exec`로 프로브한다.
7. **벤치 오버레이:** `deploy/robot/dev/core_dev_overlay.py`는 docker/native 두 backend를 가진다. native(D-179)는
   이미 완성돼 있고 docker는 compose 시절 벤치 잔존분이다.
8. **이미지 부속품:** `deploy/robot/.env.example`, `entrypoint.sh`, `requirements-core.txt`, `requirements-io.txt`는
   Dockerfile 전용이다.

native 장치는 서명 이미지(D-164)와 first-boot로만 만든다. ARTIFACT gate가 열리기 전까지 벤치에는 compose
장치와 native 장치가 함께 존재한다.

**Decision:**

1. **안전 게이트를 먼저 native로 만든다 — ARTIFACT와 무관하게 지금.** 모터 안전 검증이 Docker의 존재에 의존하는
   것은 결함이다. `verify-motors.sh`의 게이트에 systemd 판정(해당 모드 유닛의 활성 상태, 예: `rosy-io.service`)을
   추가하고 프로브는 native 설치 트리에서 `probe-io-runtime.py`와 같은 경로로 실행한다. compose 판정은 compose
   벤치가 사라질 때까지 병행 유지한다. 게이트는 닫히는 쪽으로 실패한다는 기존 원칙을 그대로 적용한다.
2. **검증·계측의 native 경로를 같은 모양으로 맞춘다.** `verify-pi.sh`는 `systemctl`의 rosy-core 상태와
   `GET /api/v1` health로, `measure-dds-baseline.sh`은 native 트리에서 `ros2 topic bw`와 host 측정으로,
   `device_readback.py`는 컨테이너 조회 대신 systemd 상태와 HTTP health로 바꾼다. readback JSON의 fail-closed
   의미는 유지하고 `container_id` 같은 컨테이너 필드는 대응하는 native 필드(유닛·설정 개정)로 바꾼다.
3. **install-pi.sh는 대체하지 않고 폐기한다.** native 장치의 유일한 출생 경로는 서명 이미지와 first-boot다.
   마지막 compose 벤치 장치를 재굽고 나면 삭제한다. 기존 compose 장치의 전환은 업그레이드가 아니라 재굽기다.
   병행 전환 도구를 새로 만들지 않는다.
4. **모드 전환의 native 소유자는 설정과 유닛이다.** `/etc/rosy`(runtime.env, rosy-config)와 `systemctl`
   (rosy-runtime.target, rosy-io, navigation)이 전환을 소유한다. `runtime-mode.sh`은 compose 래퍼이므로 폐기
   대상이고 native 래퍼를 새로 만들지 않는다.
5. **레거시 유닛·부속품은 D-197 2항의 정리 변경에 합류한다.** `rosy-runtime.service`,
   `rosy-release-runtime.service`, `rosy-release-recovery.service`, `rosy-release`, `release-recover.sh`,
   `.env.example`, `entrypoint.sh`, `requirements-*.txt` — 삭제 시점과 순서는 D-197의 순서 계약(계약 테스트
   재고정 먼저)을 따른다.
6. **dev overlay의 docker backend는 마지막 compose 벤치가 사라질 때 삭제한다.** native backend(D-179)가
   이미 표준이다.
7. **이 운영면을 고정하는 계약 테스트도 같이 옮긴다.** `test_device_readback.py`의 docker 모형,
   `test_pi_wifi_deployment.py`의 install-pi/compose 가정, 그리고 D-197 3항의 `test_dds_identity_contracts.py`·
   `test_dds_rmw_contracts.py` 고정 대상 — native 표면으로 먼저 옮기고 나서 해당 파일을 지운다.

**Consequences:**

- native 벤치에서 표준 절차로 모터를 검증할 수 있게 된다. 오늘은 compose 장치에서만 가능하다.
- compose 벤치가 존속하는 동안 검증 스크립트가 이중 경로를 가진다. 이 유지비를 명시적으로 수용한다.
- compose 장치는 재굽기로만 native가 된다.
- D-197의 트리거(native payload ARTIFACT 통과)와 이 결정의 트리거(마지막 compose 벤치 소멸)는 독립적으로
  도래하고, 둘 다 채워야 Docker 파일이 실제로 사라진다.
- install-pi.sh가 사라지면 Docker가 장치에 들어오는 공식 경로는 없다 — D-161 금지사항의 실행 완료다.
