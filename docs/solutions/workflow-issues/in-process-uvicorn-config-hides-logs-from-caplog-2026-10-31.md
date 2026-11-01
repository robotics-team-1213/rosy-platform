---
module: operations/fleet/test
date: 2026-10-31
problem_type: workflow_issue
component: testing_framework
severity: major
tags: ["caplog", "uvicorn", "logging", "ci-shard", "test-isolation", "publish"]
applies_when: "시험이 caplog로 uvicorn.* 로거 출력을 확인할 때, 시험에서 uvicorn.Config·uvicorn.Server를 같은 프로세스에 만들 때, 또는 게시 PR CI에서만 로그 단언이 빈 문자열로 실패하고 시험 PC에서는 재현되지 않을 때"
---

# 같은 프로세스의 uvicorn.Config가 caplog에서 로그를 숨긴다

## 증상

2026-10-31 게시 PR #223의 `fleet-2of5` CI job이 두 번 연속 실패했다. 실패한 시험은 `test_assistant_preprocessing.py::test_fleet_checks_usage_binding_and_logs_no_original_text_or_identity[False-*]`이고, 오류는 `assert '"input_tokens": 100' in ''`(caplog가 비어 있음)였다.

시험 PC에서는 재현되지 않았다. 같은 커밋으로 다음 세 가지를 돌렸고 모두 통과했다.
- 같은 순서의 앞 파일
- 브라우저 시험을 켠 실행
- shard 97개 파일 전체를 수집한 `-k` 실행

이 시험과 로그 코드는 직전 게시보다 오래됐다.

## 원인

`uvicorn.Config(...)`는 만들 때 uvicorn 기본 `LOGGING_CONFIG`를 적용한다. 이 설정은 `uvicorn` 로거를 `propagate=False`로 바꾼다. 그 뒤로 같은 프로세스에서 `uvicorn.error`로 남긴 로그는 root에 닿지 않는다. caplog는 root에 붙은 handler로 듣는다. `caplog.at_level(..., logger='uvicorn.error')`는 level만 바꾸고 전파는 되돌리지 않는다.

CI는 파일 목록을 shard로 나눠 한 프로세스에서 알파벳 순서로 돌린다. 시험이 늘어 shard 구성이 바뀌자 `test_account_admin_browser.py`가 같은 shard 맨 앞에 왔다. 이 파일은 in-process `uvicorn.Config`를 만든다.

시험 PC에서 재현되지 않은 이유는 그 브라우저 시험이 시험 PC에서 건너뛰어졌기 때문으로 본다. 단독 실행 결과가 2 skipped였다. 건너뛰면 Config가 만들어지지 않는다.

## 해결

로그 단언 구간에서 caplog handler를 대상 로거에 직접 붙이고, 끝나면 뗀다(`576dca5989`). 그러면 다른 시험이 uvicorn 로깅 설정을 적용했는지와 상관없이 잡힌다.

## 검증 근거

- uvicorn 0.52.4(CI와 같은 버전)에서 root handler에 붙여 확인했다. `uvicorn.Config(app=None, log_level='error')` 전 로그는 잡히고, 뒤 로그는 잡히지 않았다. `logging.getLogger('uvicorn').propagate`는 `False`였다.
- 고친 시험은 `test_account_admin_browser.py`와 함께 원격에서 통과했다(43 passed, 2 skipped).
- 대체 게시 PR의 CI 결과는 그 PR에 남는다.

## 다음에 적용할 조건

- 다른 시험 파일 35개가 in-process `uvicorn.Config`를 만든다. caplog로 `uvicorn.*` 로그를 단언하려면 대상 로거에 handler를 직접 붙인다.
- 게시 PR에서만 실패하고 시험 PC에서 재현되지 않으면, 먼저 그 job의 pytest 줄(`##[group]pytest ...`)에서 같은 shard 파일 목록을 확인한다. 그다음 시험 PC에서 그 파일이 건너뛰어졌는지 본다.
- 실패한 게시 PR은 `publish_main.py`가 고칠 수 없다. 열린 게시 PR이 있으면 새 게시를 거절하기 때문이다. 고침을 착지하고, 실패한 PR을 대체 사유와 함께 닫고, `--force-blocked`로 새 게시 PR을 연다.
