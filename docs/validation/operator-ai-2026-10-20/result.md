# 통합관제 관제 AI 소스 검증

2026-10-20, D-810/API v1.289. `feat/operator-ai`의 첫 조회 전용 구현이다. 운영 설치·모델 활성화·장치 작업 실행의 수용 기록은 아니다. 최종 제품 소스는 `f22bedca05`, 설치 시험 자료/설계 표기는 `228c793584`, Fleet 통합 시험 자료는 `25b77d00b6`이다. 이후 결과 문서 커밋은 제품 동작을 바꾸지 않는다.

운영자는 기존 `/console`의 **관제 AI**에서 텍스트로 묻는다. Fleet가 기명 운영자 권한, 대화 소유권, 중복 접수, 현재 관측 근거와 영속 상태를 관리한다. Decision은 별도 Console 출처의 의미를 검증한다. 모델 broker는 기존 forced command 안에서 별도 프로토콜·평가 증거를 검증한다. 화면·음성, Fleet 대화 처리, Decision 의미 검증, 모델 추론/평가는 각 소유 모듈에 있다. 구체적인 위치와 설정은 [운영 안내](../../../operations/fleet/docs/operator-assistant.md)를 따른다.

## 검증 결과와 범위

모든 pytest와 Chromium은 커밋된 소스를 원격 시험 PC에 전달해 실행했다. 로컬 pytest·장치 접근·실제 모델 호출은 하지 않았다. 원격 서버의 가짜 모델 응답으로 상태·권한·표시·전송·복원 동작을 검증했다.

| 범위 | 소스 | 결과 | 원본 로그 위치¹ |
|---|---|---|---|
| 기존 Discord 대화 기준 | `f661deaa90` | 89 통과 | `baseline/run-1.txt` |
| 집중 계약·서버·CLI·기존 대화 | `dab629c171`² | 167 통과 | `review-green/run-1.txt` |
| 요청 취소·운영자 간 모델 호출 직렬화 포함 서버 회귀 | `823a0500ce` | 27 통과 | `concurrency-green/run-1.txt` |
| 등록된 FULL 22개 invocation | `823a0500ce` | 28,557 통과, 14 실패, 1,950 건너뜀 | `full-matrix/run-1.txt` … `run-22.txt` |
| 공용 UI 계약 + 실제 Chromium | `f22bedca05` | 65 통과, 건너뜀 없음. 이 중 Chromium 25개 | `ui-tier-green/run-1.txt` |
| wheel/sdist 설치·배포 경계 | `228c793584` | 84 통과 | `installed-green/run-1.txt` |
| Fleet 통합 계약·문서 import·Node 18 회귀 | `25b77d00b6` | 121 통과. 내부 Console Node 시험 342 통과 | `fleet-integration-green/run-1.txt` |

¹ 원본 루트는 작업 PC의 `%LOCALAPPDATA%/Temp/operator-ai/`다. 주소·계정 등이 포함될 수 있어 원본 로그는 공개 저장소에 복사하지 않았다. ² RED/GREEN 개발 이력은 `feat/operator-ai-tdd`에 보존했고 전달 브랜치는 크기 검사에 맞춰 계약/제품 커밋으로 정리했다.

FULL은 두 invocation 배열 모두 `full_invocations`로 지정했다. 최초의 `full/` 실행은 한 배열만 바꾼 **mapped affected** 실행이므로 FULL 증거로 사용하지 않는다. FULL의 건너뜀을 통과로 세지 않았다. 실제 브라우저 범위는 별도로 `ROSY_RUN_BROWSER_TESTS=1`을 지정한 25개에 한정한다. 최종 소스 전체를 다시 FULL로 실행한 기록은 없으며, 아래 수정분의 해당 범위를 검증한 결과를 함께 사용한다.

FULL의 14개 실패는 `test/known_failures.py`에서 모두 NEW였다. 알려진 실패로 등록하거나 제외하지 않았다.

| 최초 실패 | 수정 | 확인 |
|---|---|---|
| `run-9` 3개: 버튼 종류·비활성 사유·반응형 조건 | `e396351e2f`, `f22bedca05`: primary/사유 표시, 기존 64rem 범위 문법 | 공용 UI + Chromium 65 통과 |
| `run-20` 3개: Console 자산 수 107→110, 설계의 긴 기준 Git SHA를 비밀 탐지기가 토큰으로 인식 | `228c793584`: 설치 자산 기대값과 짧은 Git 참조 정렬 | 설치·배포 경계 84 통과 |
| `run-12` 8개: 기존 API 버전 기대값 5개, 문서 import 소유 목록, 자체 CSS 목록, Node 18의 crypto 전역 부재 | `25b77d00b6`: v1.289 시험 자료와 자산 경로/소유 목록 정렬, 시험에만 webcrypto 제공 | Fleet 통합 121 및 내부 Node 342 통과 |

