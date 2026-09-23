---
title: unit의 샌드박스, 그 사용자의 HOME, 그 Python 의존성은 제품의 일부다 — 실제로 도는 곳에서 시험한다
date: 2026-09-24
category: workflow-issues
module: deploy/robot/native + deploy/image (Pinky Pro release 2026.09.23-005 첫 실기 부팅)
problem_type: workflow_issue
component: development_workflow
severity: critical
applies_when:
  - systemd unit에 ProtectSystem=strict, ProtectHome=true, StateDirectory=, ReadWritePaths=, User=를 쓰거나 바꿀 때
  - 서비스 계정(--system --no-create-home)으로 도는 프로그램이 Path.home(), expanduser("~")를 쓸 때
  - 제품 이미지가 rosdep/apt로, 시험 환경이 pip으로 같은 이름의 Python 패키지를 깔 때
  - 이미지 검증이 진입점을 root chroot에서 --help로만 실행할 때
symptoms:
  - "rosy-release-recover: [Errno 30] Read-only file system: '/var/lib/rosy/releases'"
  - "ImportError: cannot import name 'field_validator' from 'pydantic'"
  - "~/.rosy/rosy.yaml stat에서 EACCES (ENOENT가 아님)"
  - "/var/lib/rosy/provisioning, releases, config가 rosy-core 소유"
  - host 시험, CI, 이미지 빌드, 서명, 매체 검증이 모두 초록
root_cause: missing_validation
tags: [systemd, sandbox, protect-system, protect-home, state-directory, pydantic, rosdep, pip, hash-lock, image-verification, pinky-pro]
---

# unit의 샌드박스, 그 사용자의 HOME, 그 Python 의존성은 제품의 일부다 — 실제로 도는 곳에서 시험한다

## Context

D-174에서 "저장소에서 통과한 도구도 설치 위치에서 실행해 봐야 한다"를 배웠고, customizer가 설치된 진입점을
chroot에서 실행하게 했다. release `2026.09.23-005`는 그 검사를 통과했고, 서명되고, 구워졌고, 부팅해서
`PROVISIONED`·Wi-Fi·SSH까지 갔다. CORE는 뜨지 않았다. 결함 네 개가 줄지어 있었다(D-189).

| 결함 | 시험이 본 것 | 장치가 한 것 |
|---|---|---|
| 복구 gate 쓰기 불가 | unit에 `ProtectSystem=strict`라는 **문자열**이 있다 | `/` 전체가 읽기 전용, 쓰기 경로 0개 |
| pydantic 1 | CI가 `pip install pydantic` (최신 2.x) | rosdep이 apt `python3-pydantic` 1.10 |
| HOME EACCES | CORE 시험은 개발자 HOME에서 | 서비스 계정 HOME `/home/rosy-core`, `ProtectHome=true` |
| root 상태 chown | 지시어 존재 확인뿐 | `StateDirectory=rosy`가 매 시작마다 `/var/lib/rosy` 전체를 chown |

D-174의 설치 위치 실행은 "어디에 설치되는가"는 재현했지만 "누가, 어떤 namespace에서, 어떤 패키지로"는
재현하지 않았다. root chroot에는 샌드박스도, 서비스 계정도, 쓰기 금지도 없다. 그리고 CORE는 아예 import되지
않았다 — `ros2 pkg prefix core`로 존재만 봤다.

## Guidance

1. **unit 지시어는 문자열이 아니라 의미로 시험한다.** 지시어가 있다는 시험은 그 지시어가 무엇을 막는지 모른다.
   unit을 systemd처럼 파싱해(빈 대입은 초기화) 쓰기 집합을 계산하고, 프로그램이 쓰는 경로 목록과 비교한다.
   목록은 코드 위치 주석과 함께 시험 옆에 두고, 프로그램 소스를 grep해 새 경로·`Path.home()`이 생기면 분류를
   강제한다. 그 가드가 **이미 출하된 unit에서 실패하는지** 먼저 확인한다(이번에는 005 unit에서 9건 적색).
2. **공유 부모를 서비스에 주지 않는다.** `StateDirectory=X`는 `User=`에게 X를 재귀 chown한다. 부모는 root가
   갖고(tmpfiles `d`), 각 unit은 `StateDirectory=X/<unit>`만 갖는다. 쓰는 주체가 따로 있는 디렉터리(지도)는
   그 주체에게 준다 — 응급 조치가 준 권한이 필요한 권한이라는 보장은 없다.
3. **서비스 계정의 HOME은 unit이 정한다.** `--no-create-home` 계정 + `ProtectHome=true`에서 `Path.home()`은 EACCES를
   낸다(ENOENT가 아니라서 "없으면 기본값" 코드도 못 넘긴다). `ProtectHome=true`인 비 root unit은 쓰기 집합 안의
   `HOME`을 둔다. ROS 로그만 옮긴 D-174 F6은 같은 함정의 절반이었다.
4. **Python 런타임은 이름이 아니라 해시로 고정한 입력이다.** 시험 환경과 제품 환경이 공유하는 것이 패키지
   이름뿐이면 메이저 버전이 갈려도 아무도 모른다. 하나의 해시 고정 파일을 이미지와 CI가 같은 플래그
   (`--require-hashes --no-deps --only-binary=:all:`)로 깔고, 이미지 lock이 그 파일의 해시를 고정한다.
5. **이미지 안에서 서비스가 시작 때 import하는 것을 import한다.** `--help`는 함수 안의 늦은 import에 닿지 않는다.
   진입 모듈의 AST에서 늦은 import를 모아(`try` 안의 선택 import 제외) 서비스와 같은 환경(ROS source, 쓸 수 없는
   HOME, `-B`)에서 import하고, 핵심 버전(pydantic 2)을 단정하고, 실패하면 이미지 빌드를 실패시킨다.
6. **남은 간극을 이름으로 적는다.** 정적 계약과 chroot import도 systemd namespace를 세우지는 않는다. 서명 전에
   rootfs를 `systemd-nspawn --boot`로 띄워 `CORE_READY`를 기다리는 것이 다음 단계다(D-189 가드 C). 그 전까지
   "초록"은 "계산상 쓸 수 있고 import된다"이지 "부팅한다"가 아니다.

## Why This Matters

네 결함은 모두 설계 문서, 시험, 리뷰, 이미지 파이프라인을 통과했고 한 번의 실기 부팅에서 순서대로 드러났다.
하나를 고치면 다음 것이 나오는 구조라 원격으로 고쳤다면 부팅 네 번이 들었다. 표시 계층(D-174 T0)과
운영자 SSH(D-174 F3) 덕분에 카드를 회수하지 않고 한 번에 진단할 수 있었다 — 그 투자가 이번에 값을 했다.
같은 결함 부류가 다시 서명 이미지에 들어가지 않게 하는 것은 가드 A·B이고, 막지 못한 나머지는 가드 C의 몫이다.
