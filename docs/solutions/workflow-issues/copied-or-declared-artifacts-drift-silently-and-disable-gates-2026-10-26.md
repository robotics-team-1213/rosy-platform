---
title: 복사본과 선언 목록은 원본에서 조용히 멀어져 게이트를 끈다
date: 2026-10-26
category: workflow-issues
module: tools/hooks (install.sh, pre-push), deploy/hosts/services.yaml, tools/remote/update_status.py
problem_type: workflow_issue
component: development_workflow
severity: high
root_cause: missing_tooling
resolution_type: tooling_addition
symptoms:
  - "공유 clone의 .git/hooks/pre-push가 2026-10-11 복사본(6993 bytes)이었고 tools/hooks/pre-push는 그 뒤로 바뀌어 있었다"
  - "10-11 뒤에 넣은 pre-push 게이트(착지 기록 재사용, Safety-Review 범위 검사, 게시 전용 검사)가 2주 동안 실제 push에서 한 번도 돌지 않았고, 아무 실패도 보이지 않았다"
  - "현장 PC에 시험 저장소 정비 타이머가 없었는데 update_status.py는 아무것도 보고하지 않았다"
applies_when:
  - "설치 스크립트가 파일을 링크가 아니라 복사로 놓는 곳(git hook, systemd unit, 호스트 정비 도구)을 고칠 때"
  - "새 게이트를 hook이나 배포 도구에 넣고 '이제 막힌다'고 판단하려 할 때"
  - "선언된 것만 점검하는 감사 도구(update_status.py 같은)의 침묵을 '정상'으로 읽으려 할 때"
tags: [drift, installed-copy, git-hooks, pre-push, services-manifest, update-status, gates, silent-failure]
---

# 복사본과 선언 목록은 원본에서 조용히 멀어져 게이트를 끈다

## 증상

2026-10-26에 같은 부류의 문제 세 건을 확인했다. 셋 다 실패 문구가 없었다. 게이트가 돌지 않은 것이 '통과'로 보였다.