먼저 실행한 mapped affected `6a119a94b2`에서는 G1 협조 동작 contact gap p99가 0.528227초로 0.5초 한도를 넘었다. 변경 전 `f661deaa90`의 정확한 시험은 통과했고, 실패 전에 독립적으로 시작한 FULL `823a0500ce`에서도 해당 시험이 통과했다. 시간 시험 코드를 바꾸거나 한도를 완화하지 않았다. 원인은 확정하지 않았으며, 앞선 실패는 `full/run-2.txt`, 기준 비교는 `timing-baseline/run-1.txt`에 남아 있다. 같은 실패 SHA를 반복해 통과만 골라 기록하지 않았다.

실행 방식은 `python -X utf8 tools/remote/remote_pytest.py --log-dir <외부-로그> --wait 30 -- <대상> -q`다. 브라우저는 대상 앞에 `ROSY_RUN_BROWSER_TESTS=1`을 붙였다. Node는 기존 `register-console-assets.mjs` loader와 전체 `*.test.mjs`를 사용했다. 처음 Node loader 없이 실행한 import 오류와 잘못된 `--run-browser` 옵션으로 끝난 exit 4는 검증 통과로 세지 않았다. 크기 검사는 `size_range.py f661deaa90 HEAD`에서 제품/시험 수정 8개 커밋을 통과했고 harness lint는 오류 0개·경고 33개였다.

## 검토 후 보완

별도 읽기 전용 검토가 `f661deaa90`부터 `74a6d10c46`까지 확인했다. 중요 발견 네 건인 계정 변경 직후 이전 대화 노출, 페이지 복원 시 대기 요청/녹음 상태 정체, 모델 CHAT의 근거 없는 물리 완료 표현, API 버전 세 위치 불일치를 수정했다. 새 모델 자유 문장 대신 서버의 고정 도움말을 표시하고, 상태/원인 답변은 현재 관측 근거로 표시한다. 권한 격리와 대기 요청 복원은 실제 브라우저에서 재현 후 통과했다. 녹음 복원 시험의 최초 fixture 오류는 고쳐 검증했으며 유효한 RED로 주장하지 않는다. 이후 FULL이 발견한 시험 자료 정렬도 위 표에 구분했다.

## 선택과 남은 조건

- 작업 공간 수 제한으로 기존의 본인 전용 worktree를 별도 기능 브랜치로 재사용했다. `D:/Dev/Robot/Rosy/rosy-platform/.worktrees/operator-ai-plan`을 보존하며 main·원격 브랜치는 바꾸지 않았다.
- 큰 공용 facade를 늘리지 않고 전용 DTO 모듈과 대화 CLI/경로 설치 모듈을 사용했다. 호출자는 `core_common.protocol.assistant`를 직접 import한다.
- 새 STT 서버 대신 선택적 브라우저 로컬 한국어 adapter를 먼저 연결했다. 지원되지 않으면 텍스트를 사용한다. 브라우저 수용 실패 시 AI PC STT 구현/평가 단계로 돌아간다.
- 한국어 음성 팩·마이크·TTS 실제 품질과 실제 모델의 독립 의미 평가는 수행하지 않았다. 모델 미설정이 기본이고 자유 대화는 고정 도움말로 제한된다.
- 기존 D-728 설치 도구는 새 operator 보호 설정 설치를 아직 지원하지 않는다. 보호 설치 지원과 독립 모델 평가 전에는 `primary_admitted=true`로 운영 활성화하지 않는다.
- 장치 작업 실행·작업 결과 알림은 첫 조회 버전 수용 뒤의 다음 단계다. 현재 패널의 실행 요청은 기존 작업 화면으로 안내한다. push·병합·운영 배포·모델/장비 승격은 하지 않았다.

## 원본 무결성

FULL 원본 디렉터리 digest는 `run-*.txt` 파일명을 사전순 정렬한 뒤 각 `파일명 + NUL + 파일 SHA-256(소문자 hex) + LF`를 연결한 UTF-8 문자열의 SHA-256이다. 파일 22개, sha256: `2179c5a322302ac0bdd929ff7157f7f2d46733df46e842347be8e746be438aee`.

| 로그 | SHA-256 |
|---|---|
| `ui-tier-green/run-1.txt` | sha256: `55c823246eb78aa7433a1726dc60eafc4b2d57bcf5526ee5a7307de2bfb3651b` |
| `installed-green/run-1.txt` | sha256: `20f5f27046a7bba4f1632529723920cb0714405e7c436f83ff72626e3a37131b` |
| `fleet-integration-green/run-1.txt` | sha256: `5c1efef16fa6ff9673da138e07e9c1adbeb2357ef1a29dd303f373643bc8d17c` |
| `concurrency-green/run-1.txt` | sha256: `86b2e371bc507ace555c496b083db59b1080e1b320647da3710f056ceb1df822` |
