---
title: R에 손으로 복사한 파일의 한글이 이중 인코딩되면 자동 보정 타이머가 사이트 지도 이름을 계속 망가뜨린다
date: 2026-11-17
category: deployment
module: site vision overlay (world_261026_auto.py, map_register.py, rectify.py), site map save path, contracts/foundation/core_common/text_encoding.py
problem_type: data_integrity
component: site_stack_runtime
severity: high
symptoms:
  - "Fleet 콘솔 지도 호버 카드 제목이 `S3 · S3 ìƒë‹¨ í•˜ì—­ ì •ì§€ì„  (cell_s)`처럼 깨짐(제목은 `${pl.id} · ${pl.name}`)"
  - "site_map_versions.body의 places/edges 이름 27개(장소 13, 간선 14)가 v255~v257에서 깨짐"
root_cause: environment_constraint
resolution_type: code_and_ops
tags: [fleet-r, hotpatch, encoding, mojibake, site-map, auto-calibration]
applies_when:
  - "R(rosy-fleet-r)의 컨테이너 이미지에 COPY·scp·Windows 도구로 .py를 손으로 넣을 때"
  - "사이트 지도·UI에 보이는 한글이 코드 리터럴(world_*.py 등)에서 오고, 자동 타이머가 그 값을 저장 경로로 되쓸 때"
---

# R에 손으로 복사한 파일의 한글이 이중 인코딩되면 자동 보정 타이머가 사이트 지도 이름을 계속 망가뜨린다

관련: [핫패치 root 시작](site-stack-hotpatch-preserves-root-entrypoint-and-stateful-cell-handoff-2026-11-12.md), [PowerShell 한글 쓰기](../workflow-issues/powershell-redirect-eats-korean-2026-09-29.md). 옛 pyc 문제는 같은 핫패치 경로의 다른 함정이다(overlay에서 `__pycache__` 제거 후 py_compile).

## 증상

Fleet 콘솔 지도 호버 카드의 장소 이름이 UTF-8 바이트를 cp1252로 읽은 모양(`ìƒë‹¨ …`)으로 보였다. 저장소 파일은 모든 커밋에서 깨끗했다.

## 원인

- 2026-11-16 17:40 KST에 R의 site vision 이미지(서명 기준 커밋 위)에 COPY 레이어 세 개(`world_261026_auto.py`, `map_register.py`, `rectify.py`)를 핫패치했다. 한글 리터럴이 이중 인코딩(UTF-8 바이트를 cp1252로 해석 후 재인코딩)이었다. UTF-8을 명시하지 않은 Windows 도구로 옮긴 것과 일치한다. 서명 기준 커밋에는 그 파일이 없었다. `/opt/rosy/model-watch/src/...`에도 깨진 사본이 하나 더 있었다.
- 전파: `rosy-auto-track-calibration.timer`(2분마다)가 활성 지도를 읽어 `world_261026_auto.py`로 places/edges 이름을 덮어쓰고 draft PUT + activate 한다. 그래서 깨진 리터럴이 v255~v257에 들어갔다. 이전 v136/v138은 운영자 업로드로 깨졌고 v137/v139에서 고쳤다. 영향은 `site_map_versions.body`뿐이다.

## 해결

1. 같은 태그 위에 main의 세 파일로 새 overlay를 만들었다(양쪽 sha256 대조). 옛 `__pycache__` 항목을 지우고 py_compile, chown 10001. 옛 이미지는 `rosy-site-vision:f525196-pre-encfix-20261117`로 백업했다. `/etc/rosy/site/site.env`에 `-f compose.cross-host-peer.yaml` 줄이 남아 있는지 확인하고 `systemctl restart rosy-site-stack`, 실행 중 컨테이너의 파일 해시를 확인했다.
2. 타이머는 보정이 바뀔 때만 쓰므로 지도는 저절로 낫지 않았다. 기명 운영자(Account 흐름 로그인, 세션 쿠키 확인 후 호출)로 `GET site-map/active` → 이름 수리 → `PUT site-map/draft`(expected_revision은 GET draft에서; `Origin` 헤더가 콘솔 콜백 origin과 같아야 하며 아니면 403 `CSRF_REJECTED`) → `POST activate`. 결과 v258, 깨진 이름 0, 스크립트로 `name` 필드만 바뀐 것을 확인했다.
3. 재발 방지(커밋 0d7553c29b): 공용 `looks_double_encoded`(`contracts/foundation/core_common/text_encoding.py`); site map `save_draft`/`save_profile`이 이중 인코딩 이름을 400 `TEXT_DOUBLE_ENCODED`(메시지에 필드 경로)로 거부; `test/test_source_encoding.py`가 추적 텍스트 파일의 mojibake를 실패 처리; PowerShell `Get-Content`와 Python `read_text` 호출에 UTF-8 명시.
   - 주의: 이 서버 검사가 배포되면 깨진 vision 소스는 자동 보정 PUT을 실패시킨다. 소스부터 고친다.

## 검증 근거

증거 파일: `D:/DevTemp/ui-ux-impl-1117/encoding/`. 컨테이너 파일 해시 = main 해시, v258에서 깨진 이름 0, 이름 외 필드 불변. 이 확인은 R 실물 관측이며, 재발 방지 코드의 시험(pytest)은 별도다.

## 감지법

- 의심 문자열: `s.encode('cp1252').decode('utf-8')`로 복원되면 이중 인코딩(정의 없는 다섯 바이트는 latin-1로).
- 컨테이너 안 파일 해시를 `git show main:<path>`와 비교.
- `docker image history`로 핫패치 COPY 레이어 확인.

## 복구·롤백

백업 이미지를 원래 태그로 다시 태그하고 `systemctl restart rosy-site-stack`. 이전 지도 버전은 모두 남아 있어 draft로 되돌려 activate 할 수 있다(단 깨진 소스로 되돌리면 타이머가 다시 덮는다).

## 적용 조건

R에 손으로 복사하는 모든 파일, 코드 리터럴에서 나와 저장되는 모든 사이트 텍스트. 복사 도구는 UTF-8을 명시하거나 바이트 그대로 옮기고, 복사 뒤 양쪽 sha256을 대조한다.
