---
title: 합성 픽스처에서만 검증한 가드는 실제 파이프라인의 가장 비싼 지점에서 깨진다
date: 2026-09-23
last_updated: 2026-10-29
category: workflow-issues
module: deploy/robot/pinky_pro/image + deploy/robot/pinky_pro/sd (Pinky Pro release 003·004)
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - 새 거부 규칙(가드)을 이미지 빌드나 릴리스 파이프라인에 넣을 때
  - 픽스처가 실제 산출물 트리(colcon install, 서명 릴리스)를 흉내만 낼 때
  - PowerShell이나 셸을 통해 프로그램에 값을 넘기는 코드를 시험할 때
symptoms:
  - 20분짜리 ARM64 이미지 빌드가 customizer 단계에서 실패
  - "bytecode cache in signed release" 수백 줄, 모두 colcon 정상 산출물
  - 호스트 테스트는 통과하는데 실제 실행에서 "operator key is not an allowed single-line public key"
root_cause: missing_validation
tags: [guard-scope, fixtures, colcon, powershell, bom, arm64, image-pipeline, pinky-pro]
---

# 합성 픽스처에서만 검증한 가드는 실제 파이프라인의 가장 비싼 지점에서 깨진다

## Context

D-174/D-175 리뷰 반영으로 두 가지를 넣었다. 둘 다 호스트 테스트는 초록이었고, 둘 다 실제 실행에서 깨졌다.

**1. 너무 넓은 거부 규칙.** 서명 릴리스에 런타임 bytecode가 생기면 `verify()`가 unlisted 파일로 거부한다는 리뷰
지적(MEDIUM)을 받아, 마운트 이미지 검증기에 이렇게 넣었다.

```python
for cache in sorted(release.rglob("__pycache__")):
    findings.append(f"bytecode cache in signed release: ...")
```

release `2026.09.23-003`의 ARM64 빌드는 20분을 돌고 customizer에서 죽었다. colcon이
`install/lib/python3.12/site-packages/*/__pycache__`를 **payload의 일부로** 설치하기 때문이다. 테스트 픽스처는
`native_release.py` 같은 빈 파일 몇 개로 릴리스 트리를 흉내 냈을 뿐, colcon 트리를 담지 않았다.

위험이 실제로 생기는 경로는 런타임이 import하는 네이티브 런타임 사본 두 곳뿐이다. 규칙을 그 두 곳으로 좁히고,
colcon `__pycache__`가 다시 막히지 않는 회귀 시험을 함께 넣었다.

```python
for runtime in (root / "opt/rosy/native-runtime", release / "deploy/robot/pinky_pro/native"):
    if runtime.is_dir():
        for cache in sorted(runtime.rglob("__pycache__")):
            ...
```

**2. 콘솔이 없는 픽스처.** 운영자 공개키를 PowerShell에서 Python으로 넘길 때 파이프를 썼다.

```powershell
$operatorFingerprint = ($operatorKey | & $PythonExe -c $fingerprintCode)   # 실제 실행에서 실패
```

계약 시험 5건은 통과했다. 실제 카드 작업에서는 키가 거부됐다. 같은 키를 Python에 직접 넣으면 유효했다.
차이는 콘솔이다. Windows PowerShell 5.1이 콘솔을 거쳐 파이프로 보낼 때 BOM이 앞에 붙고, `strip()`은 BOM을
지우지 않는다. 테스트는 `subprocess`로 콘솔 없이 실행돼 이 경로를 밟지 않았다.

공개키는 비밀이 아니므로 인자로 넘기게 바꿨다(`sys.argv[1]`). 비밀은 여전히 stdin으로 넘기되, 그 경로는
`create-provision-bundle.py` 호출처럼 `$OutputEncoding`과 `PYTHONUTF8`를 함께 고정한 곳에서만 쓴다.

## Guidance

### 실물 진단 import도 서명 트리를 바꿀 수 있다 (2026-10-29)

로봇의 서명 릴리스 안에 있는 Python 모듈을 root 진단 스크립트에서 import한 뒤,
다음 부팅의 릴리스 검증이 `CHECKSUM_UNLISTED_FILE`로 막혔다. 진단 당시 서비스가
정상이어도 다음 부팅 검증까지 안전하다는 뜻은 아니다. 서명 manifest에는 정상 빌드
산출물인 bytecode 1,302개가 있었고, 진단 시간대에 생성된 미등록 bytecode 59개가 별도로 있었다.

