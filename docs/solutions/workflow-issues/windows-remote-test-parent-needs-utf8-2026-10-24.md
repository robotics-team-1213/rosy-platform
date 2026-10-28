---
module: tools
date: 2026-10-24
last_updated: 2026-10-27
problem_type: workflow_issue
component: development_workflow
severity: medium
tags: ["windows", "python", "utf8", "remote-tests", "evidence"]
applies_when: "Windows Python의 cp1252 표준 출력으로 한국어 시험 결과나 상태 변경 명령의 사유를 출력할 때"
---

# 원격 시험의 부모 Python도 UTF-8로 실행한다

## 증상과 원인

원격 pytest가 끝나 로그가 회수됐는데 개발 PC의 runner가 `UnicodeEncodeError`로 종료했다. 첫 호출은 정상적인 시험 실패를 끝까지 보고하지 못했고, 같은 커밋을 UTF-8로 다시 요청하자 원래의 실패 1건을 정상 출력했다. 성공한 원격 시험으로 해석하면 안 된다.

`tools/remote/remote_pytest.py`의 `one()`은 회수한 로그를 UTF-8로 읽은 뒤 그 꼬리를 부모 프로세스의 stdout에 출력한다. 파일을 UTF-8로 읽는 것과 stdout 인코딩은 별개다. 관측한 Windows Python 3.12의 기본 stdout은 `cp1252`였으며 한국어 assert 문맥을 출력하지 못했다. 원격 자식의 UTF-8 설정만으로 부모 출력은 바뀌지 않는다.

## 실행과 복구

같은 고정 SHA와 원래 시험 대상을 유지하고 부모 Python부터 UTF-8 모드로 실행한다. 이 옵션은 노트북에서 pytest를 실행하라는 뜻이 아니다.

```powershell
python -X utf8 tools/remote/remote_pytest.py --sha <commit> --log-dir <scratch> -- <test-path>
python -X utf8 test/known_failures.py <scratch>/run-1.txt
```

원래 로그를 덮어쓰지 않도록 재실행은 다른 scratch 디렉터리에 남긴다. 회수 로그가 있으면 실제 실패 ID를 비교하고, 원격 실행 여부·runner 종료·NEW 수를 각각 확인한다. 출력 인코딩 문제를 제품 실패나 통과로 대체하지 않는다. 이 관측을 이유로 시험 기준선·제품 UI·전역 Git 설정을 바꾸지 않았다.

`-X utf8`는 지정한 Python 프로세스에 적용된다. 다른 Python을 실행하는 착지 도구까지 같은 조건으로 쓰려면 그 호출의 환경에 `$env:PYTHONUTF8 = '1'`을 설정한다. 부모에 옵션만 준 자식 stdout은 관측 환경에서 여전히 cp1252였고, 환경 변수를 지정해 실행한 자식은 utf-8이었다. 시스템 전체 설정을 변경할 필요는 없다.

## 확인 근거와 적용 조건

- 로컬 시험 commit `cdfd415c91`: 첫 runner는 회수된 한국어 실패 꼬리 출력에서 `charmap` 예외로 끝났다. 원시 로그에는 로스터 내부 접근 계약 위반 1건이 남았다. 이 SHA를 GitHub에 게시하거나 원격 main에 병합한 것으로 주장하지 않는다.
- 같은 commit `cdfd415c91`을 `-X utf8`로 재실행: 해당 assert의 실패 1건과 정상 runner 종료 경로를 확인했다. known-failure 비교는 1 NEW이며 기준선에 넣지 않았다.
- `python -c "import sys; print(sys.stdout.encoding)"`은 `cp1252`, `python -X utf8 -c "import sys; print(sys.stdout.encoding)"`은 `utf-8`이었다.
- 후속 UI 수정은 별도 commit에서 원격 검증했다. 인코딩 복구만으로 UI가 고쳐진 것으로 계산하지 않는다. 원시 두 로그는 Git 밖 작업 기록 `Rosy/docs/workspace-records/2026-10-24/fleet-ui-boundaries-evidence/`에서 보존한다.

예방 조건은 **부모 표준 출력의 실제 인코딩**이다. 모든 Windows 환경이 cp1252라고 일반화하지 않는다. 파일에 한글을 쓰는 경로의 인코딩 손실은 [별도 기록](powershell-utf8-append-mangles-korean-journals.md)을 따른다. 이번 방법은 runner 출력 복구이며 파일 쓰기 방법을 대체하지 않는다.

## 상태 변경 명령은 실패 전에 일부 작업을 끝냈을 수 있다

2026-10-27 `worktrees.py new`도 같은 출력 문제를 보였다. 승인된 임시 슬롯을 재사용하는 호출이 워크트리 생성·Git 등록을 끝낸 뒤 한국어 한도 예외 사유를 출력하다 실패했고, 이후 단계의 소유 메타데이터는 저장되지 않았다. 명령의 실패 종료만 보고 생성 자체가 없었다고 판단하면 안 된다.

재실행 전에 실제 경로, Git 워크트리 등록, 저장소 루트, 대상 브랜치와 HEAD, 작업 트리의 clean 상태, 소유 메타데이터를 대조했다. 생성된 워크트리가 의도한 기준 커밋과 일치하고 마지막 메타데이터만 없음을 확인한 뒤, 현재 공식 도구의 identity와 이미 승인된 사유로 그 누락 단계만 완료했다. 저장된 값이 의도한 값과 같은지도 확인했다. 임의 소유자를 만들거나 `new`를 다시 실행하거나 기존 경로를 삭제하지 않았다. 경로나 저장소 정체가 불확실하면 [빈 워크트리의 Git 실행 주의](empty-worktree-folder-runs-git-on-the-shared-main-2026-10-25.md)를 먼저 따른다.

예방 호출은 `python -X utf8 tools/worktrees.py new ...`이며, 자식 Python까지 필요하면 위의 `PYTHONUTF8` 조건을 적용한다. 이는 검증한 부분 실행 복구와 호출 인코딩 예방이다. `worktrees.py` 소스의 출력 순서나 예외 처리를 수정한 것은 아니며, 같은 문제가 난 모든 명령에 메타데이터 복구를 일반화하지 않는다. 각 명령의 실제 단계와 완료된 부작용부터 확인한다. 이 후속 관련 교훈 검색은 복구 뒤에 수행했다.
