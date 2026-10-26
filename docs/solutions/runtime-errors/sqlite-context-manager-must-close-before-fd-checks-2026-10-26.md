---
title: SQLite 트랜잭션 종료와 연결 닫기를 구분해야 한다
date: 2026-10-26
category: runtime-errors
module: learning/curation/perception/learning_workspace.py
problem_type: database_issue
component: database
severity: medium
root_cause: wrong_api
resolution_type: code_fix
symptoms:
  - "카탈로그 단독 시험은 통과하지만 root-test-3of3에서는 열린 파일 수가 40에서 38로 감소해 실패한다."
  - "금지된 파일 읽기와 저장 내용 보존 검사는 통과한다."
tags: [sqlite, resource-lifetime, http-error, test-isolation, descriptors]
---

# SQLite 트랜잭션 종료와 연결 닫기를 구분해야 한다

## 증상과 원인

카탈로그 가져오기 거절 시험은 전후 파일 수를 엄격히 비교한다. 실패 당시 디스크립터 번호와 대상을 기록하니 사라진 두 자원은 **앞선 카메라 웹 시험의** `reviews.sqlite3`와 소켓이었다. 카탈로그가 연 파일이 아니었다. 진단용으로 수집을 강제했을 때도 같은 두 자원이 닫혔다.

`Workspace`의 다섯 `with sqlite3.connect(...)` 블록은 트랜잭션만 끝내고 연결은 닫지 않았다. 카메라 시험도 예상한 `HTTPError` 응답을 닫지 않았고, 데몬 요청 스레드는 서버 종료 시 기다리지 않았다. 이전 시험의 자원이 나중에 수거되면서 다음 시험의 파일 수가 줄었다.

## 수정

연결을 만든 다섯 위치에서 기존 커밋·롤백을 유지한 뒤 명시적으로 닫는다.

```python
with closing(sqlite3.connect(self.db)) as conn, conn:
    ...
```

카메라 시험은 정상 응답과 `HTTPError`를 모두 컨텍스트로 닫는다. 요청 스레드를 기다리도록 구성하고, 초기화와 `yield`를 `try/finally`로 감싸 서버를 정리한다. 카탈로그의 원래 읽기·저장 보존·동일 파일 수 검사는 유지한다. 진단용 디스크립터 지도와 강제 수집 코드는 최종 수정에서 제거했다.

## 검증과 복구

회귀 검사는 실제 SQLite 연결 객체를 보유한 채 `SELECT 1`이 닫힌 연결 오류를 내는지 확인한다. 수거 시점에 기대지 않는다. 수정 전에는 기존 Workspace 사례 여섯 개의 정리 검사에서 실패했고, 수정 후 관련 56개가 통과했다. 수정 커밋 `76813631a2`의 원래 213파일 묶음은 원격에서 3,343개 통과·421개 건너뜀, NEW 0이었다. 이 기록을 준비할 때 공식 병합은 대기 중이며 이미지·장치 수용을 뜻하지 않는다.

배포 복구가 필요하면 기존 릴리스를 복원하고 해당 프로세스를 정상 종료해 남은 연결을 닫는다. 검수 DB를 재생성하거나 사람 라벨을 변경하는 복구는 필요하지 않다.

파일 수가 감소하는 순서 의존 실패에서는 먼저 사라진 디스크립터의 대상을 확인한다. 다른 시험이 만든 자원이면 생성한 쪽의 수명을 고친다. 개수 비교를 `<=`로 바꾸거나 강제 수집을 최종 해결로 남기면 실제 누수를 놓칠 수 있다.