1. **설치된 pre-push hook이 낡은 복사본이었다.** 공유 clone의 `.git/hooks/pre-push`는 2026-10-11 복사본(6993 bytes)이었다. `tools/hooks/pre-push`는 그 뒤로 여러 번 바뀌었다. 10-11 뒤에 넣은 게이트(착지 기록 재사용, Safety-Review 범위 검사, 게시 전용 검사)는 2주 동안 실제 push에서 하나도 돌지 않았다. 시험은 저장소의 `tools/hooks/pre-push`를 돌리므로 모두 녹색이었다.
2. **선언 목록에 역할 하나가 빠져 있었다.** `deploy/hosts/services.yaml`은 `rosy-test-storage.service/.timer`를 model과 ai 역할에만 선언했다. site 역할에는 없었다. 그래서 현장 PC는 시험 저장소 정비를 받지 못했다. `tools/remote/update_status.py`는 선언된 unit만 점검하므로 계속 조용했다.
3. **실험실 PC의 정비 도구가 옛 버전이었다.** 10-26에 다시 배포하기 전까지 그랬다(rosy-ops PR #3).

## 원인 패턴

- **링크가 아니라 복사다.** `tools/hooks/install.sh`는 hook을 `sed`로 복사한다. 원본이 바뀌어도 복사본은 그대로다. 복사본을 쓰는 쪽은 자신이 낡았는지 확인하지 않았다.
- **감사는 선언된 것만 본다.** `update_status.py`는 선언과 실제를 비교한다. 선언에서 빠진 것은 비교 대상에 들어가지 않는다. 선언 목록이 완전한지는 아무도 확인하지 않았다.
- **둘 다 실패가 아니라 침묵으로 끝난다.** 게이트가 돌지 않거나 점검 대상이 없으면 출력은 정상과 같다.

## 어떻게 찾았나

게시 전용 검사를 착지한 뒤 그 검사가 실제 push에서 도는지 보려고 `cmp .git/hooks/pre-push tools/hooks/pre-push`를 돌렸다. 두 파일이 달랐고, 설치된 쪽은 10-11 복사본이었다. 시험과 감사 도구는 이것을 잡지 못했다. 설치본을 직접 비교해서 찾았다. 선언 누락도 `update_status.py`가 아니라 선언 목록을 직접 열어 찾았다.

## 해결

- 공유 clone에서 `bash tools/hooks/install.sh`를 다시 돌렸다.
- hook에 자기 비교를 넣었다(커밋 `58b1456a7d`). `rosy.publishOnly` clone에서 설치된 복사본(`$0`)이 push하는 커밋의 `tools/hooks/pre-push`와 다르면(CR 무시) `bash tools/hooks/install.sh`를 안내하고 push를 거절한다. 시험은 `test/test_pre_push_hook.py::test_a_stale_installed_copy_refuses_the_push`다.
- site 역할에 `rosy-test-storage.service/.timer`를 선언했다(커밋 `a4a357a416`). `test/test_host_services_manifest.py`가 model·ai·site 세 역할 모두 정비 unit과 timer를 선언하는지 확인한다. 현장 PC에는 10-26에 손으로 타이머를 놓았다.
- 실험실 PC 정비 도구는 10-26에 다시 배포했다(rosy-ops PR #3).

## 확인 근거

- 자기 비교 시험은 같음·다름 두 경우를 본다. bash로 같은 구간을 돌려 같음 exit 0, 다름 exit 1을 확인했다.
- 선언 시험은 site 역할이 빠지면 실패한다.
- 이것은 시험과 손 확인이다. 다음 게시 push에서 자기 비교가 실제로 도는지는 그 push에서 확인한다.

## 같은 부류, 아직 열림

코드 감사에서 읽기만 해서 찾았다. 고치지 않았다.

- 원격 시험 환경 id에 pytest·playwright·setuptools 버전이 들어가지 않는다. 설치는 버전을 고정하지 않는다(`tools/remote/remote_test_tools.py` 160-161행). 이 패키지가 바뀌어도 같은 환경으로 보이고, 착지 캐시가 그 환경의 옛 통과를 쓸 수 있다.
- `update_status.py`의 `repo_digest`는 `origin/main`의 파일과 비교한다(`tools/remote/update_status.py` 184-191행). `git fetch`를 하지 않았으면 낡은 `origin/main`과 비교한다.
- `tools/release/robot_cd.py`의 `verify_snapshot`은 설치된 스냅숏이 바뀌지 않았는지만 본다(71-80행). 그 스냅숏이 main보다 얼마나 낡았는지는 보지 않는다.

## 복구

```bash
# 설치된 hook이 원본과 같은지 본다 (다르면 재설치)
cmp <(sed 's/\r$//' .git/hooks/pre-push) <(sed 's/\r$//' tools/hooks/pre-push) || bash tools/hooks/install.sh
# 실험실 PC의 선언과 실제 unit·복사본을 비교한다 (fetch 먼저: repo_digest는 origin/main과 비교한다)
git fetch origin && python tools/remote/update_status.py
# 선언 목록 시험 (노트북에서 pytest 금지: 원격으로)
python tools/remote/remote_pytest.py --log-dir "$ROSY_SCRATCH/<name>" -- test/test_host_services_manifest.py test/test_pre_push_hook.py
```

`update_status.py`가 조용해도 선언이 완전하다는 뜻은 아니다. 새 역할이나 새 PC를 넣었으면 그 역할의 선언을 먼저 연다.

## 다음에 적용할 조건

- **설치된 복사본마다 쓰는 순간 자기 비교나 버전 도장 확인을 둔다.** 복사본이 원본과 다르면 조용히 옛 동작을 하지 말고 멈추고 재설치 명령을 찍는다. hook은 `58b1456a7d`의 방식이 본보기다.
- **'선언된 것을 감사하는' 도구에는 선언이 완전한지 보는 시험을 붙인다.** 감사 도구의 침묵은 선언 범위 안에서만 의미가 있다. `test/test_host_services_manifest.py`처럼 모든 역할이 꼭 있어야 할 항목을 갖는지 시험으로 고정한다.
- **새 게이트를 넣었으면 실제 경로에서 도는지 한 번 본다.** 저장소 시험의 녹색은 설치본이 같은 코드라는 증거가 아니다.
