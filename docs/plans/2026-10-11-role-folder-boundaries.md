# Drive 책임 폴더 이동 실행 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Base 주행 동작과 기존 이동 제어 ROS 어댑터를 Drive로 옮기고, 설치 identity와 안전 권한을 유지한다.

**Architecture:** D-649는 소스 소유와 Python/ROS 설치 이름을 구분한다. 기존 패키지 빌드 매핑을 재사용하며 공통 CORE 정책과 Perception 관측 근거의 소유를 유지한다.

**Tech Stack:** Python, setuptools/ament, ROS 2 Jazzy, existing remote pytest runner and architecture manifest.

## Task 1: 이동 원본과 소비자 기록 — 완료

- `docs/adr/D-649-drive-behavior-source-ownership.md`와 ADR Log의 같은 번호 행을 기록한다.
- `middleware/core/services/core_features/`의 기존 일곱 폴더를 `middleware/control/drive/behaviors/`로 옮긴다: `line_follow`, `docking`, `navigation`, `localization`, `swarm`, `road_behaviour`, `traffic_policy`.
- `middleware/perception/control/{control_node,goal_node,wander_node,safety_node}.py`를 `middleware/control/drive/runtime/`으로 옮긴다.
- `core_features.*`, `control.*`, ROS entry point, Command/Safety 중재, callback 순서와 구현 바이트를 유지한다.
- 호출자·import·소스 검사·setup/sdist·native/container 구성·Safety 태그와 anchor·구조 결합도/크기 검사·고립 설치 fixture·안내 문서·소유 매니페스트에 반영한다. 과거 ADR·로그·검증 기록은 당시 증거로 유지한다.

## Task 2: 소스·설치 매핑 반영 — 완료

- 기존 `core_features` 패키지에 명시적 소스 매핑을 추가한다. 소스 체크아웃에서만 선언한 behaviors 원본을 검색하며 설치 import는 저장소에 의존하지 않는다.
- 기존 Perception 패턴으로 setuptools 매핑과 자체 완결된 sdist를 구성한다.
- Perception의 기존 빌드·소스 archive·소스 검사에 Drive runtime 모듈을 한 벌만 포함한다. wrapper 복사나 발행기 활성화는 추가하지 않는다.
- Safety 경로와 의미 소유를 함께 옮긴다. 기존 예산과 독립 크기 단위를 유지하고, 구조 검사가 실제 설치 패키지의 이동 원본을 계산하도록 한다.
- Docker COPY와 `.dockerignore`, 개발 overlay, 모델 PC 코드 archive의 이동 원본도 반영한다.

## Task 3: 검증·통합 — 완료

- 원격 scratch에서 `core_features` sdist와 wheel을 빌드한다. 고립 설치에서 line-follow·docking·localization·traffic policy의 기존 import, 단일 구현, 저장소 경로 독립성을 확인한다.
- Perception 고립 설치 시험에서 이동 진입 모듈 네 개와 기존 provider·지도 리소스를 확인한다.
- 독립 Safety 검토를 받고 정확한 파일 목록과 `Safety-Review:` 증거를 커밋한다.
- `tools/remote/remote_pytest.py`로 CORE services/gateway·구조·설치 검사를 실행하고, 로그를 `test/known_failures.py`와 비교한다. 노트북에서는 pytest를 실행하지 않는다.
- 중복 시험 파일명을 피하기 위해 Perception은 별도 원격 호출로 검증하고 같은 비교를 수행한다.
- lint 후 `python tools/land.py --tests auto`로 사용자가 승인한 main fast-forward 통합을 수행한다. 발행된 정확한 SHA의 CI·릴리스 관문을 통과한 뒤 배포한다. 오프라인 Pinky는 기존 자동 업데이트 경로를 유지한다.

## Progress

- ADR, 80개 파일 이동, 설치·소스 archive 매핑, 독립 Safety 검토와 책임 안내 문서를 반영했다. [검증 기록](../validation/d649-drive-boundaries-2026-10-11/result.md)은 초기 실패와 수정 후 재검증을 구분한다.
- 최신 main 통합은 세 차례 재검증 후 source `5da31e05cb8965ad40a7c44b4094470d4f138461`로 완료하고 발행했다. 최종 영향 시험은 8,342건과 Perception 3,028건 통과, 모두 zero NEW다. pre-push 추가 208건도 통과했다.
- 최종 source `2891e10061233b1067fd315cdcbad78bdb1b5d46`의 전체 CI·Site 빌드·Android 검사를 통과한 후 온라인 Site·AI·모델 PC 배포를 완료했다. 실제 설치·서비스 경로·API·지도와 Review 데이터 보존은 [배포 수용 기록](../validation/d649-drive-boundaries-2026-10-11/deployment.md)에 있다. 오프라인 로봇의 장치·실주행 수용은 포함하지 않는다.
- 이전 `53c557136957` 후보는 map-label 브라우저 CI 실패로 서명·적용하지 않았다. 로봇은 사용자 결정으로 오프라인을 유지한다.