복구는 manifest의 파일 집합과 실제 파일 집합의 차이를 먼저 계산하고, 이번 진단이
생성한 것으로 소유자·시각·확장자·경로를 확인한 59개만 릴리스 밖의 root 전용 백업으로
격리했다. 원래 상대 경로와 SHA-256을 receipt에 남겼다. 기존 manifest·서명·등록된
bytecode는 바꾸지 않았다. 같은 native verifier가 통과한 뒤 복구 서비스와 runtime target을
시작해 CORE·카메라의 정상 실행을 확인했다. 전체 `__pycache__` 삭제는 복구 방법이 아니다.

다음 실물 조사에서는 첫 import부터 `python3 -B`를 사용한다. 스크립트 안에서도
서명된 패키지 import 전에 `sys.dont_write_bytecode = True`를 설정한다. 특히 `-I`는
`PYTHONDONTWRITEBYTECODE` 같은 환경 설정을 무시하므로 환경 변수 하나에 의존하지 않는다.
진단 뒤에는 동일 verifier로 미등록 파일이 없는지 확인한다. 이 규칙은 설치된 모듈이나
네이티브 런타임을 직접 import하는 운영·복구 스크립트에도 적용한다.

근거: 현장 manifest 차이 59개 → 경로·해시 receipt를 남긴 가역 격리 → 동일 verifier 성공 →
부팅 복구 서비스 성공 및 CORE·카메라 active. 새 ARM64 이미지 구축·OS 슬롯 전환 수용은
이 복구 확인에 포함되지 않는다.

1. **가드는 위험이 생기는 경로에만 건다.** "어디에도 X가 없어야 한다"는 규칙을 쓰기 전에, X가 정상적으로 존재하는
   위치를 먼저 센다. 정상 산출물을 막는 가드는 결국 꺼지고, 그때 진짜 위험까지 같이 꺼진다.
2. **가드를 넣을 때 정상 케이스 시험을 같이 넣는다.** 거부 시험만 있으면 과잉 거부는 드러나지 않는다. 이번에는
   colcon `__pycache__`가 통과하는 시험이 그 역할을 한다.
3. **픽스처가 실제 트리를 대표하는지 확인한다.** 릴리스 트리 픽스처에는 빌드가 실제로 만드는 디렉터리 모양이
   들어가야 한다. 빈 파일 몇 개는 존재 검사만 대표한다.
4. **셸을 통과하는 값은 셸에서 시험한다.** Windows PowerShell 5.1의 파이프는 콘솔 인코딩에 좌우된다. 비밀이
   아닌 값은 인자로, 비밀은 인코딩을 고정한 stdin으로 넘기고, 두 경로 모두 실제 콘솔에서 한 번 실행해 본다.
5. **비싼 단계 앞에 싼 검사를 둔다.** ARM64 이미지 빌드는 20-40분이다. 그 안에서만 드러나는 실패는 픽스처를
   현실화하거나 같은 검사를 호스트에서 먼저 돌려 앞당긴다.

## Why This Matters

003 빌드 실패는 태그·워크플로·다운로드까지 한 회차를 통째로 버렸고, 004로 번호를 올려 다시 돌려야 했다. 키
문제는 카드를 굽기 직전에야 드러났다. 두 결함 모두 호스트 시험이 초록인 채로 통과했으므로, 초록은 "실제
환경에서 동작한다"는 증거가 아니라 "픽스처에서 동작한다"는 증거였다.

## When to Apply

- `deploy/robot/pinky_pro/image`의 검증기나 customizer에 새 검사를 추가할 때
- `prepare-rosy-sd.ps1`처럼 PowerShell이 Python·외부 도구를 호출하는 코드를 고칠 때
- 리뷰 지적을 반영해 거부 규칙을 넓힐 때

## Related

- ADR: `docs/adr/D-174-first-boot-defects-and-boot-indicator.md`
- 같은 부류의 교훈: `installed-layout-import-passes-repo-tests-2026-09-22.md`,
  `sim-perception-green-host-tests-hide-live-gazebo-defects-2026-09-22.md`
