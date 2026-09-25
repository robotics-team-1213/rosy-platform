## D-246 런타임 유연성 — 네이티브가 기본값이고 컨테이너는 선언된 비안전 워크로드에만, 장치별 차이는 profile/slice로만

**Date:** 2026-09-25

**Status:** Accepted

**Context:** D-161과 D-197/D-198은 제품 런타임을 Ubuntu Server 24.04 arm64 + native ROS 2 Jazzy
systemd로 못 박았고, D-197은 제품 아티팩트 체인의 신규 Docker 의존을 금지했다. 그러나
`docs/architecture/15_ROSY_Ubuntu_Modular_Installation.md` §2는 "Docker optional" 한 줄만 적어 있어
읽는 사람에 따라 "제품 로봇에 Docker를 써도 된다"로 읽힌다. 반대로 리소스 예산이 완전히 다른 장치
(가벼운 lite 로봇 vs GPU/AI 박스)를 한 문장으로 묶는다. 요구는 "필요한 장치에만 Docker CE를 깔고
그렇지 않은 장치는 네이티브로 돌리는 유연성"이다.

그 유연성을 "로봇 한 대가 Docker/네이티브를 고르는 런타임 스위치"로 두면 세 비용이 생긴다.

1. **Docker 데몬이 모터 UART 앞에 선다.** `docs/solutions/workflow-issues/inability-to-check-recorded-as-clean-result.md`가
   기록했듯 모터 preflight는 docker가 없어서, compose 파일이 읽히지 않아서 실패했고 그때 UART는
   한 번도 못 건드렸다. "모터 런타임이 꺼져 있는 게 맞나?"를 확인하기 위해 데몬 하나를 더 신뢰해야 한다.
2. **증거 체인이 갈라진다.** device readback, commissioning G0-G5, release activation은 한 런타임
   모델을 전제로 계약이 박혀 있다(`deploy/image/inputs.lock.yaml`의
   `runtime.container_runtime_required: false`). 장치마다 두 모델이면 readback이 "이 로봇은 어느
   쪽인가"를 먼저 알아야 하고 DEVICE/FIELD 게이트를 두 번 통과해야 한다.
3. **리소스가 오히려 늘어난다.** arm64에서 dockerd+containerd 유휴 수십 MB, ROS 베이스 레이어의
   GB 단위 저장, overlayfs 상단 레이어 쓰기는 SD 카드 수명을 소모한다. 네이티브 deb 설치가 항상
   가볍다. 예외는 이미지 하나로 배포되는 검증된 서드파티 런타임뿐이다.

**Decision:**

1. **제어·안전 플레인은 장치 종류와 무관하게 네이티브 systemd다.** `rosy-core`, `rosy-io`,
   navigation, motor deadman, DDS, 최종 `cmd_vel` 단일 발행자는 어떤 장치에서도 컨테이너로 돌리지
   않는다. D-161 5항과 D-197 1항은 이 결정으로 바뀌지 않는다.
2. **컨테이너 런타임의 기본값은 미설치다.** Docker CE는 *장치 프로필이 컨테이너 워크로드를 선언할
   때만* 설치한다. "필요할 때 설치"가 아니라 "선언된 프로필이 요구할 때만 설치"다. 선언이 없으면
   데몬·소켓·이미지 레이어가 그 장치에 없다.
3. **유연성의 표현 수단은 프로필이다.** 아키텍처 15의 `rosy-profile-*` 메타패키지와
   `deploy/robot/config/board.yaml`의 `slices`/`presets`로 장치별 구성과 리소스 예산을 표현한다.
   **같은 로봇의 런타임을 Docker와 네이티브로 갈라타는 옵션은 만들지 않는다.** 한 장치가 가질 수
   있는 운영 모델은 하나뿐이다.
4. **컨테이너 사이드카 레인은 안전 계획 밖 워크로드에 한한다**(비전·AI 추론, 검증된 서드파티
   런타임). 다음 네 조건을 **모두** 만족해야 한다.
   - `rosy-runtime.target`의 부팅 경로에 없고 CORE/I/O의 필수 슬라이스가 아니다.
   - UART·GPIO·I2C·SPI·video 장치와 최종 `cmd_vel`를 소유하지 않는다.
   - 안전 게이트(`verify-motors.sh` UART preflight, motor deadman, device readback)는 컨테이너가
     설치되지 않은 상태에서 항상 통과할 수 있어야 한다.
   - 제품 릴리스 payload의 필수 항목이 되지 않는다(D-197 1항 유지).
5. **문서 규칙:** 아키텍처 15 §11의 "Docker optional" 문구는 이 결정으로 대체하고, README·운용
   문서에는 "제품 런타임은 네이티브 systemd이고 Docker는 개발·CI와 선언된 사이드카에만"이라고
   명시한다. 이 선언은 `test/test_native_runtime_docs.py`로 고정한다.

**Alternatives:** (a) 장치 부팅 시 Docker/네이티브를 고르는 런타임 스위치는 1~3항의 비용을 모두
지불하면서 얻는 것이 없어 거절한다. (b) 비전·AI까지 무조건 네이티브로 고정하면 검증된 서드파티
이미지를 매번 재빌드해야 해 사이드카 레인을 남긴다 — 단, 4항의 조건을 만족하는 워크로드에만.
(c) 제품 전체를 컨테이너로 유지하는 안은 D-161이 이미 거절했다.

**Consequences:** lite 로봇에는 컨테이너 데몬이 없고, GPU/AI 박스는 프로필에 사이드카를 선언한다.
`install-pi.sh`의 docker-ce 설치 경로는 D-198의 폐기 대상으로 남아 있고, 그 대체가 없이 유지하지
않는다. 사이드카가 제품 게이트에 스며들면(필수 payload·부팅 경로·장치 소유) D-197 1항 위반이다.
문서가 "Docker optional"처럼 읽히면 계약 테스트가 빨간색이 된다.

**Validation / Transition:** `test/test_native_runtime_docs.py`가 README, `raspberry-pi-runtime.md`,
`docs/deployment/AGENTS.md`, 아키텍처 15와 ADR 색인이 이 규칙을 말하는지 고정한다. 사이드카 레인을
실제 장치에서 여는 변경은 별도 ADR과 ARTIFACT/DEVICE 증거를 요구한다.

**References:** D-161, D-197, D-198, D-144,
`docs/architecture/15_ROSY_Ubuntu_Modular_Installation.md`,
`docs/solutions/workflow-issues/inability-to-check-recorded-as-clean-result.md`,
`deploy/robot/native/AGENTS.md`, `deploy/robot/config/board.yaml`.
