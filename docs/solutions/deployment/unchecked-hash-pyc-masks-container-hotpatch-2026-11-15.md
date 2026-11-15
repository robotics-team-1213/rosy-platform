---
title: "PEP 552 unchecked-hash .pyc files silently mask hot-patched .py files in sealed site containers"
date: "2026-11-15"
module: "rosy-site-vision / rosy-site-fleet container images (deploy/site)"
problem_type: runtime_error
component: deployment
severity: high
symptoms:
  - "Modified .py source inside rosy-site-vision:f525196ee50... (LedConfig.on_fraction=0.005, _view_for recalibration reset) showed new source on disk inside the running container, yet runtime kept executing 0.02 and skipped _view_for reset."
  - "PYTHONDONTWRITEBYTECODE=1 prevents Python from writing new bytecode while still loading pre-existing __pycache__/*.pyc."
root_cause: environment_assumption
resolution_type: workflow_fix
tags: ["docker", "pyc", "pep-552", "unchecked-hash", "rosy-site-vision", "hotfix"]
---

## 증상

현장 `rosy-fleet-r`의 `rosy-site-vision` / `rosy-site-fleet` 컨테이너 이미지를 핫패치(`COPY *.py` + `docker build`)한 뒤 컨테이너 내부 `.py` 파일을 읽으면 수정값이 보이는데도, 실제 실행 동작과 `docker exec ... python3 -c "from ... import ..."` 결과는 여전히 수정 전 상수(`LedConfig().on_fraction == 0.02`)와 수정 전 메서드로 동작한다.

## 원인

기반 이미지의 `__pycache__/*.cpython-312.pyc`가 PEP 552 `unchecked-hash` 플래그(`bit_field == 1`)로 컴파일되어 있어 CPython이 `.py`의 mtime·size·해시를 검사하지 않고 `.pyc`를 무조건 신뢰한다. 여기에 런타임 환경 변수 `PYTHONDONTWRITEBYTECODE=1`이 설정되어 있어 새 바이트코드를 덮어쓰지도 않는다.

## 해결·복구 절차

1. 호스트에서 컨테이너 이미지를 패치하거나 임시 핫픽스를 올릴 때는 수정한 모든 `.py`에 대해 대응 `__pycache__/<module>.*.pyc`를 먼저 지우고 `python3 -m py_compile <module>.py`로 다시 컴파일한다.
2. 컨테이너 재기동 뒤 파일 내용을 읽는 것만으로 끝내지 말고, 반드시 `docker exec <container> python3 -c "..."`로 실제 import된 객체의 속성(`LedConfig().on_fraction`, `inspect.getsource(...)`)을 확인한다.

## 다음에 적용할 조건

- `PYTHONDONTWRITEBYTECODE=1` 환경 또는 사전에 `compileall`된 Docker 이미지를 패치할 때, 그리고 `unittest`/`pytest` 밖의 현장 핫픽스에서 소스 수정이 런타임에 반영되지 않을 때 즉시 `.pyc` 헤더 플래그와 `__pycache__`를 의심한다.
- 정식 빌드는 항상 `rosy-platform` 커밋 + CI 이미지 재빌드로 내보내어 소스와 `.pyc`가 한 번에 생성되게 한다.
